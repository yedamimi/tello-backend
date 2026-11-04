"""직원 호출 데이터 저장소."""

from app.core.firebase import get_db_reference
import time

def create_help_request_if_not_pending(help_request: dict) -> bool:
    requests_ref = get_db_reference("help_requests")

    request_id = help_request["requestId"]
    session_id = help_request["sessionId"]

    def update_requests(current):
        if not isinstance(current, dict):
            current = {}

        # 같은 세션에 처리되지 않은 호출이 있는지 확인
        for request in current.values():
            if (
                isinstance(request, dict)
                and request.get("sessionId") == session_id
                and request.get("status") == "pending"
            ):
                return current

        # 미처리 호출이 없다면 새 호출 저장
        updated = dict(current)
        updated[request_id] = help_request

        return updated

    result = requests_ref.transaction(update_requests)

    return (
        isinstance(result, dict)
        and request_id in result
    )
def get_help_requests(store_id: str) -> list[dict]:
    """특정 매장의 직원 호출 목록을 조회한다."""

    if not store_id:
        raise ValueError("STORE_ID_INVALID")

    requests = get_db_reference("help_requests").get()

    if not isinstance(requests, dict):
        return []

    result = []

    for request_id, request in requests.items():
        if not isinstance(request, dict):
            continue

        if request.get("storeId") != store_id:
            continue

        request_data = dict(request)
        request_data["requestId"] = request_id

        result.append(request_data)

    result.sort(
        key=lambda request: request.get("createdAt", 0),
        reverse=True,
    )

    return result



def complete_help_request(
    request_id: str,
    store_id: str
) -> dict:
    """직원 호출을 완료 처리한다."""

    request_ref = get_db_reference(
        f"help_requests/{request_id}"
    )

    now_ms = time.time_ns() // 1_000_000

    def update_request(current):
        if current is None:
            raise ValueError("HELP_REQUEST_NOT_FOUND")

        if not isinstance(current, dict):
            raise ValueError("HELP_REQUEST_NOT_FOUND")

        if current.get("storeId") != store_id:
            raise ValueError("HELP_REQUEST_STORE_MISMATCH")

        if current.get("status") == "completed":
            raise ValueError("HELP_REQUEST_ALREADY_COMPLETED")

        if current.get("status") != "pending":
            raise ValueError("HELP_REQUEST_INVALID_STATUS")

        updated = dict(current)
        updated["status"] = "completed"
        updated["completedAt"] = now_ms

        return updated

    return request_ref.transaction(update_request)
