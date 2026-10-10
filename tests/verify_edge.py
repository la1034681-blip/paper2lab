"""边缘情况测试集审计——验证交叉审查防线(失败示众/不支持格式/拒收/内部不一致)。"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from paper2lab.pipeline import run_audit

audit, report = run_audit("demo/paper.pdf", "demo/edge_code.zip", None, force_mock=True)
cov = audit.coverage
print(f"可信度: {cov['confidence_level']} ({cov['confidence_score']})")
print(f"扣分: {cov['confidence_notes']}")
print(f"失败文件: {cov['code_failed_list']}")
print(f"不支持格式: {cov['unsupported']}")
print(f"拒收: {cov['rejected']}")
print(f"自检: {audit.selfcheck['passed']}/{audit.selfcheck['checked']} 通过")
print(f"就绪度: {audit.readiness['total']}")
for f in audit.findings:
    print(f"  [{f.status.value}] {f.display_name} risk={f.risk.value} verified={f.verified}")
    for ev in f.extra:
        print(f"      附加证据: {ev.raw_value} @ {ev.location}")
with open("demo/edge_audit_report.md", "w", encoding="utf-8") as fh:
    fh.write(report)
print("REPORT SAVED")
