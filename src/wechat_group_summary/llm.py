"""LLM 与视觉模型调用封装。"""

from __future__ import annotations

import base64
import mimetypes
from typing import Any, Protocol

import httpx
from openai import OpenAI

from .constants import IMAGE_DESCRIPTION_PROMPT
from .exceptions import LLMError
from .models import ProviderConfig


class LLMGateway(Protocol):
    """抽象出文本生成和图片描述两个能力，便于测试替换。"""

    def generate_text(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str: ...

    def describe_image(self, image_url: str) -> str: ...


class OpenAIChatGateway:
    """兼容 OpenAI Chat Completions 风格的网关实现。"""

    def __init__(
        self,
        provider: ProviderConfig,
        http_client: httpx.Client | None = None,
        openai_client: OpenAI | None = None,
    ):
        self.provider = provider
        self._http_client = http_client or httpx.Client(timeout=provider.timeout_seconds)
        self._owns_http_client = http_client is None
        self._client = openai_client or OpenAI(
            base_url=provider.base_url,
            api_key=provider.resolved_api_key(),
            timeout=provider.timeout_seconds,
        )

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def generate_text(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
        """调用文本模型生成总结或中间摘要。"""
        try:
            response = self._client.chat.completions.create(
                model=model or self.provider.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            raise LLMError(f"文本模型调用失败：{exc}") from exc

        return self._extract_text(response)

    def describe_image(self, image_url: str) -> str:
        """先把图片转成 data URL，再交给视觉模型生成可嵌入转录的描述。"""
        data_url = self._build_data_url(image_url)
        try:
            response = self._client.chat.completions.create(
                model=self.provider.resolved_vision_model(),
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": IMAGE_DESCRIPTION_PROMPT},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
            )
        except Exception as exc:
            raise LLMError(f"视觉模型调用失败：{exc}") from exc

        return self._extract_text(response)

    def _build_data_url(self, image_url: str) -> str:
        """把本地 WeFlow 暴露的媒体 URL 下载后封装成 data URL。"""
        if image_url.startswith("data:"):
            return image_url

        try:
            response = self._http_client.get(image_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"下载图片失败：{exc}") from exc

        content_type = response.headers.get("content-type")
        if not content_type:
            guessed, _ = mimetypes.guess_type(image_url)
            content_type = guessed or "image/jpeg"
        encoded = base64.b64encode(response.content).decode("utf-8")
        return f"data:{content_type};base64,{encoded}"

    def _extract_text(self, response: Any) -> str:
        """兼容字符串和富文本数组两种响应内容格式。"""
        try:
            message_content = response.choices[0].message.content
        except Exception as exc:
            raise LLMError("模型返回内容为空") from exc

        if isinstance(message_content, str):
            text = message_content.strip()
        elif isinstance(message_content, list):
            parts: list[str] = []
            for item in message_content:
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if text_value:
                        parts.append(str(text_value))
                else:
                    text_value = getattr(item, "text", None)
                    if text_value:
                        parts.append(str(text_value))
            text = "\n".join(parts).strip()
        else:
            text = str(message_content).strip()

        if not text:
            raise LLMError("模型返回内容为空")
        return text
