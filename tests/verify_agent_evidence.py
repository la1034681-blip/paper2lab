"""Agent 证据核对（可复现的独立复核工具）。

做三件事:
  1. 关键取值核对 —— 把 Agent 采纳/拒绝的取值拿回 PDF 原文逐条列出;
  2. 训练轮数分布 —— 判断"未取到 iterations/epochs"是漏抽还是论文本来没写;
  3. 待补目标触发来源 —— 区分"论文真在讲这个参数"与"别名误命中"。

用法: .venv\\Scripts\\python.exe verify_agent_evidence.py
输出: Paper2Lab测试集/agent_evidence_report.md
"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import re
import time
from pathlib import Path

import pymupdf

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
OUT = ROOT / "agent_evidence_report.md"

KEY_CASES = [
    ("05_ViT", 13, ["dropout"], "Agent 补回 Dropout=0.0 —— 原文是否真有?"),
    ("03_NeRF", 9, ["iteration"], "Agent 拒绝 100-300k —— 原文是否真是收敛范围?"),
    ("04_PointNet", 10, ["dropout"], "Agent 拒绝 0.7 —— 原文是否真是 keep ratio?"),
]

ROUND_CASES = [
    ("02_DETR", ["iteration", "epoch"]),
    ("03_NeRF", ["iteration", "epoch"]),
    ("04_PointNet", ["epoch", "iteration"]),
]

TARGET_CASES = {
    "02_DETR": ["input_size"],
    "03_NeRF": ["iterations"],
    "04_PointNet": ["dropout", "epochs"],
}

ALIASES = {
    "iterations": ["iterations", "iteration", "n_iter", "num_iter", "max_iter",
                   "max_steps", "num_steps", "total_steps", "training steps"],
    "epochs": ["epochs", "epoch", "training epochs"],
    "input_size": ["input_size", "image_size", "img_size", "crop_size", "resolution"],
    "dropout": ["dropout"],
}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _pages(name: str) -> list[str]:
    doc = pymupdf.open(str(ROOT / name / "paper.pdf"))
    pages = [_flat(doc[i].get_text()) for i in range(doc.page_count)]
    doc.close()
    return pages


def _sents_with(flat: str, keys: list[str]) -> list[str]:
    res = []
    for s in re.split(r"(?<=[.;])\s+", flat):
        if any(k.lower() in s.lower() for k in keys) and re.search(r"\d", s):
            res.append(s.strip()[:380])
    return res


def section_key() -> list[str]:
    lines = ["## 一、关键取值核对", "",
             "把 Agent 采纳/拒绝的取值拿回原文, 逐条判定「补回得对不对、拒绝得对不对」。", ""]
    for name, page, keys, why in KEY_CASES:
        doc = pymupdf.open(str(ROOT / name / "paper.pdf"))
        n = doc.page_count
        txt = doc[page - 1].get_text() if 1 <= page <= n else ""
        doc.close()
        lines.append(f"### {name} — Page {page}")
        lines.append(f"- 核对目的: {why}")
        hits = _sents_with(_flat(txt), keys)
        if not hits:
            lines.append("- （该页未找到含关键词且带数字的句子）")
        for h in hits:
            lines.append(f"  - {h}")
        lines.append("")
    return lines


def section_rounds() -> list[str]:
    lines = ["## 二、训练轮数在原文的分布", "",
             "用于判断 `iterations` / `epochs` 的「未取到」是**漏抽**还是**论文本来没写**。", ""]
    for name, keys in ROUND_CASES:
        pages = _pages(name)
        lines.append(f"### {name}")
        found = False
        for pno, flat in enumerate(pages, 1):
            for s in _sents_with(flat, keys):
                lines.append(f"  - [p{pno}] {s}")
                found = True
        if not found:
            lines.append("- （全文没有任何「含关键词且带数字」的句子）")
        lines.append("")
    return lines


def section_targets() -> list[str]:
    lines = ["## 三、待补目标的触发来源", "",
             "列出每个待补目标是被哪句话判定为「论文提到过」的, 用于识别**别名误命中**。", ""]
    for name, kinds in TARGET_CASES.items():
        pages = _pages(name)
        lines.append(f"### {name}")
        for kind in kinds:
            lines.append(f"- ▸ 待补目标 `{kind}`")
            shown = 0
            for pno, flat in enumerate(pages, 1):
                if shown >= 4:
                    break
                low = flat.lower()
                for a in ALIASES[kind]:
                    if shown >= 4:
                        break
                    for m in re.finditer(r"\b" + re.escape(a) + r"\b", low):
                        if shown >= 4:
                            break
                        s, e = max(0, m.start() - 100), min(len(flat), m.end() + 100)
                        lines.append(f"  - [p{pno}] …{flat[s:e].strip()}…")
                        shown += 1
            if shown == 0:
                lines.append("  - （未找到触发句）")
        lines.append("")
    return lines


def section_veto() -> list[str]:
    """展示别名同形异义否决规则, 并核对 DETR 那处否决是否合理。"""
    from paper2lab.paper_parser import _ALIAS_VETO
    lines = ["## 四、别名同形异义否决（本次修复）", "",
             "`iterations` 这类别名是裸词, 会把「同形异义搭配」误判成",
             "「论文提到了该参数」, 从而虚增「未取到」并让 Agent 白花预算。",
             "已加入的否决规则:", ""]
    for key, pats in _ALIAS_VETO.items():
        for p in pats:
            lines.append(f"- `{key}` ← 否决 `{p.pattern}`")
    lines.append("")
    lines.append("核对: 02_DETR 全文 `iteration` 的出现位置（应以「反复改设计」为主）")
    for pno, flat in enumerate(_pages("02_DETR"), 1):
        for m in re.finditer(r"iterations?", flat.lower()):
            s, e = max(0, m.start() - 90), min(len(flat), m.end() + 90)
            lines.append(f"  - [p{pno}] …{flat[s:e].strip()}…")
    lines.append("")
    return lines


def main():
    head = ["# 抽取 Agent 证据核对报告", "",
            f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M')}",
            "- 用途: 独立复核 Agent 的采纳/拒绝是否经得起回原文检验, 并量化「未取到」指标的水分",
            "- 配套: 结论见 agent_report.md（开/关消融）", ""]
    body = (head + section_key() + section_rounds()
            + section_targets() + section_veto())
    OUT.write_text("\n".join(body), encoding="utf-8")
    print(f"报告: {OUT}")


if __name__ == "__main__":
    main()
