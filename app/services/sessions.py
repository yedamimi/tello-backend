"""주문 세션·장바구니 처리 로직."""

import hashlib
import secrets
import time
from uuid import uuid4

from app.core.firebase import get_db_reference


def _get_authenticated_session(
    session_id: str,
    session_token: str,
) -> dict:
    """토큰과 세션 상태를 확인한다."""

    if not session_token:
        raise ValueError("SESSION_UNAUTHORIZED")

    session = get_db_reference(f"sessions/{session_id}").get()

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

    return session


def _validate_quantity(quantity: int):
    """수량은 bool을 제외한 1 이상의 정수여야 한다."""

    if type(quantity) is not int or quantity < 1:
        raise ValueError("CART_QUANTITY_INVALID")


def _calculate_unit_price(menu: dict, options: dict) -> int:
    """옵션 조합을 검증하고 1개 가격을 계산한다."""

    if not isinstance(options, dict):
        raise ValueError("CART_OPTION_INVALID")

    if set(options) - {"size", "temperature", "ice"}:
        raise ValueError("CART_OPTION_INVALID")

    size_options = menu.get("sizeOptions") or {}
    temperature_options = menu.get("temperatureOptions") or {}
    ice_options = menu.get("iceOptions") or {}

    extra_price = 0

    if size_options:
        size_id = options.get("size")
        if size_id not in size_options:
            raise ValueError("CART_OPTION_INVALID")
        extra_price += size_options[size_id]["extraPrice"]
    elif "size" in options:
        raise ValueError("CART_OPTION_INVALID")

    if temperature_options:
        temperature_id = options.get("temperature")
        if temperature_id not in temperature_options:
            raise ValueError("CART_OPTION_INVALID")
        extra_price += temperature_options[temperature_id]["extraPrice"]
    elif "temperature" in options:
        raise ValueError("CART_OPTION_INVALID")

    if options.get("temperature") == "ice":
        ice_id = options.get("ice")
        if ice_id not in ice_options:
            raise ValueError("CART_OPTION_INVALID")
        extra_price += ice_options[ice_id]["extraPrice"]
    elif "ice" in options:
        raise ValueError("CART_OPTION_INVALID")

    return menu["price"] + extra_price


def create_session(store_id: str) -> dict:
    """매장을 확인하고 주문 세션을 생성한다."""

    store = get_db_reference(f"stores/{store_id}").get()

    if store is None:
        raise ValueError("STORE_NOT_FOUND")

    if store.get("isOpen") is not True:
        raise ValueError("STORE_CLOSED")

    session_id = uuid4().hex
    session_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    get_db_reference(f"sessions/{session_id}").set({
        "storeId": store_id,
        "status": "active",
        "createdAt": time.time_ns() // 1_000_000,
        "tokenHash": token_hash,
    })

    return {
        "sessionId": session_id,
        "storeId": store_id,
        "sessionToken": session_token,
    }


def get_session_cart(session_id: str, session_token: str) -> dict:
    """품절·삭제된 메뉴도 표시하여 사용자가 장바구니를 복구하도록 한다."""

    session = _get_authenticated_session(session_id, session_token)
    store_id = session["storeId"]
    cart = session.get("cart") or {}
    saved_items = cart.get("items") or {}

    items = []
    total_price = 0
    has_unavailable_items = False

    for item_id, item in saved_items.items():
        menu_id = item["menuId"]
        menu = get_db_reference(
            f"menus/{store_id}/{menu_id}"
        ).get()

        is_available = (
            menu is not None
            and menu.get("isAvailable") is True
        )
        if not is_available:
            has_unavailable_items = True

        options = item.get("selectedOptions") or {}
        quantity = item["quantity"]
        _validate_quantity(quantity)

        if menu is None:
            items.append({
                "itemId": item_id,
                "menuId": menu_id,
                "name": "판매 종료된 메뉴",
                "quantity": quantity,
                "selectedOptions": options,
                "unitPrice": None,
                "subtotal": None,
                "isAvailable": False,
            })
            continue

        try:
            unit_price = _calculate_unit_price(menu, options)
            subtotal = unit_price * quantity
        except (ValueError, KeyError, TypeError):
            has_unavailable_items = True
            is_available = False
            unit_price = None
            subtotal = None

        if is_available and subtotal is not None:
            total_price += subtotal

        items.append({
            "itemId": item_id,
            "menuId": menu_id,
            "name": menu["name"],
            "quantity": quantity,
            "selectedOptions": options,
            "unitPrice": unit_price,
            "subtotal": subtotal,
            "isAvailable": is_available,
        })

    return {
        "sessionId": session_id,
        "items": items,
        "totalPrice": total_price,
        "canCheckout": not has_unavailable_items,
    }


def add_cart_item(
    session_id: str,
    session_token: str,
    menu_id: str,
    quantity: int,
    selected_options: dict,
) -> dict:
    """메뉴·수량·옵션을 검증하고 새 항목을 추가한다."""

    session = _get_authenticated_session(session_id, session_token)
    store_id = session["storeId"]
    menu = get_db_reference(
        f"menus/{store_id}/{menu_id}"
    ).get()

    if menu is None:
        raise ValueError("MENU_NOT_FOUND")

    if menu.get("isAvailable") is not True:
        raise ValueError("MENU_SOLD_OUT")

    _validate_quantity(quantity)
    _calculate_unit_price(menu, selected_options)

    get_session_cart(session_id, session_token)

    item_id = uuid4().hex
    get_db_reference(
        f"sessions/{session_id}/cart/items/{item_id}"
    ).set({
        "menuId": menu_id,
        "quantity": quantity,
        "selectedOptions": selected_options,
    })

    return get_session_cart(session_id, session_token)


def update_cart_item(
    session_id: str,
    session_token: str,
    item_id: str,
    changes: dict,
) -> dict:
    """기존 옵션을 유지하며 전달받은 값만 변경한다."""

    session = _get_authenticated_session(session_id, session_token)
    item_ref = get_db_reference(
        f"sessions/{session_id}/cart/items/{item_id}"
    )
    current_item = item_ref.get()

    if current_item is None:
        raise ValueError("CART_ITEM_NOT_FOUND")

    store_id = session["storeId"]
    menu_id = current_item["menuId"]
    menu = get_db_reference(
        f"menus/{store_id}/{menu_id}"
    ).get()

    if menu is None or menu.get("isAvailable") is not True:
        raise ValueError("CART_MENU_UNAVAILABLE")

    quantity = changes.get("quantity", current_item["quantity"])
    options = dict(current_item.get("selectedOptions") or {})

    if "selectedOptions" in changes:
        changed_options = changes["selectedOptions"]
        options.update(changed_options)

        if (
            changed_options.get("temperature") == "hot"
            and "ice" not in changed_options
        ):
            options.pop("ice", None)

    _validate_quantity(quantity)
    _calculate_unit_price(menu, options)

    item_ref.update({
        "quantity": quantity,
        "selectedOptions": options or None,
    })

    return get_session_cart(session_id, session_token)


def delete_cart_item(
    session_id: str,
    session_token: str,
    item_id: str,
) -> dict:
    """품절 항목을 포함해 개별 장바구니 항목을 삭제한다."""

    _get_authenticated_session(session_id, session_token)
    item_ref = get_db_reference(
        f"sessions/{session_id}/cart/items/{item_id}"
    )

    if item_ref.get() is None:
        raise ValueError("CART_ITEM_NOT_FOUND")

    item_ref.delete()
    return get_session_cart(session_id, session_token)


def clear_cart(
    session_id: str,
    session_token: str,
) -> dict:
    """세션 인증 후 장바구니의 모든 항목을 삭제한다."""

    _get_authenticated_session(session_id, session_token)
    get_db_reference(
        f"sessions/{session_id}/cart/items"
    ).delete()

    return get_session_cart(session_id, session_token)
