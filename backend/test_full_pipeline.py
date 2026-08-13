from recommendation import get_recommendations

query = """
I need a laptop under 50000.
RAM should be 16GB.
Battery life matters.
"""

result = get_recommendations(query)

print(result["parsed_preferences"])

for rec in result["recommendations"]:
    print()
    print(rec["product"]["name"])
    print(rec["match_percent"])
    print(rec["explanation"])