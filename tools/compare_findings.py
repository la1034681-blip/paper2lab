"""对比两份审计报告的"逐项详情"清单，列出新增/消失的结论。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BAK = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_备份_20260928")
CUR = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")


def items(p: Path) -> list[str]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^###\s+[^\s]+\s+(.+?)\s+—\s+(.+)$", ln)
        if m:
            out.append(f"{m.group(1)} — {m.group(2)}")
    return out


for name in ("01_DDPM", "02_DETR", "03_NeRF", "04_PointNet", "05_ViT", "DEMO"):
    f = f"full_flow_{name}.md"
    a, b = items(BAK / f), items(CUR / f)
    if not a and not b:
        continue
    print(f"=== {name} ===")
    print(f"  改前 {len(a)} 条 / 改后 {len(b)} 条")
    for x in a:
        if x not in b:
            print(f"  - 消失: {x}")
    for x in b:
        if x not in a:
            print(f"  + 新增: {x}")
    print()
