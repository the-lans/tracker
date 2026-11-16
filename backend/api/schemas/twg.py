"""Публичные поля личного подключения TWG; секрет только во входном запросе."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class TwgConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str = Field(min_length=1, max_length=253)
    email: str = Field(min_length=3, max_length=254)
    token: SecretStr | None = Field(default=None, max_length=8192)


class TwgConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    configured: bool
    site: str | None = None
    email: str | None = None
