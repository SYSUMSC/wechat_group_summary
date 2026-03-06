"""项目路径解析。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import DEFAULT_OUTPUT_DIRNAME, DEFAULT_CONFIG_FILENAME, GROUP_CACHE_FILENAME, STATE_DIRNAME


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config_path: Path
    state_dir: Path
    group_cache_path: Path
    outputs_dir: Path

    @classmethod
    def from_config(cls, config_path: str | Path = DEFAULT_CONFIG_FILENAME) -> "ProjectPaths":
        """解析运行目录。

        默认配置名会优先落到“主项目根目录”，而不是当前 shell 所在目录。
        这样即使用户在 `refs/` 这类参考目录里执行命令，也会把本地运行文件写回仓库根目录。
        """
        resolved_config = resolve_config_path(config_path)
        root = resolved_config.parent
        state_dir = root / STATE_DIRNAME
        return cls(
            root=root,
            config_path=resolved_config,
            state_dir=state_dir,
            group_cache_path=state_dir / GROUP_CACHE_FILENAME,
            outputs_dir=root / DEFAULT_OUTPUT_DIRNAME,
        )


def resolve_config_path(config_path: str | Path) -> Path:
    """把配置路径解析成绝对路径。"""
    candidate = Path(config_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    if candidate == Path(DEFAULT_CONFIG_FILENAME):
        workspace_root = discover_workspace_root(Path.cwd())
        return (workspace_root / DEFAULT_CONFIG_FILENAME).resolve()

    return (Path.cwd() / candidate).resolve()


def discover_workspace_root(start: Path) -> Path:
    """从当前目录向上查找主项目根目录。"""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if looks_like_workspace_root(candidate):
            return candidate
    return current


def looks_like_workspace_root(path: Path) -> bool:
    """判断一个目录是否像当前 CLI 的主项目根目录。"""
    return (path / "pyproject.toml").is_file() and (path / "src" / "wechat_group_summary").is_dir()
