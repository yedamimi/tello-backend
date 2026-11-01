# 매장 및 메뉴 조회를 담당하는 Service 모듈
# Repository에서 가져온 매장, 메뉴 데이터 확인하고 API에서 사용할 수 있도록 가공하는 역할

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.repositories.store_repository import (
    get_store,
    get_store_menus,
)

# 매장 조회 API의 공통 URL 경로
router = APIRouter(
    prefix="/api/stores",
    tags=["stores"],
)

# 매장 ID를 이용해서 매장 정보 조회 
def get_store_info(store_id: str) -> dict:
    store = get_store(store_id)

# 존재하지 않는 매장인지 확인
    if store is None:
        raise ValueError("STORE_NOT_FOUND")

    return store

# 매장의 메뉴 목록 조회
def get_menu_list(store_id: str, category: str = None) -> list:
    # 먼저 매장이 실제로 존재하는지 확인
    get_store_info(store_id)

# Repository를 통해 해당 매장의 전체 메뉴 조회
    menus = get_store_menus(store_id)

# 메뉴 데이터가 없는 경우 예외 발생
    if not menus:
        raise ValueError("MENU_NOT_FOUND")

# 각 메뉴 ID와 메뉴 정보를 하나의 목록으로 변환
    menu_list = []

    for menu_id, menu_info in menus.items():
        menu = {
            "menuId": menu_id,
            **menu_info,
        }

# 카테고리가 전달된 경우 해당 카테고리만 선택
        if category is None or menu.get("category") == category:
            menu_list.append(menu)

    return menu_list

# 매장 정보 조회하는 API 
@router.get(
        "/{store_id}",
        summary="Get Store",
        description="매장 ID를 이용해 매장 정보를 조회한다"
            )   
def read_store(store_id: str):

    try:
        store = get_store_info(store_id)

        return {
            "storeId": store_id,
            "store": store,
        }

    except ValueError as error:
        if str(error) == "STORE_NOT_FOUND":
            return JSONResponse(
                status_code=404,
                content={"detail": "STORE_NOT_FOUND"},
            )
        raise


# 전체 메뉴 또는 카테코리별 메뉴 조회하는 API
@router.get(
        "/{store_id}/menus",
        summary="Get Store Menus",
        description="매장 ID를 이용해 전체 메뉴 또는 카테고리별 메뉴를 조회한다"
            )
def read_store_menus(
    store_id: str,
    category: str = None,
):

    try:
        menus = get_menu_list(store_id, category)

        return {
            "storeId": store_id,
            "category": category,
            "menus": menus,
        }

    except ValueError as error:
        if str(error) in ("STORE_NOT_FOUND", "MENU_NOT_FOUND"):
            return JSONResponse(
                status_code=404,
                content={"detail": str(error)},
            )
        raise