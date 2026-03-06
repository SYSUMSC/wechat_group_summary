from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .exceptions import ConfigError
from .models import GroupCache, SyncedGroup


class GroupCacheStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> GroupCache | None:
        if not self.path.exists():
            return None
        try:
            return GroupCache.model_validate_json(self.path.read_text("utf-8"))
        except ValidationError as exc:
            raise ConfigError(f"群缓存文件格式错误：{self.path}") from exc

    def save(self, groups: list[SyncedGroup], synced_at: datetime | None = None) -> GroupCache:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cache = GroupCache(
            synced_at=synced_at or datetime.now(timezone.utc),
            groups=sorted(groups, key=lambda item: (item.display_name.lower(), item.talker.lower())),
        )
        self.path.write_text(cache.model_dump_json(indent=2), encoding="utf-8")
        return cache

