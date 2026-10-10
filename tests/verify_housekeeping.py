"""验证「两轮审计之间清运行态、保记忆」的口径。

断言的是**边界**:
  · 运行缓存 (llm_cache / vision_cache)  —— 必须清掉
  · 上一轮上传的临时文件                  —— 必须清掉
  · 跨任务记忆 (audit_memory.json)        —— 必须**一字不动**地留下
  · keep_cache=True 时                      —— 缓存必须保留(复现实验要它)

这条边界如果错了, 一边是"白清", 另一边是"真丢东西", 所以逐条断言。
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import sys
import tempfile
from pathlib import Path

from paper2lab.housekeeping import (CACHE_DIR, MEMORY_FILE, RUN_CACHE_FILES,
                                    format_report, purge_run_state)

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("  OK   " if ok else "  FAIL ") + msg)
    if not ok:
        fails.append(msg)


CACHE_DIR.mkdir(parents=True, exist_ok=True)
memory_before = MEMORY_FILE.read_bytes() if MEMORY_FILE.exists() else None
print(f"（记忆文件{'存在' if memory_before is not None else '不存在'}：{MEMORY_FILE.name}）")

# ---------------------------------------------------------------- ①
print("① 运行缓存：必须清掉")
for f in RUN_CACHE_FILES:
    f.write_text(json.dumps({"__test__": 1}), encoding="utf-8")
rep = purge_run_state()
check(all((not f.exists()) or f.stat().st_size == 0 for f in RUN_CACHE_FILES),
      "两个运行缓存已清空（删除，或删不掉时截断为 0 字节）")
check(len([c for c in rep["cleared"] if c["kind"] == "运行缓存"]) == 2,
      "回执里如实记了 2 个运行缓存")

# ---------------------------------------------------------------- ②
print("② 跨任务记忆：必须一字不动")
check(MEMORY_FILE.exists() or memory_before is None, "audit_memory.json 未被清掉")
if memory_before is not None:
    check(MEMORY_FILE.read_bytes() == memory_before, "内容与清理前逐字节一致")
if memory_before is not None:
    check(any(k["name"] == MEMORY_FILE.name for k in rep["kept"]),
          "回执里把它列为「保留」并写明理由")

# ---------------------------------------------------------------- ③
print("③ 上一轮上传的临时文件：必须清掉")
tmp_up = CACHE_DIR / "_tmp_upload_probe.pdf"
tmp_up.write_bytes(b"x" * 1024)
rep3 = purge_run_state(extra_files=[str(tmp_up)])
check((not tmp_up.exists()) or tmp_up.stat().st_size == 0, "上传的临时文件已清空")
check(len([c for c in rep3["cleared"] if c["kind"] == "上传临时文件"]) == 1,
      "回执里记为「上传临时文件」1 个")
check(purge_run_state(extra_files=[""])["cleared"] == [], "空路径被安全忽略（不崩）")

# ---------------------------------------------------------------- ④
print("④ keep_cache=True：缓存必须保留（复现实验要它）")
for f in RUN_CACHE_FILES:
    f.write_text(json.dumps({"__test__": 2}), encoding="utf-8")
rep4 = purge_run_state(keep_cache=True)
check(all(f.exists() and f.stat().st_size > 0 for f in RUN_CACHE_FILES),
      "两个缓存都还在")
check(rep4["cleared"] == [], "本次没清任何东西")
check("保留" in format_report(rep4), "回执如实说明是「保留」而非「已清」")
purge_run_state()                      # 收尾：把测试造的假缓存真清掉

# ---------------------------------------------------------------- ⑤
print("⑤ 删不掉的退路：不崩、且如实报 failed")
d = Path(tempfile.mkdtemp())            # 目录无法被 unlink -> 走 failed 分支
try:
    rep5 = purge_run_state(extra_files=[str(d)])
    check("failed" in rep5 and len(rep5["failed"]) >= 1,
          "把「删不掉」如实报进 failed，而不是假装成功")
    check("未能清理" in format_report(rep5), "回执里如实标出未能清理的文件")
finally:
    try:
        d.rmdir()
    except OSError:
        pass

# ---------------------------------------------------------------- ⑥
print("⑥ 记忆仍未被动过（全程）")
if memory_before is not None:
    check(MEMORY_FILE.read_bytes() == memory_before, "audit_memory.json 全程零改动")
else:
    print("  --   本机无记忆文件，跳过内容比对（既不算通过也不算失败）")

# ---------------------------------------------------------------- ⑦
print("⑦ 回执文案：一行功能名 + 事实（**不解释为什么**）")
txt = format_report({
    "cleared": [{"name": "llm_cache.json", "kind": "运行缓存",
                 "bytes": 2048, "action": "deleted"}],
    "kept": [{"name": "audit_memory.json", "bytes": 512, "reason": "跨任务记忆"}],
    "freed_bytes": 2048, "keep_cache": False, "failed": [],
})
check("llm_cache.json" in txt, "写明了清掉的文件名")
check("audit_memory.json" in txt, "写明了保留的文件名")
# 2026-09-29 用户要求精简界面文案（"看着很乱，简洁保留功能名就好"），
# 这条断言把要求固化：回执里不许夹带说理，且要足够短。
check("记忆不是缓存" not in txt and len(txt) < 80,
      f"不夹带说理且足够短（实测 {len(txt)} 字）")

print()
if fails:
    print(f"未通过 {len(fails)} 项：")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("全部通过（清得干净、留得准确）")
