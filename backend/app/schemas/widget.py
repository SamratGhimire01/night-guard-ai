from pydantic import BaseModel, field_validator


class WidgetMessageRequest(BaseModel):
    # Absent/null on a visitor's very first message — the server mints one.
    session_token: str | None = None
    content: str

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field must not be blank.")
        return value


class WidgetMessageResponse(BaseModel):
    session_token: str
    response: str
    intent: str
