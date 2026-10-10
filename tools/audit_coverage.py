"""解析覆盖体检: 对每套样本打印"参数 × 载体"矩阵, 找出漏抽的具体位置。"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from pathlib import Path

from paper2lab.code_analyzer import analyze_code
from paper2lab.paper_parser import parse_paper
from paper2lab.synonyms import PARAM_SYNONYMS

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
KEYS = list(PARAM_SYNONYMS)

for d in sorted(p for p in ROOT.iterdir() if p.is_dir() and (p / "paper.pdf").exists()):
    p = parse_paper(str(d / "paper.pdf"))
    c = analyze_code(str(d / "code.zip"))
    print(f"=== {d.name} ===")
    print(f"  论文抽到 {len(p.params)} 类 / 代码抽到 {len(c.params)} 类; "
          f"论文提到未取值: {p.alias_kinds and sorted(set(p.alias_kinds) - set(p.params))}")
    rows = []
    for k in KEYS:
        pv = p.params.get(k)
        cv = (c.params.get(k) or [None])[0]
        if pv or cv:
            rows.append(f"    {k:14} 论文={str(pv.raw_value)[:16] if pv else '—':17} "
                        f"代码={str(cv.raw_value)[:22] if cv else '—'}")
    print("\n".join(rows))
    print()
