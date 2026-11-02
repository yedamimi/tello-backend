
"""Firebase 미완성 주문 저장 및 삭제 테스트."""

from app.core.firebase import get_db_reference
from app.services.sessions import create_session
from app.services.messages import (
    save_pending_order,
    get_pending_order,
)

session = create_session("store_001")
session_id = session["sessionId"]

try:
    # 1. 수량이 누락된 미완성 주문
    result = {
        "intent": "add_item",
        "items": [
            {
                "menu_text": "아메리카노",
                "menu_id": "americano",
                "quantity": None,
                "options": {
                    "size": None,
                    "temperature": None,
                    "ice": None,
                },
            }
        ],
        "issues": [
            {
                "itemIndex": 0,
                "code": "QUANTITY_REQUIRED",
                "field": "quantity",
            }
        ],
        "needsClarification": True,
        "question": "아메리카노는 몇 잔 주문하시겠어요?",
    }

    # 2. Firebase에 미완성 주문 저장
    save_pending_order(session_id, result)

    pending = get_pending_order(session_id)

    assert pending is not None
    assert pending["intent"] == "add_item"
    assert pending["items"][0]["menu_id"] == "americano"

    # Firebase는 null 필드를 저장하지 않을 수 있음
    assert pending["items"][0].get("quantity") is None
    assert pending["items"][0].get("options", {}).get("size") is None

    print("PASS 1: Pending order saved")

    # 3. 미완성 주문 삭제
    result["needsClarification"] = False

    save_pending_order(session_id, result)

    assert get_pending_order(session_id) is None

    print("PASS 2: Pending order cleared")

finally:
    # 테스트에서 생성한 세션만 삭제
    get_db_reference(
        f"sessions/{session_id}"
    ).delete()
