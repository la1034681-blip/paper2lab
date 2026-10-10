"""列出各样本被**新守卫**拒收的抽取（用于判断是改对还是误伤）。"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.paper_parser import parse_paper      # noqa: E402

OLD = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
NEW = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")
CASES = [
    ("01_DDPM", OLD / "01_DDPM/paper.pdf"),
    ("02_DETR", OLD / "02_DETR/paper.pdf"),
    ("03_NeRF", OLD / "03_NeRF/paper.pdf"),
    ("04_PointNet", OLD / "04_PointNet/paper.pdf"),
    ("05_ViT", OLD / "05_ViT/paper.pdf"),
    ("demo", HERE / "demo/paper.pdf"),
    ("D题", HERE / "demo/D题论文.pdf"),
    ("E题", Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf")),
]

# 新守卫的理由关键词（用来区分"新增的拒收"与原有的先验拒收）
NEW_MARKS = ("参考文献", "语境", "纯数字", "表格的多列", "连字符", "动词", "虚词")

out = ["# 各样本被拒收的抽取（★ = 新守卫所致）", ""]
for name, pdf in CASES:
    if not pdf.exists():
        continue
    p = parse_paper(str(pdf))
    rej = p.rejected or []
    cnt = Counter(r["reason"][:14] for r in rej)
    out.append(f"## {name}（共拒收 {len(rej)} 条）")
    out.append("")
    out.append("| 参数 | 取值 | 位置 | 原因 | 新守卫 |")
    out.append("|---|---|---|---|---|")
    for r in rej:
        mark = "★" if any(k in r["reason"] for k in NEW_MARKS) else ""
        out.append(f"| {r['key']} | `{r['value']}` | {r['location']} | "
                   f"{r['reason'][:70]} | {mark} |")
    out.append("")
    out.append(f"- 按原因计数: {dict(cnt)}")
    out.append("")

(OLD / "_rejections.md").write_text("\n".join(out), encoding="utf-8")
print("done")
