"""命令行入口。"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from .config import init_workspace, load_settings, load_settings_if_exists
from .constants import DEFAULT_CONFIG_FILENAME
from .exceptions import AppError
from .llm import OpenAIChatGateway
from .models import ProviderConfig, WeFlowSettings
from .paths import ProjectPaths
from .state import GroupCacheStore
from .summary import SummaryRequest, SummaryService, build_group_rows, resolve_group_choice
from .weflow import WeFlowClient

console = Console()
app = typer.Typer(help="WeFlow 群聊总结 CLI")
groups_app = typer.Typer(help="群同步与查看")
app.add_typer(groups_app, name="groups")


def create_weflow_client(settings: WeFlowSettings) -> WeFlowClient:
    """为 CLI 提供可替换的 WeFlow 客户端工厂，便于测试打桩。"""
    return WeFlowClient(settings)


def create_llm_gateway(provider: ProviderConfig) -> OpenAIChatGateway:
    """为 CLI 提供可替换的 LLM 网关工厂，便于测试打桩。"""
    return OpenAIChatGateway(provider)


def exit_with_error(error: Exception) -> None:
    """统一输出中文错误并以非零状态码退出。"""
    console.print(f"[red]错误：{error}[/red]")
    raise typer.Exit(code=1) from error


@app.command()
def init(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_FILENAME), "--config", help="配置文件路径"),
) -> None:
    """初始化项目模板文件。"""
    paths = ProjectPaths.from_config(config)
    created = init_workspace(paths)

    console.print(f"[green]初始化完成[/green]：{paths.root}")
    if created:
        for key, path in created.items():
            console.print(f"- {key}: {path}")
    else:
        console.print("- 所有模板文件已存在，未覆盖")


@groups_app.command("sync")
def groups_sync(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_FILENAME), "--config", help="配置文件路径"),
) -> None:
    """从 WeFlow 同步当前账号下的群聊列表到本地缓存。"""
    try:
        paths = ProjectPaths.from_config(config)
        settings = load_settings(paths.config_path)
        with create_weflow_client(settings.weflow) as client:
            if not client.health_check():
                raise AppError(f"WeFlow API 不可用：{settings.weflow.base_url}")
            groups = client.list_groups()
        cache = GroupCacheStore(paths.group_cache_path).save(groups)
    except Exception as exc:
        exit_with_error(exc)

    console.print(f"[green]同步完成[/green]：共 {len(cache.groups)} 个群")


@groups_app.command("list")
def groups_list(
    keyword: str | None = typer.Option(None, "--keyword", help="按群名或 talker 过滤"),
    config: Path = typer.Option(Path(DEFAULT_CONFIG_FILENAME), "--config", help="配置文件路径"),
) -> None:
    """列出已同步群和已配置群，方便用户核对 talker。"""
    try:
        paths = ProjectPaths.from_config(config)
        settings = load_settings_if_exists(paths.config_path)
        cache_store = GroupCacheStore(paths.group_cache_path)
        cache = cache_store.load()

        # 如果本地还没有缓存，则尝试直接从 WeFlow 拉一次只读列表。
        if cache is None:
            weflow_settings = settings.weflow if settings else WeFlowSettings()
            with create_weflow_client(weflow_settings) as client:
                if client.health_check():
                    cache = cache_store.save(client.list_groups(keyword=keyword))

        rows = build_group_rows(settings.groups if settings else {}, cache, keyword=keyword)
    except Exception as exc:
        exit_with_error(exc)

    if not rows:
        console.print("[yellow]没有找到群，请先执行 `groups sync` 或检查关键字[/yellow]")
        raise typer.Exit(code=0)

    table = Table(title="群列表")
    table.add_column("Display Name")
    table.add_column("Talker")
    table.add_column("Configured")
    table.add_column("Provider")
    table.add_column("Synced")

    for row in rows:
        table.add_row(
            row.display_name,
            row.talker,
            "yes" if row.configured else "no",
            row.provider or "-",
            "yes" if row.synced else "no",
        )

    console.print(table)


@app.command()
def summarize(
    group: str = typer.Option(..., "--group", help="群显示名或 talker"),
    hours: float | None = typer.Option(None, "--hours", help="仅覆盖本次总结时间窗口（小时）"),
    output: Path | None = typer.Option(None, "--output", help="输出 Markdown 路径"),
    no_images: bool = typer.Option(False, "--no-images", help="本次运行忽略图片理解"),
    config: Path = typer.Option(Path(DEFAULT_CONFIG_FILENAME), "--config", help="配置文件路径"),
) -> None:
    """生成单个群的总结结果并保存为 Markdown。"""
    try:
        paths = ProjectPaths.from_config(config)
        settings = load_settings(paths.config_path)
        cache = GroupCacheStore(paths.group_cache_path).load()
        resolved_group = resolve_group_choice(group, settings.groups, cache)
        provider = settings.providers[resolved_group.group.provider]
        request = SummaryRequest(
            talker=resolved_group.talker,
            display_name=resolved_group.display_name,
            provider_name=resolved_group.group.provider,
            provider=provider,
            group=resolved_group.group,
            window_hours=hours if hours is not None else resolved_group.group.window_hours,
            include_images=resolved_group.group.enable_images and not no_images,
            output_path=output,
        )

        with create_weflow_client(settings.weflow) as weflow_client:
            if not weflow_client.health_check():
                raise AppError(f"WeFlow API 不可用：{settings.weflow.base_url}")
            llm_gateway = create_llm_gateway(provider)
            try:
                service = SummaryService(weflow_client, llm_gateway)
                result = service.summarize(request=request, paths=paths)
            finally:
                llm_gateway.close()
    except Exception as exc:
        exit_with_error(exc)

    console.rule(f"{result.display_name} 群聊总结")
    console.print(Markdown(result.summary_text))
    console.print(f"\n[green]已保存[/green]：{result.output_path}")


def main() -> None:
    """供 `python -m` 和脚本入口共用。"""
    app()


if __name__ == "__main__":
    main()
