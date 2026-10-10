"""核实新样本里"论文声明的结果指标"是否抽对了（回原文看片段）。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.paper_parser import parse_paper      # noqa: E402

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")
out: list[str] = ["# 结果指标出处核实", ""]
for d in sorted(p for p in ROOT.iterdir() if p.is_dir()):
    pdf = d / "paper.pdf"
    if not pdf.exists():
        continue
    p = parse_paper(str(pdf))
    out.append(f"## {d.name}  （{p.title[:60] if p.title else '?'}）")
    if not p.results:
        out.append("- 论文未声明可对照的结果指标")
    for k, ev in p.results.items():
        out.append(f"- **{k} = {ev.raw_value}**")
        out.append(f"  - 位置: {ev.location}")
        out.append(f"  - 原文片段: …{ev.snippet}…")
    out.append("")

(ROOT / "_result_evidence.md").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
