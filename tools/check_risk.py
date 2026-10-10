"""验证风险分级策略: 打印每条的等级与理由。"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from paper2lab.pipeline import run_audit
from paper2lab.risk import MISMATCH_RISK, assess_risk
from paper2lab.models import Risk, Status

print("=== 参数重要性表(不一致时的风险) ===")
for k, v in MISMATCH_RISK.items():
    print(f"  {k:14} -> {v.value}")

print()
print("=== 关键规则自检 ===")
cases = [
    (Status.INCONSISTENT, "learning_rate"),   # 关键参数矛盾 -> 高
    (Status.INCONSISTENT, "dropout"),         # 次要参数矛盾 -> 低
    (Status.MISSING_IN_PAPER, "batch_size"),  # 代码有/论文没写(重要参数) -> 中
    (Status.MISSING_IN_PAPER, "dropout"),     # 代码有/论文没写(次要) -> 低
    (Status.MISSING_IN_PAPER, "seed"),        # 种子特例 -> 低
    (Status.MISSING_IN_CODE, "learning_rate"),# 论文有/代码没找到(关键) -> 中
    (Status.MISSING_IN_CODE, "dropout"),      # 论文有/代码没找到(次要) -> 低
    (Status.NOT_FIXED, "seed"),               # 未固定随机性 -> 中
    (Status.UNVERIFIABLE, "learning_rate"),   # 动态确定 -> 低
]
for st, key in cases:
    r, why = assess_risk(st, key)
    print(f"  {st.value:20} {key:14} -> {r.value:6} | {why[:70]}")

print()
print("=== demo 实际发现(含理由) ===")
a, _r = run_audit("demo/paper.pdf", "demo/project.zip", None, force_mock=True)
print(f"就绪度 {a.readiness['total']} | 自检 {a.selfcheck['passed']}/{a.selfcheck['checked']}")
for f in a.findings:
    print(f"  [{f.risk.value:6}] {f.status.value:20} {f.display_name:18} | {f.risk_reason[:66]}")
