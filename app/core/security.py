"""관리자 인증 및 권한 검증."""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth

from app.core.firebase import initialize_firebase
from app.repositories.admin_repository import get_admin


admin_bearer = HTTPBearer(auto_error=False)


def verify_admin_token(id_token: str) -> dict:
    """Firebase ID Token을 검증하고 관리자 정보를 반환한다."""

    if not id_token:
        raise ValueError("ADMIN_TOKEN_MISSING")

    try:
        initialize_firebase()
        decoded_token = auth.verify_id_token(id_token)

    except Exception:
        raise ValueError("ADMIN_TOKEN_INVALID")

    uid = decoded_token.get("uid")

    if not uid:
        raise ValueError("ADMIN_TOKEN_INVALID")

    admin = get_admin(uid)

    if not admin:
        raise ValueError("ADMIN_NOT_FOUND")

    if admin.get("role") != "admin":
        raise ValueError("ADMIN_PERMISSION_DENIED")

    if admin.get("isActive") is not True:
        raise ValueError("ADMIN_INACTIVE")

    store_id = admin.get("storeId")

    if not isinstance(store_id, str) or not store_id.strip():
        raise ValueError("ADMIN_STORE_INVALID")

    return {
        "uid": uid,
        "storeId": store_id,
        "role": admin["role"],
        "isActive": admin["isActive"],
        "createdAt": admin.get("createdAt"),
    }


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        admin_bearer
    ),
) -> dict:
    """요청에 포함된 토큰으로 관리자 인증."""

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="ADMIN_TOKEN_MISSING",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return verify_admin_token(credentials.credentials)

    except ValueError as exc:
        code = str(exc)

        status_code = (
            401
            if code in (
                "ADMIN_TOKEN_MISSING",
                "ADMIN_TOKEN_INVALID",
            )
            else 403
        )

        raise HTTPException(
            status_code=status_code,
            detail=code,
        )