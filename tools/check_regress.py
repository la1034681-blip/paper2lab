"""回归守护: 确认本次改动没有让既有样本变差。"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from pathlib import Path

from paper2lab.pipeline import run_audit

print("=== 1) 中文数模集(demo/D题/E题) ===")
for name, pdf, zp in [
    ("demo", "demo/paper.pdf", "demo/project.zip"),
    ("D题", "demo/D题论文.pdf", "demo/D题代码.zip"),
    ("E题", r"C:\Users\lijiahui\Desktop\E题论文.pdf", r"C:\Users\lijiahui\Desktop\E题作答.zip"),
]:
    a, _ = run_audit(pdf, zp, None, force_mock=True)
    fs = [(f.display_name, f.paper.raw_value if f.paper else None,
           f.code.raw_value if f.code else None) for f in a.findings]
    print(f"{name}: 就绪度 {a.readiness['total']} | 自检 {a.selfcheck['passed']}/{a.selfcheck['checked']} "
          f"| 发现 {len(a.findings)}")
    print("   参数值:", [f"{n}:论文={p}/代码={c}" for n, p, c in fs])

print()
print("=== 2) PointNet 论文 num_clusters 是否仍在(检查是否回退) ===")
p = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\04_PointNet\paper.pdf")
from paper2lab.paper_parser import parse_paper
pp = parse_paper(str(p))
for k in ("num_clusters", "threshold", "input_size", "dataset"):
    ev = pp.params.get(k)
    print(f"  {k}: {ev.raw_value if ev else None} @ {ev.location if ev else '—'}"
          f" | 片段: {(ev.snippet[:60] if ev else '')}")

print()
print("=== 3) 边缘集(诱饵/拒收/不支持格式) ===")
a, _ = run_audit("demo/paper.pdf", "demo/edge_code.zip", None, force_mock=True)
cov = a.coverage
print(f"  可信度 {cov.get('confidence_level')}({cov.get('confidence_score')}) | "
      f"自检 {a.selfcheck['passed']}/{a.selfcheck['checked']} | 拒收 {len(cov.get('rejected') or [])}")
print("  多语言:", [(m['file'], m['params']) for m in (cov.get('multilang') or [])])
print("  拒收:", [(x['key'], x['value']) for x in (cov.get('rejected') or [])])
