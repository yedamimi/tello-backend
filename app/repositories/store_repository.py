# 매장 및 메뉴 데이터 조회 담당 
from app.core.firebase import get_db_reference

# 매장 ID 이용해서 매장 정보 조회
def get_store(store_id: str):
    return get_db_reference(f"stores/{store_id}").get()

# 매장 ID 이용해서 해당 매장 전체 메뉴 조회
def get_store_menus(store_id: str):
    return get_db_reference(f"menus/{store_id}").get()
