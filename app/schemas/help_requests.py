from pydantic import BaseModel, Field


class HelpRequestCreate(BaseModel):
    session_id: str = Field(
        alias="sessionId",
        pattern=r"^[a-f0-9]{32}$"
    )

    model_config = {"populate_by_name": True}