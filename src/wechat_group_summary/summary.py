"""群聊总结核心流程。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .constants import CHATLAB_CONTACT, CHATLAB_IMAGE, CHATLAB_LINK, CHATLAB_REPLY, CHATLAB_SHARE, CHATLAB_TEXT, PARTIAL_SUMMARY_PROMPT
from .exceptions import GroupResolutionError, LLMError, NoMessagesError
from .llm import LLMGateway
from .models import ChatLabConversation, ChatLabMessage, GroupCache, GroupConfig, NormalizedMessage, ProviderConfig, ResolvedGroup, SummaryResult
from .paths import ProjectPaths
from .weflow import WeFlowClient


@dataclass(frozen=True)
class GroupListRow:
    """`groups list` 命令展示用的行模型。"""

    talker: str
    display_name: str
    configured: bool
    provider: str | None
    synced: bool


@dataclass(frozen=True)
class SummaryRequest:
    """执行一次总结时的入参。"""

    talker: str
    display_name: str
    provider_name: str
    provider: ProviderConfig
    group: GroupConfig
    window_hours: float
    include_images: bool
    output_path: Path | None = None


def display_name_for(talker: str, group: GroupConfig, cache: GroupCache | None) -> str:
    """显示名优先读配置，其次读同步缓存，最后回退到 talker。"""
    if group.display_name:
        return group.display_name
    if cache:
        for item in cache.groups:
            if item.talker == talker:
                return item.display_name
    return talker


def resolve_group_choice(query: str, groups: dict[str, GroupConfig], cache: GroupCache | None) -> ResolvedGroup:
    """按 talker / 精确群名 / 唯一模糊匹配 的顺序解析目标群。"""
    normalized_query = query.strip().lower()
    if not normalized_query:
        raise GroupResolutionError("--group 不能为空")

    exact_talker_matches = [talker for talker in groups if talker.lower() == normalized_query]
    if len(exact_talker_matches) == 1:
        talker = exact_talker_matches[0]
        group = groups[talker]
        return ResolvedGroup(talker=talker, display_name=display_name_for(talker, group, cache), group=group)

    exact_name_matches = [
        talker
        for talker, group in groups.items()
        if display_name_for(talker, group, cache).lower() == normalized_query
    ]
    if len(exact_name_matches) == 1:
        talker = exact_name_matches[0]
        group = groups[talker]
        return ResolvedGroup(talker=talker, display_name=display_name_for(talker, group, cache), group=group)
    if len(exact_name_matches) > 1:
        candidates = ", ".join(sorted(f"{talker} ({display_name_for(talker, groups[talker], cache)})" for talker in exact_name_matches))
        raise GroupResolutionError(f"找到多个同名群，请改用 talker：{candidates}")

    fuzzy_matches = [
        talker
        for talker, group in groups.items()
        if normalized_query in talker.lower() or normalized_query in display_name_for(talker, group, cache).lower()
    ]
    if len(fuzzy_matches) == 1:
        talker = fuzzy_matches[0]
        group = groups[talker]
        return ResolvedGroup(talker=talker, display_name=display_name_for(talker, group, cache), group=group)
    if len(fuzzy_matches) > 1:
        candidates = ", ".join(sorted(f"{talker} ({display_name_for(talker, groups[talker], cache)})" for talker in fuzzy_matches))
        raise GroupResolutionError(f"匹配到多个群，请输入更精确的群名或 talker：{candidates}")

    if cache:
        synced_hit = [item for item in cache.groups if normalized_query in item.talker.lower() or normalized_query in item.display_name.lower()]
        if synced_hit:
            examples = ", ".join(sorted(f"{item.talker} ({item.display_name})" for item in synced_hit))
            raise GroupResolutionError(f"群已同步但未配置：{examples}")

    raise GroupResolutionError(f"未找到匹配的群：{query}")


def build_group_rows(groups: dict[str, GroupConfig], cache: GroupCache | None, keyword: str | None = None) -> list[GroupListRow]:
    """把配置群和缓存群合并成统一列表。"""
    cache_map = {item.talker: item for item in (cache.groups if cache else [])}
    talkers = set(cache_map) | set(groups)
    rows: list[GroupListRow] = []

    for talker in talkers:
        group = groups.get(talker)
        synced = cache_map.get(talker)
        display_name = group.display_name if group and group.display_name else (synced.display_name if synced else talker)
        row = GroupListRow(
            talker=talker,
            display_name=display_name,
            configured=group is not None,
            provider=group.provider if group else None,
            synced=synced is not None,
        )
        rows.append(row)

    if keyword:
        keyword_lower = keyword.lower()
        rows = [row for row in rows if keyword_lower in row.talker.lower() or keyword_lower in row.display_name.lower()]

    return sorted(rows, key=lambda item: (not item.configured, item.display_name.lower(), item.talker.lower()))


def normalize_messages(messages: list[ChatLabMessage], include_images: bool) -> list[NormalizedMessage]:
    """把 ChatLab 消息压平成内部统一结构，并过滤不支持的类型。"""
    normalized: list[NormalizedMessage] = []
    for message in messages:
        kind = classify_message_kind(message.type)
        if kind is None:
            continue
        if kind == "image" and not include_images:
            continue

        text = (message.content or "").strip()
        if kind == "image":
            text = text or "[图片]"
        elif not text:
            continue

        speaker_name = (message.groupNickname or message.accountName or message.sender or "未知用户").strip()
        speaker_id = (message.sender or speaker_name).strip()
        normalized.append(
            NormalizedMessage(
                timestamp=message.timestamp,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                kind=kind,
                text=text,
                media_path=message.mediaPath,
            )
        )

    return sorted(normalized, key=lambda item: (item.timestamp, item.speaker_name.lower(), item.text))


def classify_message_kind(message_type: int) -> str | None:
    """只保留当前版本支持的 4 种消息。"""
    if message_type in {CHATLAB_TEXT, CHATLAB_REPLY}:
        return "text"
    if message_type == CHATLAB_IMAGE:
        return "image"
    if message_type == CHATLAB_LINK:
        return "link"
    if message_type in {CHATLAB_CONTACT, CHATLAB_SHARE}:
        return "card"
    return None


def chunk_lines(lines: list[str], max_chars: int) -> list[str]:
    """按近似字符数切分转录，避免一次性塞给模型过长上下文。"""
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for line in lines:
        line_size = len(line) + 1
        if current and current_size + line_size > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_size = line_size
            continue
        current.append(line)
        current_size += line_size

    if current:
        chunks.append("\n".join(current))
    return chunks


def slugify(value: str) -> str:
    """生成稳定输出目录名。"""
    lowered = value.strip().lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff_-]+", "-", lowered).strip("-") or "group"


class SummaryService:
    """串起消息抓取、图片理解、摘要分块和 Markdown 输出。"""

    def __init__(self, weflow_client: WeFlowClient, llm_gateway: LLMGateway):
        self.weflow_client = weflow_client
        self.llm_gateway = llm_gateway

    def summarize(self, request: SummaryRequest, paths: ProjectPaths, now: datetime | None = None) -> SummaryResult:
        """执行完整总结流程。"""
        end_dt = now or datetime.now().astimezone()
        start_dt = end_dt - timedelta(hours=request.window_hours)

        conversation = self.weflow_client.fetch_messages(
            talker=request.talker,
            start_ts=int(start_dt.timestamp()),
            end_ts=int(end_dt.timestamp()),
            max_messages=request.group.max_messages,
            enable_images=request.include_images,
        )

        normalized_messages = normalize_messages(conversation.messages, include_images=request.include_images)
        if not normalized_messages:
            raise NoMessagesError("时间窗口内没有可用于总结的文本、图片、卡片或链接消息")

        transcript_lines = self._build_transcript_lines(normalized_messages, request.include_images)
        summary_text = self._generate_summary(
            request=request,
            conversation=conversation,
            normalized_messages=normalized_messages,
            transcript_lines=transcript_lines,
            start_dt=start_dt,
            end_dt=end_dt,
        )

        output_path = request.output_path or self._default_output_path(paths, request, end_dt)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            self._render_markdown(
                request=request,
                summary_text=summary_text,
                start_dt=start_dt,
                end_dt=end_dt,
                transcript_count=len(normalized_messages),
            ),
            encoding="utf-8",
        )

        return SummaryResult(
            talker=request.talker,
            display_name=request.display_name,
            provider_name=request.provider_name,
            model_name=request.provider.model,
            window_hours=request.window_hours,
            started_at=start_dt,
            ended_at=end_dt,
            transcript_count=len(normalized_messages),
            summary_text=summary_text,
            output_path=output_path,
        )

    def _build_transcript_lines(self, messages: list[NormalizedMessage], include_images: bool) -> list[str]:
        """把标准消息转成供 LLM 输入的线性转录。"""
        image_cache: dict[str, str] = {}
        lines: list[str] = []

        for message in messages:
            text = message.text
            if message.kind == "image":
                if include_images and message.media_path:
                    # 同一张图片只描述一次，避免重复调用视觉模型。
                    if message.media_path not in image_cache:
                        try:
                            image_cache[message.media_path] = self.llm_gateway.describe_image(message.media_path)
                        except LLMError:
                            # 视觉失败时退化为占位符，但不阻断整次总结。
                            image_cache[message.media_path] = "[图片]"
                    text = f"[图片] {image_cache[message.media_path]}"
                else:
                    text = "[图片]"
            elif message.kind == "card":
                text = f"[卡片] {text}"
            elif message.kind == "link":
                text = f"[链接] {text}"

            timestamp = datetime.fromtimestamp(message.timestamp).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"{timestamp} {message.speaker_name}: {text}")

        return lines

    def _generate_summary(
        self,
        request: SummaryRequest,
        conversation: ChatLabConversation,
        normalized_messages: list[NormalizedMessage],
        transcript_lines: list[str],
        start_dt: datetime,
        end_dt: datetime,
    ) -> str:
        """单段直接总结，多段先做中间摘要再汇总。"""
        metadata = self._build_context(request, conversation, normalized_messages, start_dt, end_dt)
        chunks = chunk_lines(transcript_lines, request.group.chunk_char_limit)

        if len(chunks) == 1:
            user_prompt = f"{metadata}\n\n群聊转录：\n{chunks[0]}"
            return self.llm_gateway.generate_text(request.group.system_prompt, user_prompt)

        partials: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            partial_prompt = (
                f"{metadata}\n\n当前是第 {index}/{len(chunks)} 段群聊转录。"
                f"\n请先输出这个片段的中间摘要，便于后续合并：\n{chunk}"
            )
            partial_summary = self.llm_gateway.generate_text(PARTIAL_SUMMARY_PROMPT, partial_prompt)
            partials.append(f"第 {index} 段摘要：\n{partial_summary}")

        final_prompt = f"{metadata}\n\n以下是按顺序整理的分段摘要，请综合输出最终群聊总结：\n\n" + "\n\n".join(partials)
        return self.llm_gateway.generate_text(request.group.system_prompt, final_prompt)

    def _build_context(
        self,
        request: SummaryRequest,
        conversation: ChatLabConversation,
        normalized_messages: list[NormalizedMessage],
        start_dt: datetime,
        end_dt: datetime,
    ) -> str:
        """构造固定的用户侧上下文，减少每个群 prompt 的重复配置。"""
        participant_counter = Counter(message.speaker_name for message in normalized_messages)
        participants = "、".join(f"{name}({count})" for name, count in participant_counter.most_common(10))
        return "\n".join(
            [
                f"群聊名称：{request.display_name}",
                f"会话ID：{request.talker}",
                f"WeFlow 会话名：{conversation.meta.name or request.display_name}",
                f"时间范围：{start_dt.strftime('%Y-%m-%d %H:%M:%S')} 至 {end_dt.strftime('%Y-%m-%d %H:%M:%S')}",
                f"有效消息数：{len(normalized_messages)}",
                f"参与者统计：{participants or '无'}",
            ]
        )

    def _default_output_path(self, paths: ProjectPaths, request: SummaryRequest, end_dt: datetime) -> Path:
        """在默认输出目录下按群和时间生成结果文件名。"""
        group_slug = slugify(request.display_name or request.talker)
        filename = end_dt.strftime("%Y%m%d-%H%M%S") + ".md"
        return paths.outputs_dir / group_slug / filename

    def _render_markdown(
        self,
        request: SummaryRequest,
        summary_text: str,
        start_dt: datetime,
        end_dt: datetime,
        transcript_count: int,
    ) -> str:
        """渲染最终 Markdown 文件内容。"""
        return "\n".join(
            [
                f"# {request.display_name} 群聊总结",
                "",
                f"- 会话 ID：`{request.talker}`",
                f"- 时间窗口：最近 `{request.window_hours:g}` 小时",
                f"- 实际范围：`{start_dt.strftime('%Y-%m-%d %H:%M:%S')}` ~ `{end_dt.strftime('%Y-%m-%d %H:%M:%S')}`",
                f"- Provider：`{request.provider_name}`",
                f"- Model：`{request.provider.model}`",
                f"- 有效消息数：`{transcript_count}`",
                "",
                "## 总结",
                "",
                summary_text.strip(),
                "",
            ]
        )
