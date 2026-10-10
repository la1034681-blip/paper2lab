"""摸清新样本：论文声明了哪些结果指标、抽到哪些参数、代码侧配置情况。

用途: 决定每个样本的 results.json 该放什么(键名必须与论文指标同名),
并判断样本是否"有内容可审"(抽不到参数或代码无配置的样本价值低)。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.code_analyzer import analyze_code      # noqa: E402
from paper2lab.paper_parser import parse_paper        # noqa: E402

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")

out: list[str] = ["# 新样本摸底", ""]
for d in sorted(p for p in ROOT.iterdir() if p.is_dir()):
    pdf, zp = d / "paper.pdf", d / "code.zip"
    out.append(f"## {d.name}")
    if not pdf.exists():
        out.append("- 缺 paper.pdf"); out.append(""); continue
    p = parse_paper(str(pdf))
    c = analyze_code(str(zp)) if zp.exists() else None
    out.append(f"- 论文标题: {p.title or '(未识别)'}")
    out.append(f"- 页数: {p.page_count}　声明参数种类: {len(p.params)}"
               f"　**声明结果指标: {list(p.results) or '（无）'}**")
    if p.results:
        for k, ev in p.results.items():
            out.append(f"    - {k} = {ev.raw_value}  ← {ev.location}")
    out.append(f"- 参数明细: {sorted(p.params)}")
    if p.params_all:
        extra = sorted(set(p.params_all) - set(p.params))
        out.append(f"- 另有(未选中最佳值的)参数: {extra}")
    if c is not None:
        out.append(f"- 代码: {c.python_files} 个 py　参数种类 "
                   f"{len(c.params)}　依赖 {len(c.requirements)} 项"
                   f"　seed_fixed={c.seed_fixed}")
        out.append(f"- 代码参数明细: {sorted(c.params)}")
    out.append("")

(ROOT / "_survey.md").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
