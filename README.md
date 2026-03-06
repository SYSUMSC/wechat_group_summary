# WeFlow 群聊总结 CLI

一个基于 `uv + Python 3.13` 的本地命令行工具：从 WeFlow HTTP API 拉取微信群消息，再调用 OpenAI 兼容模型生成群聊总结。

## 功能范围

- 支持内容：文本、图片、卡片、链接
- 不处理：音频、视频、文件、表情
- 每个群可单独配置：`prompt`、`provider`、`model`、`base_url`、`api_key`、`总结时间窗口`
- 输出到：终端 + 本地 Markdown 文件

## 快速开始

1. 确认 WeFlow 的 HTTP API 已开启，默认地址通常是 `http://127.0.0.1:5031`
2. 安装 Python 3.13 并同步依赖：

```bash
uv python install 3.13
uv sync --python 3.13 --extra dev
```

3. 初始化配置模板：

```bash
uv run --python 3.13 wechat-group-summary init
```

4. 编辑根目录的 `wechat_group_summary.toml`，直接填写你的模型 `base_url`、`api_key`、`model`
5. 执行群同步，确认群 `talker`：

```bash
uv run --python 3.13 wechat-group-summary groups sync
uv run --python 3.13 wechat-group-summary groups list
```

6. 继续编辑 `wechat_group_summary.toml`，为目标群配置 `provider` 和 `prompt`
7. 生成总结：

```bash
uv run --python 3.13 wechat-group-summary summarize --group 你的群名
```

## 主要命令

```bash
wechat-group-summary init
wechat-group-summary groups sync
wechat-group-summary groups list [--keyword xxx]
wechat-group-summary summarize --group <群名或talker> [--hours N] [--output PATH] [--no-images]
```

## 配置说明

配置文件名默认是 `wechat_group_summary.toml`，并已默认加入 `.gitignore`。

- `weflow`：WeFlow HTTP API 地址和超时
- `providers.<name>`：OpenAI 兼容模型连接，直接配置 `base_url`、`api_key`、`model`
- `groups."<talker>"`：单个群的总结配置

## 输出目录

- 群缓存：`.wechat-group-summary/groups_cache.json`
- 总结文件：`outputs/<group_slug>/<YYYYMMDD-HHMMSS>.md`
