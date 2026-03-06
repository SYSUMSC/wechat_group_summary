from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from wechat_group_summary.cli import app
from wechat_group_summary.models import GroupCache, SyncedGroup


runner = CliRunner()


class FakeWeFlowClient:
    def __init__(self, groups=None):
        self.groups = groups or [SyncedGroup(talker="room@chatroom", display_name="项目群")]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def close(self):
        return None

    def health_check(self):
        return True

    def list_groups(self, keyword=None):
        return self.groups


class FakeLLM:
    def generate_text(self, system_prompt, user_prompt, model=None):
        return "最终总结"

    def describe_image(self, image_url):
        return "图片描述"

    def close(self):
        return None


class FakeSummaryService:
    def __init__(self, weflow_client, llm_gateway):
        self.weflow_client = weflow_client
        self.llm_gateway = llm_gateway

    def summarize(self, request, paths, now=None):
        output_path = paths.outputs_dir / "demo" / "result.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# demo", encoding="utf-8")
        from wechat_group_summary.models import SummaryResult

        return SummaryResult(
            talker=request.talker,
            display_name=request.display_name,
            provider_name=request.provider_name,
            model_name=request.provider.model,
            window_hours=request.window_hours,
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
            transcript_count=3,
            summary_text="最终总结",
            output_path=output_path,
        )


def write_config(root: Path) -> Path:
    config_path = root / "wechat_group_summary.toml"
    config_path.write_text(
        """
[weflow]
base_url = "http://127.0.0.1:5031"

[providers.main]
base_url = "https://api.openai.com/v1"
api_key = "secret"
model = "gpt-4.1-mini"

[groups."room@chatroom"]
display_name = "项目群"
provider = "main"
window_hours = 6
system_prompt = "请总结"
""".strip(),
        encoding="utf-8",
    )
    return config_path


def test_groups_sync_writes_cache(tmp_path: Path, monkeypatch) -> None:
    from wechat_group_summary import cli

    config_path = write_config(tmp_path)
    monkeypatch.setattr(cli, "create_weflow_client", lambda settings: FakeWeFlowClient())

    result = runner.invoke(app, ["groups", "sync", "--config", str(config_path)])

    assert result.exit_code == 0
    assert (tmp_path / ".wechat-group-summary" / "groups_cache.json").exists()


def test_summarize_uses_override_hours(tmp_path: Path, monkeypatch) -> None:
    from wechat_group_summary import cli

    config_path = write_config(tmp_path)
    cache_path = tmp_path / ".wechat-group-summary" / "groups_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    GroupCache(synced_at=datetime.now(timezone.utc), groups=[SyncedGroup(talker="room@chatroom", display_name="项目群")]).model_dump_json
    cache_path.write_text(
        GroupCache(
            synced_at=datetime.now(timezone.utc),
            groups=[SyncedGroup(talker="room@chatroom", display_name="项目群")],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "create_weflow_client", lambda settings: FakeWeFlowClient())
    monkeypatch.setattr(cli, "create_llm_gateway", lambda provider: FakeLLM())
    monkeypatch.setattr(cli, "SummaryService", FakeSummaryService)

    result = runner.invoke(app, ["summarize", "--config", str(config_path), "--group", "项目群", "--hours", "3"])

    assert result.exit_code == 0
    assert "已保存" in result.stdout

