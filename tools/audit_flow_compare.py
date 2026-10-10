"""对比全流程输出的**汇总表**（逐列），用来判定"重跑一遍结果是否一致"。

用法: .venv\\Scripts\\python.exe audit_flow_compare.py <基线> <新输出> [<基线2> <新输出2>]

为什么不用 diff_flow_runs.py: 那个是**逐行**比对，输出结构一变（比如这次报告里
"10 个进度节点"改成按 `len(STEPS)` 派生）就会整片错位、把真实差异埋在噪声里。
判断"结论有没有变"要看**汇总表的列**，而不是行。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROW = re.compile(r"^\|\s*(01_|02_|03_|04_|05_|06_|demo|D题|E题)")
TIME_CELL = re.compile(r"\|\s*[\d.]+s\s*\|")


def table(p: Path) -> list[str]:
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ROW.match(ln):
            out.append(TIME_CELL.sub("| T |", ln.rstrip()))
    return out


def head(p: Path) -> list[str]:
    return [ln.rstrip() for ln in p.read_text(encoding="utf-8").splitlines()
            if "个进度节点由" in ln]


def compare(base: Path, new: Path) -> tuple[list[str], list[str]]:
    a, b = table(base), table(new)
    sa, sb = set(a), set(b)
    only_a = [x for x in a if x not in sb]
    only_b = [x for x in b if x not in sa]
    return only_a, only_b


args = sys.argv[1:]
if len(args) < 2:
    print(__doc__)
    raise SystemExit(2)

pairs = [(Path(args[i]), Path(args[i + 1])) for i in range(0, len(args) - 1, 2)]
for base, new in pairs:
    print("=" * 78)
    print(f"{base.name}  →  {new.name}")
    print("=" * 78)
    if not base.exists() or not new.exists():
        print("  文件缺失，跳过")
        continue
    only_a, only_b = compare(base, new)
    if not only_a and not only_b:
        print(f"  ✅ 汇总表 {len(table(new))} 行 **逐列一致**（耗时列已归一化）")
    else:
        print(f"  ⚠️ 有差异：基线独有 {len(only_a)} 行 / 新输出独有 {len(only_b)} 行")
        for x in only_a:
            print("    - 基线:", x)
        for x in only_b:
            print("    + 本次:", x)
    ha, hb = head(base), head(new)
    if ha != hb:
        print("  报告里的「进度节点」说明行有变化（预期内）：")
        for x in ha:
            print("    - 基线:", x)
        for x in hb:
            print("    + 本次:", x)
    print("")
