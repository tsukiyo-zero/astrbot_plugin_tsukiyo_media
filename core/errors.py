"""插件内部异常。全部继承 TsukiyoMediaError，方便入口统一兜底。"""
from __future__ import annotations


class TsukiyoMediaError(Exception):
    """插件内所有可预期错误的基类。"""


class ConfigError(TsukiyoMediaError):
    """配置缺项或不合法。"""


class RoutingError(TsukiyoMediaError):
    """无法确定 kind / 模型。"""


class WorkflowNotFound(TsukiyoMediaError):
    """工作流文件不存在。"""


class BindError(TsukiyoMediaError):
    """工作流节点绑定失败（找不到必需节点或存在歧义）。"""


class BackendError(TsukiyoMediaError):
    """ComfyUI 通信失败、提交被拒、执行失败。"""


class JobTimeout(TsukiyoMediaError):
    """ComfyUI 任务超时。"""
