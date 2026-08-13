"""
Tests focus on the deterministic parts (scoring, filtering, cold-start) so they
run without Ollama installed. LLM-dependent functions (parse_preferences,
generate_explanation) are mocked or skipped.
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from scoring import budget_fit_score, attribute_match_score, brand_bonus_score, \
    build_catalog_ranges, compute_score
from recommendation import hard_filter, cold_start_recommendations, load_products


def test_budget_fit_within_range_scores_high():
    score = budget_fit_score(price=60000, budget_min=0, budget_max=80000)
    assert 0.7 <= score <= 1.0


def test_budget_fit_over_budget_is_penalized():
    in_budget = budget_fit_score(price=79000, budget_min=0, budget_max=80000)
    over_budget = budget_fit_score(price=150000, budget_min=0, budget_max=80000)
    assert over_budget < in_budget


def test_brand_bonus_matches_preferred_brand():
    product = {"brand": "Dell"}
    assert brand_bonus_score(product, ["Dell", "HP"]) == 1.0
    assert brand_bonus_score(product, ["Apple"]) == 0.2
    assert brand_bonus_score(product, []) == 0.5


def test_hard_filter_respects_category():
    products = load_products()
    prefs = {"category": "laptop", "budget_max": None}
    filtered = hard_filter(products, prefs)
    assert all(p["category"] == "laptop" for p in filtered)
    assert len(filtered) == 10


def test_hard_filter_respects_budget_ceiling():
    products = load_products()
    prefs = {"category": "smartphone", "budget_max": 20000}
    filtered = hard_filter(products, prefs)
    assert all(p["price"] <= 20000 * 1.2 for p in filtered)


def test_cold_start_returns_diverse_categories():
    products = load_products()
    results = cold_start_recommendations(products, top_n=5)
    categories = set(r["product"]["category"] for r in results)
    assert len(categories) >= 2  # should not be all one category


def test_compute_score_prefers_cheaper_option_when_budget_priority():
    products = load_products()
    catalog_ranges = build_catalog_ranges(products)
    prefs = {"budget_min": 0, "budget_max": 60000, "priorities": ["budget"],
              "preferred_brands": [], "min_ram_gb": None, "min_storage_gb": None,
              "min_battery": None, "min_camera_mp": None}
    laptops = [p for p in products if p["category"] == "laptop"]
    scored = [(p, compute_score(p, prefs, catalog_ranges)[0]) for p in laptops]
    scored.sort(key=lambda x: x[1], reverse=True)
    # cheapest in-budget laptop should rank in the upper half when budget is the
    # priority (not necessarily #1, since popularity/rating also factor in)
    cheapest = min(laptops, key=lambda p: p["price"])
    top_ids = [p["id"] for p, _ in scored[:5]]
    assert cheapest["id"] in top_ids


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
