"""직원 호출 처리 로직."""

import time
from uuid import uuid4

from app.repositories.help_requests import (
    create_help_request_if_not_pending,
    complete_help_request,
)
from app.services.sessions import _get_authenticated_session

from app.repositories.help_requests import get_help_requests as find_help_requests


def get_store_help_requests(store_id: str) -> list[dict]:
    """매장별 직원 호출 목록을 조회한다."""

    return find_help_requests(store_id)

def create_help_request(
    session_id: str,
    session_token: str
) -> dict:
    # 고객 세션 인증
    session = _get_authenticated_session(
        session_id,
        session_token
    )

    # 호출 데이터 생성
    request_id = uuid4().hex
    now_ms = time.time_ns() // 1_000_000

    help_request = {
        "requestId": request_id,
        "sessionId": session_id,
        "storeId": session["storeId"],
        "status": "pending",
        "createdAt": now_ms,
        "completedAt": None,
    }

    # 중복 호출 확인 및 저장
    created = create_help_request_if_not_pending(
        help_request
    )

    if not created:
        raise ValueError("HELP_REQUEST_ALREADY_PENDING")

    return {
        "requestId": request_id,
        "status": "pending",
    }
def finish_help_request(
    request_id: str,
    store_id: str
) -> dict:
    """직원 호출을 완료 처리한다."""

    result = complete_help_request(
        request_id=request_id,
        store_id=store_id
    )

    return {
        "requestId": request_id,
        "status": result["status"],
        "completedAt": result["completedAt"],
    }