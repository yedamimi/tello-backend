
"""수량 누락 검증 단위 테스트."""

from app.schemas.messages import (
    AnalyzedItem,
    AnalyzedOptions,
    OrderAnalysis,
)
from app.services.messages import validate_order_analysis


analysis = OrderAnalysis(
    intent="add_item",
    items=[
        AnalyzedItem(
            menu_text="아메리카노",
            menu_id="americano",
            quantity=None,
            options=AnalyzedOptions(
                size=None,
                temperature=None,
                ice=None,
            ),
        )
    ],
)

result = validate_order_analysis(
    store_id="store_001",
    analysis=analysis,
)

codes = {
    issue["code"]
    for issue in result["issues"]
}

assert "QUANTITY_REQUIRED" in codes, (
    f"Expected QUANTITY_REQUIRED, got {codes}"
)

assert result["needsClarification"] is True

print("PASS: Missing quantity detected")
print("Issues:", result["issues"])
