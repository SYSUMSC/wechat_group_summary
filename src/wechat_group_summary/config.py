"""配置加载与初始化逻辑。"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import ValidationError

from .constants import DEFAULT_SYSTEM_PROMPT, GITIGNORE_ENTRIES
from .exceptions import ConfigError
from .models import AppConfig
from .paths import ProjectPaths


def render_sample_config() -> str:
    """生成仓库内可直接使用的示例配置模板。"""
    prompt = DEFAULT_SYSTEM_PROMPT.replace('"""', '\"\"\"')
    return f'''[weflow]
base_url = "http://127.0.0.1:5031"
timeout_seconds = 30

[providers.default]
base_url = "https://api.openai.com/v1"
api_key = ""
model = "gpt-4.1-mini"
vision_model = "gpt-4.1-mini"
timeout_seconds = 60

[groups."1234567890@chatroom"]
display_name = "把这里改成你的群名"
provider = "default"
window_hours = 12
enable_images = true
max_messages = 500
chunk_char_limit = 12000
system_prompt = """{prompt}"""
'''


def format_validation_error(exc: ValidationError) -> str:
    """把 Pydantic 的错误转换成更适合 CLI 展示的中文文本。"""
    lines = ["配置文件校验失败："]
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = error.get("msg", "未知错误")
        lines.append(f"- {location}: {message}")
    return "\n".join(lines)


def load_settings(config_path: Path) -> AppConfig:
    """读取 TOML 配置。"""
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在：{config_path}")

    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件 TOML 解析失败：{exc}") from exc

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(format_validation_error(exc)) from exc


def load_settings_if_exists(config_path: Path) -> AppConfig | None:
    """配置文件可选加载，用于 `groups list` 等弱依赖场景。"""
    if not config_path.exists():
        return None
    return load_settings(config_path)


def ensure_gitignore_entries(gitignore_path: Path, entries: tuple[str, ...] = GITIGNORE_ENTRIES) -> bool:
    """确保状态目录、输出目录和本地配置文件被 Git 忽略。"""
    existing = gitignore_path.read_text("utf-8") if gitignore_path.exists() else ""
    normalized_existing = {line.strip() for line in existing.splitlines()}
    missing = [entry for entry in entries if entry not in normalized_existing]
    if not missing:
        return False

    prefix = "\n" if existing and not existing.endswith("\n") else ""
    payload = prefix + "\n".join(missing) + "\n"
    gitignore_path.write_text(existing + payload, encoding="utf-8")
    return True


def init_workspace(paths: ProjectPaths) -> dict[str, Path]:
    """初始化运行目录和示例配置。"""
    created: dict[str, Path] = {}
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.outputs_dir.mkdir(parents=True, exist_ok=True)

    if not paths.config_path.exists():
        paths.config_path.write_text(render_sample_config(), encoding="utf-8")
        created["config"] = paths.config_path

    gitignore_path = paths.root / ".gitignore"
    if ensure_gitignore_entries(gitignore_path):
        created["gitignore"] = gitignore_path

    return created
