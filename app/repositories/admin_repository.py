"""Firebase 관리자 정보 조회 및 등록."""

from datetime import datetime, timezone

from app.core.firebase import get_db_reference


def get_admin(uid: str) -> dict | None:
    """Firebase Auth UID로 관리자 정보 조회."""
    if not uid or not isinstance(uid, str):
        raise ValueError("ADMIN_UID_INVALID")

    return get_db_reference(
        f"admins/{uid}"
    ).get()


def register_admin(
    uid: str,
    store_id: str,
) -> dict:
    """Firebase Authentication에 생성된 관리자 UID 등록."""

    if not isinstance(uid, str) or not uid.strip():
        raise ValueError("ADMIN_UID_INVALID")

    if not isinstance(store_id, str) or not store_id.strip():
        raise ValueError("ADMIN_STORE_INVALID")

    ref = get_db_reference(f"admins/{uid}")

    if ref.get() is not None:
        raise ValueError("ADMIN_ALREADY_EXISTS")

    data = {
        "storeId": store_id,
        "role": "admin",
        "isActive": True,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    ref.set(data)
    return data
