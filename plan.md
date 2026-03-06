# WeFlow 群聊总结 CLI 设计方案（收缩到文本/图片/卡片/链接）

## 摘要
- 做一个本地手动触发的 CLI 工具，使用 `uv + Python 3.13`，从 WeFlow HTTP API 拉群消息并调用 OpenAI 兼容 LLM 生成总结。
- v1 只支持总结这 4 类内容：文本、图片、卡片、链接；明确不处理音频、视频、文件、表情。
- 每个群可独立配置 `prompt`、`provider/llm`、`api key`、`base_url`、`总结时间窗口（小时）`；执行一条命令即可生成该群总结。
- 输出固定为终端打印 + 本地 Markdown 文件；不做自动定时总结，不做自动回发微信群。

## 公共接口
- CLI 命令固定为：
  - `wechat-group-summary init`
  - `wechat-group-summary groups sync`
  - `wechat-group-summary groups list [--keyword xxx]`
  - `wechat-group-summary summarize --group <群名或talker> [--hours N] [--output PATH] [--no-images]`
- 配置结构固定为：
  - `weflow`: `base_url`、`timeout_seconds`
  - `providers.<name>`: `base_url`、`api_key`、`model`、`vision_model?`、`timeout_seconds`
  - `groups."<talker>"`: `display_name`、`provider`、`window_hours`、`system_prompt`、`enable_images`、`max_messages`、`chunk_char_limit`
- 群匹配规则固定为：优先 `talker/chatroom id`，其次群显示名精确匹配，最后唯一模糊匹配；歧义时报错并列候选。
- 密钥直接写在本地配置文件中，配置文件默认加入 `.gitignore`。

## 核心实现
- 项目采用 `src` 布局，依赖固定为：`typer`、`httpx`、`pydantic`、`openai`、`rich`。
- WeFlow 适配层只封装：健康检查、群列表同步、消息抓取；默认连接 `http://127.0.0.1:5031`。
- 消息抓取统一走 `GET /api/v1/messages?format=chatlab`，使用精确时间戳 `start/end` 实现“最近 N 小时”，不是按自然日。
- 内容标准化规则固定为：
  - 文本：直接使用 `content/parsedContent`
  - 图片：当群配置 `enable_images=true` 时请求 `media=1&image=1&voice=0&video=0&emoji=0`，拿到 `mediaPath` 后调用视觉模型生成简短描述，再回填为文本上下文
  - 卡片/链接：直接使用 WeFlow 已解析的结构化文本，不做媒体下载
  - 其他类型：直接过滤，不进入总结输入
- 内部统一消息模型固定为：`timestamp`、`speaker_id`、`speaker_name`、`kind(text|image|card|link)`、`text`、`media_path?`。
- 总结链路固定为：先筛允许类型，再补图片描述，最后把标准化转录交给总结模型。
- 长上下文处理固定为：超出 `chunk_char_limit` 时先分块总结，再做一次汇总总结。
- 输出固定保存到 `outputs/<group_slug>/<YYYYMMDD-HHMMSS>.md`，文件头包含群名、talker、时间窗口、provider/model、生成时间。

## 测试与验收
- 单元测试覆盖：配置校验、provider/group 解析、群选择规则、时间窗口换算、消息类型过滤、消息标准化、图片开关、分段总结触发条件。
- 集成测试用 mock WeFlow + mock LLM 覆盖：
  - `groups sync` 只同步 `@chatroom` 群会话
  - `summarize` 使用群自己的 provider、model、prompt、window_hours
  - `--hours` 只覆盖本次运行，不写回配置
  - 图片开启时会走视觉描述；视觉失败时退化为 `[图片]` 占位但不中断总结
  - 卡片、链接能被稳定保留到转录文本中
  - 音频、视频、文件、表情会被过滤，不进入总结
  - 同名群冲突时报候选列表
  - 时间窗口内无有效消息时返回友好提示并以非零退出码结束

## 默认假设
- WeFlow HTTP API 已在本机启动，默认地址是 `http://127.0.0.1:5031`。
- v1 不处理音频、视频、文件、表情，也不做微信群内 `/总结` 指令。
- 卡片和链接的理解依赖 WeFlow 已解析出的结构化文本；只有图片需要额外视觉模型。
- 当前环境里检测到的是 Python 3.11，但实现时用 `uv` 固定 Python 3.13 虚拟环境。
