"""AI 两条通道的**真机实测**：让 AI 真排一次计划、真提名一次补丁目标，看程序盖了哪些章。

用法: .venv\\Scripts\\python.exe probe_ai_channels.py [样本名，默认 04_DeiT]
      （在 v2 测试集里找同名目录；带 LLM key 时才真调 API，否则会自动回退并如实说明）

它与 verify_llm_planner.py 的分工:
  · verify_llm_planner.py —— 断言**盖章器**（注入提案，不调 API，确定性）；
  · 本脚本            —— 跑**真实模型**，用来人工看"AI 到底提了什么、程序挡了什么"
    （观察用，不做断言：模型输出本就有波动，拿它当门禁会变成随机失败）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.envfile import load_env            # noqa: E402
from paper2lab.pipeline import run_audit           # noqa: E402

load_env()
V2 = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")
name = sys.argv[1] if len(sys.argv) > 1 else "04_DeiT"
d = V2 / name
if not d.exists():
    print(f"找不到样本 {d}")
    raise SystemExit(1)

ur = json.loads((d / "results.json").read_text(encoding="utf-8")) \
    if (d / "results.json").exists() else None
audit, _ = run_audit(str(d / "paper.pdf"), str(d / "code.zip"), ur,
                     plan_mode=True, llm_planner=True, llm_patch=True)

ex = audit.execution_log or {}
plan = ex.get("plan") or {}
print("=" * 78)
print(f"样本 {name}　排计划方式 = {plan.get('planner')}（rule=规则版 / llm=AI 排的）")
print("=" * 78)
print("【决策表】只有 AI 有动作或程序否决 AI 的行才打印（其余是默认执行 / 材料事实）")
for x in plan.get("decisions", []):
    if x.get("source") != "llm" or x.get("action") == "skip":
        print(f"  {x['action']:4} ｜ {x['source']:5} ｜ {x['title']:14} ｜ {x['reason'][:66]}")
print("")
print("【notes（节选）】")
for n in (ex.get("notes") or [])[:5]:
    print("  ·", n[:150])
print("")
print("【补丁草案】status: proposed=确定性推出 / proposed-llm=AI 提名且过了盖章 / refused=不给")
for p in (getattr(audit, "patches", None) or []):
    print(f"  {p.status:13} src={p.source:5} {p.display:18} {str(p.target or '—'):18} "
          f"{(p.refuse_reason or p.rationale or '')[:60]}")
    for s in (getattr(p, "stamps", None) or []):
        print(f"        盖章: {s}")
