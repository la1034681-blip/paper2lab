"""整理新测试集的产出文件名（把 _ 前缀的分析文件改成一眼能懂的中文名）。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")

RENAME = {
    "_download_report.md": "测试集_下载来源与校验.md",
    "_survey.md": "抽查_参数与指标.md",
    "_result_evidence.md": "抽查_结果指标出处核实.md",
    "_param_evidence.md": "抽查_论文取值回原文核对.md",
    "_findings_report.md": "测试发现_论文取值精度问题.md",
}

for old, new in RENAME.items():
    src, dst = ROOT / old, ROOT / new
    if src.exists():
        src.replace(dst)
        print(f"renamed {old} -> {new}")

# 修正文件内互相引用的旧名
for p in ROOT.glob("*.md"):
    t = p.read_text(encoding="utf-8")
    t2 = t
    for old, new in RENAME.items():
        t2 = t2.replace(f"`{old}`", f"`{new}`")
    if t2 != t:
        p.write_text(t2, encoding="utf-8")
        print(f"引用已更新: {p.name}")

print()
for p in sorted(ROOT.iterdir()):
    print(("[目录] " if p.is_dir() else "[文件] ") + p.name)
