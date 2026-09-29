"""极简 .env 读取(不引入额外依赖)。

项目根目录下的 .env 形如 `KEY=VALUE`(支持 # 注释与引号), 仅在进程环境变量缺失时生效,
不覆盖已存在的环境变量。用途: 把 API key 等本地私有配置与代码分离。
"""

from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def env_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".env"


def load_streamlit_secrets(force: bool = False) -> dict[str, str]:
    """把 Streamlit Secrets 桥接成环境变量（仅在 Streamlit 运行时里生效）。

    为什么需要这座桥: 本项目的配置读取**统一走 os.environ**（见 `get()`），而
    Streamlit Community Cloud / Hugging Face Spaces 上的密钥是在平台的 Secrets 里配的
    —— 平台不会自动把它变成环境变量，中间需要接一下。

    三条刻意的约束:
      1. **只在 streamlit 已被导入时**才尝试（模块在 `sys.modules` 里），
         这样 CLI / 验证脚本不会因为 import streamlit 变慢；
      2. 只在**真正的 Streamlit 运行时**里读 secrets（`runtime.exists()`），
         在 `streamlit run` 之外调用 `st.secrets` 会抛异常；
      3. 只填充**尚未存在**的键 —— 本地 `.env` 与真实环境变量永远优先，
         所以"本地怎么跑，线上还怎么跑"。
    """
    import sys
    out: dict[str, str] = {}
    if "streamlit" not in sys.modules:
        return out
    try:
        import streamlit as st

        if not st.runtime.exists():
            return out
        for k, v in dict(st.secrets).items():
            sv = str(v)
            out[k] = sv
            if sv and not os.environ.get(k):
                os.environ[k] = sv
    except Exception:      # noqa: BLE001 —— 桥接失败不能影响主流程
        return out
    return out


def load_env(force: bool = False) -> dict[str, str]:
    """读取 .env 并写入 os.environ(不覆盖已有变量), 再桥接平台 Secrets。返回解析出的键值对。"""
    global _LOADED
    if _LOADED and not force:
        return {}
    _LOADED = True
    out: dict[str, str] = {}
    p = env_path()
    if p.exists():
        try:
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if not k:
                    continue
                out[k] = v
                if v and not os.environ.get(k):
                    os.environ[k] = v
        except Exception:
            pass
    # 平台 Secrets -> 环境变量（本地无 streamlit 运行时时为空操作）
    out.update(load_streamlit_secrets())
    return out


def get(key: str, default: str = "") -> str:
    load_env()
    return os.environ.get(key, default)
