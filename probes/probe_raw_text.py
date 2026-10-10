"""把新样本里出问题的位置, 原文文本层原样打出来 —— 设计守卫前先看事实。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import fitz  # noqa: E402

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")

# (样本, 关键词, 说明)
SPOTS = [
    ("03_ConvNeXt", "resolution is", "Input Size: 抽到 2242.（疑上标丢失）"),
    ("01_Swin", "warmup of", "Warmup: 抽到 1（疑千分位 1,500 截断）"),
    ("04_DeiT", "fixed size of", "Batch Size: 抽到 16（疑 patch 尺寸 16×16）"),
    ("01_Swin", "multiple of", "Input Size: 抽到 2（疑下采样倍数 2×2）"),
    ("02_MAE", "minibatch SGD", "Optimizer: 抽到 SGD（疑参考文献）"),
    ("06_ImprovedDDPM", "dealing with", "Model: 抽到 dealing（疑动词）"),
    ("06_ImprovedDDPM", "K = 5", "Cluster K: 抽到 5.（疑句号）"),
    ("03_ConvNeXt", "weight decay of 0.05", "Momentum: 抽到 0.05（疑表串列）"),
]

out = ["# 原文文本层原样（用于设计守卫）", ""]
for name, kw, why in SPOTS:
    pdf = ROOT / name / "paper.pdf"
    if not pdf.exists():
        continue
    out.append(f"## {name} —— {why}")
    out.append(f"关键词: `{kw}`")
    hit = False
    with fitz.open(str(pdf)) as doc:
        for i, page in enumerate(doc, 1):
            t = page.get_text("text")
            j = t.find(kw)
            if j < 0:
                continue
            hit = True
            raw = t[max(0, j - 90): j + 130]
            out.append(f"- 第 {i} 页，原文一字不改（`\\n` 为换行）:")
            out.append("")
            out.append("```")
            out.append(raw.replace("\r", ""))
            out.append("```")
            out.append(f"- 该片段 repr（看隐藏字符）: `{raw!r}`")
            break
    if not hit:
        out.append("- ⚠ 关键词在 PDF 里找不到（可能文本层与显示不一致）")
    out.append("")

(ROOT / "_raw_text.md").write_text("\n".join(out), encoding="utf-8")
print("done")
