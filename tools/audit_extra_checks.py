"""跑一遍**不在 run_all_checks.py 里**的验证脚本，逐个记结果（找漏网的 bug）。

用法:
  .venv\\Scripts\\python.exe audit_extra_checks.py           # 非界面那批
  .venv\\Scripts\\python.exe audit_extra_checks.py --ui      # 界面那批（会抢 8501 端口，需单独跑）

为什么要单独一份: `run_all_checks` 里的 20 项是"每次改动都要跑"的核心集；
还有一批是**按需跑**的专项脚本（Agent 消融、记忆容量、分片并发、读图 A/B、真机界面组合…），
平时不进核心集（太慢），但"全面检查"时一个都不能漏。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PY = str(HERE / ".venv/Scripts/python.exe")

NON_UI = [
    ("计划 vs 经典 一致性",        ["verify_plan_mode.py"], 600),
    ("抽取 Agent 消融(开/关)",     ["verify_agent.py"], 900),
    ("Agent 采纳/拒绝 回原文核对", ["verify_agent_evidence.py"], 900),
    ("记忆容量上限与压缩",         ["verify_memory_capacity.py"], 600),
    ("第二三期 案例实测",          ["verify_phase23.py"], 600),
    ("LLM 归因 分片并发",          ["verify_shards.py"], 900),
    ("读图 分片并发",              ["verify_vision_shards.py"], 900),
    ("分布参数守卫(单测)",         ["verify_dist_guard.py"], 300),
    ("读图耗时预算",               ["verify_vision_budget.py"], 600),
    ("读图语境守卫 八套 A/B",      ["verify_vision_context_guard.py"], 900),
]
UI = [
    ("界面 两种模式四种组合(含流程面板未执行)", ["verify_modes_ui.py"], 600),
    ("界面 Agent 面板随材料变",                ["verify_agent_panel_ui.py"], 600),
    ("界面 执行记录面板(计划模式)",             ["verify_plan_ui.py"], 600),
]

CHECKS = UI if "--ui" in sys.argv else NON_UI

rows = []
for i, (name, args, to) in enumerate(CHECKS, 1):
    print(f"[{i}/{len(CHECKS)}] {name} …", flush=True)
    t0 = time.time()
    try:
        p = subprocess.run([PY, "-X", "utf8", *args], cwd=str(HERE),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=to)
        out = (p.stdout or "") + (p.stderr or "")
        code, tmo = p.returncode, False
    except subprocess.TimeoutExpired as e:
        def _s(v):
            return v if isinstance(v, str) else (v or b"").decode("utf-8", "replace")
        out = _s(e.stdout) + _s(e.stderr)
        code, tmo = -1, True
    el = time.time() - t0
    tail = "\n".join([ln for ln in out.splitlines() if ln.strip()][-6:])
    rows.append((name, "TIMEOUT" if tmo else ("OK" if code == 0 else f"exit={code}"), el, tail))
    print(f"    -> {rows[-1][1]}  {el:.1f}s", flush=True)

print("\n=================== 汇总 ===================")
for name, st, el, _ in rows:
    print(f"{name:36} {st:10} {el:7.1f}s")
bad = [r for r in rows if r[1] != "OK"]
print(f"\n异常 {len(bad)} 项")
for name, st, _, tail in bad:
    print(f"\n--- {name} ({st}) 输出尾部 ---")
    print(tail)
