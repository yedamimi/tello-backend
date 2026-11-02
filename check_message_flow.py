
"""8번 주문 분석 흐름 통합 테스트 (외부 서비스 모의 처리)."""

from unittest.mock import patch

from app.schemas.messages import OrderAnalysis
from app.services.messages import process_order_message


STORE_ID = "store_001"
SESSION_ID = "test_session"
TOKEN = "test_token"

menus = {
    "americano": {
        "name": "아메리카노",
        "price": 3000,
        "isAvailable": True,
        "sizeOptions": {
            "regular": 0,
            "large": 500,
        },
        "temperatureOptions": {
            "hot": 0,
            "ice": 0,
        },
        "iceOptions": {
            "regular": 0,
            "more": 0,
            "less": 0,
        },
    },
    "cookie": {
        "name": "쿠키",
        "price": 2000,
        "isAvailable": True,
    },
    "soldout": {
        "name": "품절 메뉴",
        "price": 1000,
        "isAvailable": False,
    },
}

pending = None
added_items = []


def make_item(
    name, menu_id, quantity,
    size=None, temperature=None, ice=None,
):
    return {
        "menu_text": name,
        "menu_id": menu_id,
        "quantity": quantity,
        "options": {
            "size": size,
            "temperature": temperature,
            "ice": ice,
        },
    }


def mock_analyze(store_id, text):
    if text == "아메리카노 주세요":
        items = [
            make_item("아메리카노", "americano", None)
        ]
    elif text == "쿠키 2개 주세요":
        items = [
            make_item("쿠키", "cookie", 2)
        ]
    elif text == "두 메뉴 주세요":
        items = [
            make_item("쿠키", "cookie", 1),
            make_item("쿠키", "cookie", 2),
        ]
    elif text == "없는 메뉴 주세요":
        items = [
            make_item("없는 메뉴", None, 1)
        ]
    elif text == "품절 메뉴 주세요":
        items = [
            make_item("품절 메뉴", "soldout", 1)
        ]
    else:
        raise AssertionError(f"Unexpected text: {text}")

    return OrderAnalysis.model_validate({
        "intent": "add_item",
        "items": items,
    })


def mock_get_pending(session_id):
    return pending


def mock_save_pending(session_id, result):
    global pending

    pending = {
        "items": result["items"],
        "issues": result["issues"],
        "question": result["question"],
    }


def mock_clear_pending(session_id):
    global pending
    pending = None


def mock_add_items(session_id, session_token, items):
    added_items.extend(items)
    return {"items": list(added_items)}


def send(text):
    return process_order_message(
        session_id=SESSION_ID,
        session_token=TOKEN,
        text=text,
    )


patches = [
    patch(
        "app.services.messages._get_authenticated_session",
        return_value={"storeId": STORE_ID},
    ),
    patch(
        "app.services.messages.get_store_menus",
        return_value=menus,
    ),
    patch(
        "app.services.messages.analyze_order_text",
        side_effect=mock_analyze,
    ),
    patch(
        "app.services.messages.get_pending_order",
        side_effect=mock_get_pending,
    ),
    patch(
        "app.services.messages.save_pending_order",
        side_effect=mock_save_pending,
    ),
    patch(
        "app.services.messages.clear_pending_order",
        side_effect=mock_clear_pending,
    ),
    patch(
        "app.services.messages.add_analyzed_items",
        side_effect=mock_add_items,
    ),
    patch(
        "app.services.messages._calculate_unit_price",
        return_value=3000,
    ),
]

try:
    for mock in patches:
        mock.start()

    # 1. 수량과 옵션이 누락된 주문
    result = send("아메리카노 주세요")
    assert result["needsClarification"] is True
    assert pending is not None
    print("PASS 1: Missing information detected")

    # 2. 수량 후속 답변
    result = send("두 잔이요")
    assert result["items"][0]["quantity"] == 2
    assert result["needsClarification"] is True
    print("PASS 2: Quantity follow-up")

    # 3. 크기 후속 답변
    result = send("라지")
    assert result["items"][0]["options"]["size"] == "large"
    print("PASS 3: Size follow-up")

    # 4. 온도 후속 답변
    result = send("아이스")
    assert result["items"][0]["options"]["temperature"] == "ice"
    print("PASS 4: Temperature follow-up")

    # 5. 얼음 후속 답변 및 장바구니 추가
    result = send("보통")
    assert result["needsClarification"] is False
    assert result["cart"] is not None
    assert len(added_items) == 1
    assert pending is None
    print("PASS 5: Completed order added to cart")

    # 6. 추가 질문 없는 주문
    result = send("쿠키 2개 주세요")
    assert result["needsClarification"] is False
    assert len(added_items) == 2
    print("PASS 6: Direct cart addition")

    # 7. 다중 메뉴
    result = send("두 메뉴 주세요")
    assert result["needsClarification"] is False
    assert len(added_items) == 4
    print("PASS 7: Multiple items")

    # 8. 존재하지 않는 메뉴
    previous_count = len(added_items)
    result = send("없는 메뉴 주세요")
    assert result["needsClarification"] is True
    assert any(
        issue["code"] == "MENU_UNKNOWN"
        for issue in result["issues"]
    )
    assert len(added_items) == previous_count
    print("PASS 8: Unknown menu rejected")

    # 9. 품절 메뉴
    mock_clear_pending(SESSION_ID)
    result = send("품절 메뉴 주세요")
    assert result["needsClarification"] is True
    assert any(
        issue["code"] == "MENU_SOLD_OUT"
        for issue in result["issues"]
    )
    assert len(added_items) == previous_count
    print("PASS 9: Sold-out menu rejected")

    print("\nALL MESSAGE FLOW TESTS PASSED")

finally:
    for mock in reversed(patches):
        mock.stop()
