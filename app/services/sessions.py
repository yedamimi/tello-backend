"""주문 세션 생성 로직."""

import hashlib
import secrets
import time
from uuid import uuid4

from app.core.firebase import get_db_reference


def create_session(store_id: str) -> dict:
    """매장을 확인하고 고객의 주문 세션을 생성한다."""

    # 1. 매장 확인
    store = get_db_reference(f"stores/{store_id}").get()

    if store is None:
        raise ValueError("STORE_NOT_FOUND")

    if store.get("isOpen") is not True:
        raise ValueError("STORE_CLOSED")

    # 2. 세션 ID와 고객 확인용 토큰 생성
    session_id = uuid4().hex
    session_token = secrets.token_urlsafe(32)

    # 원본 토큰 대신 해시값을 DB에 저장
    token_hash = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    # 3. 세션 저장
    session_data = {
        "storeId": store_id,
        "status": "active",
        "createdAt": time.time_ns() // 1_000_000,
        "tokenHash": token_hash
    }

    get_db_reference(
        f"sessions/{session_id}"
    ).set(session_data)

    # 4. 고객에게 전달할 결과
    return {
        "sessionId": session_id,
        "storeId": store_id,
        "sessionToken": session_token
    }
    
def get_session_cart(session_id: str, session_token: str) -> dict:
    """고객 토큰을 확인하고 장바구니 금액을 계산한다."""

    if not session_token:
        raise ValueError("SESSION_UNAUTHORIZED")

    session = get_db_reference(f"sessions/{session_id}").get()

    # 없는 세션과 잘못된 토큰은 같은 오류로 처리
    if session is None:
        raise ValueError("SESSION_UNAUTHORIZED")

    token_hash = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    if not secrets.compare_digest(
        token_hash,
        session.get("tokenHash", "")
    ):
        raise ValueError("SESSION_UNAUTHORIZED")

    if session.get("status") != "active":
        raise ValueError("SESSION_INACTIVE")

    store_id = session["storeId"]
    cart = session.get("cart") or {}
    saved_items = cart.get("items") or {}

    items = []
    total_price = 0

    for item_id, item in saved_items.items():
        menu_id = item["menuId"]

        menu = get_db_reference(
            f"menus/{store_id}/{menu_id}"
        ).get()

        if menu is None or menu.get("isAvailable") is not True:
            raise ValueError("CART_MENU_UNAVAILABLE")

        selected_options = item.get("selectedOptions") or {}
        size_id = selected_options.get("size")
        size_options = menu.get("sizeOptions") or {}
        extra_price = 0

        if size_options:
            if size_id not in size_options:
                raise ValueError("CART_OPTION_INVALID")

            extra_price = size_options[size_id]["extraPrice"]

        elif selected_options:
            raise ValueError("CART_OPTION_INVALID")

        quantity = item["quantity"]

        if type(quantity) is not int or quantity < 1:
            raise ValueError("CART_QUANTITY_INVALID")

        unit_price = menu["price"] + extra_price
        subtotal = unit_price * quantity
        total_price += subtotal

        items.append({
            "itemId": item_id,
            "menuId": menu_id,
            "name": menu["name"],
            "quantity": quantity,
            "selectedOptions": selected_options,
            "unitPrice": unit_price,
            "subtotal": subtotal,
        })

    return {
        "sessionId": session_id,
        "items": items,
        "totalPrice": total_price,
    }
    
def add_cart_item(
    session_id: str,
    session_token: str,
    menu_id: str,
    quantity: int,
    selected_options: dict,
) -> dict:
    """메뉴와 옵션을 검증한 뒤 장바구니에 추가한다."""

    # 기존 조회 함수로 고객 인증·세션 상태 확인
    get_session_cart(session_id, session_token)

    session = get_db_reference(
        f"sessions/{session_id}"
    ).get()

    store_id = session["storeId"]

    # 메뉴 확인
    menu = get_db_reference(
        f"menus/{store_id}/{menu_id}"
    ).get()

    if menu is None:
        raise ValueError("MENU_NOT_FOUND")

    if menu.get("isAvailable") is not True:
        raise ValueError("MENU_SOLD_OUT")

    # 옵션 확인
    size_options = menu.get("sizeOptions") or {}
    size_id = selected_options.get("size")

    if size_options:
        if size_id not in size_options:
            raise ValueError("CART_OPTION_INVALID")
    elif selected_options:
        raise ValueError("CART_OPTION_INVALID")

    # 저장 전 수량 재확인
    if type(quantity) is not int or quantity < 1:
        raise ValueError("CART_QUANTITY_INVALID")

    # 장바구니에 새 항목 저장
    item_id = uuid4().hex

    get_db_reference(
        f"sessions/{session_id}/cart/items/{item_id}"
    ).set({
        "menuId": menu_id,
        "quantity": quantity,
        "selectedOptions": selected_options,
    })

    # 계산된 장바구니 전체 반환
    return get_session_cart(session_id, session_token)
  
def update_cart_item(
    session_id: str,
    session_token: str,
    item_id: str,
    changes: dict,
) -> dict:
    """장바구니 항목의 수량·옵션을 변경한다."""

    # 고객 인증 및 현재 장바구니 확인
    cart = get_session_cart(session_id, session_token)

    current_item = next(
        (
            item for item in cart["items"]
            if item["itemId"] == item_id
        ),
        None,
    )

    if current_item is None:
        raise ValueError("CART_ITEM_NOT_FOUND")

    session = get_db_reference(
        f"sessions/{session_id}"
    ).get()

    store_id = session["storeId"]
    menu_id = current_item["menuId"]

    menu = get_db_reference(
        f"menus/{store_id}/{menu_id}"
    ).get()

    if menu is None or menu.get("isAvailable") is not True:
        raise ValueError("CART_MENU_UNAVAILABLE")

    # 전달받은 값만 변경
    updates = {}

    if "quantity" in changes:
        quantity = changes["quantity"]

        if type(quantity) is not int or quantity < 1:
            raise ValueError("CART_QUANTITY_INVALID")

        updates["quantity"] = quantity

    if "selectedOptions" in changes:
        selected_options = changes["selectedOptions"]
        size_options = menu.get("sizeOptions") or {}
        size_id = selected_options.get("size")

        if size_options:
            if size_id not in size_options:
                raise ValueError("CART_OPTION_INVALID")
        elif selected_options:
            raise ValueError("CART_OPTION_INVALID")

        # 옵션 없는 메뉴는 해당 경로 삭제
        updates["selectedOptions"] = selected_options or None

    get_db_reference(
        f"sessions/{session_id}/cart/items/{item_id}"
    ).update(updates)

    return get_session_cart(session_id, session_token)
  
def delete_cart_item(
    session_id: str,
    session_token: str,
    item_id: str,
) -> dict:
    """고객 본인의 장바구니 항목을 삭제한다."""

    if not session_token:
        raise ValueError("SESSION_UNAUTHORIZED")

    session = get_db_reference(
        f"sessions/{session_id}"
    ).get()

    if session is None:
        raise ValueError("SESSION_UNAUTHORIZED")

    token_hash = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    if not secrets.compare_digest(
        token_hash,
        session.get("tokenHash", ""),
    ):
        raise ValueError("SESSION_UNAUTHORIZED")

    if session.get("status") != "active":
        raise ValueError("SESSION_INACTIVE")

    item_ref = get_db_reference(
        f"sessions/{session_id}/cart/items/{item_id}"
    )

    if item_ref.get() is None:
        raise ValueError("CART_ITEM_NOT_FOUND")

    item_ref.delete()

    return get_session_cart(session_id, session_token)