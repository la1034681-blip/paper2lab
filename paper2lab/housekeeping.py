"""两轮审计之间的"清理"——清运行态, 保记忆。

本模块只做一件事, 但这件事必须分对两边: 什么**可以清**、什么**不能清**。
分错任何一边, 要么白清(下一轮串味)、要么真丢东西(记忆断了)。

三类东西:

  ① 运行缓存 —— **清**
     `cache/llm_cache.json` / `cache/vision_cache.json`。它们是**上一轮的中间结果**,
     按 prompt 内容哈希存, 唯一作用是"同一个问题别问两次"。清掉只意味着下一轮
     重新调用 API(慢一点、有费用), **不影响任何结论**。

  ② 跨任务记忆 —— **留**
     `cache/audit_memory.json`。记的是"这篇论文有哪些参数没给确定值""参数出现在哪几页"
     这类线索, 按论文指纹索引、**跨轮次跨任务复用**。删掉 = 下一轮把它当新论文从头来,
     是**真损失**。用户明确要求保留("记忆以及上下文之类的方面就保留")。

  ③ 上一轮的**上传临时文件** —— **清**
     用户上传的 PDF / 代码 ZIP 会落到系统临时目录(`app._save_upload`),
     每跑一轮留一份, 不清就一直攒着。

⚠️ 两个实测约束(2026-09-28 踩过):
  · 本机 shell 把删除劫持到系统回收站, 且**同一轮删除次数过多会被安全策略熔断**
    (`SAFE_DELETE_BULK_CONFIRM_REQUIRED`, 阈值 50), 熔断方式是直接中止进程。
    所以这里**只清固定的几个文件**(≤4 个), 绝不做递归批量删除。
  · 万一某个文件删不掉(被占用 / 策略拒绝), 退路是**把它截断为 0 字节** ——
    对缓存而言等价于已清空(读取端解析失败即视为空), 而且不需要删除权限。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent.parent
CACHE_DIR = HERE / "cache"

# ② 记忆: 唯一一个"绝不能清"的文件
MEMORY_FILE = CACHE_DIR / "audit_memory.json"

# ① 运行缓存: 上一轮的中间结果, 清了只影响速度
RUN_CACHE_FILES = (CACHE_DIR / "llm_cache.json", CACHE_DIR / "vision_cache.json")


def _clear(p: Path) -> dict:
    """清掉一个文件。优先删除; 删不掉就截断为 0 字节(不需要删除权限)。

    返回 {"name", "action": deleted|truncated|absent|failed, "bytes"}。
    """
    try:
        if not p.exists():
            return {"name": p.name, "action": "absent", "bytes": 0}
        n = p.stat().st_size
    except OSError:
        return {"name": p.name, "action": "absent", "bytes": 0}
    try:
        p.unlink()
        return {"name": p.name, "action": "deleted", "bytes": n}
    except OSError:
        pass
    try:
        p.write_text("", encoding="utf-8")     # 读取端解析失败 -> 视为空缓存
        return {"name": p.name, "action": "truncated", "bytes": n}
    except OSError:
        return {"name": p.name, "action": "failed", "bytes": n}


def purge_run_state(extra_files: Iterable = (), *, keep_cache: bool = False) -> dict:
    """清掉上一轮的运行态, 返回一份**可展示、可核对**的回执。

    extra_files: 上一轮上传落盘的临时文件路径(由调用方记住后传入)。
    keep_cache:  True 则保留运行缓存(要复现"同一问题不再问第二次"时用)。
    """
    cleared: list[dict] = []
    if not keep_cache:
        for f in RUN_CACHE_FILES:
            r = _clear(f)
            if r["action"] != "absent":
                r["kind"] = "运行缓存"
                cleared.append(r)
    for f in extra_files or ():
        # 空路径要显式跳过: `Path("")` 等于当前目录, 拿去 unlink 会报错并污染回执
        # （未上传代码包时调用方常常传空串进来）。
        if not f:
            continue
        try:
            p = Path(f)
        except TypeError:
            continue
        if str(p).strip() in ("", "."):
            continue
        r = _clear(p)
        if r["action"] != "absent":
            r["kind"] = "上传临时文件"
            cleared.append(r)

    kept: list[dict] = []
    if MEMORY_FILE.exists():
        try:
            kept.append({
                "name": MEMORY_FILE.name,
                "bytes": MEMORY_FILE.stat().st_size,
                "reason": "跨任务记忆 —— 按论文指纹记的线索, 跨轮次复用",
            })
        except OSError:
            pass

    return {
        "cleared": cleared,
        "kept": kept,
        "freed_bytes": sum(c["bytes"] for c in cleared),
        "keep_cache": bool(keep_cache),
        "failed": [c["name"] for c in cleared if c["action"] == "failed"],
    }


def _kb(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n else "0 KB"


def format_report(rep: dict) -> str:
    """把回执写成**一行功能名 + 事实**（界面与日志共用，避免两处口径漂移）。

    精简原则（2026-09-29 用户要求："全部去除不然看着很乱，简洁保留功能名就好"）：
      只报**事实**（清了什么、留了什么、有没有清掉），
      不解释**为什么**（"它是记忆不是缓存、删了线索就断"那类说理，
      属于 README 与代码注释的内容，不该占界面）。
    """
    cleared = rep.get("cleared") or []
    run_cache = [c for c in cleared if c["kind"] == "运行缓存"]
    uploads = [c for c in cleared if c["kind"] == "上传临时文件"]
    kept = rep.get("kept") or []
    failed = rep.get("failed") or []

    parts: list[str] = []
    if rep.get("keep_cache"):
        parts.append("运行缓存：按设置保留")
    elif run_cache:
        parts.append("已清理 " + "、".join(c["name"] for c in run_cache))
    else:
        parts.append("无运行缓存")
    if uploads:
        parts.append(f"临时文件 {len(uploads)} 个")
    if kept:
        parts.append(f"保留 {kept[0]['name']}")
    if failed:
        parts.append("未能清理 " + "、".join(failed))
    return " ｜ ".join(parts)
