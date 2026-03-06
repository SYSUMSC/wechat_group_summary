from pathlib import Path

import pytest

from wechat_group_summary.config import init_workspace, load_settings, render_sample_config
from wechat_group_summary.exceptions import ConfigError
from wechat_group_summary.paths import ProjectPaths


def test_render_sample_config_contains_group_block() -> None:
    content = render_sample_config()
    assert "[providers.default]" in content
    assert 'api_key = ""' in content
    assert "[groups.\"1234567890@chatroom\"]" in content


def test_init_workspace_creates_config_and_gitignore_entries(tmp_path: Path) -> None:
    paths = ProjectPaths.from_config(tmp_path / "wechat_group_summary.toml")
    created = init_workspace(paths)

    assert "config" in created
    assert paths.config_path.exists()

    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".wechat-group-summary/" in gitignore
    assert "outputs/" in gitignore
    assert "wechat_group_summary.toml" in gitignore


def test_load_settings_uses_plain_api_key(tmp_path: Path) -> None:
    config_path = tmp_path / "wechat_group_summary.toml"
    config_path.write_text(
        """
[weflow]
base_url = "http://127.0.0.1:5031"

[providers.main]
base_url = "https://api.openai.com/v1"
api_key = "secret"
model = "gpt-4.1-mini"

[groups."a@chatroom"]
provider = "main"
window_hours = 6
system_prompt = "hello"
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)
    assert settings.providers["main"].resolved_api_key() == "secret"


def test_load_settings_invalid_provider_reference(tmp_path: Path) -> None:
    config_path = tmp_path / "wechat_group_summary.toml"
    config_path.write_text(
        """
[providers.main]
base_url = "https://api.openai.com/v1"
api_key = "secret"
model = "gpt-4.1-mini"

[groups."a@chatroom"]
provider = "missing"
window_hours = 6
system_prompt = "hello"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_settings(config_path)
