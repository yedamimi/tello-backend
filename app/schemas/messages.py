"""음성 주문 텍스트의 분석 결과 모델."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AnalyzedOptions(BaseModel):
    """옵션 필드는 모두 반환하고, 언급하지 않은 값은 null로 둔다."""

    model_config = ConfigDict(extra="forbid")

    size: Literal["regular", "large"] | None = Field(
        description=(
            "크기. 보통은 regular, 큰 사이즈는 large. "
            "언급하지 않았거나 불명확하면 null"
        ),
    )
    temperature: Literal["hot", "ice"] | None = Field(
        description=(
            "온도. 따뜻한 것은 hot, 차가운 것은 ice. "
            "언급하지 않았거나 불명확하면 null"
        ),
    )
    ice: Literal["more", "regular", "less"] | None = Field(
        description=(
            "얼음 양. 많이는 more, 보통은 regular, 적게는 less. "
            "언급하지 않았거나 불명확하면 null"
        ),
    )


class AnalyzedItem(BaseModel):
    """하나의 주문 항목에 메뉴·수량·옵션을 함께 기록한다."""

    model_config = ConfigDict(extra="forbid")

    menu_text: str = Field(
        description="해당 주문 항목에 대한 고객의 메뉴 표현",
    )
    menu_id: str | None = Field(
        description=(
            "제공된 매장 메뉴의 ID. "
            "메뉴를 특정할 수 없으면 null"
        ),
    )
    quantity: int | None = Field(
        strict=True,
        gt=0,
        description=(
            "고객이 말한 수량. "
            "언급하지 않았거나 불명확하면 null"
        ),
    )
    options: AnalyzedOptions = Field(
        description=(
            "이 주문 항목의 크기·온도·얼음 옵션. "
            "객체와 내부 필드를 생략하지 않는다"
        ),
    )


class OrderAnalysis(BaseModel):
    """고객 발화의 의도와 메뉴 분석 결과."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal[
        "add_item",
        "update_item",
        "remove_item",
        "clear_cart",
        "browse_menu",
        "recommend",
        "answer",
        "review_order",
        "request_help",
        "unknown",
    ]
    items: list[AnalyzedItem] = Field(
        description=(
            "고객이 요청한 주문 항목 목록. "
            "옵션만 별도 항목으로 분리하지 않는다. "
            "추출할 메뉴가 없으면 빈 목록을 반환한다"
        ),
    )