"""对比两次全流程输出，判断"结果是否可复现"。

用法: .venv\\Scripts\\python.exe diff_flow_runs.py <基线> <新输出>

做法：**先把"本就会变的东西"归一化掉，再逐行比对** —— 而不是整行排除。
（整行排除汇总表是错的：那张表同时含「结论/就绪度/可信度」与「耗时」两列，
  整行排除会把"结论数变了"也一起掩盖掉。实测踩过这个坑。）

归一化掉的内容（都不影响结论）:
  · 各步耗时、总耗时、调度行耗时
  · 跨任务记忆的「本机已审计 N 次」与「上次 时间」
  · 汇总表里的「耗时」列（其他列照常比对）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TIMING = [
    (re.compile(r"（[\d.]+s）"), "（s）"),
    (re.compile(r"全流程 [\d.]+s"), "全流程 s"),
    (re.compile(r"｜ [\d.]+s ｜"), "｜ s ｜"),
]
MEMORY = [
    (re.compile(r"本篇论文在本机已审计 \d+ 次"), "本篇论文在本机已审计 N 次"),
    (re.compile(r"记忆库 \d+ 条明细"), "记忆库 N 条明细"),
    (re.compile(r"记忆库明细 \d+ 篇"), "记忆库明细 N 篇"),
    (re.compile(r"上次 20\d\d-\d\d-\d\d \d\d:\d\d"), "上次 时间"),
]
TABLE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|")


def normalize_line(line: str) -> str:
    out = line
    for pat, rep in TIMING + MEMORY:
        out = pat.sub(rep, out)
    # 汇总表：把「耗时」那一列抹掉再比（其余列必须一致）
    if out.startswith("|") and out.count("|") >= 8:
        cells = out.split("|")
        if len(cells) >= 5:
            cells[2] = " TO "          # 第 2 个数据格 = 耗时列
            out = "|".join(cells)
    return out


def load(p: str) -> list[str]:
    return Path(p).read_text(encoding="utf-8").splitlines()


a, b = load(sys.argv[1]), load(sys.argv[2])
na, nb = [normalize_line(x) for x in a], [normalize_line(x) for x in b]

print(f"总行数: {len(a)} / {len(b)}")
if len(na) != len(nb):
    print("⚠ 行数不同 —— 输出结构发生了变化")

real, vol = [], []
for i in range(max(len(na), len(nb))):
    xa = na[i] if i < len(na) else "<缺失>"
    xb = nb[i] if i < len(nb) else "<缺失>"
    ra = a[i] if i < len(a) else "<缺失>"
    rb = b[i] if i < len(b) else "<缺失>"
    if xa == xb:                       # 归一化后一致 -> 不算差异
        if ra != rb:                   # 但原文不同 -> 属于"耗时/计数"这类正常波动
            vol.append((i + 1, ra, rb))
        continue
    real.append((i + 1, ra, rb))       # 归一化后仍不同 -> 实质差异

print(f"仅耗时/记忆计数不同（归一化后相同）: {len(vol)}")
print(f"**实质性差异: {len(real)}**")
print()
if real:
    print("=== 实质差异明细 ===")
    for n, la, lb in real:
        print(f"  行 {n}:")
        print(f"    - 上次: {la}")
        print(f"    + 本次: {lb}")
    sys.exit(1)

print("两次运行在**全部非耗时/非计数内容**上完全一致 ✅")
print()
print("（含汇总表的 结论数/风险数/就绪度/可信度/Agent补回/挡下/待确认/根因/补丁 各列，")
print("  以及每个样本的执行计划、审计结论、根因、补丁、复现清单、读图调度）")
print()
print("=== 归一化掉的行（抽样 8 条）===")
for n, la, lb in vol[:8]:
    print(f"  行 {n}:")
    print(f"    - {la}")
    print(f"    + {lb}")
