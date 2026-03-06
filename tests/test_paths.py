from pathlib import Path

from wechat_group_summary.constants import DEFAULT_CONFIG_FILENAME
from wechat_group_summary.paths import ProjectPaths, discover_workspace_root, looks_like_workspace_root, resolve_config_path


def test_discover_workspace_root_skips_refs(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    (root / "src" / "wechat_group_summary").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='wechat-group-summary'\n", encoding="utf-8")
    refs = root / "refs"
    refs.mkdir()
    monkeypatch.chdir(refs)

    assert discover_workspace_root(Path.cwd()) == root
    assert looks_like_workspace_root(root)
    assert not looks_like_workspace_root(refs)


def test_resolve_default_config_to_workspace_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    (root / "src" / "wechat_group_summary").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='wechat-group-summary'\n", encoding="utf-8")
    refs = root / "refs"
    refs.mkdir()
    monkeypatch.chdir(refs)

    resolved = resolve_config_path(DEFAULT_CONFIG_FILENAME)
    assert resolved == root / DEFAULT_CONFIG_FILENAME

    paths = ProjectPaths.from_config(DEFAULT_CONFIG_FILENAME)
    assert paths.root == root
    assert paths.config_path == root / DEFAULT_CONFIG_FILENAME
