
"""8번 실제 Firebase 장바구니 저장 테스트."""

from app.core.firebase import get_db_reference
from app.services.sessions import create_session, get_session_cart
from app.services.messages import add_analyzed_items


session = create_session("store_001")
session_id = session["sessionId"]
session_token = session["sessionToken"]

try:
    items = [{
        "menu_text": "아메리카노",
        "menu_id": "americano",
        "quantity": 2,
        "options": {
            "size": "regular",
            "temperature": "ice",
            "ice": "regular",
        },
    }]

    result = add_analyzed_items(
        session_id,
        session_token,
        items,
    )

    cart = get_session_cart(session_id, session_token)

    assert result is not None
    assert cart is not None

    print("PASS 1: Firebase cart write")
    print("Cart:", cart)

    # 실제 저장된 장바구니 항목 검사
    stored_items = get_db_reference(
        f"sessions/{session_id}/cart/items"
    ).get() or {}

    assert any(
        item.get("menuId") == "americano"
        and item.get("quantity") == 2
        for item in stored_items.values()
    )

    print("PASS 2: Stored menu and quantity verified")

finally:
    get_db_reference(
        f"sessions/{session_id}"
    ).delete()

    print("PASS 3: Test session cleaned up")

print("\nALL FIREBASE TESTS PASSED")
