"""
scoring.py
----------
Pure scoring math + fact generation. No LLM calls here on purpose - keeps
ranking deterministic, fast, testable and reproducible, while the AI parts
(understanding the query, semantic similarity, explaining results) live in
llm_service.py.

v2 change: added explicit numeric requirement matching (min_ram_gb etc.) and
build_grounding_facts(), which produces plain-English, verifiably-true
sentences from the real product data. These facts - not the raw product JSON -
are what get handed to the LLM for explanation, so the LLM has nothing left
to invent.
"""

import math

# vague "priority" words -> which product attribute they map to, per category
PRIORITY_ATTRIBUTE_MAP = {
    "performance": {"laptop": ("ram_gb", "high"), "smartphone": ("ram_gb", "high")},
    "battery": {"laptop": ("battery_hours", "high"), "smartphone": ("battery_mah", "high"),
                "headphone": ("battery_hours", "high")},
    "camera": {"smartphone": ("camera_mp", "high")},
    "portability": {"laptop": ("weight_kg", "low")},
    "budget": {"laptop": ("price", "low"), "smartphone": ("price", "low"), "headphone": ("price", "low")},
    "storage": {"laptop": ("storage_gb", "high"), "smartphone": ("storage_gb", "high")},
    "audio_quality": {"headphone": ("rating", "high")},
    "noise_cancellation": {"headphone": ("anc", "bool")},
    "gaming": {"laptop": ("ram_gb", "high"), "smartphone": ("ram_gb", "high")},
    "programming": {"laptop": ("ram_gb", "high")},
    "business": {"laptop": ("weight_kg", "low")},
}

# explicit numeric requirements -> (attribute, category) the field applies to
REQUIREMENT_MAP = {
    "min_ram_gb": {"laptop": "ram_gb", "smartphone": "ram_gb"},
    "min_storage_gb": {"laptop": "storage_gb", "smartphone": "storage_gb"},
    "min_battery": {"laptop": "battery_hours", "headphone": "battery_hours", "smartphone": "battery_mah"},
    "min_camera_mp": {"smartphone": "camera_mp"},
}

WEIGHTS = {
    "budget_fit": 0.25,
    "requirement_fit": 0.20,
    "attribute_match": 0.15,
    "semantic_similarity": 0.20,
    "brand_bonus": 0.05,
    "popularity": 0.15,
}


def format_currency(value) -> str:
    return f"\u20b9{value:,.0f}"


def budget_fit_score(price: float, budget_min: float, budget_max):
    """1.0 = perfectly fills the budget without exceeding it. Decays sharply once
    over budget, decays gently if far under budget (likely under-specced)."""
    if budget_max is None:
        return 0.5
    if price > budget_max:
        overshoot = (price - budget_max) / budget_max
        return max(0.0, 1 - overshoot * 2)
    if price < budget_min:
        undershoot = (budget_min - price) / max(budget_min, 1)
        return max(0.3, 1 - undershoot)
    span = max(budget_max - budget_min, 1)
    return 0.7 + 0.3 * ((price - budget_min) / span)


def _normalize(value, lo, hi):
    if hi == lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def attribute_match_score(product: dict, priorities: list, catalog_ranges: dict):
    """Covers vague/qualitative priorities like 'performance' or 'battery'."""
    if not priorities:
        return 0.5
    category = product["category"]
    scores = []
    for priority in priorities:
        mapping = PRIORITY_ATTRIBUTE_MAP.get(priority, {}).get(category)
        if not mapping:
            continue
        attr, direction = mapping
        if attr not in product:
            continue
        if direction == "bool":
            scores.append(1.0 if product[attr] else 0.0)
            continue
        lo, hi = catalog_ranges.get((category, attr), (0, 1))
        norm = _normalize(product[attr], lo, hi)
        scores.append(norm if direction == "high" else 1 - norm)
    return sum(scores) / len(scores) if scores else 0.5


def requirement_fit_score(product: dict, prefs: dict):
    """Covers explicit numeric asks like '16GB RAM' or '5000mAh battery'.
    Full credit for meeting/exceeding, partial + honest penalty for falling short."""
    category = product["category"]
    scores = []
    for req_key, per_category_attr in REQUIREMENT_MAP.items():
        required_value = prefs.get(req_key)
        attr = per_category_attr.get(category)
        if required_value is None or not attr or attr not in product:
            continue
        actual = product[attr]
        if actual >= required_value:
            scores.append(1.0)
        else:
            scores.append(max(0.0, actual / required_value))
    if not scores:
        return None  # no explicit numeric requirements applicable - caller treats as neutral
    return sum(scores) / len(scores)


def brand_bonus_score(product: dict, preferred_brands: list):
    if not preferred_brands:
        return 0.5
    return 1.0 if product.get("brand", "").lower() in [b.lower() for b in preferred_brands] else 0.2


def cosine_similarity(vec_a, vec_b):
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return None
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return None
    return dot / (norm_a * norm_b)


def popularity_score(product: dict, catalog_ranges: dict):
    lo, hi = catalog_ranges.get((product["category"], "reviews"), (0, 1))
    rating_norm = _normalize(product.get("rating", 0), 0, 5)
    reviews_norm = _normalize(product.get("reviews", 0), lo, hi)
    return 0.6 * rating_norm + 0.4 * reviews_norm


def build_catalog_ranges(products: list):
    ranges = {}
    numeric_attrs = ["ram_gb", "storage_gb", "battery_hours", "battery_mah",
                      "camera_mp", "weight_kg", "price", "reviews", "rating"]
    categories = set(p["category"] for p in products)
    for cat in categories:
        cat_products = [p for p in products if p["category"] == cat]
        for attr in numeric_attrs:
            values = [p[attr] for p in cat_products if attr in p]
            if values:
                ranges[(cat, attr)] = (min(values), max(values))
    return ranges


def compute_score(product: dict, prefs: dict, catalog_ranges: dict, user_embedding=None):
    b_fit = budget_fit_score(product["price"], prefs.get("budget_min", 0), prefs.get("budget_max"))
    a_match = attribute_match_score(product, prefs.get("priorities", []), catalog_ranges)
    req_fit = requirement_fit_score(product, prefs)
    req_fit_for_score = req_fit if req_fit is not None else 0.5
    brand = brand_bonus_score(product, prefs.get("preferred_brands", []))
    pop = popularity_score(product, catalog_ranges)

    sim = None
    if user_embedding and product.get("_embedding"):
        sim = cosine_similarity(user_embedding, product["_embedding"])
    sim_score = sim if sim is not None else 0.5

    breakdown = {
        "budget_fit": round(b_fit, 3),
        "requirement_fit": round(req_fit_for_score, 3),
        "attribute_match": round(a_match, 3),
        "semantic_similarity": round(sim_score, 3),
        "brand_bonus": round(brand, 3),
        "popularity": round(pop, 3),
    }
    final = sum(WEIGHTS[k] * v for k, v in breakdown.items())
    return round(final, 4), breakdown


def build_grounding_facts(product: dict, prefs: dict) -> list:
    """
    Produces a list of plain-English sentences that are 100% derived from real
    product/preference data. This is what gets handed to the LLM to rephrase -
    it cannot invent a spec that isn't already stated as a fact here.
    """
    facts = []
    category = product["category"]
    price_str = format_currency(product["price"])

    # --- budget fact ---
    budget_max = prefs.get("budget_max")
    if budget_max:
        budget_str = format_currency(budget_max)
        if product["price"] <= budget_max:
            facts.append(f"Price is {price_str}, within the stated budget of up to {budget_str}.")
        else:
            over = format_currency(product["price"] - budget_max)
            facts.append(f"Price is {price_str}, which is {over} over the stated budget of {budget_str}.")
    else:
        facts.append(f"Price is {price_str}.")

    # --- explicit numeric requirements ---
    for req_key, per_category_attr in REQUIREMENT_MAP.items():
        required_value = prefs.get(req_key)
        attr = per_category_attr.get(category)
        if required_value is None or not attr or attr not in product:
            continue
        actual = product[attr]
        label = attr.replace("_", " ")
        if actual >= required_value:
            facts.append(f"Requested {label} of at least {required_value}: this product has {actual} {label} - MET.")
        else:
            facts.append(f"Requested {label} of at least {required_value}: this product has only {actual} {label} - NOT MET.")

    # --- qualitative priorities ---
    for priority in prefs.get("priorities", []):
        mapping = PRIORITY_ATTRIBUTE_MAP.get(priority, {}).get(category)
        if not mapping:
            continue
        attr, direction = mapping
        if attr not in product:
            continue
        label = attr.replace("_", " ")
        if direction == "bool":
            facts.append(f"Priority '{priority}': this product {'has' if product[attr] else 'does not have'} it.")
        else:
            facts.append(f"Priority '{priority}' relates to {label}, which is {product[attr]} for this product.")

    # --- brand ---
    preferred_brands = prefs.get("preferred_brands", [])
    if preferred_brands:
        if product.get("brand", "").lower() in [b.lower() for b in preferred_brands]:
            facts.append(f"Brand is {product['brand']}, matching the preferred brand.")
        else:
            facts.append(f"Brand is {product['brand']}, not one of the preferred brands ({', '.join(preferred_brands)}).")

    # --- popularity, always included as neutral context ---
    facts.append(f"Rated {product.get('rating')}/5 from {product.get('reviews')} reviews.")

    return facts



# """
# scoring.py
# ----------
# Pure scoring math + fact generation. No LLM calls here on purpose - keeps
# ranking deterministic, fast, testable and reproducible, while the AI parts
# (understanding the query, semantic similarity, explaining results) live in
# llm_service.py.

# v2 change: added explicit numeric requirement matching (min_ram_gb etc.) and
# build_grounding_facts(), which produces plain-English, verifiably-true
# sentences from the real product data. These facts - not the raw product JSON -
# are what get handed to the LLM for explanation, so the LLM has nothing left
# to invent.
# """

# import math

# # vague "priority" words -> which product attribute they map to, per category
# PRIORITY_ATTRIBUTE_MAP = {
#     "performance": {"laptop": ("ram_gb", "high"), "smartphone": ("ram_gb", "high")},
#     "battery": {"laptop": ("battery_hours", "high"), "smartphone": ("battery_mah", "high"),
#                 "headphone": ("battery_hours", "high")},
#     "camera": {"smartphone": ("camera_mp", "high")},
#     "portability": {"laptop": ("weight_kg", "low")},
#     "budget": {"laptop": ("price", "low"), "smartphone": ("price", "low"), "headphone": ("price", "low")},
#     "storage": {"laptop": ("storage_gb", "high"), "smartphone": ("storage_gb", "high")},
#     "audio_quality": {"headphone": ("rating", "high")},
#     "noise_cancellation": {"headphone": ("anc", "bool")},
#     "gaming": {"laptop": ("ram_gb", "high"), "smartphone": ("ram_gb", "high")},
#     "programming": {"laptop": ("ram_gb", "high")},
#     "business": {"laptop": ("weight_kg", "low")},
# }

# # explicit numeric requirements -> (attribute, category) the field applies to
# REQUIREMENT_MAP = {
#     "min_ram_gb": {"laptop": "ram_gb", "smartphone": "ram_gb"},
#     "min_storage_gb": {"laptop": "storage_gb", "smartphone": "storage_gb"},
#     "min_battery": {"laptop": "battery_hours", "headphone": "battery_hours", "smartphone": "battery_mah"},
#     "min_camera_mp": {"smartphone": "camera_mp"},
# }

# WEIGHTS = {
#     "budget_fit": 0.25,
#     "requirement_fit": 0.20,
#     "attribute_match": 0.15,
#     "semantic_similarity": 0.20,
#     "brand_bonus": 0.05,
#     "popularity": 0.15,
# }


# def format_currency(value) -> str:
#     return f"\u20b9{value:,.0f}"


# def budget_fit_score(price: float, budget_min: float, budget_max):
#     """1.0 = perfectly fills the budget without exceeding it. Decays sharply once
#     over budget, decays gently if far under budget (likely under-specced)."""
#     if budget_max is None:
#         return 0.5
#     if price > budget_max:
#         overshoot = (price - budget_max) / budget_max
#         return max(0.0, 1 - overshoot * 2)
#     if price < budget_min:
#         undershoot = (budget_min - price) / max(budget_min, 1)
#         return max(0.3, 1 - undershoot)
#     span = max(budget_max - budget_min, 1)
#     return 0.7 + 0.3 * ((price - budget_min) / span)


# def _normalize(value, lo, hi):
#     if hi == lo:
#         return 0.5
#     return max(0.0, min(1.0, (value - lo) / (hi - lo)))


# def attribute_match_score(product: dict, priorities: list, catalog_ranges: dict):
#     """Covers vague/qualitative priorities like 'performance' or 'battery'."""
#     if not priorities:
#         return 0.5
#     category = product["category"]
#     scores = []
#     for priority in priorities:
#         mapping = PRIORITY_ATTRIBUTE_MAP.get(priority, {}).get(category)
#         if not mapping:
#             continue
#         attr, direction = mapping
#         if attr not in product:
#             continue
#         if direction == "bool":
#             scores.append(1.0 if product[attr] else 0.0)
#             continue
#         lo, hi = catalog_ranges.get((category, attr), (0, 1))
#         norm = _normalize(product[attr], lo, hi)
#         scores.append(norm if direction == "high" else 1 - norm)
#     return sum(scores) / len(scores) if scores else 0.5


# def requirement_fit_score(product: dict, prefs: dict):
#     """Covers explicit numeric asks like '16GB RAM' or '5000mAh battery'.
#     Full credit for meeting/exceeding, partial + honest penalty for falling short."""
#     category = product["category"]
#     scores = []
#     for req_key, per_category_attr in REQUIREMENT_MAP.items():
#         required_value = prefs.get(req_key)
#         attr = per_category_attr.get(category)
#         if required_value is None or not attr or attr not in product:
#             continue
#         actual = product[attr]
#         if actual >= required_value:
#             scores.append(1.0)
#         else:
#             scores.append(max(0.0, actual / required_value))
#     if not scores:
#         return None  # no explicit numeric requirements applicable - caller treats as neutral
#     return sum(scores) / len(scores)


# def brand_bonus_score(product: dict, preferred_brands: list):
#     if not preferred_brands:
#         return 0.5
#     return 1.0 if product.get("brand", "").lower() in [b.lower() for b in preferred_brands] else 0.2


# def cosine_similarity(vec_a, vec_b):
#     if not vec_a or not vec_b or len(vec_a) != len(vec_b):
#         return None
#     dot = sum(a * b for a, b in zip(vec_a, vec_b))
#     norm_a = math.sqrt(sum(a * a for a in vec_a))
#     norm_b = math.sqrt(sum(b * b for b in vec_b))
#     if norm_a == 0 or norm_b == 0:
#         return None
#     return dot / (norm_a * norm_b)


# def popularity_score(product: dict, catalog_ranges: dict):
#     lo, hi = catalog_ranges.get((product["category"], "reviews"), (0, 1))
#     rating_norm = _normalize(product.get("rating", 0), 0, 5)
#     reviews_norm = _normalize(product.get("reviews", 0), lo, hi)
#     return 0.6 * rating_norm + 0.4 * reviews_norm


# def build_catalog_ranges(products: list):
#     ranges = {}
#     numeric_attrs = ["ram_gb", "storage_gb", "battery_hours", "battery_mah",
#                       "camera_mp", "weight_kg", "price", "reviews", "rating"]
#     categories = set(p["category"] for p in products)
#     for cat in categories:
#         cat_products = [p for p in products if p["category"] == cat]
#         for attr in numeric_attrs:
#             values = [p[attr] for p in cat_products if attr in p]
#             if values:
#                 ranges[(cat, attr)] = (min(values), max(values))
#     return ranges


# def compute_score(product: dict, prefs: dict, catalog_ranges: dict, user_embedding=None):
#     b_fit = budget_fit_score(product["price"], prefs.get("budget_min", 0), prefs.get("budget_max"))
#     a_match = attribute_match_score(product, prefs.get("priorities", []), catalog_ranges)
#     req_fit = requirement_fit_score(product, prefs)
#     req_fit_for_score = req_fit if req_fit is not None else 0.5
#     brand = brand_bonus_score(product, prefs.get("preferred_brands", []))
#     pop = popularity_score(product, catalog_ranges)

#     sim = None
#     if user_embedding and product.get("_embedding"):
#         sim = cosine_similarity(user_embedding, product["_embedding"])
#     sim_score = sim if sim is not None else 0.5

#     breakdown = {
#         "budget_fit": round(b_fit, 3),
#         "requirement_fit": round(req_fit_for_score, 3),
#         "attribute_match": round(a_match, 3),
#         "semantic_similarity": round(sim_score, 3),
#         "brand_bonus": round(brand, 3),
#         "popularity": round(pop, 3),
#     }
#     final = sum(WEIGHTS[k] * v for k, v in breakdown.items())
#     return round(final, 4), breakdown


# def build_grounding_facts(product: dict, prefs: dict) -> list:
#     """
#     Produces a list of plain-English sentences that are 100% derived from real
#     product/preference data. This is what gets handed to the LLM to rephrase -
#     it cannot invent a spec that isn't already stated as a fact here.
#     """
#     facts = []
#     category = product["category"]
#     price_str = format_currency(product["price"])

#     # --- budget fact ---
#     budget_max = prefs.get("budget_max")
#     if budget_max:
#         budget_str = format_currency(budget_max)
#         if product["price"] <= budget_max:
#             facts.append(f"Price is {price_str}, within the stated budget of up to {budget_str}.")
#         else:
#             over = format_currency(product["price"] - budget_max)
#             facts.append(f"Price is {price_str}, which is {over} over the stated budget of {budget_str}.")
#     else:
#         facts.append(f"Price is {price_str}.")

#     # --- explicit numeric requirements ---
#     for req_key, per_category_attr in REQUIREMENT_MAP.items():
#         required_value = prefs.get(req_key)
#         attr = per_category_attr.get(category)
#         if required_value is None or not attr or attr not in product:
#             continue
#         actual = product[attr]
#         label = attr.replace("_", " ")
#         if actual >= required_value:
#             facts.append(f"Requested {label} of at least {required_value}: this product has {actual} {label} - MET.")
#         else:
#             facts.append(f"Requested {label} of at least {required_value}: this product has only {actual} {label} - NOT MET.")

#     # --- qualitative priorities ---
#     for priority in prefs.get("priorities", []):
#         mapping = PRIORITY_ATTRIBUTE_MAP.get(priority, {}).get(category)
#         if not mapping:
#             continue
#         attr, direction = mapping
#         if attr not in product:
#             continue
#         label = attr.replace("_", " ")
#         if direction == "bool":
#             facts.append(f"Priority '{priority}': this product {'has' if product[attr] else 'does not have'} it.")
#         else:
#             facts.append(f"Priority '{priority}' relates to {label}, which is {product[attr]} for this product.")

#     # --- brand ---
#     preferred_brands = prefs.get("preferred_brands", [])
#     if preferred_brands:
#         if product.get("brand", "").lower() in [b.lower() for b in preferred_brands]:
#             facts.append(f"Brand is {product['brand']}, matching the preferred brand.")
#         else:
#             facts.append(f"Brand is {product['brand']}, not one of the preferred brands ({', '.join(preferred_brands)}).")

#     # --- popularity, always included as neutral context ---
#     facts.append(f"Rated {product.get('rating')}/5 from {product.get('reviews')} reviews.")

#     return facts
