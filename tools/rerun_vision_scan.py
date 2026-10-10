"""快速复跑: 扫描件样例的读图链路(验证压缩优化后仍正常, 并利用缓存)。"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import time
from pathlib import Path

from paper2lab.pipeline import run_audit

ROOT = Path(__file__).resolve().parent.parent
t0 = time.time()
audit, report = run_audit(str(ROOT / "demo" / "scan_paper.pdf"),
                          str(ROOT / "demo" / "scan_code.zip"), None, force_mock=True)
img = audit.coverage.get("image", {})
print(f"耗时 {time.time() - t0:.1f}s | 区域 {img.get('regions')} 读图 {img.get('regions_read')} "
      f"采信 {img.get('kept')} 丢弃 {img.get('dropped')} | 就绪度 {audit.readiness.get('total')}")
for f in audit.findings:
    if f.paper and f.paper.parser == "vlm":
        cv = f.code.raw_value if f.code else "—"
        print(f"  读图: {f.display_name} 图={f.paper.raw_value} 码={cv} "
              f"{f.status.value} {f.confidence.value}")
(ROOT / "demo" / "scan_audit_report.md").write_text(report, encoding="utf-8")
print("报告已更新")
