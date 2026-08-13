"""
recommendation.py
------------------
Orchestrates the full pipeline:
  free text -> llm_service.parse_preferences -> hard filter -> scoring.compute_score
  -> rank -> scoring.build_grounding_facts -> llm_service.generate_explanation -> response

Cold-start: no query and no history skips straight to a popularity-based
fallback instead of forcing the LLM to parse an empty string.
"""

import json
import os

import llm_service
from scoring import build_catalog_ranges, compute_score, build_grounding_facts, popularity_score

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_products():
    with open(os.path.join(DATA_DIR, "products.json"), "r") as f:
        return json.load(f)


def load_profiles():
    with open(os.path.join(DATA_DIR, "user_profiles.json"), "r") as f:
        return json.load(f)


def hard_filter(products: list, prefs: dict):
    """Non-negotiable filters: category, and a generous soft budget ceiling
    (20% over max is still shown - scoring already penalizes it - so we never
    return zero results just because the LLM's parsed budget was slightly off)."""
    filtered = products
    if prefs.get("category"):
        filtered = [p for p in filtered if p["category"] == prefs["category"]]

    budget_max = prefs.get("budget_max")
    if budget_max:
        ceiling = budget_max * 1.2
        filtered = [p for p in filtered if p["price"] <= ceiling]

    return filtered


def cold_start_recommendations(products: list, top_n: int = 5, category: str = None):
    catalog_ranges = build_catalog_ranges(products)
    candidates = [p for p in products if p["category"] == category] if category else products

    scored = [(p, popularity_score(p, catalog_ranges)) for p in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)

    results = []
    seen_categories = set()
    for p, score in scored:
        if category or p["category"] not in seen_categories:
            results.append((p, score))
            seen_categories.add(p["category"])
        if len(results) >= top_n:
            break
    if len(results) < top_n:
        for p, score in scored:
            if (p, score) not in results:
                results.append((p, score))
            if len(results) >= top_n:
                break

    output = []
    for product, pop_score in results[:top_n]:
        breakdown = {"popularity": round(pop_score, 3)}
        explanation = (
            f"We don't have your preferences yet, so this is one of the top-rated "
            f"{product['category']}s in our catalog ({product['rating']}/5 from "
            f"{product['reviews']} reviews). Tell us your budget and priorities for "
            f"personalized picks."
        )
        output.append({
            "product": product,
            "match_percent": round(pop_score * 100, 1),
            "score_breakdown": breakdown,
            "explanation": explanation,
        })
    return output


def get_recommendations(user_text: str = "", category_hint: str = None, top_n: int = 5):
    products = load_products()

    is_cold_start = not user_text or not user_text.strip()
    if is_cold_start:
        return {
            "mode": "cold_start",
            "parsed_preferences": None,
            "recommendations": cold_start_recommendations(products, top_n, category_hint),
        }

    # 1. Understand the user (AI: NLU)
    prefs = llm_service.parse_preferences(user_text)
    if category_hint and not prefs.get("category"):
        prefs["category"] = category_hint

    # 2. Hard filter
    candidates = hard_filter(products, prefs)
    if not candidates:
        candidates = [p for p in products if not prefs.get("category") or p["category"] == prefs["category"]]

    # 3. Semantic similarity setup (AI: embeddings)
    user_embedding = llm_service.get_embedding(user_text)
    if user_embedding:
        for p in candidates:
            p["_embedding"] = llm_service.get_embedding(p["description"])

    catalog_ranges = build_catalog_ranges(products)

    # 4. Deterministic scoring + ranking
    scored = []
    for product in candidates:
        score, breakdown = compute_score(product, prefs, catalog_ranges, user_embedding)
        clean_product = {k: v for k, v in product.items() if k != "_embedding"}
        scored.append((clean_product, score, breakdown))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:top_n]

    # 5. Ground the facts, then explain each pick (AI: grounded NLG)
    results = []
    for product, score, breakdown in top:
        facts = build_grounding_facts(product, prefs)
        explanation = llm_service.generate_explanation(product, prefs, breakdown, facts)
        results.append({
            "product": product,
            "match_percent": round(score * 100, 1),
            "score_breakdown": breakdown,
            "explanation": explanation,
        })

    return {
        "mode": "personalized",
        "parsed_preferences": prefs,
        "recommendations": results,
    }




# """
# recommendation.py
# ------------------
# Orchestrates the full pipeline:
#   free text -> llm_service.parse_preferences -> hard filter -> scoring.compute_score
#   -> rank -> scoring.build_grounding_facts -> llm_service.generate_explanation -> response

# Cold-start: no query and no history skips straight to a popularity-based
# fallback instead of forcing the LLM to parse an empty string.
# """

# import json
# import os

# import llm_service
# from scoring import build_catalog_ranges, compute_score, build_grounding_facts, popularity_score

# DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


# def load_products():
#     with open(os.path.join(DATA_DIR, "products.json"), "r") as f:
#         return json.load(f)


# def load_profiles():
#     with open(os.path.join(DATA_DIR, "user_profiles.json"), "r") as f:
#         return json.load(f)


# def hard_filter(products: list, prefs: dict):
#     """Non-negotiable filters: category, and a generous soft budget ceiling
#     (20% over max is still shown - scoring already penalizes it - so we never
#     return zero results just because the LLM's parsed budget was slightly off)."""
#     filtered = products
#     if prefs.get("category"):
#         filtered = [p for p in filtered if p["category"] == prefs["category"]]

#     budget_max = prefs.get("budget_max")
#     if budget_max:
#         ceiling = budget_max * 1.2
#         filtered = [p for p in filtered if p["price"] <= ceiling]

#     return filtered


# def cold_start_recommendations(products: list, top_n: int = 5, category: str = None):
#     catalog_ranges = build_catalog_ranges(products)
#     candidates = [p for p in products if p["category"] == category] if category else products

#     scored = [(p, popularity_score(p, catalog_ranges)) for p in candidates]
#     scored.sort(key=lambda x: x[1], reverse=True)

#     results = []
#     seen_categories = set()
#     for p, score in scored:
#         if category or p["category"] not in seen_categories:
#             results.append((p, score))
#             seen_categories.add(p["category"])
#         if len(results) >= top_n:
#             break
#     if len(results) < top_n:
#         for p, score in scored:
#             if (p, score) not in results:
#                 results.append((p, score))
#             if len(results) >= top_n:
#                 break

#     output = []
#     for product, pop_score in results[:top_n]:
#         breakdown = {"popularity": round(pop_score, 3)}
#         explanation = (
#             f"We don't have your preferences yet, so this is one of the top-rated "
#             f"{product['category']}s in our catalog ({product['rating']}/5 from "
#             f"{product['reviews']} reviews). Tell us your budget and priorities for "
#             f"personalized picks."
#         )
#         output.append({
#             "product": product,
#             "match_percent": round(pop_score * 100, 1),
#             "score_breakdown": breakdown,
#             "explanation": explanation,
#         })
#     return output


# def get_recommendations(user_text: str = "", category_hint: str = None, top_n: int = 5):
#     products = load_products()

#     is_cold_start = not user_text or not user_text.strip()
#     if is_cold_start:
#         return {
#             "mode": "cold_start",
#             "parsed_preferences": None,
#             "recommendations": cold_start_recommendations(products, top_n, category_hint),
#         }

#     # 1. Understand the user (AI: NLU)
#     prefs = llm_service.parse_preferences(user_text)
#     if category_hint and not prefs.get("category"):
#         prefs["category"] = category_hint

#     # 2. Hard filter
#     candidates = hard_filter(products, prefs)
#     if not candidates:
#         candidates = [p for p in products if not prefs.get("category") or p["category"] == prefs["category"]]

#     # 3. Semantic similarity setup (AI: embeddings)
#     user_embedding = llm_service.get_embedding(user_text)
#     if user_embedding:
#         for p in candidates:
#             p["_embedding"] = llm_service.get_embedding(p["description"])

#     catalog_ranges = build_catalog_ranges(products)

#     # 4. Deterministic scoring + ranking
#     scored = []
#     for product in candidates:
#         score, breakdown = compute_score(product, prefs, catalog_ranges, user_embedding)
#         clean_product = {k: v for k, v in product.items() if k != "_embedding"}
#         scored.append((clean_product, score, breakdown))

#     scored.sort(key=lambda x: x[1], reverse=True)
#     top = scored[:top_n]

#     # 5. Ground the facts, then explain each pick (AI: grounded NLG)
#     results = []
#     for product, score, breakdown in top:
#         facts = build_grounding_facts(product, prefs)
#         explanation = llm_service.generate_explanation(product, prefs, breakdown, facts)
#         results.append({
#             "product": product,
#             "match_percent": round(score * 100, 1),
#             "score_breakdown": breakdown,
#             "explanation": explanation,
#         })

#     return {
#         "mode": "personalized",
#         "parsed_preferences": prefs,
#         "recommendations": results,
#     }
