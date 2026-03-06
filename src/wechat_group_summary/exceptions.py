class AppError(Exception):
    pass


class ConfigError(AppError):
    pass


class GroupResolutionError(AppError):
    pass


class NoMessagesError(AppError):
    pass


class WeFlowError(AppError):
    pass


class LLMError(AppError):
    pass

