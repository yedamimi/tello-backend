
"""Firebase 기반 규칙형 카페 메뉴 추천."""

import re

from app.repositories.store_repository import get_store_menus


TASTE_KEYWORDS = {
    "sweet": (
        "달달", "달콤", "단거", "단 거",
        "달게", "달콤한", "달달한",
    ),
    "bitter": (
        "쓴", "쌉싸름", "쌉쌀", "진한 커피",
    ),
    "smooth": (
        "부드러운", "부드럽", "고소한 음료",
    ),
    "refreshing": (
        "상큼", "상쾌", "시원한 맛",
    ),
    "fruity": (
        "과일", "과일맛", "과일 맛",
    ),
    "chocolate": (
        "초코", "초콜릿", "초콜렛",
    ),
    "nutty": (
        "고소", "견과",
    ),
    "buttery": (
        "버터", "버터향",
    ),
    "savory": (
        "짭짤", "담백",
    ),
}

DRINK_CATEGORIES = {"coffee", "drink"}
DESSERT_CATEGORIES = {"dessert"}


def is_recommendation_request(text: str) -> bool:
    """추천을 명시적으로 요청했는지 확인한다."""
    return bool(re.search(
        r"추천|뭐\s*마실|뭘\s*마실|"
        r"뭐\s*먹을|뭘\s*먹을|"
        r"(?:안\s*쓰고|달달|달콤).*(?:있어요|있나요|추천)",
        text,
    ))


def extract_preferences(text: str) -> dict:
    """발화에서 추천 조건을 추출한다."""

    tastes = {
        tag
        for tag, words in TASTE_KEYWORDS.items()
        if any(word in text for word in words)
    }

    category = None

    if re.search(r"디저트|빵|쿠키|간식", text):
        category = "dessert"
    elif re.search(r"커피", text):
        category = "coffee"
    elif re.search(r"음료|마실|주스|우유", text):
        category = "drink"

    # 온도는 추천 선호 조건이다.
    # 실제 주문 가능 여부는 temperatureOptions로 확인한다.
    temperature = None

    if re.search(r"아이스|차가운|차갑게|시원한", text):
        temperature = "ice"

    if re.search(r"따뜻한|따뜻하게|뜨거운|핫", text):
        if temperature == "ice":
            temperature = "conflict"
        else:
            temperature = "hot"

    return {
        "tastes": tastes,
        "category": category,
        "temperature": temperature,
    }


def recommend_menus(
    store_id: str,
    text: str,
    limit: int = 2,
    exclude_menu_ids: set[str] | None = None,
) -> dict:
    """판매 중인 메뉴에서 조건에 맞는 후보를 추천한다.

    메뉴 특성은 Firebase의 tasteTags,
    recommendTemperature를 기준으로 사용한다.
    """

    # 시연 매장의 티 음료 요청: 판매 중인 사과주스를 대안으로 안내
    if re.search(r"티\s*음료", text):
        menus = get_store_menus(store_id) or {}
        menu = menus.get("apple_juice")

        available = (
            isinstance(menu, dict)
            and menu.get("isAvailable") is True
            and "apple_juice" not in (exclude_menu_ids or set())
        )

        candidates = [{
            "menuId": "apple_juice",
            "name": menu.get("name", "사과주스"),
            "price": menu.get("price", 0),
            "category": menu.get("category"),
            "tasteTags": menu.get("tasteTags") or [],
        }] if available else []

        return {
            "intent": "recommend",
            "items": [],
            "issues": [],
            "needsClarification": not bool(candidates),
            "question": (
                "죄송해요, 지금은 티 음료가 없어요. "
                "대신 커피가 아닌 사과주스는 어떠세요?"
                if candidates
                else "지금은 티 음료가 없고, 추천할 대안 메뉴도 없어요."
            ),
            "cart": None,
            "nextAction": (
                "show_recommendations" if candidates
                else "recommend_empty"
            ),
            "candidates": candidates,
        }

    preferences = extract_preferences(text)
    menus = get_store_menus(store_id) or {}

    tastes = preferences["tastes"]
    category = preferences["category"]
    temperature = preferences["temperature"]

    if temperature == "conflict":
        return {
            "intent": "recommend",
            "items": [],
            "issues": [],
            "needsClarification": True,
            "question": (
                "따뜻한 메뉴와 차가운 메뉴 중 "
                "어느 쪽을 추천해 드릴까요?"
            ),
            "cart": None,
            "nextAction": "recommend_clarification",
            "candidates": [],
        }

    candidates = []
    excluded = set(exclude_menu_ids or [])

    for menu_id, menu in menus.items():
        if menu_id in excluded:
            continue
        if not isinstance(menu, dict):
            continue

        # 품절·판매 중단 메뉴 제외
        if menu.get("isAvailable") is not True:
            continue

        menu_category = menu.get("category")
        tags = set(menu.get("tasteTags") or [])

        # 메뉴 분류 조건
        if category == "dessert":
            if menu_category not in DESSERT_CATEGORIES:
                continue

        elif category == "coffee":
            if menu_category != "coffee":
                continue

        elif category == "drink":
            if menu_category not in DRINK_CATEGORIES:
                continue

        # 맛 조건: 요청한 특성과 일치해야 함
        matched_tastes = tastes & tags

        if tastes and not matched_tastes:
            continue

        # 선호 온도와 실제 주문 허용 온도 모두 확인
        if temperature:
            allowed_temperatures = (
                menu.get("temperatureOptions") or {}
            )
            recommended_temperatures = (
                menu.get("recommendTemperature") or []
            )

            if temperature not in allowed_temperatures:
                continue

            if (
                recommended_temperatures
                and temperature not in recommended_temperatures
            ):
                continue

        # 조건과의 일치 정도로 정렬
        score = len(matched_tastes)

        if category:
            score += 1

        if temperature:
            score += 1

        candidates.append({
            "menuId": menu_id,
            "name": menu.get("name", menu_id),
            "price": menu.get("price", 0),
            "category": menu_category,
            "tasteTags": sorted(tags),
            "score": score,
        })

    # 높은 일치 점수, 낮은 가격, 메뉴 ID 순서
    if not tastes and not category and not temperature:
        priority = {
            "americano": 0,
            "cafe_latte": 1,
            "vanilla_latte": 2,
            "choco_milk": 3,
        }
        candidates.sort(
            key=lambda item: (
                priority.get(item["menuId"], 100),
                item["price"],
                item["menuId"],
            )
        )
    else:
        sweet_priority = (
            {"vanilla_latte": 0, "choco_milk": 1}
            if "sweet" in tastes else {}
        )
        candidates.sort(
            key=lambda item: (
                -item["score"],
                sweet_priority.get(item["menuId"], 100),
                item["price"],
                item["menuId"],
            )
        )

    # 내부 정렬 점수는 프론트에 전달하지 않음
    selected = []

    for candidate in candidates[:limit]:
        selected.append({
            key: value
            for key, value in candidate.items()
            if key != "score"
        })

    if selected:
        question = (
            "이런 메뉴를 추천해 드릴게요. "
            "마음에 드는 메뉴를 골라 주세요."
        )
    else:
        question = (
            "조건에 맞는 판매 중인 메뉴를 찾지 못했어요. "
            "다른 맛이나 종류로 말씀해 주세요."
        )

    return {
        "intent": "recommend",
        "items": [],
        "issues": [],
        "needsClarification": not bool(selected),
        "question": question,
        "cart": None,
        "nextAction": (
            "show_recommendations"
            if selected
            else "recommend_empty"
        ),
        "candidates": selected,
    }
