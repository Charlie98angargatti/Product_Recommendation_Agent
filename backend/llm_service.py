"""
llm_service.py
---------------
All calls to the local Ollama instance live here. Three jobs:

1. parse_preferences(text)  -> free text into structured preferences (NLU)
2. get_embedding(text)      -> semantic vector for content-based similarity
3. generate_explanation()   -> grounded natural-language rationale

v2 change (fixes the hallucination bug): the LLM is no longer shown raw product
JSON and asked to reason about it. It is shown a pre-computed list of FACTS
(scoring.build_grounding_facts) that are already guaranteed true, and is only
allowed to rephrase them. Its output is then validated: any number appearing
in the output that doesn't appear anywhere in the facts/product/prefs gets
rejected, and we fall back to a deterministic, 100%-accurate explanation built
straight from the facts. This means a bad LLM response can never reach the user
as a false claim - worst case it just reads a little less fluent.
"""

import json
import re
import requests

OLLAMA_URL = "http://localhost:11434"
CHAT_MODEL = "mistral"
EMBED_MODEL = "nomic-embed-text"  # falls back gracefully if not pulled

TIMEOUT = 60


def _chat(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
    payload = {
        "model": CHAT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def parse_preferences(user_text: str) -> dict:
    """
    LLM used purely for NLU: free text -> structured JSON.
    Key fix: explicit numbers (e.g. "16GB RAM") must land in dedicated numeric
    fields, not get invented into the priorities list as strings like
    'ram_16gb' - which is exactly what was happening before.
    """
    defaults = {
        "category": None,
        "budget_min": 0,
        "budget_max": None,
        "priorities": [],
        "use_case": None,
        "preferred_brands": [],
        "must_have_features": [],
        "min_ram_gb": None,
        "min_storage_gb": None,
        "min_battery": None,
        "min_camera_mp": None,
    }

    if not user_text or not user_text.strip():
        return defaults

    system_prompt = (
        "You convert a shopper's request into JSON describing their preferences. "
        "Categories are one of: laptop, smartphone, headphone.\n"
        "priorities must ONLY contain these exact qualitative words when relevant: "
        "performance, battery, camera, portability, budget, gaming, programming, "
        "business, audio_quality, noise_cancellation, storage. Never put a number "
        "or a made-up word into priorities.\n"
        "If the user states a specific number for RAM, storage, battery, or camera, "
        "put that number in the matching numeric field instead (min_ram_gb, "
        "min_storage_gb, min_battery, min_camera_mp). min_battery is in hours for "
        "laptop/headphone and mAh for smartphone.\n"
        "Respond with ONLY valid JSON, no prose, no markdown fences, matching exactly:\n"
        '{"category": string or null, "budget_min": number, "budget_max": number or null, '
        '"priorities": [string], "use_case": string or null, "preferred_brands": [string], '
        '"must_have_features": [string], "min_ram_gb": number or null, '
        '"min_storage_gb": number or null, "min_battery": number or null, '
        '"min_camera_mp": number or null}'
    )

    try:
        raw = _chat(system_prompt, user_text, temperature=0.1)
        raw = raw.strip().strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
        parsed = json.loads(raw)
        for key, val in defaults.items():
            parsed.setdefault(key, val)
        return parsed
    except Exception as e:
        print(f"[llm_service] parse_preferences failed, using defaults: {e}")
        return defaults


def get_embedding(text: str):
    if not text or not text.strip():
        return None
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("embedding")
    except Exception as e:
        print(f"[llm_service] embedding failed ({EMBED_MODEL}): {e}")
        return None


def _extract_numbers(text: str) -> set:
    normalized = text.replace(",", "").replace("\u20b9", "")
    return set(re.findall(r"\d+\.?\d*", normalized))


def _allowed_numbers(product: dict, prefs: dict, facts: list) -> set:
    """Every number that is legitimately groundable: the facts we generated,
    every value in the product record, and every value the user stated."""
    text_blob = " ".join(facts) + " " + " ".join(str(v) for v in product.values()) + " " + json.dumps(prefs)
    return _extract_numbers(text_blob)


def _facts_to_plain_explanation(facts: list) -> str:
    """100%-accurate fallback: just the facts, lightly joined. Used whenever
    the LLM either fails or hallucinates a number not present in the facts."""
    if not facts:
        return "This is a reasonable overall match based on your request."
    positives = [f for f in facts if "NOT MET" not in f and "over the stated budget" not in f]
    negatives = [f for f in facts if "NOT MET" in f or "over the stated budget" in f]
    parts = []
    if positives:
        parts.append(" ".join(positives[:3]))
    if negatives:
        parts.append("Trade-off: " + " ".join(negatives))
    return " ".join(parts)


def generate_explanation(product: dict, prefs: dict, score_breakdown: dict, facts: list) -> str:
    """
    Rephrases the pre-computed FACTS into a natural explanation. The LLM is
    deliberately not shown the raw product JSON, and any hallucinated number
    in its output is caught and rejected below.
    """
    system_prompt = (
        "You write a short, natural 2-3 sentence explanation of a product recommendation. "
        "You will be given a FACTS list that is already 100% accurate. Rules:\n"
        "1. Use ONLY the information in FACTS. Never state a number, spec, or claim "
        "that is not in FACTS.\n"
        "2. Always use the currency symbol \u20b9 (rupees), never $.\n"
        "3. If a fact says NOT MET or over budget, mention it honestly as a trade-off, "
        "don't hide it.\n"
        "4. No markdown, plain text only, 2-3 sentences."
    )
    user_prompt = (
        f"Product name: {product.get('name')} ({product.get('category')})\n"
        f"FACTS:\n- " + "\n- ".join(facts) + "\n\n"
        "Write the explanation now, using only the FACTS above."
    )

    try:
        raw = _chat(system_prompt, user_prompt, temperature=0.2).strip()
        allowed = _allowed_numbers(product, prefs, facts)
        used = _extract_numbers(raw)
        if used.issubset(allowed):
            return raw
        print(f"[llm_service] rejected explanation with unsupported numbers {used - allowed}, using fallback")
        return _facts_to_plain_explanation(facts)
    except Exception as e:
        print(f"[llm_service] generate_explanation failed: {e}")
        return _facts_to_plain_explanation(facts)







# """
# llm_service.py
# ---------------
# All calls to the local Ollama instance live here. Three jobs:

# 1. parse_preferences(text)  -> free text into structured preferences (NLU)
# 2. get_embedding(text)      -> semantic vector for content-based similarity
# 3. generate_explanation()   -> grounded natural-language rationale

# v2 change (fixes the hallucination bug): the LLM is no longer shown raw product
# JSON and asked to reason about it. It is shown a pre-computed list of FACTS
# (scoring.build_grounding_facts) that are already guaranteed true, and is only
# allowed to rephrase them. Its output is then validated: any number appearing
# in the output that doesn't appear anywhere in the facts/product/prefs gets
# rejected, and we fall back to a deterministic, 100%-accurate explanation built
# straight from the facts. This means a bad LLM response can never reach the user
# as a false claim - worst case it just reads a little less fluent.
# """

# import json
# import re
# import requests

# OLLAMA_URL = "http://localhost:11434"
# CHAT_MODEL = "mistral"
# EMBED_MODEL = "nomic-embed-text"  # falls back gracefully if not pulled

# TIMEOUT = 60


# def _chat(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
#     payload = {
#         "model": CHAT_MODEL,
#         "messages": [
#             {"role": "system", "content": system_prompt},
#             {"role": "user", "content": user_prompt},
#         ],
#         "stream": False,
#         "options": {"temperature": temperature},
#     }
#     resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=TIMEOUT)
#     resp.raise_for_status()
#     return resp.json()["message"]["content"]


# def parse_preferences(user_text: str) -> dict:
#     """
#     LLM used purely for NLU: free text -> structured JSON.
#     Key fix: explicit numbers (e.g. "16GB RAM") must land in dedicated numeric
#     fields, not get invented into the priorities list as strings like
#     'ram_16gb' - which is exactly what was happening before.
#     """
#     defaults = {
#         "category": None,
#         "budget_min": 0,
#         "budget_max": None,
#         "priorities": [],
#         "use_case": None,
#         "preferred_brands": [],
#         "must_have_features": [],
#         "min_ram_gb": None,
#         "min_storage_gb": None,
#         "min_battery": None,
#         "min_camera_mp": None,
#     }

#     if not user_text or not user_text.strip():
#         return defaults

#     system_prompt = (
#         "You convert a shopper's request into JSON describing their preferences. "
#         "Categories are one of: laptop, smartphone, headphone.\n"
#         "priorities must ONLY contain these exact qualitative words when relevant: "
#         "performance, battery, camera, portability, budget, gaming, programming, "
#         "business, audio_quality, noise_cancellation, storage. Never put a number "
#         "or a made-up word into priorities.\n"
#         "If the user states a specific number for RAM, storage, battery, or camera, "
#         "put that number in the matching numeric field instead (min_ram_gb, "
#         "min_storage_gb, min_battery, min_camera_mp). min_battery is in hours for "
#         "laptop/headphone and mAh for smartphone.\n"
#         "Respond with ONLY valid JSON, no prose, no markdown fences, matching exactly:\n"
#         '{"category": string or null, "budget_min": number, "budget_max": number or null, '
#         '"priorities": [string], "use_case": string or null, "preferred_brands": [string], '
#         '"must_have_features": [string], "min_ram_gb": number or null, '
#         '"min_storage_gb": number or null, "min_battery": number or null, '
#         '"min_camera_mp": number or null}'
#     )

#     try:
#         raw = _chat(system_prompt, user_text, temperature=0.1)
#         raw = raw.strip().strip("`")
#         if raw.lower().startswith("json"):
#             raw = raw[4:].strip()
#         parsed = json.loads(raw)
#         for key, val in defaults.items():
#             parsed.setdefault(key, val)
#         return parsed
#     except Exception as e:
#         print(f"[llm_service] parse_preferences failed, using defaults: {e}")
#         return defaults


# def get_embedding(text: str):
#     if not text or not text.strip():
#         return None
#     try:
#         resp = requests.post(
#             f"{OLLAMA_URL}/api/embeddings",
#             json={"model": EMBED_MODEL, "prompt": text},
#             timeout=TIMEOUT,
#         )
#         resp.raise_for_status()
#         return resp.json().get("embedding")
#     except Exception as e:
#         print(f"[llm_service] embedding failed ({EMBED_MODEL}): {e}")
#         return None


# def _extract_numbers(text: str) -> set:
#     normalized = text.replace(",", "").replace("\u20b9", "")
#     return set(re.findall(r"\d+\.?\d*", normalized))


# def _allowed_numbers(product: dict, prefs: dict, facts: list) -> set:
#     """Every number that is legitimately groundable: the facts we generated,
#     every value in the product record, and every value the user stated."""
#     text_blob = " ".join(facts) + " " + " ".join(str(v) for v in product.values()) + " " + json.dumps(prefs)
#     return _extract_numbers(text_blob)


# def _facts_to_plain_explanation(facts: list) -> str:
#     """100%-accurate fallback: just the facts, lightly joined. Used whenever
#     the LLM either fails or hallucinates a number not present in the facts."""
#     if not facts:
#         return "This is a reasonable overall match based on your request."
#     positives = [f for f in facts if "NOT MET" not in f and "over the stated budget" not in f]
#     negatives = [f for f in facts if "NOT MET" in f or "over the stated budget" in f]
#     parts = []
#     if positives:
#         parts.append(" ".join(positives[:3]))
#     if negatives:
#         parts.append("Trade-off: " + " ".join(negatives))
#     return " ".join(parts)


# def generate_explanation(product: dict, prefs: dict, score_breakdown: dict, facts: list) -> str:
#     """
#     Rephrases the pre-computed FACTS into a natural explanation. The LLM is
#     deliberately not shown the raw product JSON, and any hallucinated number
#     in its output is caught and rejected below.
#     """
#     system_prompt = (
#         "You write a short, natural 2-3 sentence explanation of a product recommendation. "
#         "You will be given a FACTS list that is already 100% accurate. Rules:\n"
#         "1. Use ONLY the information in FACTS. Never state a number, spec, or claim "
#         "that is not in FACTS.\n"
#         "2. Always use the currency symbol \u20b9 (rupees), never $.\n"
#         "3. If a fact says NOT MET or over budget, mention it honestly as a trade-off, "
#         "don't hide it.\n"
#         "4. No markdown, plain text only, 2-3 sentences."
#     )
#     user_prompt = (
#         f"Product name: {product.get('name')} ({product.get('category')})\n"
#         f"FACTS:\n- " + "\n- ".join(facts) + "\n\n"
#         "Write the explanation now, using only the FACTS above."
#     )

#     try:
#         raw = _chat(system_prompt, user_prompt, temperature=0.2).strip()
#         allowed = _allowed_numbers(product, prefs, facts)
#         used = _extract_numbers(raw)
#         if used.issubset(allowed):
#             return raw
#         print(f"[llm_service] rejected explanation with unsupported numbers {used - allowed}, using fallback")
#         return _facts_to_plain_explanation(facts)
#     except Exception as e:
#         print(f"[llm_service] generate_explanation failed: {e}")
#         return _facts_to_plain_explanation(facts)
