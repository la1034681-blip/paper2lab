"""访问口令（部署到公网时的统一入口门）—— 逻辑独立于 Streamlit, 便于单测。

为什么需要: 本项目的审计会**消耗 API 额度**（归因与读图）。把链接发给评委的同时,
也等于把额度交给了"任何拿到链接的人"。所以公网部署时设一道统一口令:
拿到链接 ≠ 能跑审计。

设计原则（与项目其它部分一致）:
- **不设口令就不生效** —— 本地开发/自用完全不被打扰, 行为与从前一字不差;
- 口令只从环境变量读（Streamlit Cloud 的 Secrets 会由 envfile 桥接成环境变量）,
  **不落盘、不进日志、不进报告**;
- 比较用 `hmac.compare_digest`（定时安全比较），避免逐字符试探;
- 这道门只挡"要不要给页面", **不改变任何审计结论**。
"""
from __future__ import annotations

import hmac
import os

# 部署方在平台 Secrets / 环境变量里设置它（名字带项目前缀, 避免与别的应用撞车）
CODE_ENV_KEYS = ("PAPER2LAB_ACCESS_CODE", "ACCESS_CODE")


def configured_code() -> str:
    """取当前生效的口令; 没配置则返回空串（= 不启用访问门）。"""
    for k in CODE_ENV_KEYS:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def gate_enabled() -> bool:
    """是否需要显示访问门。"""
    return bool(configured_code())


def verify_code(entered: str, expected: str | None = None) -> bool:
    """校验口令（定时安全比较）。expected 为空时按当前配置取。"""
    exp = configured_code() if expected is None else (expected or "").strip()
    if not exp:
        return True                      # 没设口令 -> 直接放行
    return hmac.compare_digest((entered or "").strip(), exp)
