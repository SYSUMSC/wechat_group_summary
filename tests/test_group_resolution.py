from datetime import datetime, timezone

import pytest

from wechat_group_summary.models import GroupCache, GroupConfig, SyncedGroup
from wechat_group_summary.summary import build_group_rows, resolve_group_choice
from wechat_group_summary.exceptions import GroupResolutionError


def make_cache() -> GroupCache:
    return GroupCache(
        synced_at=datetime.now(timezone.utc),
        groups=[
            SyncedGroup(talker="one@chatroom", display_name="项目群"),
            SyncedGroup(talker="two@chatroom", display_name="项目群"),
            SyncedGroup(talker="three@chatroom", display_name="闲聊群"),
        ],
    )


def test_resolve_group_prefers_exact_talker() -> None:
    groups = {
        "one@chatroom": GroupConfig(provider="main", system_prompt="x"),
        "three@chatroom": GroupConfig(provider="main", system_prompt="x"),
    }
    resolved = resolve_group_choice("one@chatroom", groups, make_cache())
    assert resolved.talker == "one@chatroom"


def test_resolve_group_raises_on_ambiguous_name() -> None:
    groups = {
        "one@chatroom": GroupConfig(provider="main", display_name="项目群", system_prompt="x"),
        "two@chatroom": GroupConfig(provider="main", display_name="项目群", system_prompt="x"),
    }
    with pytest.raises(GroupResolutionError):
        resolve_group_choice("项目群", groups, make_cache())


def test_build_group_rows_merges_config_and_cache() -> None:
    groups = {
        "one@chatroom": GroupConfig(provider="main", display_name="项目群", system_prompt="x"),
        "four@chatroom": GroupConfig(provider="backup", display_name="新群", system_prompt="x"),
    }
    rows = build_group_rows(groups, make_cache())
    assert any(row.talker == "one@chatroom" and row.configured and row.synced for row in rows)
    assert any(row.talker == "four@chatroom" and row.configured and not row.synced for row in rows)

