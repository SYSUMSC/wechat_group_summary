from datetime import datetime
from pathlib import Path

from wechat_group_summary.models import ChatLabConversation, ChatLabMessage, ChatLabMeta, GroupConfig, NormalizedMessage, ProviderConfig
from wechat_group_summary.paths import ProjectPaths
from wechat_group_summary.summary import SummaryRequest, SummaryService, chunk_lines, normalize_messages


class FakeWeFlowClient:
    def __init__(self, conversation: ChatLabConversation):
        self.conversation = conversation

    def fetch_messages(self, **kwargs):
        return self.conversation


class FakeLLM:
    def __init__(self):
        self.text_calls: list[tuple[str, str, str | None]] = []
        self.image_calls: list[str] = []

    def generate_text(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
        self.text_calls.append((system_prompt, user_prompt, model))
        return f"summary-call-{len(self.text_calls)}"

    def describe_image(self, image_url: str) -> str:
        self.image_calls.append(image_url)
        return "一张展示项目看板的截图"

    def close(self) -> None:
        return None


def build_conversation() -> ChatLabConversation:
    return ChatLabConversation(
        meta=ChatLabMeta(name="项目群", groupId="room@chatroom"),
        messages=[
            ChatLabMessage(sender="u1", accountName="张三", timestamp=100, type=0, content="今天先过一下需求"),
            ChatLabMessage(sender="u2", accountName="李四", timestamp=101, type=1, content="[图片]", mediaPath="http://127.0.0.1:5031/api/v1/media/room/images/1.jpg"),
            ChatLabMessage(sender="u1", accountName="张三", timestamp=102, type=7, content="PRD 链接：xxx"),
            ChatLabMessage(sender="u3", accountName="王五", timestamp=103, type=24, content="腾讯文档卡片：迭代计划"),
            ChatLabMessage(sender="u4", accountName="赵六", timestamp=104, type=2, content="[语音]"),
        ],
    )


def test_normalize_messages_filters_unsupported_types() -> None:
    messages = normalize_messages(build_conversation().messages, include_images=True)
    assert [message.kind for message in messages] == ["text", "image", "link", "card"]


def test_chunk_lines_splits_large_transcript() -> None:
    chunks = chunk_lines(["a" * 8, "b" * 8, "c" * 8], max_chars=10)
    assert len(chunks) == 3


def test_summary_service_uses_image_description_and_chunking(tmp_path: Path) -> None:
    provider = ProviderConfig(base_url="https://api.openai.com/v1", api_key="secret", model="gpt-4.1-mini")
    group = GroupConfig(provider="main", system_prompt="请总结", chunk_char_limit=40, max_messages=20)
    request = SummaryRequest(
        talker="room@chatroom",
        display_name="项目群",
        provider_name="main",
        provider=provider,
        group=group,
        window_hours=12,
        include_images=True,
    )
    paths = ProjectPaths.from_config(tmp_path / "wechat_group_summary.toml")
    fake_llm = FakeLLM()
    service = SummaryService(FakeWeFlowClient(build_conversation()), fake_llm)

    result = service.summarize(request, paths=paths, now=datetime.fromtimestamp(200).astimezone())

    assert result.summary_text == "summary-call-5"
    assert len(fake_llm.image_calls) == 1
    assert len(fake_llm.text_calls) == 5
    assert result.output_path.exists()
