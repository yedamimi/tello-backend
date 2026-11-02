
"""Gemini order validation integration test."""

from app.services.llm import analyze_order_text
from app.services.messages import validate_order_analysis

STORE_ID = "store_001"

tests = [
    (
        "Missing quantity",
        "아메리카노 주세요",
        "QUANTITY_REQUIRED",
    ),
    (
        "Missing options",
        "아메리카노 두 잔 주세요",
        "OPTION_REQUIRED",
    ),
    (
        "Unknown menu",
        "딸기 스무디 두 잔 주세요",
        "MENU_UNKNOWN",
    ),
]

for name, text, expected_code in tests:
    print(f"\nTesting: {name}", flush=True)

    analysis = analyze_order_text(STORE_ID, text)
    result = validate_order_analysis(STORE_ID, analysis)

    print("Intent:", result["intent"])
    print("Issues:", result["issues"])

    codes = {issue["code"] for issue in result["issues"]}

    assert expected_code in codes, (
        f"Expected {expected_code}, got {codes}"
    )
    assert result["needsClarification"] is True

    print(f"PASS: {name}")

print("\nALL VALIDATION TESTS PASSED")
