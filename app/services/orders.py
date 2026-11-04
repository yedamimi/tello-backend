
"""주문 확정·저장 및 조회 로직."""

import hashlib
import secrets
import time
from uuid import uuid4

from app.core.firebase import get_db_reference
from app.services.sessions import (
    _calculate_unit_price,
    _validate_quantity,
)
# 주문 상태별 이미지 ID
ORDER_STATUS_IMAGES = {
    "pending": "order_complete",
    "preparing": "preparing",
    "completed": "ready",
}


def get_status_image(status: str) -> str:
    """주문 상태에 맞는 이미지 ID를 반환한다."""

    image_id = ORDER_STATUS_IMAGES.get(status)

    if image_id is None:
        raise ValueError("ORDER_STATUS_INVALID")

    return image_id

def _hash_idempotency_key(key: str) -> str:
    """중복 방지 키를 해시한다."""

    return hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()


def _build_order(
    session_id: str,
    session: dict,
    menus: dict,
) -> dict:
    """장바구니를 검증하고 주문 데이터를 생성한다."""

    cart = session.get("cart") or {}
    saved_items = cart.get("items") or {}

    if not isinstance(saved_items, dict) or not saved_items:
        raise ValueError("CART_EMPTY")

    items = []
    total_price = 0

    for item_id, item in saved_items.items():

        if not isinstance(item, dict):
            raise ValueError("CART_MENU_UNAVAILABLE")

        menu_id = item.get("menuId")
        menu = menus.get(menu_id)

        # 메뉴 존재 여부와 품절 여부 확인
        if (
            not isinstance(menu, dict)
            or menu.get("isAvailable") is not True
            or not isinstance(menu.get("name"), str)
            or not menu.get("name")
        ):
            raise ValueError("CART_MENU_UNAVAILABLE")

        # 수량 검증
        quantity = item.get("quantity")
        _validate_quantity(quantity)

        # 옵션 검증 및 최신 가격 계산
        options = item.get("selectedOptions") or {}

        if not isinstance(options, dict):
            raise ValueError("CART_OPTION_INVALID")

        unit_price = _calculate_unit_price(
            menu,
            options,
        )

        subtotal = unit_price * quantity
        total_price += subtotal

        items.append({
            "itemId": item_id,
            "menuId": menu_id,
            "name": menu["name"],
            "quantity": quantity,
            "selectedOptions": options,
            "unitPrice": unit_price,
            "subtotal": subtotal,
        })

    # 세션 하나당 주문 하나
    order_id = session_id

    # 주문 번호 생성
    order_number = uuid4().hex[:8].upper()

    return {
        "orderId": order_id,
        "orderNumber": order_number,
        "sessionId": session_id,
        "storeId": session["storeId"],
        "status": "pending",
        "imageId": get_status_image("pending"),
        "items": items,
        "totalPrice": total_price,
        "createdAt": time.time_ns() // 1_000_000,
    }


def _normalize_order_response(order: dict) -> dict:
    """Firebase?? ??? ? ?? ??? API ??? ????."""
    result = dict(order)
    result["items"] = [
        {
            **item,
            "selectedOptions": item.get("selectedOptions") or {},
        }
        for item in result.get("items", [])
    ]
    return result


def create_order(
    session_id: str,
    session_token: str,
    idempotency_key: str,
) -> dict:
    """주문을 검증하고 중복 없이 확정한다."""

    # 중복 방지 키 검증
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or len(idempotency_key) > 128
    ):
        raise ValueError("IDEMPOTENCY_KEY_INVALID")

    session_ref = get_db_reference(
        f"sessions/{session_id}"
    )

    session = session_ref.get()

    if session is None or not session_token:
        raise ValueError("SESSION_UNAUTHORIZED")

    # 세션 토큰 검증
    token_hash = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    if not secrets.compare_digest(
        token_hash,
        session.get("tokenHash") or "",
    ):
        raise ValueError("SESSION_UNAUTHORIZED")

    key_hash = _hash_idempotency_key(idempotency_key)

    # 이미 주문된 세션인지 확인
    if session.get("status") == "ordered":

        if session.get("idempotencyKeyHash") == key_hash:
            order = session.get("order")

            if order:
                return _normalize_order_response(order)

            raise ValueError("ORDER_CONFIRM_FAILED")

        raise ValueError("ORDER_ALREADY_CONFIRMED")

    if session.get("status") != "active":
        raise ValueError("SESSION_INACTIVE")

    store_id = session.get("storeId")

    if not store_id:
        raise ValueError("SESSION_INACTIVE")

    # 장바구니의 메뉴를 Firebase에서 다시 조회
    cart = session.get("cart") or {}
    saved_items = cart.get("items") or {}

    if not saved_items:
        raise ValueError("CART_EMPTY")

    menus = {}

    for item in saved_items.values():

        if not isinstance(item, dict):
            raise ValueError("CART_MENU_UNAVAILABLE")
        
        menu_id = item.get("menuId")

        if not menu_id:
            raise ValueError("CART_MENU_UNAVAILABLE")

        if menu_id not in menus:
            menus[menu_id] = get_db_reference(
                f"menus/{store_id}/{menu_id}"
            ).get()

    # 최종 가격, 수량, 옵션, 품절 검증
    order = _build_order(
        session_id,
        session,
        menus,
    )

    # 트랜잭션 시작 전 장바구니 상태 보관
    original_cart = session.get("cart") or {}

    def confirm_transaction(current):
        """세션과 주문을 하나의 트랜잭션으로 변경한다."""

        if current is None:
            return current

        # 인증 정보 재확인
        current_token_hash = current.get("tokenHash") or ""

        if not secrets.compare_digest(
            token_hash,
            current_token_hash,
        ):
            return current

        # 이미 다른 요청에서 주문이 확정된 경우
        if current.get("status") == "ordered":
            return current

        if current.get("status") != "active":
            return current

        # 매장이 변경된 경우 확정하지 않음
        if current.get("storeId") != store_id:
            return current

        # 검증 도중 장바구니가 변경된 경우 확정하지 않음
        if (current.get("cart") or {}) != original_cart:
            return current

        updated = dict(current)

        # 세션 상태 변경
        updated["status"] = "ordered"

        # 주문 정보 저장
        updated["orderId"] = session_id
        updated["idempotencyKeyHash"] = key_hash
        updated["order"] = order

        return updated

    # Firebase 트랜잭션 실행
    session_ref.transaction(confirm_transaction)

    # 실제 저장된 데이터 다시 조회
    saved_session = session_ref.get()

    if saved_session is None:
        raise ValueError("SESSION_UNAUTHORIZED")

    # 저장 결과의 인증 정보 확인
    saved_token_hash = saved_session.get("tokenHash") or ""

    if not secrets.compare_digest(
        token_hash,
        saved_token_hash,
    ):
        raise ValueError("SESSION_UNAUTHORIZED")

    # 주문이 이미 확정된 경우
    if saved_session.get("status") == "ordered":

        if saved_session.get("idempotencyKeyHash") == key_hash:
            saved_order = saved_session.get("order")

            if saved_order:
                return _normalize_order_response(saved_order)

            raise ValueError("ORDER_CONFIRM_FAILED")

        raise ValueError("ORDER_ALREADY_CONFIRMED")

    if saved_session.get("status") != "active":
        raise ValueError("SESSION_INACTIVE")

    # 장바구니 변경 여부 확인
    if (saved_session.get("cart") or {}) != original_cart:
        raise ValueError("CART_CHANGED")

    if saved_session.get("storeId") != store_id:
        raise ValueError("ORDER_CONFIRM_FAILED")

    raise ValueError("ORDER_CONFIRM_FAILED")


def get_order(
    order_id: str,
    session_token: str,
) -> dict:
    """본인의 주문 결과와 상태를 조회한다."""

    if not session_token:
        raise ValueError("SESSION_UNAUTHORIZED")

    # 주문 ID는 세션 ID와 동일하게 사용
    session = get_db_reference(
        f"sessions/{order_id}"
    ).get()

    if session is None:
        raise ValueError("ORDER_NOT_FOUND")

    # 세션 소유자 인증
    token_hash = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    if not secrets.compare_digest(
        token_hash,
        session.get("tokenHash") or "",
    ):
        raise ValueError("SESSION_UNAUTHORIZED")

    # 주문 확정 여부 확인
    if session.get("status") != "ordered":
        raise ValueError("ORDER_NOT_FOUND")

    order = session.get("order")

    if not order:
        raise ValueError("ORDER_NOT_FOUND")

    # 현재 주문 상태에 맞는 이미지 ID 반환 
    order["imageId"] = get_status_image(
        order["status"]
    )

    return _normalize_order_response(order)

def update_order_status(
    order_id: str,
    new_status: str,
    store_id: str,
) -> dict:
    """주문 상태를 다음 단계로 변경한다."""

    # 허용되는 상태 전이
    allowed_transitions = {
        "pending": "preparing",
        "preparing": "completed",
    }

    if new_status not in ("preparing", "completed"):
        raise ValueError("ORDER_STATUS_INVALID")

    session_ref = get_db_reference(
        f"sessions/{order_id}"
    )

    def update_transaction(current):
        """주문 상태를 트랜잭션으로 변경한다."""

        if current is None:
            raise ValueError("ORDER_NOT_FOUND")
        
        if current.get("storeId") != store_id:
            raise ValueError("ORDER_NOT_FOUND")

        if current.get("status") != "ordered":
            raise ValueError("ORDER_NOT_FOUND")

        order = current.get("order")

        if not isinstance(order, dict):
            raise ValueError("ORDER_NOT_FOUND")

        current_status = order.get("status")

        # 이미 같은 상태라면 그대로 반환
        if current_status == new_status:
            return current

        # 다음 단계로만 변경 허용
        if allowed_transitions.get(current_status) != new_status:
            raise ValueError("ORDER_STATUS_INVALID")

        updated = dict(current)
        updated_order = dict(order)

        updated_order["status"] = new_status
        updated_order["imageId"] = get_status_image(
            new_status
        )

        updated["order"] = updated_order

        return updated

    # Firebase 트랜잭션 실행
    session_ref.transaction(update_transaction)

    # 변경된 주문 다시 조회
    saved_session = session_ref.get()

    if saved_session is None:
        raise ValueError("ORDER_NOT_FOUND")

    if saved_session.get("status") != "ordered":
        raise ValueError("ORDER_NOT_FOUND")

    saved_order = saved_session.get("order")

    if not isinstance(saved_order, dict):
        raise ValueError("ORDER_NOT_FOUND")

    if saved_order.get("status") != new_status:
        raise ValueError("ORDER_STATUS_INVALID")

    return {
        "orderId": order_id,
        "status": saved_order["status"],
        "imageId": get_status_image(
            saved_order["status"]
        ),
    }
def get_orders(store_id: str) -> list[dict]:
    """매장의 전체 주문 목록을 최신순으로 조회한다."""

    if not store_id:
        raise ValueError("STORE_ID_INVALID")

    sessions = get_db_reference("sessions").get()

    if not isinstance(sessions, dict):
        return []

    orders = []

    for session_id, session in sessions.items():
        if not isinstance(session, dict):
            continue

        if session.get("status") != "ordered":
            continue

        if session.get("storeId") != store_id:
            continue

        order = session.get("order")

        if not isinstance(order, dict):
            continue

        order_data = dict(order)
        order_data["orderId"] = session_id
        order_data["imageId"] = get_status_image(
            order_data["status"]
        )

        orders.append(_normalize_order_response(order_data))

    orders.sort(
        key=lambda order: order.get("createdAt", 0),
        reverse=True,
    )

    return orders
def get_admin_order(
    order_id: str,
    store_id: str,
) -> dict:
    """관리자 담당 매장의 주문 상세 정보를 조회한다."""

    session = get_db_reference(
        f"sessions/{order_id}"
    ).get()

    if not isinstance(session, dict):
        raise ValueError("ORDER_NOT_FOUND")

    if session.get("status") != "ordered":
        raise ValueError("ORDER_NOT_FOUND")

    if session.get("storeId") != store_id:
        raise ValueError("ORDER_NOT_FOUND")

    order = session.get("order")

    if not isinstance(order, dict):
        raise ValueError("ORDER_NOT_FOUND")

    order_data = dict(order)
    order_data["orderId"] = order_id
    order_data["imageId"] = get_status_image(
        order_data["status"]
    )

    return _normalize_order_response(order_data)
