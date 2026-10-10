"""命令行审计入口——不开 Streamlit 也能验证整条管线。

用法:
  .venv/Scripts/python run_audit_cli.py                       # 用内置 demo 数据
  .venv/Scripts/python run_audit_cli.py paper.pdf code.zip [results.json]
"""

from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import sys
from pathlib import Path

from paper2lab.models import Status
from paper2lab.pipeline import run_audit

BASE = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) >= 3:
        pdf_path, code_path = sys.argv[1], sys.argv[2]
        user_results = None
        if len(sys.argv) >= 4:
            user_results = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    else:
        pdf_path = str(BASE / "demo" / "paper.pdf")
        code_path = str(BASE / "demo" / "project.zip")
        user_results = json.loads((BASE / "demo" / "results.json").read_text(encoding="utf-8"))

    def on_progress(i, name):
        print(f"  [{i + 1}/7] {name}")

    audit, report_md = run_audit(pdf_path, code_path, user_results,
                                 force_mock=True, progress=on_progress)

    print("\n========== 审计结果 ==========")
    print(f"论文: {audit.paper.title}")
    _tot = audit.readiness.get("total")
    print(f"复现就绪度: {'—（无任何可核验维度）' if _tot is None else str(_tot) + ' / 100'}")
    for k, v in audit.readiness.get("categories", {}).items():
        print(f"  - {k}: {'未核验(不计入总分)' if v is None else v}")
    for k, why in (audit.readiness.get("unverified") or {}).items():
        print(f"      · {k} 未核验原因: {why}")
    print(f"\nFindings ({len(audit.findings)}):")
    for f in audit.findings:
        mark = "OK " if f.status == Status.CONSISTENT else "!!!"
        pv = f.paper.raw_value if f.paper else "-"
        pl = f.paper.location if f.paper else "-"
        cv = f.code.raw_value if f.code else "-"
        cl = f.code.location if f.code else "-"
        print(f"  [{mark}] {f.display_name:<18} {f.status.value:<16} risk={f.risk.value:<6}")
        print(f"        paper: {pv}  @ {pl}")
        print(f"        code : {cv}  @ {cl}")
        if f.ai_analysis:
            print(f"        AI   : {f.ai_analysis[:80]}...")

    out = BASE / "demo" / "audit_report.md"
    out.write_text(report_md, encoding="utf-8")
    print(f"\n报告已写入: {out}")


if __name__ == "__main__":
    main()
