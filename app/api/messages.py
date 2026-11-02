
"""음성 주문 메시지 API."""

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from app.schemas.messages import MessageRequest
from app.services.messages import process_order_message


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
    "CART_ITEM_NOT_FOUND": (
        404, "장바구니 항목을 찾을 수 없어요."
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
    "FOLLOWUP_NOT_RESOLVED": (
        409, "답변을 이해하지 못했어요. 다시 말씀해 주세요."
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
}


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
    """고객 메시지를 분석하고 주문 상태를 처리한다."""

    session_token = (
        credentials.credentials
        if credentials
        and credentials.scheme.lower() == "bearer"
        else ""
    )

    try:
        return process_order_message(
            session_id=session_id,
            session_token=session_token,
            text=request.text,
        )

    except ValueError as exc:
        code = str(exc)

        if code not in ERRORS:
            raise

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
