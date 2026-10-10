"""回原文核对：新样本的"论文声明值"是否抽对了（尤其是被拿去做补丁的那些）。

补丁的语义是"把代码改成论文的值"，所以**论文侧那个值错了，补丁就是错的**。
本脚本把每个样本的论文侧取值连同原文片段打出来供人工核对。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.envfile import load_env            # noqa: E402
from paper2lab.pipeline import run_audit           # noqa: E402

load_env()
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")

out: list[str] = ["# 回原文核对：论文侧取值", "",
                  "补丁 = 把代码改成论文的值 ⇒ **论文侧取值错，补丁就错**。逐条核对。", ""]
for d in sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")):
    pdf, code = d / "paper.pdf", d / "code.zip"
    res = d / "results.json"
    if not (pdf.exists() and code.exists()):
        continue
    ur = json.loads(res.read_text(encoding="utf-8")) if res.exists() else None
    audit, _ = run_audit(str(pdf), str(code), ur, plan_mode=True,
                         force_mock=True)     # 取值与 LLM 无关, 用 mock 提速
    out.append(f"## {d.name}")
    out.append("")
    out.append("| 参数 | 论文侧取值 | 代码侧取值 | 判定 | 原文片段 |")
    out.append("|---|---|---|---|---|")
    for f in audit.findings:
        if not f.paper:
            continue
        sn = (f.paper.snippet or "").replace("|", "\\|").replace("\n", " ")[:110]
        out.append(f"| {f.display_name} | `{f.paper.raw_value}` | "
                   f"`{(f.code.raw_value if f.code else '—')}` | {f.status.value} | …{sn}… |")
    # 结果类单独列
    for k, ev in (audit.paper.results or {}).items():
        sn = (ev.snippet or "").replace("|", "\\|").replace("\n", " ")[:110]
        out.append(f"| Result: {k} | `{ev.raw_value}` | "
                   f"（实测 {ur.get(k) if ur else '—'}） | — | …{sn}… |")
    out.append("")

(ROOT / "_param_evidence.md").write_text("\n".join(out), encoding="utf-8")
print("done")
