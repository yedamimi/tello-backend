
"""8번 품절 메뉴 검증 테스트."""

from unittest.mock import patch

from app.schemas.messages import OrderAnalysis
from app.services.messages import validate_order_analysis


analysis = OrderAnalysis.model_validate({
    "intent": "add_item",
    "items": [{
        "menu_text": "품절 테스트 메뉴",
        "menu_id": "soldout_test",
        "quantity": 1,
        "options": {
            "size": None,
            "temperature": None,
            "ice": None,
        },
    }],
})

with patch(
    "app.services.messages.get_store_menus",
    return_value={
        "soldout_test": {
            "name": "품절 테스트 메뉴",
            "price": 3000,
            "isAvailable": False,
        },
    },
):
    result = validate_order_analysis(
        "store_001",
        analysis,
    )

assert any(
    issue["code"] == "MENU_SOLD_OUT"
    for issue in result["issues"]
)

assert result["needsClarification"] is True

print("PASS: Sold-out menu rejected")
