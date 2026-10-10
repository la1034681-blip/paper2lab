"""对比两次全流程报告的汇总表（抽取改动前后）。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def table(p: Path) -> list[list[str]]:
    t = p.read_text(encoding="utf-8")
    m = re.search(r"\| 样本 \| 耗时.*?\n\|[-|]+\n((?:\|.*\n)+)", t, re.S)
    if not m:
        return []
    rows = []
    for ln in m.group(1).strip().splitlines():
        rows.append([c.strip() for c in ln.strip("|").split("|")])
    return rows


a = table(HERE / sys.argv[1])
b = table(HERE / sys.argv[2])
HEAD = ["样本", "耗时", "结论", "风险", "就绪度", "可信度", "Agent补回", "挡下",
        "待确认", "根因可定位", "补丁给/拒"]
# 耗时列不参与实质比较
CMP = [0, 2, 3, 4, 5, 6, 7, 8, 9, 10]

print(f"{'样本':<16} " + " ".join(f"{HEAD[i]:>10}" for i in CMP))
diff = 0
for ra, rb in zip(a, b):
    marks = []
    for i in CMP:
        x = ra[i] if i < len(ra) else "—"
        y = rb[i] if i < len(rb) else "—"
        marks.append(("  " if x == y else "* ") + f"{x}→{y}" if x != y else f"{x:>10}")
        if x != y:
            diff += 1
    print(f"{ra[0]:<16} " + " ".join(f"{m:>10}" for m in marks))

print()
print(f"实质性变化单元格: {diff}")
