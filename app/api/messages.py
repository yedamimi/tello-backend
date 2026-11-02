
"""음성 주문 분석 및 미완성 주문 취소 API."""

from fastapi import APIRouter, Depends, Header, Path
from fastapi.responses import JSONResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from app.schemas.messages import MessageRequest
from app.services.messages import (
    cancel_pending_order,
    process_order_message,
)


router = APIRouter(
    prefix="/api/sessions",
    tags=["messages"],
)

bearer_scheme = HTTPBearer(auto_error=False)


ERRORS = {
    "SESSION_UNAUTHORIZED": (
        401, "주문 세션 인증에 실패했어요."
    ),
    "SESSION_INACTIVE": (
        409, "사용할 수 없는 주문 세션이에요."
    ),
    "STORE_NOT_FOUND": (
        404, "매장을 찾을 수 없어요."
    ),
    "MENU_NOT_FOUND": (
        404, "메뉴를 찾을 수 없어요."
    ),
    "MENU_SOLD_OUT": (
        409, "품절된 메뉴예요."
    ),
    "MESSAGE_TEXT_INVALID": (
        422, "올바른 주문 문장을 입력해 주세요."
    ),
    "MESSAGE_NO_ITEMS": (
        422, "추가할 메뉴를 확인할 수 없어요."
    ),
    "CART_MENU_UNAVAILABLE": (
        409, "판매할 수 없는 메뉴가 있어요."
    ),
    "CART_OPTION_INVALID": (
        409, "메뉴 옵션을 다시 확인해 주세요."
    ),
    "CART_QUANTITY_INVALID": (
        409, "주문 수량을 다시 확인해 주세요."
    ),
    "PENDING_ORDER_INVALID": (
        409, "이전 주문 정보를 확인할 수 없어요."
    ),
    "LLM_TIMEOUT": (
        504, "주문 분석 시간이 초과됐어요."
    ),
    "LLM_EMPTY_RESPONSE": (
        502, "주문 분석 결과가 비어 있어요."
    ),
    "LLM_INVALID_RESPONSE": (
        502, "주문 분석 결과가 올바르지 않아요."
    ),
    "LLM_API_ERROR": (
        502, "주문 분석 서비스에 문제가 발생했어요."
    ),
    "GEMINI_API_KEY_MISSING": (
        503, "주문 분석 서비스 설정을 확인해 주세요."
    ),
    "GEMINI_MODEL_MISSING": (
        503, "주문 분석 모델 설정을 확인해 주세요."
    ),
}


def get_session_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    if not credentials:
        return ""

    if credentials.scheme.lower() != "bearer":
        return ""

    return credentials.credentials


def error_response(exc: ValueError):
    code = str(exc)

    if code not in ERRORS:
        raise exc

    status_code, message = ERRORS[code]

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


@router.post("/{sessionId}/messages")
def analyze_message(
    request: MessageRequest,
    session_id: str = Path(
        alias="sessionId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """메시지 분석 및 주문 처리."""

    token = get_session_token(credentials)

    try:
        return process_order_message(
            session_id=session_id,
            session_token=token,
            text=request.text,
        )
    except ValueError as exc:
        return error_response(exc)


@router.delete("/{sessionId}/pending-order")
def delete_pending_order(
    session_id: str = Path(
        alias="sessionId",
        pattern=r"^[a-f0-9]{32}$",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
):
    """음성 주문 도중 메뉴판 전환 시 미완성 주문만 삭제."""

    token = get_session_token(credentials)

    try:
        return cancel_pending_order(
            session_id=session_id,
            session_token=token,
        )
    except ValueError as exc:
        return error_response(exc)
