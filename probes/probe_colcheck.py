"""定位"表格串列/跨句误抓"的精确命中：把候选别名处的原文逐处打出来。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.paper_parser import _extract_pages     # noqa: E402

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")

CASES = [
    ("03_ConvNeXt", ["momentum"], "动量抽成 0.05（代码侧是 0.9）"),
    ("03_ConvNeXt", ["iterations", "iteration"], "训练迭代次数抽成 16"),
    ("04_DeiT", ["weight decay"], "权重衰减抽成 0.3"),
    ("05_LoRA", ["batch size"], "批大小抽成 32"),
    ("05_LoRA", ["epoch"], "轮数抽成 30"),
]

out = ["# 串列问题定位（别名每一处命中及其前后原文）", ""]
for name, aliases, why in CASES:
    pdf = ROOT / name / "paper.pdf"
    if not pdf.exists():
        continue
    pages, _ = _extract_pages(str(pdf))
    out.append(f"## {name} —— {why}（别名: {aliases}）")
    out.append("")
    n = 0
    for page_no, text in pages:
        for a in aliases:
            for m in re.finditer(rf"(?<![A-Za-z0-9_]){re.escape(a)}(?![A-Za-z0-9_])",
                                 text, re.IGNORECASE):
                n += 1
                if n > 12:
                    break
                seg = text[max(0, m.start() - 70): m.end() + 70]
                out.append(f"- 第 {page_no} 页 `{a}`：…{seg.replace(chr(10), ' ⏎ ')}…")
        if n > 12:
            break
    out.append("")

(ROOT / "_colcheck.md").write_text("\n".join(out), encoding="utf-8")
print("done")
