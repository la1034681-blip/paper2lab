"""验证记忆库的容量控制: 到极限时自动"压缩成摘要", 而不是直接丢弃。"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import json
import re
from pathlib import Path

from paper2lab import memory

out: list[str] = []
out.append("容量上限: 明细 %d 条 / %d 字符（可用环境变量覆盖）"
           % (memory.MAX_ENTRIES, memory.MAX_CHARS))

backup = memory.MEM_PATH.read_text(encoding="utf-8") if memory.MEM_PATH.exists() else None
try:
    # 造 60 篇合成论文的记忆（远超明细上限 40 条）
    data = {}
    for i in range(60):
        data["test%04d" % i] = {
            "title": "合成论文 %d" % i,
            "runs": 1,
            "last_seen": "2026-09-%02d 10:00" % ((i % 28) + 1),
            "unresolved": ["dropout", "iterations"] if i % 3 == 0 else [],
            "page_hints": {"dropout": [2, 3], "learning_rate": [9]},
            "where": {"dropout": "text"},
        }
    out.append("")
    out.append("写入 60 篇明细后 →")
    memory._save(data)

    info = memory.capacity_info()
    out.append("  明细 %d 篇 / 摘要覆盖 %d 篇 / 合计 %d 篇 / %d 字符（用量 %.1f%%）"
               % (info["entries"], info["digest_papers"], info["total_papers"],
                  info["chars"], info["usage"] * 100))
    out.append("  摘要生成时间: %s" % info["compressed_at"])
    for ln in memory.digest_lines():
        out.append("  · " + ln)

    out.append("")
    out.append("跨任务统计（应包含已压缩的历史，不能因压缩而'失忆'）：")
    for ln in memory.cross_task_stats():
        out.append("  · " + ln)

    out.append("")
    out.append("—— 边界自查：摘要里同样只能有线索 ——")
    raw = memory.MEM_PATH.read_text(encoding="utf-8")
    digest = (json.loads(raw).get("_digest") or {})
    out.append("  文件字符数: %d（上限 %d）" % (len(raw), memory.MAX_CHARS))
    out.append("  摘要字段: %s" % list(digest.keys()))
    float_re = re.compile(r"\b\d+\.\d+\b")
    val_re = re.compile(r"0[.]1|1e-4|\b32\b")
    out.append("  浮点数（应仅为计数/页码）: %s" % float_re.findall(raw)[:12])
    out.append("  是否含参数取值（0.1 / 32 / 1e-4）: %s" % bool(val_re.search(raw)))

    out.append("")
    out.append("—— 压缩后是否仍可正常读写 ——")
    probe = memory.recall("test0000")
    out.append("  查询明细（可能已被挤出）: %s" % ("命中" if probe else "未命中（已并入摘要）"))
    out.append("  容量信息条数: %d" % len(info))
finally:
    if backup is not None:
        memory.MEM_PATH.write_text(backup, encoding="utf-8")
        out.append("")
        out.append("已还原原记忆库（%d 字符，%d 条明细）"
                   % (len(backup), memory.size()))

Path("_memc.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
