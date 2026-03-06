# WeFlow 群聊总结 CLI 设计方案

## 摘要
- 做一个本地手动触发的 CLI 工具，技术栈固定为 `uv + Python 3.13`，从 WeFlow HTTP API 拉群消息，再调用 OpenAI 兼容 LLM 生成总结。
- v1 只做“命令触发总结”，输出到终端并保存 Markdown；不做自动定时任务，也不做自动回发微信群。
- 配置采用“`provider` + `group`”混合模式：模型连接单独定义，群配置引用 provider，并单独配置 prompt、时间窗口、媒体开关等。
- 数据源优先走 WeFlow 的 `ChatLab` 输出；图片/表情通过媒体导出 + 视觉描述补全文本上下文，语音/视频先不纳入 v1。

## 公共接口
- CLI 命令固定为：
  - `wechat-group-summary init`：生成示例配置、`.env.example`、本地忽略规则。
  - `wechat-group-summary groups sync`：从 WeFlow 同步群列表到本地状态缓存。
  - `wechat-group-summary groups list [--keyword xxx]`：查看可配置群，支持按名字过滤。
  - `wechat-group-summary summarize --group <群名或talker> [--hours N] [--output PATH] [--no-media]`：按群执行总结。
- `summarize` 的群选择规则固定为：先精确匹配 `talker/chatroom id`，再精确匹配群显示名，最后做唯一模糊匹配；若命中多个同名群则直接报错并列出候选，不自动猜。
- 配置结构固定为：
  - `weflow`：`base_url`、`timeout_seconds`
  - `providers.<name>`：`base_url`、`api_key_env|api_key`、`model`、`vision_model?`、`timeout_seconds`
  - `groups."<talker>"`：`display_name`、`provider`、`window_hours`、`system_prompt`、`enable_images`、`enable_emojis`、`max_messages`、`chunk_char_limit`
- 密钥默认走环境变量；允许明文 `api_key` 仅作为兼容兜底，文档里明确推荐 `api_key_env`。

## 核心实现
- 项目骨架采用 `src` 布局，依赖固定为：`typer`、`httpx`、`pydantic`、`python-dotenv`、`openai`、`rich`。
- WeFlow 适配层只封装 3 个能力：健康检查、群列表同步、消息抓取；消息抓取统一走 `GET /api/v1/messages`，使用秒级时间戳 `start/end` 实现“最近 N 小时”，而不是按自然日。
- 消息获取统一使用 `format=chatlab`；媒体仅在群配置启用时追加 `media=1&image=1&emoji=1&voice=0&video=0`，避免无谓导出。
- 内部标准消息模型固定为：`timestamp`、`speaker_id`、`speaker_name`、`message_type`、`text`、`media_path?`；说话人名称优先级固定为 `groupNickname > accountName > sender id`。
- 默认总结 prompt 以 `wxqunBot` 现有总结提示词为种子模板，但最终配置项以每个群自己的 `system_prompt` 为准；程序只负责补固定的用户侧上下文（群名、时间范围、参与者统计、消息转录）。
- 图片/表情处理采用“两阶段”方案：
  - 先对媒体消息做视觉描述，产出文本 caption 并回填到转录内容。
  - 再把完整文本转录交给总结模型。
- `vision_model` 规则固定为：优先用 provider 的 `vision_model`；若未配置则尝试复用 `model`；若模型不支持图片输入或调用失败，则退化为 `[图片]` / `[表情]` 占位，不阻断总结主流程。
- 为避免长群聊超上下文，摘要流程固定支持自动分段：
  - 转录内容未超过预算时单次总结。
  - 超过预算时按 `chunk_char_limit` 分块，先做 chunk summary，再合并成最终总结。
- 输出固定为两份：
  - 终端彩色打印最终总结。
  - 保存到 `outputs/<group_slug>/<YYYYMMDD-HHMMSS>.md`，文件头包含群名、talker、时间窗口、provider/model、生成时间。

## 测试与验收
- 单元测试覆盖：配置校验、provider/group 引用解析、群选择规则、时间窗口转查询参数、消息标准化、分段触发条件、媒体降级逻辑。
- 集成测试用 mock WeFlow + mock LLM 覆盖：
  - `groups sync` 只写入 `@chatroom` 群会话。
  - `summarize` 确实使用群自己的 provider、prompt、window_hours。
  - `--hours` 只覆盖本次运行，不写回配置。
  - 图片/表情开启时会调用视觉描述链路；视觉失败时仍能完成文本总结。
  - 同名群冲突时返回候选列表，不错误命中。
  - 最近窗口无消息时返回友好提示并以非零退出码结束。
- 验收标准固定为：对任一已配置群，执行一条命令即可按该群独立的模型连接和 prompt 生成 Markdown 总结。

## 默认假设
- WeFlow API 已在本机启动，默认地址为 `http://127.0.0.1:5031`。
- v1 范围就是“本地 CLI 手动总结”；自动定时、微信群内 `/总结` 指令、自动回发群消息全部放到后续阶段。
- v1 媒体范围仅含图片和表情；语音、视频、文件只保留 WeFlow 已解析出的文本占位，不做额外理解。
- 配置采用仓库内示例文件 + 本地 `.env` 的方式管理；当前规划环境里是 Python 3.11.2，但实现时用 `uv` 锁定并创建 Python 3.13 运行环境。
