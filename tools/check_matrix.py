"""验收: 参数覆盖清单 + 风险理由 在 demo 与真实样本上的输出。"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from paper2lab.pipeline import run_audit

for name, pdf, zp in [
    ("demo", "demo/paper.pdf", "demo/project.zip"),
    ("DDPM", r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\01_DDPM\paper.pdf",
     r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\01_DDPM\code.zip"),
]:
    a, rep = run_audit(pdf, zp, None, force_mock=True)
    pm = a.coverage["param_matrix"]
    hit = sum(1 for x in pm if str(x["是否进入比对"]).startswith("✓"))
    print(f"=== {name}: 就绪度 {a.readiness['total']} | 覆盖清单 {len(pm)} 项(进入比对 {hit}) | "
          f"报告含清单: {'参数覆盖清单' in rep}")
    for x in pm:
        print(f"  {x['参数']:18} 论文: {x['论文侧'][:40]:42} 代码: {x['代码侧'][:34]:36} "
              f"{x['是否进入比对']}")
    print("  风险理由示例:",
          (a.findings[0].risk_reason[:70] if a.findings else "(无)"))
    print()
