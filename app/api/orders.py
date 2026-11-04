
"""주문 확정·조회 API."""

from fastapi import APIRouter, Depends, Header, Path
from app.core.security import get_current_admin
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.schemas.orders import (
    OrderCreateRequest,
    OrderCreateResponse,
    OrderReadResponse,
    OrderStatusUpdateRequest,
    OrderStatusUpdateResponse,
    OrderListResponse,
)
from app.services.orders import (
    create_order,
    get_order,
    update_order_status,
    get_orders,
    get_admin_order,
)

router = APIRouter(
    prefix="/orders",
    tags=["orders"],
)
admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
)

bearer_scheme = HTTPBearer(auto_error=False)


def get_session_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    """Bearer 토큰을 반환한다."""

    return credentials.credentials if credentials else ""


@router.post(
    "",
    response_model=OrderCreateResponse,
    status_code=201,
)
def confirm_order(
    request: OrderCreateRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """주문을 확정하고 저장한다."""

    session_token = get_session_token(credentials)

    try:
        return create_order(
            session_id=request.session_id,
            session_token=session_token,
            idempotency_key=idempotency_key,
        )

    except ValueError as exc:
        code = str(exc)

        errors = {
            "SESSION_UNAUTHORIZED": (
                401, "주문 세션 인증을 확인해 주세요."
            ),
            "SESSION_INACTIVE": (
                409, "현재 사용할 수 없는 주문 세션이에요."
            ),
            "CART_EMPTY": (
                409, "장바구니가 비어 있어요."
            ),
            "CART_MENU_UNAVAILABLE": (
                409, "품절되었거나 판매할 수 없는 메뉴가 있어요."
            ),
            "CART_OPTION_INVALID": (
                409, "메뉴 옵션을 다시 확인해 주세요."
            ),
            "CART_QUANTITY_INVALID": (
                409, "주문 수량을 다시 확인해 주세요."
            ),
            "IDEMPOTENCY_KEY_INVALID": (
                400, "중복 방지 키가 올바르지 않아요."
            ),
            "ORDER_ALREADY_CONFIRMED": (
                409, "이미 주문이 확정된 세션이에요."
            ),
            "CART_CHANGED": (
                409, "장바구니가 변경되었어요. 다시 확인해 주세요."
            ),
            "ORDER_CONFIRM_FAILED": (
                409, "주문 확정에 실패했어요. 다시 시도해 주세요."
            ),
        }

        if code not in errors:
            raise

        status_code, message = errors[code]

        return JSONResponse(
            status_code=status_code,
            content={
                "code": code,
                "message": message,
            },
            headers=(
                {"WWW-Authenticate": "Bearer"}
                if status_code == 401
                else None
            ),
        )


@router.get(
    "/{orderId}",
    response_model=OrderReadResponse,
)
def read_order(
    order_id: str = Path(
        alias="orderId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """본인의 주문 상태를 조회한다."""

    session_token = get_session_token(credentials)

    try:
        return get_order(
            order_id=order_id,
            session_token=session_token,
        )

    except ValueError as exc:
        code = str(exc)

        errors = {
            "SESSION_UNAUTHORIZED": (
                401, "주문 세션 인증을 확인해 주세요."
            ),
            "ORDER_NOT_FOUND": (
                404, "주문을 찾을 수 없어요."
            ),
        }

        if code not in errors:
            raise

        status_code, message = errors[code]

        return JSONResponse(
            status_code=status_code,
            content={
                "code": code,
                "message": message,
            },
            headers=(
                {"WWW-Authenticate": "Bearer"}
                if status_code == 401
                else None
            ),
        )

@admin_router.patch(
    "/orders/{orderId}/status",
    response_model=OrderStatusUpdateResponse,
)
def change_order_status(
    request: OrderStatusUpdateRequest,
    order_id: str = Path(
        alias="orderId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    admin: dict = Depends(get_current_admin),
):
    """주문 상태를 다음 단계로 변경한다."""

    try:
        return update_order_status(
            order_id=order_id,
            new_status=request.status,
            store_id=admin["storeId"],
        )

    except ValueError as exc:
        code = str(exc)

        errors = {
            "ORDER_NOT_FOUND": (
                404, "주문을 찾을 수 없어요."
            ),
            "ORDER_STATUS_INVALID": (
                409, "변경할 수 없는 주문 상태예요."
            ),
        }

        if code not in errors:
            raise

        status_code, message = errors[code]

        return JSONResponse(
            status_code=status_code,
            content={
                "code": code,
                "message": message,
            },
        )

@admin_router.get(
    "/orders",
    response_model=OrderListResponse,
)
def read_orders(
    admin: dict = Depends(get_current_admin),
):
    """관리자 담당 매장의 전체 주문 목록을 조회한다."""

    orders = get_orders(store_id=admin["storeId"])

    return {
        "orders": orders,
    }
@admin_router.get(
    "/orders/{orderId}",
    response_model=OrderReadResponse,
)
def read_admin_order(
    order_id: str = Path(
        alias="orderId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    admin: dict = Depends(get_current_admin),
):
    """관리자 담당 매장의 주문 상세 조회."""

    try:
        return get_admin_order(
            order_id=order_id,
            store_id=admin["storeId"],
        )

    except ValueError as exc:
        if str(exc) == "ORDER_NOT_FOUND":
            return JSONResponse(
                status_code=404,
                content={"detail": "ORDER_NOT_FOUND"},
            )

        raise