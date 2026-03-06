"""项目常量。"""

DEFAULT_CONFIG_FILENAME = "wechat_group_summary.toml"
STATE_DIRNAME = ".wechat-group-summary"
GROUP_CACHE_FILENAME = "groups_cache.json"
DEFAULT_OUTPUT_DIRNAME = "outputs"
WEFLOW_BATCH_LIMIT = 1000

# ChatLab 消息类型常量，只保留本项目当前会用到的类型。
CHATLAB_TEXT = 0
CHATLAB_IMAGE = 1
CHATLAB_LINK = 7
CHATLAB_SHARE = 24
CHATLAB_REPLY = 25
CHATLAB_CONTACT = 27

GITIGNORE_ENTRIES = (
    f"{STATE_DIRNAME}/",
    f"{DEFAULT_OUTPUT_DIRNAME}/",
    DEFAULT_CONFIG_FILENAME,
)

DEFAULT_SYSTEM_PROMPT = """你是一个中文微信群聊总结助手。请根据输入的群聊记录输出一份准确、紧凑、可转发的总结。

输出要求：
1. 先给出 2 到 4 句话的整体概览。
2. 按主题列出主要讨论点，尽量包含：主题、参与者、关键结论、时间范围。
3. 单独总结聊天里出现的链接或卡片内容及其用途。
4. 如果聊天中有图片描述，请提炼图片与讨论的关系。
5. 最后列出明确待办；若没有待办，写“无明确待办”。

其他要求：
- 只基于提供内容，不要编造。
- 使用简体中文。
- 结构清晰，避免空话。
- 信息不足时明确写出“不足以判断”。"""

PARTIAL_SUMMARY_PROMPT = """你是群聊中间摘要助手。你会收到一段群聊转录，请忠实提炼该片段中的：主要话题、参与者、关键结论、链接/卡片信息、图片描述、待办事项。不要输出与片段无关的内容，也不要编造事实。"""

IMAGE_DESCRIPTION_PROMPT = "请用简体中文在 1 到 2 句话内描述这张群聊图片里最关键的可见信息，只描述能直接看到的内容，不要猜测未展示的事实。"
