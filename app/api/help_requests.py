"""직원 호출 API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from app.schemas.help_requests import HelpRequestCreate
from app.services.help_requests import (
    create_help_request,
    get_store_help_requests,
    finish_help_request,
)

router = APIRouter(
    prefix="/api/help-requests",
    tags=["help-requests"]
)

admin_router = APIRouter(
    prefix="/api/admin/help-requests",
    tags=["admin-help-requests"],
)

security = HTTPBearer(auto_error=False)


@router.post("")
def create_help_request_api(
    payload: HelpRequestCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    session_token = (
        credentials.credentials if credentials else ""
    )

    try:
        return create_help_request(
            session_id=payload.session_id,
            session_token=session_token,
        )

    except ValueError as exc:
        error_code = str(exc)

        if error_code == "SESSION_UNAUTHORIZED":
            raise HTTPException(
                status_code=401,
                detail="유효하지 않은 세션입니다."
            )

        if error_code == "SESSION_INACTIVE":
            raise HTTPException(
                status_code=403,
                detail="사용할 수 없는 세션입니다."
            )

        if error_code == "HELP_REQUEST_ALREADY_PENDING":
            raise HTTPException(
                status_code=409,
                detail="이미 처리 대기 중인 직원 호출이 있습니다."
            )

        raise
@admin_router.get("")
def read_help_requests(
    store_id: str = Query(
        alias="storeId",
        min_length=1,
    ),
):
    """매장의 직원 호출 목록을 조회한다."""

    requests = get_store_help_requests(
        store_id=store_id
    )

    return {
        "helpRequests": requests,
    }
@admin_router.patch("/{request_id}")
def complete_help_request_api(
    request_id: str,
    store_id: str = Query(alias="storeId", min_length=1),
):
    try:
        return finish_help_request(
            request_id=request_id,
            store_id=store_id,
        )

    except ValueError as exc:
        error_code = str(exc)

        if error_code == "HELP_REQUEST_NOT_FOUND":
            raise HTTPException(
                status_code=404,
                detail="직원 호출을 찾을 수 없습니다."
            )

        if error_code == "HELP_REQUEST_STORE_MISMATCH":
            raise HTTPException(
                status_code=403,
                detail="해당 매장의 직원 호출이 아닙니다."
            )

        if error_code in (
            "HELP_REQUEST_INVALID_STATUS",
            "HELP_REQUEST_ALREADY_COMPLETED",
        ):
            raise HTTPException(
                status_code=409,
                detail="완료 처리할 수 없는 직원 호출입니다."
            )

        raise