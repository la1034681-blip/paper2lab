"""回归验证脚本: 对 demo / D题 / E题 三套数据跑完整审计并打印关键结果。

用于每次改动规则后确认既有结论不无故变化(时间维度的交叉审查)。
用法: .venv\\Scripts\\python.exe verify_sets.py
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from paper2lab.pipeline import run_audit

SETS = [
    ("demo", "demo/paper.pdf", "demo/project.zip", None),
    ("D题", "demo/D题论文.pdf", "demo/D题代码.zip", None),
    ("E题", r"C:\Users\lijiahui\Desktop\E题论文.pdf",
     r"C:\Users\lijiahui\Desktop\E题作答.zip", None),
]

for name, pdf, zipf, res in SETS:
    audit, report = run_audit(pdf, zipf, res, force_mock=True)
    cov = audit.coverage
    print("=" * 64)
    print(f"### {name} | 就绪度 {audit.readiness['total']} | "
          f"可信度 {cov['confidence_level']}({cov['confidence_score']})")
    print(f"  页 {cov['pages_parsed']}/{cov['pages_total']} 薄页 {cov['pages_thin']} | "
          f"声明 {cov['decl_matched']}/{cov['decl_total']} | "
          f"代码 {cov['code_ok']}/{cov['code_files']} | "
          f"拒收 {len(cov['rejected'])} | 不支持 {len(cov['unsupported'])}")
    if cov["confidence_notes"]:
        print("  扣分原因:", "；".join(cov["confidence_notes"]))
    sc = audit.selfcheck
    print(f"  自检 {sc['passed']}/{sc['checked']} 通过, 未通过 {sc['failed']}")
    for fl in sc["failures"]:
        print("    !", fl["param"], "|", "；".join(fl["reasons"]))
    for f in audit.findings:
        print(f"  [{f.status.value}] {f.display_name} risk={f.risk.value} "
              f"verified={f.verified}")
    with open(f"demo/{name}_audit_report.md", "w", encoding="utf-8") as fh:
        fh.write(report)
print()
print("REPORTS SAVED")
