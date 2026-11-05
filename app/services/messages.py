
"""LLM 주문 검증, 후속 대화 및 장바구니 연동."""

import re
from uuid import uuid4

from app.core.firebase import get_db_reference
from app.repositories.store_repository import get_store_menus
from app.schemas.messages import AnalyzedItem, OrderAnalysis
from app.services.llm import analyze_order_text
from app.services.sessions import (
    _calculate_unit_price,
    _get_authenticated_session,
    _validate_quantity,
    get_session_cart,
    update_cart_item,
    delete_cart_item,
)
from app.services.voice_cart import (
    process_voice_cart_command,
    confirm_voice_clear,
    find_cart_target,
)
from app.services.recommendations import (
    is_recommendation_request,
    recommend_menus,
    extract_preferences,
)



OPTION_FIELDS = ("size", "temperature", "ice")

FIELD_PRIORITY = {
    "menuId": 0,
    "size": 1,
    "temperature": 2,
    "ice": 3,
    "quantity": 4,
    "options": 5,
}

YES_ANSWERS = {
    "네", "예", "응", "좋아요",
    "더주문할게요", "더주문할래요",
    "추가주문", "추가할게요",
}

NO_ANSWERS = {
    "아니요", "아니", "아뇨", "아니에요",
    "주문확인하기", "주문확인할게요",
    "주문끝났어요", "이제됐어요",
    "그만주문할게요",
}


def _normalize(text: str) -> str:
    """공백 및 마지막 문장부호 정리."""
    return re.sub(r"[\s.!?]+", "", text.strip())


def _add_issue(
    issues: list,
    index: int,
    code: str,
    field: str,
) -> None:
    issues.append({
        "itemIndex": index,
        "code": code,
        "field": field,
    })


def validate_order_analysis(
    store_id: str,
    analysis: OrderAnalysis,
) -> dict:
    """메뉴, 품절, 필수 옵션, 수량 검증."""

    items = [
        item.model_dump()
        for item in analysis.items
    ]

    result = {
        "intent": analysis.intent,
        "items": items,
        "issues": [],
        "needsClarification": False,
    }

    if analysis.intent != "add_item":
        return result

    menus = get_store_menus(store_id) or {}
    issues = result["issues"]

    for index, item in enumerate(items):
        menu_id = item.get("menu_id")
        menu = menus.get(menu_id)

        if not isinstance(menu, dict):
            _add_issue(
                issues, index, "MENU_UNKNOWN", "menuId"
            )
            continue

        if menu.get("isAvailable") is not True:
            _add_issue(
                issues, index, "MENU_SOLD_OUT", "menuId"
            )
            continue

        options = item.get("options") or {}

        # 크기 → 온도
        for field, db_field in (
            ("size", "sizeOptions"),
            ("temperature", "temperatureOptions"),
        ):
            allowed = menu.get(db_field) or {}
            value = options.get(field)

            if allowed and value is None:
                _add_issue(
                    issues, index,
                    "OPTION_REQUIRED", field
                )
            elif value is not None and value not in allowed:
                _add_issue(
                    issues, index,
                    "OPTION_INVALID", field
                )

        # 얼음: 아이스이면서 얼음 옵션이 있을 때
        ice = options.get("ice")
        ice_options = menu.get("iceOptions") or {}

        if options.get("temperature") == "ice":
            if ice_options and ice is None:
                _add_issue(
                    issues, index,
                    "OPTION_REQUIRED", "ice"
                )
            elif ice is not None and ice not in ice_options:
                _add_issue(
                    issues, index,
                    "OPTION_INVALID", "ice"
                )
        elif ice is not None:
            _add_issue(
                issues, index,
                "OPTION_INVALID", "ice"
            )

        # 수량은 옵션을 모두 확인한 뒤 마지막에 질문
        quantity = item.get("quantity")

        if quantity is None:
            _add_issue(
                issues, index,
                "QUANTITY_REQUIRED", "quantity"
            )
        else:
            try:
                _validate_quantity(quantity)
            except (ValueError, TypeError):
                _add_issue(
                    issues, index,
                    "QUANTITY_INVALID", "quantity"
                )

        # 필수 옵션 및 수량이 정상일 때 가격 검증
        item_has_issue = any(
            issue["itemIndex"] == index
            for issue in issues
        )

        if not item_has_issue:
            selected = {
                field: value
                for field, value in options.items()
                if value is not None
            }

            try:
                _calculate_unit_price(menu, selected)
            except (ValueError, TypeError, KeyError):
                _add_issue(
                    issues, index,
                    "OPTION_INVALID", "options"
                )

    issues.sort(
        key=lambda issue: (
            issue["itemIndex"],
            FIELD_PRIORITY.get(issue["field"], 99),
        )
    )

    result["needsClarification"] = bool(issues)
    return result


def _topic_particle(name: str) -> str:
    """메뉴명 마지막 글자의 받침에 따라 은/는 선택."""
    if not name:
        return "는"

    last = name[-1]
    code = ord(last)

    if 0xAC00 <= code <= 0xD7A3:
        return "은" if (code - 0xAC00) % 28 else "는"

    return "는"


def generate_clarification_question(
    result: dict,
) -> str | None:
    """우선순위가 가장 높은 누락 정보 질문."""

    issues = result.get("issues") or []

    if not issues:
        return None

    issue = issues[0]
    index = issue["itemIndex"]

    item = result["items"][index]
    name = item.get("menu_text") or "해당 메뉴"

    code = issue["code"]
    field = issue["field"]

    if code == "MENU_UNKNOWN":
        return (
            f"{name} 메뉴를 찾지 못했어요. "
            "다른 메뉴를 말씀해 주세요."
        )

    if code == "MENU_SOLD_OUT":
        return (
            f"{name}{_topic_particle(name)} 품절이에요. "
            "다른 메뉴를 말씀해 주세요."
        )

    if code in ("QUANTITY_REQUIRED", "QUANTITY_INVALID"):
        return f"{name}{_topic_particle(name)} 몇 개 주문하시겠어요?"

    questions = {
        "size": f"{name}의 크기를 골라 주세요.",
        "temperature": (
            f"{name}{_topic_particle(name)} 따뜻하게 드릴까요, "
            "차갑게 드릴까요?"
        ),
        "ice": f"{name}의 얼음은 얼마나 넣을까요?",
    }

    if code == "OPTION_REQUIRED":
        return questions.get(
            field, "옵션을 선택해 주세요."
        )

    if code == "OPTION_INVALID":
        return questions.get(
            field, "옵션을 다시 선택해 주세요."
        )

    return "주문 내용을 다시 말씀해 주세요."


def get_pending_order(session_id: str) -> dict | None:
    """미완성 음성 주문 조회."""
    return get_db_reference(
        f"sessions/{session_id}/pendingOrder"
    ).get()


def save_pending_order(
    session_id: str,
    result: dict,
) -> None:
    """추가 질문이 필요한 주문 저장."""

    if result["intent"] != "add_item":
        return

    pending_ref = get_db_reference(
        f"sessions/{session_id}/pendingOrder"
    )

    if not result["needsClarification"]:
        pending_ref.delete()
        return

    pending_ref.set({
        "intent": result["intent"],
        "items": result["items"],
        "issues": result["issues"],
        "question": result.get("question"),
    })


def clear_pending_order(session_id: str) -> None:
    """미완성 주문 삭제. 장바구니는 유지."""
    get_db_reference(
        f"sessions/{session_id}/pendingOrder"
    ).delete()


def get_dialog_state(session_id: str) -> str | None:
    """추가 주문 여부를 기다리는 대화 상태 조회."""
    return get_db_reference(
        f"sessions/{session_id}/dialogState"
    ).get()


def set_dialog_state(
    session_id: str,
    state: str | None,
) -> None:
    """추가 주문 대화 상태 저장 및 삭제."""

    ref = get_db_reference(
        f"sessions/{session_id}/dialogState"
    )

    if state is None:
        ref.delete()
    else:
        ref.set(state)


def cancel_pending_order(
    session_id: str,
    session_token: str,
) -> dict:
    """인증 후 진행 중인 음성 주문만 취소."""

    _get_authenticated_session(
        session_id,
        session_token,
    )

    clear_pending_order(session_id)
    set_dialog_state(session_id, None)

    return {
        "cancelled": True,
        "cart": get_session_cart(
            session_id,
            session_token,
        ),
    }


def _read_followup_value(
    text: str,
    field: str,
):
    """버튼 또는 짧은 음성 답변 해석."""

    value = _normalize(text)

    if field == "quantity":
        match = re.fullmatch(
            r"(하나|한|둘|두|셋|세|넷|네|[1-9][0-9]*)"
            r"(잔|장|개)?"
            r"(이요|요|주세요|만)?",
            value,
        )

        if not match:
            return None

        numbers = {
            "하나": 1, "한": 1,
            "둘": 2, "두": 2,
            "셋": 3, "세": 3,
            "넷": 4, "네": 4,
        }

        word = match.group(1)

        return (
            int(word)
            if word.isdigit()
            else numbers.get(word)
        )

    choices = {
        "size": {
            "보통": "regular",
            "보통이요": "regular",
            "보통크기": "regular",
            "레귤러": "regular",
            "레귤러요": "regular",
            "큰사이즈": "large",
            "큰사이즈요": "large",
            "큰걸로": "large",
            "큰걸로요": "large",
            "라지": "large",
            "라지요": "large",
        },
        "temperature": {
            "핫": "hot",
            "핫이요": "hot",
            "따뜻하게": "hot",
            "따뜻한거": "hot",
            "따뜻한거요": "hot",
            "아이스": "ice",
            "아이스요": "ice",
            "차갑게": "ice",
            "차가운거": "ice",
            "차가운거요": "ice",
        },
        "ice": {
            "적게": "less",
            "적게요": "less",
            "얼음적게": "less",
            "보통": "regular",
            "보통이요": "regular",
            "얼음보통": "regular",
            "많이": "more",
            "많이요": "more",
            "얼음많이": "more",
        },
    }

    return choices.get(field, {}).get(value)


def resolve_followup(
    pending: dict,
    answer: str,
) -> OrderAnalysis | None:
    """기존 주문의 다음 누락 필드에 답변 반영."""

    issues = pending.get("issues") or []
    items = pending.get("items") or []

    if not issues or not items:
        return None

    issue = issues[0]
    index = issue.get("itemIndex")
    field = issue.get("field")

    if (
        type(index) is not int
        or index < 0
        or index >= len(items)
    ):
        return None

    if issue.get("code") not in (
        "OPTION_REQUIRED",
        "OPTION_INVALID",
        "QUANTITY_REQUIRED",
        "QUANTITY_INVALID",
    ):
        return None

    if field not in (*OPTION_FIELDS, "quantity"):
        return None

    value = _read_followup_value(answer, field)

    if value is None:
        return None

    updated_items = []

    for position, previous in enumerate(items):
        data = dict(previous)
        options = dict(data.get("options") or {})

        if position == index:
            if field == "quantity":
                data["quantity"] = value
            else:
                options[field] = value

                if field == "temperature" and value == "hot":
                    options["ice"] = None

        data["options"] = {
            key: options.get(key)
            for key in OPTION_FIELDS
        }

        data.setdefault("quantity", None)

        updated_items.append(
            AnalyzedItem.model_validate(data)
        )

    return OrderAnalysis(
        intent="add_item",
        items=updated_items,
    )


def add_analyzed_items(
    session_id: str,
    session_token: str,
    items: list[dict],
) -> dict:
    """검증된 음성 주문을 장바구니에 추가."""

    session = _get_authenticated_session(
        session_id,
        session_token,
    )

    store_id = session["storeId"]
    menus = get_store_menus(store_id) or {}

    additions = {}

    for item in items:
        menu_id = item.get("menu_id")
        menu = menus.get(menu_id)

        if (
            not isinstance(menu, dict)
            or menu.get("isAvailable") is not True
        ):
            raise ValueError("CART_MENU_UNAVAILABLE")

        quantity = item.get("quantity")
        _validate_quantity(quantity)

        selected_options = {
            field: value
            for field, value in (
                item.get("options") or {}
            ).items()
            if value is not None
        }

        _calculate_unit_price(
            menu,
            selected_options,
        )

        additions[uuid4().hex] = {
            "menuId": menu_id,
            "quantity": quantity,
            "selectedOptions": selected_options,
        }

    if not additions:
        raise ValueError("MESSAGE_NO_ITEMS")

    ref = get_db_reference(
        f"sessions/{session_id}/cart/items"
    )

    def add_items_transaction(current):
        updated = dict(current or {})
        updated.update(additions)
        return updated

    ref.transaction(add_items_transaction)

    return get_session_cart(
        session_id,
        session_token,
    )




def _resolve_pending_correction(
    pending: dict,
    answer: str,
    store_id: str,
) -> OrderAnalysis | None:
    """미완성 주문 중 명확한 메뉴/온도 정정 처리."""

    items = pending.get("items") or []
    issues = pending.get("issues") or []

    if not items or not issues:
        return None

    index = issues[0].get("itemIndex")

    if type(index) is not int or not 0 <= index < len(items):
        return None

    normalized = _normalize(answer)
    current = dict(items[index])
    options = dict(current.get("options") or {})

    new_menu_id = None
    new_menu_name = None

    # "아니요 카페라떼요"처럼 메뉴를 정정하는 경우
    if normalized.startswith((
        "아니요", "아니", "아뇨", "그거말고"
    )):
        correction = re.sub(
            r"^(아니요|아니|아뇨|그거말고)",
            "",
            normalized,
        )

        # "아니요, 카페라떼요"의 쉼표 등 구분 기호 제거
        correction = re.sub(r"^[,，.!?]+", "", correction)

        menus = get_store_menus(store_id) or {}

        matches = []
        for menu_id, menu in menus.items():
            if not isinstance(menu, dict):
                continue

            name = menu.get("name")
            if not isinstance(name, str):
                continue

            clean_name = _normalize(name)

            forms = {
                clean_name,
                clean_name + "요",
                clean_name + "로요",
                clean_name + "로바꿀게요",
                clean_name + "로바꿔줘",
                clean_name + "로바꿔주세요",
            }

            if correction in forms:
                matches.append((menu_id, name))

        if len(matches) == 1:
            new_menu_id, new_menu_name = matches[0]

    if new_menu_id is not None:
        current["menu_id"] = new_menu_id
        current["menu_text"] = new_menu_name
        current["options"] = {}
    else:
        # "따뜻한 걸로 바꿀게요" 등 온도 정정
        correction_words = (
            "바꿔", "바꿀", "변경", "아니",
            "걸로", "것으로",
        )
        is_correction = any(
            word in normalized for word in correction_words
        )

        wants_hot = bool(re.search(
            r"따뜻|뜨겁|핫", normalized
        ))
        wants_ice = bool(re.search(
            r"아이스|차갑", normalized
        ))

        if not is_correction or wants_hot == wants_ice:
            return None

        if wants_hot:
            options["temperature"] = "hot"
            options.pop("ice", None)
        else:
            options["temperature"] = "ice"
            options.pop("ice", None)

        current["options"] = options

    # Ensure every option field exists for Pydantic validation.
    saved_options = current.get("options") or {}
    current["options"] = {
        key: saved_options.get(key)
        for key in OPTION_FIELDS
    }

    updated_items = []

    for position, previous in enumerate(items):
        data = current if position == index else previous
        updated_items.append(
            AnalyzedItem.model_validate(data)
        )

    return OrderAnalysis(
        intent="add_item",
        items=updated_items,
    )



def _detect_unavailable_menu_name(
    normalized: str,
    store_id: str,
) -> str | None:
    """단순 주문에서 확인 가능한 미등록 메뉴만 감지."""

    # 등록된 서로 다른 메뉴가 2개 이상 포함되면 복합 주문으로 처리
    menus = get_store_menus(store_id) or {}
    matched_menu_ids = {
        menu_id
        for menu_id, menu in menus.items()
        if isinstance(menu, dict)
        and isinstance(menu.get("name"), str)
        and _normalize(menu["name"]) in normalized
    }

    if len(matched_menu_ids) >= 2:
        return None

    match = re.fullmatch(
        r"(?P<name>[가-힣]{2,15}"
        r"(?:라떼|에이드|주스|우유|커피|티))"
        r"(?:(?:한|두|세|[1-9])(?:잔|개)|하나|둘|셋)?"
        r"(?:주세요|줘요|줘|요)?",
        normalized,
    )

    if not match:
        return None

    name = match.group("name")
    menus = get_store_menus(store_id) or {}

    for menu in menus.values():
        if not isinstance(menu, dict):
            continue
        if _normalize(str(menu.get("name") or "")) == name:
            return None

    return name



def _handle_menu_browsing(
    session_id: str,
    store_id: str,
    normalized: str,
) -> dict | None:
    """Firebase 메뉴 기준으로 목록과 가격 질문 처리."""
    browse_words = (
        "어떤메뉴", "무슨메뉴", "메뉴뭐",
        "메뉴가있", "메뉴보여", "메뉴판",
    )
    noncoffee_words = (
        "커피말고", "커피아닌", "커피빼고",
    )

    is_browse = any(w in normalized for w in browse_words)
    is_noncoffee = any(w in normalized for w in noncoffee_words)
    is_price = "얼마" in normalized or "가격" in normalized

    if not (is_browse or is_noncoffee or is_price):
        return None

    menus = get_store_menus(store_id) or {}
    available = [
        (menu_id, menu)
        for menu_id, menu in menus.items()
        if isinstance(menu, dict)
        and menu.get("isAvailable") is True
    ]

    def response(question, action, candidates=None):
        return {
            "intent": "browse_menu",
            "items": [],
            "issues": [],
            "needsClarification": action == "confirm_menu_selection",
            "question": question,
            "cart": None,
            "nextAction": action,
            "candidates": candidates or [],
        }

    if is_price:
        matches = [
            (menu_id, menu)
            for menu_id, menu in available
            if _normalize(str(menu.get("name") or ""))
            in normalized
        ]
        if matches:
            menu_id, menu = max(
                matches,
                key=lambda pair: len(pair[1].get("name") or ""),
            )
            name = menu["name"]
            price = menu.get("price", 0)
            size_options = menu.get("sizeOptions") or {}
            extra = (
                " 큰 사이즈는 500원 추가돼요."
                if "large" in size_options else ""
            )

            get_db_reference(
                f"sessions/{session_id}/menuBrowseSelection"
            ).set({
                "menuId": menu_id,
                "name": name,
            })
            set_dialog_state(
                session_id, "menu_price_offer"
            )

            return response(
                f"{name}는 {price:,}원이에요."
                f"{extra} 이걸로 할까요?",
                "confirm_menu_selection",
                [{
                    "menuId": menu_id,
                    "name": name,
                    "price": price,
                }],
            )

        return response(
            "메뉴판에서 가격을 확인할 수 있어요. "
            "원하는 메뉴를 골라 주세요.",
            "show_menu",
        )

    if is_noncoffee:
        selected = [
            menu for _, menu in available
            if menu.get("category") != "coffee"
        ]
        names = [
            str(menu.get("name"))
            for menu in selected
            if menu.get("name")
        ]
        question = (
            "커피가 아닌 메뉴로는 "
            + ", ".join(names)
            + "가 있어요. 메뉴판에서 골라 주세요."
            if names else
            "현재 판매 중인 다른 메뉴가 없어요."
        )
        return response(question, "show_menu")

    names = [
        str(menu.get("name"))
        for _, menu in available
        if menu.get("name")
    ]
    question = (
        "판매 중인 메뉴는 "
        + ", ".join(names)
        + "예요. 사진으로도 골라 보세요."
        if names else
        "현재 판매 중인 메뉴가 없어요."
    )
    return response(question, "show_menu")


def process_order_message(
    session_id: str,
    session_token: str,
    text: str,
) -> dict:
    """음성·버튼 메시지를 하나의 주문 흐름으로 처리."""

    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 1000
    ):
        raise ValueError("MESSAGE_TEXT_INVALID")

    session = _get_authenticated_session(
        session_id,
        session_token,
    )

    store_id = session["storeId"]
    normalized = _normalize(text)

    dialog_state = get_dialog_state(session_id)

    if dialog_state == "menu_price_offer":
        selection_ref = get_db_reference(
            f"sessions/{session_id}/menuBrowseSelection"
        )
        selection = selection_ref.get()

        accepted = {
            "네", "네이걸로할게요", "이걸로할게요",
            "네이걸로주세요", "이걸로주세요",
            "응", "예", "좋아요",
        }
        rejected = {
            "아니요", "아니", "다른메뉴볼래요",
            "메뉴판볼게요", "다른메뉴",
        }

        if normalized in accepted and isinstance(selection, dict):
            selection_ref.delete()
            set_dialog_state(session_id, None)

            item = AnalyzedItem.model_validate({
                "menu_id": selection["menuId"],
                "menu_text": selection["name"],
                "quantity": None,
                "options": {
                    "size": None,
                    "temperature": None,
                    "ice": None,
                },
            })
            analysis = OrderAnalysis(
                intent="add_item",
                items=[item],
            )
            result = validate_order_analysis(
                store_id, analysis
            )
            result["question"] = (
                generate_clarification_question(result)
            )
            result["cart"] = None
            result["nextAction"] = "clarification"

            if result["needsClarification"]:
                save_pending_order(session_id, result)
                return result

            result["cart"] = add_analyzed_items(
                session_id, session_token, result["items"]
            )
            result["nextAction"] = "ask_more"
            result["question"] = "더 필요한 게 있나요?"
            set_dialog_state(session_id, "awaiting_more")
            return result

        if normalized in rejected:
            selection_ref.delete()
            set_dialog_state(session_id, None)
            return {
                "intent": "browse_menu",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": "다른 메뉴를 골라 주세요.",
                "cart": None,
                "nextAction": "show_menu",
            }

        # 새로운 요청은 이전 가격 확인 상태를 종료하고 처리
        selection_ref.delete()
        set_dialog_state(session_id, None)


    if dialog_state == "unknown_menu_offer":
        if normalized in {
            "네", "예", "응", "추천해주세요",
            "네추천해주세요", "추천해줘요",
        }:
            set_dialog_state(session_id, None)
            recommendation_text = "달달한 음료 추천해 줘"
            result = recommend_menus(
                store_id=store_id,
                text=recommendation_text,
            )

            candidates = result.get("candidates") or []
            if candidates:
                get_db_reference(
                    f"sessions/{session_id}/recommendationContext"
                ).set({
                    "temperature": None,
                    "originalText": recommendation_text,
                    "refusalCount": 0,
                    "excludedMenuIds": [],
                    "candidates": [
                        {
                            "menuId": item["menuId"],
                            "name": item["name"],
                        }
                        for item in candidates
                    ],
                })
            return result

        if normalized in {
            "메뉴판볼게요", "메뉴판",
            "아니요", "아니", "아뇨",
        }:
            set_dialog_state(session_id, None)
            return {
                "intent": "browse_menu",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": "메뉴판을 열어 드릴게요.",
                "cart": None,
                "nextAction": "show_menu",
            }

        return {
            "intent": "answer",
            "items": [],
            "issues": [],
            "needsClarification": True,
            "question": (
                "다른 메뉴를 추천해 드릴까요? "
                "추천해 주세요 또는 메뉴판 볼게요로 답해 주세요."
            ),
            "cart": None,
            "nextAction": "clarification",
        }


    # 개별 장바구니 항목 삭제 확인
    if dialog_state == "confirm_remove":
        pending_ref = get_db_reference(
            f"sessions/{session_id}/pendingCartRemoval"
        )
        pending = pending_ref.get() or {}

        if normalized in YES_ANSWERS:
            pending_ref.delete()
            set_dialog_state(session_id, None)

            cart = get_session_cart(session_id, session_token)
            target = next(
                (
                    item for item in cart.get("items", [])
                    if item.get("itemId") == pending.get("itemId")
                ),
                None,
            )

            # 확인 중 다른 요청으로 장바구니가 바뀌었다면 삭제하지 않음
            if (
                not target
                or target.get("menuId") != pending.get("menuId")
                or target.get("quantity") != pending.get("originalQuantity")
            ):
                return {
                    "intent": "remove_item",
                    "items": [],
                    "issues": [],
                    "needsClarification": False,
                    "question": "주문 내용이 변경됐어요. 장바구니를 다시 확인해 주세요.",
                    "cart": cart,
                    "nextAction": "review_cart",
                }

            remove_quantity = pending.get("removeQuantity")
            current_quantity = target["quantity"]

            if remove_quantity is None or remove_quantity >= current_quantity:
                cart = delete_cart_item(
                    session_id, session_token, target["itemId"]
                )
                question = "메뉴를 삭제했어요."
            else:
                cart = update_cart_item(
                    session_id,
                    session_token,
                    target["itemId"],
                    {"quantity": current_quantity - remove_quantity},
                )
                question = f"{remove_quantity}개를 뺐어요."

            return {
                "intent": "remove_item",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": question,
                "cart": cart,
                "nextAction": "cart_updated",
            }

        if normalized in NO_ANSWERS:
            pending_ref.delete()
            set_dialog_state(session_id, None)
            return {
                "intent": "answer",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": "알겠어요. 주문 내용을 그대로 유지할게요.",
                "cart": get_session_cart(session_id, session_token),
                "nextAction": "cart_updated",
            }

        return {
            "intent": "answer",
            "items": [],
            "issues": [],
            "needsClarification": True,
            "question": "메뉴를 뺄까요? 네 또는 아니요로 답해 주세요.",
            "cart": None,
            "nextAction": "confirm_remove",
        }

    # 1. 장바구니 전체 비우기 확인
    if dialog_state == "confirm_clear":
        if normalized in YES_ANSWERS:
            result = confirm_voice_clear(
                session_id, session_token, True
            )
            set_dialog_state(session_id, None)
            return result

        if normalized in NO_ANSWERS:
            result = confirm_voice_clear(
                session_id, session_token, False
            )
            set_dialog_state(session_id, None)
            return result

        return {
            "intent": "answer",
            "items": [],
            "issues": [],
            "needsClarification": True,
            "question": (
                "장바구니를 모두 비울까요? "
                "네 또는 아니요로 답해 주세요."
            ),
            "cart": None,
            "nextAction": "confirm_clear",
        }


    # 함께 먹을 메뉴 추천에 대한 수락·거절
    if dialog_state == "pairing_offer":
        if normalized in {
            "네", "예", "응", "네담아주세요",
            "담아주세요", "이걸로할게요",
            "크루아상요", "크루아상",
        }:
            menus = get_store_menus(store_id) or {}
            menu = menus.get("croissant")

            if (
                not isinstance(menu, dict)
                or menu.get("isAvailable") is not True
            ):
                set_dialog_state(session_id, None)
                return {
                    "intent": "browse_menu",
                    "items": [],
                    "issues": [],
                    "needsClarification": False,
                    "question": "크루아상을 지금 주문할 수 없어요. 메뉴판을 확인해 주세요.",
                    "cart": None,
                    "nextAction": "show_menu",
                }

            analysis = OrderAnalysis(
                intent="add_item",
                items=[
                    AnalyzedItem.model_validate({
                        "menu_id": "croissant",
                        "menu_text": menu.get("name", "croissant"),
                        "quantity": None,
                        "options": {
                            "size": None,
                            "temperature": None,
                            "ice": None,
                        },
                    })
                ],
            )

            set_dialog_state(session_id, None)
            result = validate_order_analysis(store_id, analysis)
            result["question"] = generate_clarification_question(result)
            result["cart"] = None
            result["nextAction"] = "clarification"

            if result["needsClarification"]:
                save_pending_order(session_id, result)
                return result

            result["cart"] = add_analyzed_items(
                session_id, session_token, result["items"]
            )
            result["question"] = "더 필요한 게 있나요?"
            result["nextAction"] = "ask_more"
            set_dialog_state(session_id, "awaiting_more")
            return result

        if normalized in {"아니요", "아니", "아뇨", "괜찮아요"}:
            set_dialog_state(session_id, "awaiting_more")
            return {
                "intent": "answer",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": "알겠어요. 더 필요한 게 있나요?",
                "cart": None,
                "nextAction": "ask_more",
            }

        return {
            "intent": "answer",
            "items": [],
            "issues": [],
            "needsClarification": True,
            "question": "크루아상을 담을까요? 네 또는 아니요로 답해 주세요.",
            "cart": None,
            "nextAction": "confirm_pairing",
        }

    # 커피 주문 후 함께 먹을 디저트 추천
    if (
        dialog_state == "awaiting_more"
        and "추천" in normalized
        and any(
            word in normalized
            for word in ("같이먹을", "함께먹을", "곁들일")
        )
    ):
        menus = get_store_menus(store_id) or {}
        saved_items = get_db_reference(
            f"sessions/{session_id}/cart/items"
        ).get() or {}

        has_coffee = any(
            isinstance(item, dict)
            and isinstance(menus.get(item.get("menuId")), dict)
            and menus[item["menuId"]].get("category") == "coffee"
            for item in saved_items.values()
        )

        croissant = menus.get("croissant")

        if (
            has_coffee
            and isinstance(croissant, dict)
            and croissant.get("isAvailable") is True
        ):
            get_db_reference(
                f"sessions/{session_id}/recommendationContext"
            ).delete()
            set_dialog_state(session_id, "pairing_offer")

            name = croissant.get("name", "크루아상")
            price = croissant.get("price", 0)

            return {
                "intent": "recommend",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": (
                    f"커피와 함께라면 {name}을 추천해요. "
                    f"{price:,}원이에요. 담을까요?"
                ),
                "cart": None,
                "nextAction": "confirm_pairing",
                "candidates": [{
                    "menuId": "croissant",
                    "name": name,
                    "price": price,
                }],
            }

    # QUANTITY_CORRECTION_FOLLOWUP
    # "아니요, 한 잔이요"처럼 직전 담기 후 수량 정정
    if dialog_state == "awaiting_more":
        correction_text = re.sub(r"[,，.!?。]", "", normalized)
        quantity_match = re.fullmatch(
            r"(?:아니요|아니|아뇨)"
            r"(하나|한|두|둘|세|셋|네|넷|[1-9][0-9]*)"
            r"(?:잔|개|장)(?:이요|요)?",
            correction_text,
        )

        if quantity_match:
            quantity_word = quantity_match.group(1)
            quantity = {
                "하나": 1, "한": 1,
                "두": 2, "둘": 2,
                "세": 3, "셋": 3,
                "네": 4, "넷": 4,
            }.get(quantity_word)

            if quantity is None:
                quantity = int(quantity_word)

            cart = get_session_cart(session_id, session_token)
            cart_items = cart.get("items") or []

            if len(cart_items) != 1:
                return {
                    "intent": "answer",
                    "items": [],
                    "issues": [],
                    "needsClarification": True,
                    "question": (
                        "어떤 메뉴의 수량을 바꿀까요? "
                        "메뉴 이름과 수량을 함께 말씀해 주세요."
                    ),
                    "cart": cart,
                    "nextAction": "clarification",
                }

            target = cart_items[0]

            updated_cart = update_cart_item(
                session_id,
                session_token,
                target["itemId"],
                {"quantity": quantity},
            )

            set_dialog_state(session_id, "awaiting_more")

            return {
                "intent": "update_item",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": (
                    f"{target['name']} 수량을 "
                    f"{quantity}개로 변경했어요. "
                    "더 필요한 게 있나요?"
                ),
                "cart": updated_cart,
                "nextAction": "cart_updated",
            }

    # 2. 담기 완료 후 추가 주문 여부
    if dialog_state == "awaiting_more":
        if normalized in YES_ANSWERS:
            set_dialog_state(session_id, None)
            return {
                "intent": "answer",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": "더 드실 메뉴를 말씀해 주세요.",
                "cart": None,
                "nextAction": "continue_order",
            }

        if normalized in NO_ANSWERS:
            set_dialog_state(session_id, None)
            return {
                "intent": "answer",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": None,
                "cart": get_session_cart(
                    session_id,
                    session_token,
                ),
                "nextAction": "review_cart",
            }

    # 3. 미완성 주문 후속 답변
    pending = get_pending_order(session_id)

    if pending:
        # COMMON_TEMPERATURE_FOLLOWUP
        # 복합 주문에 명시된 공통 온도를 모든 메뉴에 적용
        common_temperatures = {
            "둘다아이스": "ice",
            "둘다차갑게": "ice",
            "둘다핫": "hot",
            "둘다따뜻하게": "hot",
        }

        common_temperature = common_temperatures.get(normalized)
        pending_items = pending.get("items") or []

        if common_temperature and len(pending_items) >= 2:
            updated_items = []

            for pending_item in pending_items:
                updated_item = dict(pending_item)
                options = {
                    "size": None,
                    "temperature": None,
                    "ice": None,
                    **(updated_item.get("options") or {}),
                }

                options["temperature"] = common_temperature

                if common_temperature == "hot":
                    options["ice"] = None

                updated_item["options"] = options
                updated_items.append(updated_item)

            updated_analysis = OrderAnalysis.model_validate({
                "intent": "add_item",
                "items": updated_items,
            })

            result = validate_order_analysis(
                store_id, updated_analysis
            )

            result["question"] = generate_clarification_question(
                result
            )
            result["cart"] = None
            result["nextAction"] = "clarification"

            if result["needsClarification"]:
                save_pending_order(session_id, result)
                return result

            get_db_reference(
                f"sessions/{session_id}/pendingOrder"
            ).delete()

            result["cart"] = add_analyzed_items(
                session_id, session_token, result["items"]
            )
            result["question"] = "더 필요한 게 있나요?"
            result["nextAction"] = "ask_more"
            set_dialog_state(session_id, "awaiting_more")
            return result

        analysis = (
            _resolve_pending_correction(
                pending, text, store_id
            )
            or resolve_followup(pending, text)
        )

        if analysis is None:
            return {
                "intent": "answer",
                "items": pending.get("items") or [],
                "issues": pending.get("issues") or [],
                "needsClarification": True,
                "question": (
                    pending.get("question")
                    or "다시 말씀해 주세요."
                ),
                "cart": None,
                "nextAction": "clarification",
            }
    else:
        browse_result = _handle_menu_browsing(
            session_id, store_id, normalized
        )
        if browse_result is not None:
            return browse_result

        # Preserve recommendation preferences until a menu is selected.
        recommendation_ref = get_db_reference(
            f"sessions/{session_id}/recommendationContext"
        )

        unavailable_name = _detect_unavailable_menu_name(
            normalized, store_id
        )
        if unavailable_name is not None:
            recommendation_ref.delete()
            set_dialog_state(session_id, "unknown_menu_offer")
            return {
                "intent": "add_item",
                "items": [],
                "issues": [{
                    "itemIndex": 0,
                    "code": "MENU_UNKNOWN",
                    "field": "menuId",
                }],
                "needsClarification": True,
                "question": (
                    f"죄송해요, {unavailable_name}는 지금 팔지 않아요. "
                    "다른 메뉴를 추천해 드릴까요?"
                ),
                "cart": None,
                "nextAction": "clarification",
            }

        context = recommendation_ref.get()

        rejection_words = (
            "다른추천", "다른거추천", "다른메뉴추천",
            "다른거", "다른메뉴",
            "둘다별로", "둘다싫", "별로예요",
            "마음에안들", "추천다시",
        )
        is_rejection = any(
            word in normalized for word in rejection_words
        )

        if isinstance(context, dict) and is_rejection:
            refusals = int(context.get("refusalCount") or 0) + 1
            excluded = set(context.get("excludedMenuIds") or [])

            for candidate in context.get("candidates") or []:
                if isinstance(candidate, dict):
                    menu_id = candidate.get("menuId")
                    if menu_id:
                        excluded.add(menu_id)

            if refusals < 2:
                result = recommend_menus(
                    store_id=store_id,
                    text=context.get("originalText") or text,
                    exclude_menu_ids=excluded,
                )

                if result.get("candidates"):
                    context["refusalCount"] = refusals
                    context["excludedMenuIds"] = sorted(excluded)
                    context["candidates"] = [
                        {
                            "menuId": item["menuId"],
                            "name": item["name"],
                        }
                        for item in result["candidates"]
                    ]
                    recommendation_ref.set(context)
                    return result

            recommendation_ref.delete()
            return {
                "intent": "recommend",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": (
                    "메뉴판을 열어 드릴게요. "
                    "사진을 보고 골라 주세요."
                ),
                "cart": None,
                "nextAction": "show_menu",
                "candidates": [],
            }

        if is_recommendation_request(text):
            result = recommend_menus(
                store_id=store_id,
                text=text,
            )

            candidates = result.get("candidates") or []

            if candidates:
                preferences = extract_preferences(text)
                recommendation_ref.set({
                    "temperature": preferences.get("temperature"),
                    "originalText": text,
                    "refusalCount": 0,
                    "excludedMenuIds": [],
                    "candidates": [
                        {
                            "menuId": candidate["menuId"],
                            "name": candidate["name"],
                        }
                        for candidate in candidates
                    ],
                })
            else:
                recommendation_ref.delete()

            return result

        context = recommendation_ref.get()
        selected = None

        if isinstance(context, dict):
            for candidate in context.get("candidates") or []:
                if not isinstance(candidate, dict):
                    continue

                name = candidate.get("name")
                if not isinstance(name, str):
                    continue

                forms = {
                    _normalize(name),
                    _normalize(name + chr(0xC694)),
                    _normalize(name + chr(0xB85C) + chr(0xC694)),
                }

                if normalized in forms:
                    selected = candidate
                    break

        if selected is not None:
            temperature = context.get("temperature")

            if temperature not in ("hot", "ice"):
                temperature = None

            item = AnalyzedItem.model_validate({
                "menu_id": selected["menuId"],
                "menu_text": selected["name"],
                "quantity": None,
                "options": {
                    "size": None,
                    "temperature": temperature,
                    "ice": None,
                },
            })

            analysis = OrderAnalysis(
                intent="add_item",
                items=[item],
            )
            recommendation_ref.delete()

        else:
            if context is not None:
                recommendation_ref.delete()

            analysis = analyze_order_text(
                store_id=store_id,
                text=text,
            )


    # 개별 삭제는 사용자 확인을 받은 뒤에만 적용
    if analysis.intent == "remove_item":
        cart = get_session_cart(session_id, session_token)

        if len(analysis.items) != 1:
            return {
                "intent": "remove_item",
                "items": [],
                "issues": [],
                "needsClarification": True,
                "question": "삭제할 메뉴를 하나씩 말씀해 주세요.",
                "cart": cart,
                "nextAction": "clarification",
            }

        item = analysis.items[0]
        target_result = find_cart_target(
            cart, item, intent="remove_item"
        )

        if target_result["status"] == "ambiguous":
            return {
                "intent": "remove_item",
                "items": [],
                "issues": [],
                "needsClarification": True,
                "question": "같은 메뉴가 여러 개 있어요. 삭제할 항목을 골라 주세요.",
                "cart": cart,
                "nextAction": "select_cart_item",
                "candidates": target_result["candidates"],
            }

        if target_result["status"] != "matched":
            return {
                "intent": "remove_item",
                "items": [],
                "issues": [],
                "needsClarification": False,
                "question": "장바구니에서 해당 메뉴를 찾지 못했어요.",
                "cart": cart,
                "nextAction": "review_cart",
            }

        target = next(
            item for item in cart["items"]
            if item["itemId"] == target_result["itemId"]
        )

        remove_quantity = analysis.items[0].quantity
        current_quantity = target["quantity"]

        if remove_quantity is not None and remove_quantity <= 0:
            return {
                "intent": "remove_item",
                "items": [],
                "issues": [],
                "needsClarification": True,
                "question": "뺄 수량을 다시 말씀해 주세요.",
                "cart": cart,
                "nextAction": "clarification",
            }

        get_db_reference(
            f"sessions/{session_id}/pendingCartRemoval"
        ).set({
            "itemId": target["itemId"],
            "menuId": target["menuId"],
            "originalQuantity": current_quantity,
            "removeQuantity": remove_quantity,
        })

        set_dialog_state(session_id, "confirm_remove")

        name = target.get("name") or item.menu_text or "해당 메뉴"
        if remove_quantity is None:
            question = f"{name}을(를) 삭제할까요?"
        else:
            question = f"{name} {remove_quantity}개를 뺄까요?"

        return {
            "intent": "remove_item",
            "items": [],
            "issues": [],
            "needsClarification": True,
            "question": question,
            "cart": cart,
            "nextAction": "confirm_remove",
        }

    # 4. 변경·삭제·전체 비우기 명령
    if analysis.intent in (
        "update_item",
        "remove_item",
        "clear_cart",
    ):
        action_result = process_voice_cart_command(
            session_id,
            session_token,
            analysis,
        )

        if action_result["nextAction"] == "confirm_clear":
            set_dialog_state(session_id, "confirm_clear")
        else:
            set_dialog_state(session_id, None)

        return action_result

    # 5. 메뉴·옵션·수량 검증
    result = validate_order_analysis(
        store_id,
        analysis,
    )

    result["question"] = generate_clarification_question(
        result
    )
    result["cart"] = None
    result["nextAction"] = None

    # 이해하지 못한 발화는 재질문으로 안내
    if result["intent"] == "unknown":
        result["needsClarification"] = True
        result["question"] = (
            "말씀하신 내용을 정확히 이해하지 못했어요. "
            "주문하실 메뉴나 원하시는 기능을 "
            "다시 말씀해 주시겠어요?"
        )
        result["nextAction"] = "clarification"
        return result

    # 주문 추가 외 의도
    if result["intent"] != "add_item":
        return result


    # 6. 미완성 주문이면 질문하고 대기
    if result["needsClarification"]:
        save_pending_order(
            session_id,
            result,
        )

        result["nextAction"] = "clarification"
        return result

    # 7. 모든 정보가 완성된 경우에만 장바구니 추가
    result["cart"] = add_analyzed_items(
        session_id,
        session_token,
        result["items"],
    )

    clear_pending_order(session_id)

    # 8. 담기 완료 후 추가 주문 여부 대기
    set_dialog_state(
        session_id,
        "awaiting_more",
    )

    result["question"] = "더 필요한 게 있나요?"
    result["nextAction"] = "ask_more"

    return result
