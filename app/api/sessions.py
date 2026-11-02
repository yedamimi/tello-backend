"""주문 세션 API."""

from fastapi import APIRouter, Depends, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import JSONResponse

from app.schemas.sessions import (
    SessionCreateRequest,
    SessionCreateResponse,
    CartItemAddRequest,
    CartItemUpdateRequest,
)
from app.services.sessions import (
    create_session,
    get_session_cart,
    add_cart_item,
    update_cart_item,
    delete_cart_item,
    clear_cart,
    end_session,
)

router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
)


@router.post(
    "",
    response_model=SessionCreateResponse,
    status_code=201,
)
def create_order_session(request: SessionCreateRequest):
    """매장을 확인하고 주문 세션을 생성한다."""

    try:
        return create_session(request.store_id)
    except ValueError as exc:
        code = str(exc)

        if code == "STORE_NOT_FOUND":
            return JSONResponse(
                status_code=404,
                content={
                    "code": code,
                    "message": "존재하지 않는 매장이에요.",
                },
            )

        if code == "STORE_CLOSED":
            return JSONResponse(
                status_code=409,
                content={
                    "code": code,
                    "message": "지금은 주문을 받지 않아요.",
                },
            )

        raise


bearer_scheme = HTTPBearer(auto_error=False)


@router.get("/{sessionId}/cart")
def read_cart(
    session_id: str = Path(
        alias="sessionId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """고객 본인의 장바구니를 조회한다."""

    session_token = (
        credentials.credentials if credentials else ""
    )

    try:
        return get_session_cart(session_id, session_token)

    except ValueError as exc:
        code = str(exc)

        errors = {
            "SESSION_UNAUTHORIZED": (
                401,
                "주문 세션 인증을 확인해 주세요.",
            ),
            "SESSION_INACTIVE": (
                409,
                "현재 사용할 수 없는 주문 세션이에요.",
            ),
            "CART_MENU_UNAVAILABLE": (
                409,
                "장바구니에 판매할 수 없는 메뉴가 있어요.",
            ),
            "CART_OPTION_INVALID": (
                409,
                "장바구니의 옵션을 다시 확인해 주세요.",
            ),
            "CART_QUANTITY_INVALID": (
                409,
                "장바구니의 수량을 다시 확인해 주세요.",
            ),
        }

        if code not in errors:
            raise

        status_code, message = errors[code]

        return JSONResponse(
            status_code=status_code,
            content={"code": code, "message": message},
            headers=(
                {"WWW-Authenticate": "Bearer"}
                if status_code == 401
                else None
            ),
        )

@router.post("/{sessionId}/cart/items")
def create_cart_item(
    request: CartItemAddRequest,
    session_id: str = Path(
        alias="sessionId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """메뉴를 추가하고 갱신된 장바구니를 반환한다."""

    session_token = (
        credentials.credentials if credentials else ""
    )

    try:
        return add_cart_item(
            session_id=session_id,
            session_token=session_token,
            menu_id=request.menu_id,
            quantity=request.quantity,
            selected_options=request.selected_options.model_dump(
                exclude_none=True
            ),
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
            "MENU_NOT_FOUND": (
                404, "존재하지 않는 메뉴예요."
            ),
            "MENU_SOLD_OUT": (
                409, "품절된 메뉴예요."
            ),
            "CART_MENU_UNAVAILABLE": (
                409, "장바구니에 판매할 수 없는 메뉴가 있어요."
            ),
            "CART_OPTION_INVALID": (
                409, "메뉴의 크기 옵션을 확인해 주세요."
            ),
            "CART_QUANTITY_INVALID": (
                409, "수량을 확인해 주세요."
            ),
        }

        if code not in errors:
            raise

        status_code, message = errors[code]

        return JSONResponse(
            status_code=status_code,
            content={"code": code, "message": message},
            headers=(
                {"WWW-Authenticate": "Bearer"}
                if status_code == 401
                else None
            ),
        )

@router.patch("/{sessionId}/cart/items/{itemId}")
def change_cart_item(
    request: CartItemUpdateRequest,
    session_id: str = Path(
        alias="sessionId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    item_id: str = Path(
        alias="itemId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """수량·옵션을 변경하고 장바구니를 반환한다."""

    session_token = (
        credentials.credentials if credentials else ""
    )

    try:
        return update_cart_item(
            session_id=session_id,
            session_token=session_token,
            item_id=item_id,
            changes=request.model_dump(
                by_alias=True,
                exclude_unset=True,
                exclude_none=True,
            ),
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
            "CART_ITEM_NOT_FOUND": (
                404, "장바구니에 해당 항목이 없어요."
            ),
            "CART_MENU_UNAVAILABLE": (
                409, "장바구니에 판매할 수 없는 메뉴가 있어요."
            ),
            "CART_OPTION_INVALID": (
                409, "메뉴의 크기 옵션을 확인해 주세요."
            ),
            "CART_QUANTITY_INVALID": (
                409, "수량을 확인해 주세요."
            ),
        }

        if code not in errors:
            raise

        status_code, message = errors[code]

        return JSONResponse(
            status_code=status_code,
            content={"code": code, "message": message},
            headers=(
                {"WWW-Authenticate": "Bearer"}
                if status_code == 401
                else None
            ),
        )
@router.delete("/{sessionId}/cart/items/{itemId}")
def remove_cart_item(
    session_id: str = Path(
        alias="sessionId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    item_id: str = Path(
        alias="itemId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """메뉴를 삭제하고 갱신된 장바구니를 반환한다."""

    session_token = (
        credentials.credentials if credentials else ""
    )

    try:
        return delete_cart_item(
            session_id,
            session_token,
            item_id,
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
            "CART_ITEM_NOT_FOUND": (
                404, "장바구니에 해당 항목이 없어요."
            ),
            "CART_MENU_UNAVAILABLE": (
                409, "남은 장바구니에 판매할 수 없는 메뉴가 있어요."
            ),
            "CART_OPTION_INVALID": (
                409, "남은 장바구니의 옵션을 확인해 주세요."
            ),
            "CART_QUANTITY_INVALID": (
                409, "남은 장바구니의 수량을 확인해 주세요."
            ),
        }

        if code not in errors:
            raise

        status_code, message = errors[code]

        return JSONResponse(
            status_code=status_code,
            content={"code": code, "message": message},
            headers=(
                {"WWW-Authenticate": "Bearer"}
                if status_code == 401
                else None
            ),
        )
        

@router.delete("/{sessionId}/cart")
def clear_session_cart(
    session_id: str = Path(
        alias="sessionId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """세션의 장바구니를 전체 비우고 갱신된 결과를 반환한다."""

    session_token = (
        credentials.credentials if credentials else ""
    )

    try:
        return clear_cart(session_id, session_token)

    except ValueError as exc:
        code = str(exc)

        errors = {
            "SESSION_UNAUTHORIZED": (
                401,
                "주문 세션 인증을 확인해 주세요.",
            ),
            "SESSION_INACTIVE": (
                409,
                "현재 사용할 수 없는 주문 세션이에요.",
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


@router.post("/{sessionId}/end")
def end_order_session(
    session_id: str = Path(
        alias="sessionId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """고객의 주문 세션을 명시적으로 종료한다."""

    session_token = (
        credentials.credentials if credentials else ""
    )

    try:
        return end_session(
            session_id=session_id,
            session_token=session_token,
        )

    except ValueError as exc:
        code = str(exc)

        errors = {
            "SESSION_UNAUTHORIZED": (
                401,
                "주문 세션 인증을 확인해 주세요.",
            ),
            "SESSION_INACTIVE": (
                409,
                "현재 사용할 수 없는 주문 세션이에요.",
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
