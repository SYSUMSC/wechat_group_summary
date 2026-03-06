"""WeFlow HTTP API 适配层。"""

from __future__ import annotations

from typing import Any

import httpx

from .constants import WEFLOW_BATCH_LIMIT
from .exceptions import WeFlowError
from .models import ChatLabConversation, ChatLabMeta, SyncedGroup, WeFlowSettings


class WeFlowClient:
    """负责与本地 WeFlow HTTP API 通信。"""

    def __init__(self, settings: WeFlowSettings, http_client: httpx.Client | None = None):
        self.base_url = settings.base_url
        self.timeout_seconds = settings.timeout_seconds
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "WeFlowClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """统一处理 GET 请求、HTTP 错误和 JSON 反序列化错误。"""
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WeFlowError(f"请求 WeFlow 失败：{exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise WeFlowError(f"WeFlow 返回了非 JSON 响应：{path}") from exc

        if isinstance(data, dict) and data.get("error"):
            raise WeFlowError(str(data["error"]))
        if not isinstance(data, dict):
            raise WeFlowError(f"WeFlow 返回格式异常：{path}")
        return data

    def health_check(self) -> bool:
        """检查本地 WeFlow HTTP API 是否可访问。"""
        data = self._get_json("/health")
        return data.get("status") == "ok"

    def list_groups(self, keyword: str | None = None, limit: int = 10000) -> list[SyncedGroup]:
        """读取会话列表，并只保留群聊会话。"""
        params: dict[str, Any] = {"limit": limit}
        if keyword:
            params["keyword"] = keyword
        data = self._get_json("/api/v1/sessions", params=params)
        rows = data.get("sessions", [])

        groups: list[SyncedGroup] = []
        for row in rows:
            talker = str(row.get("username") or row.get("userName") or "").strip()
            if not talker.endswith("@chatroom"):
                continue
            display_name = str(row.get("displayName") or row.get("display_name") or talker).strip() or talker
            groups.append(
                SyncedGroup(
                    talker=talker,
                    display_name=display_name,
                    type=str(row.get("type") or "group"),
                    last_timestamp=row.get("lastTimestamp") or row.get("lastTime"),
                    unread_count=int(row.get("unreadCount") or 0),
                )
            )
        return groups

    def fetch_messages(
        self,
        talker: str,
        start_ts: int,
        end_ts: int,
        max_messages: int,
        enable_images: bool,
    ) -> ChatLabConversation:
        """分页拉取某个群在指定时间窗口内的消息。"""
        all_messages = []
        meta: ChatLabMeta | None = None
        offset = 0

        while len(all_messages) < max_messages:
            batch_limit = min(WEFLOW_BATCH_LIMIT, max_messages - len(all_messages))
            params: dict[str, Any] = {
                "talker": talker,
                "limit": batch_limit,
                "offset": offset,
                "format": "chatlab",
                "start": start_ts,
                "end": end_ts,
            }
            # 只有在启用图片理解时才导出图片媒体，避免额外 IO。
            if enable_images:
                params.update({"media": 1, "image": 1, "voice": 0, "video": 0, "emoji": 0})

            data = self._get_json("/api/v1/messages", params=params)
            conversation = ChatLabConversation.model_validate(data)
            if meta is None:
                meta = conversation.meta
            if not conversation.messages:
                break

            all_messages.extend(conversation.messages)
            if len(conversation.messages) < batch_limit:
                break
            offset += len(conversation.messages)

        # 使用稳定键去重，避免分页场景下出现重复消息。
        deduped: dict[tuple[int, str, int, str | None, str | None], Any] = {}
        for message in all_messages:
            key = (message.timestamp, message.sender, message.type, message.content, message.mediaPath)
            deduped[key] = message

        ordered_messages = sorted(deduped.values(), key=lambda item: (item.timestamp, item.sender, item.content or ""))

        if meta is None:
            meta = ChatLabMeta(name=talker, platform="wechat", type="group", groupId=talker)
        return ChatLabConversation(meta=meta, messages=ordered_messages)
