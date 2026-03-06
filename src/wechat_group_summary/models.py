from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, field_validator, model_validator

from .exceptions import ConfigError


def _normalize_url(value: str) -> str:
    return value.strip().rstrip("/")


class WeFlowSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str = "http://127.0.0.1:5031"
    timeout_seconds: PositiveInt = 30

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("weflow.base_url 不能为空")
        return _normalize_url(value)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str
    api_key: str | None = None
    model: str
    vision_model: str | None = None
    timeout_seconds: PositiveInt = 60

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provider.base_url 不能为空")
        return _normalize_url(value)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider.model 不能为空")
        return normalized

    def resolved_api_key(self) -> str:
        """只从配置文件读取 API Key，未填写时在实际调用阶段报错。"""
        if self.api_key and self.api_key.strip():
            return self.api_key.strip()
        raise ConfigError("未找到可用的 provider API Key，请在 wechat_group_summary.toml 中填写 api_key")

    def resolved_vision_model(self) -> str:
        return (self.vision_model or self.model).strip()


class GroupConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    display_name: str | None = None
    provider: str
    window_hours: PositiveFloat = 12
    system_prompt: str
    enable_images: bool = True
    max_messages: PositiveInt = 500
    chunk_char_limit: PositiveInt = 12000

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("group.provider 不能为空")
        return normalized

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("group.system_prompt 不能为空")
        return normalized


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    weflow: WeFlowSettings = Field(default_factory=WeFlowSettings)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    groups: dict[str, GroupConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_group_provider_refs(self) -> "AppConfig":
        if not self.providers:
            raise ValueError("至少需要配置一个 provider")
        for talker, group in self.groups.items():
            if not talker.endswith("@chatroom"):
                raise ValueError(f"群配置键必须是 chatroom id: {talker}")
            if group.provider not in self.providers:
                raise ValueError(f"群 {talker} 引用了不存在的 provider: {group.provider}")
        return self


class SyncedGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    talker: str
    display_name: str
    type: str = "group"
    last_timestamp: int | None = None
    unread_count: int = 0


class GroupCache(BaseModel):
    model_config = ConfigDict(extra="ignore")

    synced_at: datetime
    groups: list[SyncedGroup] = Field(default_factory=list)


class ChatLabMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    platform: str = "wechat"
    type: str = "group"
    groupId: str | None = None
    ownerId: str | None = None


class ChatLabMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sender: str = ""
    accountName: str = ""
    groupNickname: str | None = None
    timestamp: int
    type: int
    content: str | None = None
    mediaPath: str | None = None


class ChatLabConversation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meta: ChatLabMeta
    messages: list[ChatLabMessage] = Field(default_factory=list)


@dataclass(frozen=True)
class ResolvedGroup:
    talker: str
    display_name: str
    group: GroupConfig


@dataclass(frozen=True)
class NormalizedMessage:
    timestamp: int
    speaker_id: str
    speaker_name: str
    kind: Literal["text", "image", "card", "link"]
    text: str
    media_path: str | None = None


@dataclass(frozen=True)
class SummaryResult:
    talker: str
    display_name: str
    provider_name: str
    model_name: str
    window_hours: float
    started_at: datetime
    ended_at: datetime
    transcript_count: int
    summary_text: str
    output_path: Path
