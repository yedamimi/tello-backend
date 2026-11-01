"""주문 세션·장바구니의 요청·응답 데이터 모델."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionCreateRequest(BaseModel):
    """세션 생성 요청."""

    store_id: str = Field(
        alias="storeId",
        min_length=1,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class SessionCreateResponse(BaseModel):
    """세션 생성 응답."""

    session_id: str = Field(alias="sessionId")
    store_id: str = Field(alias="storeId")
    session_token: str = Field(alias="sessionToken")


class CartOptions(BaseModel):
    """장바구니에서 선택할 크기·온도·얼음 옵션."""

    model_config = ConfigDict(extra="forbid")

    size: Literal["regular", "large"] | None = None
    temperature: Literal["hot", "ice"] | None = None
    ice: Literal["more", "regular", "less"] | None = None


class CartItemAddRequest(BaseModel):
    """장바구니 메뉴 추가 요청."""

    model_config = ConfigDict(extra="forbid")

    menu_id: str = Field(
        alias="menuId",
        min_length=1,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    quantity: int = Field(strict=True, gt=0)
    selected_options: CartOptions = Field(
        alias="selectedOptions",
        default_factory=CartOptions,
    )


class CartItemUpdateRequest(BaseModel):
    """장바구니에서 변경할 값만 받는다."""

    model_config = ConfigDict(extra="forbid")

    quantity: int | None = Field(
        default=None,
        strict=True,
        gt=0,
    )
    selected_options: CartOptions | None = Field(
        alias="selectedOptions",
        default=None,
    )

    @model_validator(mode="before")
    @classmethod
    def check_changes(cls, data):
        """빈 요청과 명시적인 null 값을 거절한다."""
        if isinstance(data, dict):
            if not data:
                raise ValueError("변경할 내용을 입력해 주세요.")

            if any(value is None for value in data.values()):
                raise ValueError("변경 값에는 null을 사용할 수 없어요.")

        return data
