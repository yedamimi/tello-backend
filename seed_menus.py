"""Tello 시연 메뉴·옵션 등록."""

from app.core.firebase import get_db_reference


def seed_menus():
    """매장 메뉴를 8개와 새 옵션 구조로 등록한다."""

    store_id = "store_001"

    if get_db_reference(f"stores/{store_id}").get() is None:
        raise ValueError("시연 매장을 먼저 등록해 주세요.")

    menu_rows = [
        ("americano", "아메리카노", "coffee", 3000),
        ("cafe_latte", "카페라떼", "coffee", 3500),
        ("vanilla_latte", "바닐라라떼", "coffee", 4000),
        ("choco_milk", "초코우유", "drink", 3500),
        ("strawberry_milk", "딸기우유", "drink", 3500),
        ("apple_juice", "사과주스", "drink", 3000),
        ("choco_cookie", "초코쿠키", "dessert", 2000),
        ("croissant", "크루아상", "dessert", 3000),
    ]

    menus = {}

    for menu_id, name, category, price in menu_rows:
        menu = {
            "name": name,
            "category": category,
            "price": price,
            "isAvailable": True,
        }

        if category in ("coffee", "drink"):
            menu["sizeOptions"] = {
                "regular": {
                    "name": "보통",
                    "extraPrice": 0,
                },
                "large": {
                    "name": "큰 사이즈",
                    "extraPrice": 500,
                },
            }

            menu["temperatureOptions"] = {
                "hot": {
                    "name": "핫",
                    "extraPrice": 0,
                },
                "ice": {
                    "name": "아이스",
                    "extraPrice": 0,
                },
            }

            menu["iceOptions"] = {
                "more": {
                    "name": "많이",
                    "extraPrice": 0,
                },
                "regular": {
                    "name": "보통",
                    "extraPrice": 0,
                },
                "less": {
                    "name": "적게",
                    "extraPrice": 0,
                },
            }

        menus[menu_id] = menu

    # 해당 매장의 메뉴 전체를 새 목록으로 교체
    get_db_reference(f"menus/{store_id}").set(menus)

    saved_menus = get_db_reference(f"menus/{store_id}").get() or {}

    print(f"메뉴 {len(saved_menus)}개 등록 완료!")

    for menu in saved_menus.values():
        print(f'{menu["name"]}: {menu["price"]:,}원')


if __name__ == "__main__":
    seed_menus()