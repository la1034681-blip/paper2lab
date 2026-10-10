"""真实读图验证——用 MiMo 视觉模型跑图像通道(扫描件样例 + 真实论文)。

对照点:
- 扫描件样例(文本层为空): 期望读到 lr=3e-5 / batch=64 / epochs=50 / dropout=0.3,
  并与代码(1e-4 / 32 / 100 / 0.3)比对出 3 不一致 + 1 一致;
- 真实论文: 观察图像通道实际读到什么(kept/dropped/notes), 并确认不影响就绪度评分。
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import time
from pathlib import Path

from paper2lab.pipeline import run_audit

ROOT = Path(__file__).resolve().parent.parent
CASES = [
    ("扫描件样例(文本层为空)", str(ROOT / "demo" / "scan_paper.pdf"),
     str(ROOT / "demo" / "scan_code.zip")),
    ("D题论文(表格为图片)", str(ROOT / "demo" / "D题论文.pdf"),
     str(ROOT / "demo" / "D题代码.zip")),
    ("E题论文(附录为代码截图)",
     r"C:\Users\lijiahui\Desktop\E题论文.pdf",
     r"C:\Users\lijiahui\Desktop\E题作答.zip"),
]

log: list[str] = ["# 图像通道真实读图验证(MiMo mimo-v2.5)", ""]

for name, pdf, zipf in CASES:
    t0 = time.time()
    audit, report = run_audit(pdf, zipf, None, force_mock=True)
    dt = time.time() - t0
    img = audit.coverage.get("image", {})
    vlm = [f for f in audit.findings if f.paper and f.paper.parser == "vlm"]
    log += [
        f"## {name}",
        "",
        f"- 耗时 {dt:.1f}s | 就绪度 **{audit.readiness.get('total')}** | "
        f"图像区域 {img.get('regions', 0)} 个, 读图 {img.get('regions_read', 0)} 个, "
        f"采信 {img.get('kept', 0)} 条, 丢弃 {img.get('dropped', 0)} 条 "
        f"(模型 {img.get('model', '—')}, 来源 {img.get('source', '—')})",
    ]
    for n in img.get("notes", []):
        log.append(f"- 提示: {n}")
    if vlm:
        log += ["", "| 参数 | 读图值 | 代码值 | 状态 | 风险 | 置信 |", "| --- | --- | --- | --- | --- | --- |"]
        for f in vlm:
            log.append(f"| {f.display_name} | `{f.paper.raw_value}` | "
                       f"`{f.code.raw_value if f.code else '—'}` | {f.status.value} | "
                       f"{f.risk.value} | {f.confidence.value} |")
    else:
        log.append("- 读图未产生新结论(该论文参数已在文本层抽到, 或读图结果被丢弃)")
    log.append("")
    (ROOT / f"demo/vision_real_{name.split('(')[0]}.md").write_text(report, encoding="utf-8")

# 2026-09-30 目录整理后：报告统一落到 docs/，别再把产物丢在项目根
# （原来写 ROOT/"vision_real_report.md"，每次跑体检都会在根目录冒出来一份）
(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs" / "vision_real_report.md").write_text("\n".join(log), encoding="utf-8")
print("\n".join(log))
