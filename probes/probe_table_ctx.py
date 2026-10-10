"""看"表格多列"判据在 D题/E题 命中的原文（判断是误伤还是真串列）。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.paper_parser import _extract_pages      # noqa: E402

CASES = [
    (HERE / "demo/D题论文.pdf", 15, ["num_bombs", "枚"]),
    (Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"), 5, ["epochs", "迭代", "训练"]),
    (Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"), 8, ["聚类", "K"]),
    (Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"), 17, ["阈值", "threshold"]),
]

out = ["# 表格判据命中的原文", ""]
for pdf, page_no, kws in CASES:
    if not pdf.exists():
        continue
    pages, _ = _extract_pages(str(pdf))
    page = next((t for n, t in pages if n == page_no), None)
    if page is None:
        out.append(f"- {pdf.name} 第 {page_no} 页不存在"); continue
    out.append(f"## {pdf.name} 第 {page_no} 页（找 {kws}）")
    out.append("")
    for kw in kws:
        for m in re.finditer(re.escape(kw), page):
            seg = page[max(0, m.start() - 90): m.end() + 90]
            out.append("- …" + seg.replace("\n", " ⏎ ") + "…")
            break
    out.append("")

(HERE / "demo/_tablecheck.md").write_text("\n".join(out), encoding="utf-8")
print("done")
