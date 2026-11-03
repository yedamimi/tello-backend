
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
)
from app.services.voice_cart import (
    process_voice_cart_command,
    confirm_voice_clear,
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
            f"{name}는 품절이에요. "
            "다른 메뉴를 말씀해 주세요."
        )

    if code in ("QUANTITY_REQUIRED", "QUANTITY_INVALID"):
        return f"{name}는 몇 개 주문하시겠어요?"

    questions = {
        "size": f"{name}의 크기를 골라 주세요.",
        "temperature": (
            f"{name}는 따뜻하게 드릴까요, "
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
            "바꿔", "바꿀", "변경", "아니"
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
        # Preserve recommendation preferences until a menu is selected.
        recommendation_ref = get_db_reference(
            f"sessions/{session_id}/recommendationContext"
        )

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
