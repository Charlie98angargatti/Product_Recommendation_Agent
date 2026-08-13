import sys
import os

# Make backend imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm_service import parse_preferences, generate_explanation


print("=" * 60)
print("LLM TEST START")
print("=" * 60)

query = """
I need a laptop under 50000.
RAM should be 16GB.
Battery life matters.
"""

print("\n1. Testing parse_preferences()...")
print("Query:", query.strip())

try:
    prefs = parse_preferences(query)

    print("\nSUCCESS: parse_preferences()")
    print("Result:")
    print(prefs)

except Exception as e:
    print("\nFAILED: parse_preferences()")
    print(type(e).__name__, ":", e)


print("\n2. Testing generate_explanation()...")

try:
    explanation = generate_explanation(
        {
            "id": "S02",
            "name": "Test Laptop",
            "price": 45000,
            "ram": "16GB",
        },
        query,
    )

    print("\nSUCCESS: generate_explanation()")
    print("Result:")
    print(explanation)

except Exception as e:
    print("\nFAILED: generate_explanation()")
    print(type(e).__name__, ":", e)


print("\n" + "=" * 60)
print("LLM TEST FINISHED")
print("=" * 60)




# print("TEST START")

# from llm_service import parse_preferences

# print("IMPORT OK")

# query = """
# I need a laptop under 50000.
# RAM should be 16GB.
# Battery life matters.
# """

# print("CALLING LLM")

# prefs = parse_preferences(query)

# print("LLM RETURNED")
# print(prefs)
# print("TEST END")