"""把每条补丁的**完整拒绝理由**逐条打出来（全流程面板每样本只显示前 4 条）。

用法: .venv\\Scripts\\python.exe probe_patch_refusals.py

覆盖两套样本（v2 六套 + 旧三套），对每个样本跑真实审计后，
按与 `run_new_set.py` / `demo_full_flow.py` **完全相同的调用方式**生成补丁：
    traces  = trace_findings(audit, max_items=8)
    patches = propose_patches(audit, traces, code_path, max_items=8)
即最多 8 条（报告里的"拒绝 N 条"也是这个口径）。

为什么要单独做: 「拒绝」在报告里只是一行摘要，而拒绝的**理由**才是有用的信息 ——
用户看到"0 条补丁"时，第一个问题必然是"为什么一条都不给"。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.envfile import load_env            # noqa: E402
from paper2lab.patch import propose_patches        # noqa: E402
from paper2lab.pipeline import run_audit           # noqa: E402
from paper2lab.rootcause import trace_findings     # noqa: E402

load_env()
V2 = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")
OLD = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
OUT = V2 / "补丁拒绝原因清单.md"

CASES: list[tuple[str, Path, Path, Path | None]] = []
for d in sorted(p for p in V2.iterdir() if p.is_dir() and not p.name.startswith("_")):
    if (d / "paper.pdf").exists():
        CASES.append((d.name, d / "paper.pdf", d / "code.zip", d / "results.json"))
for nm in ("01_DDPM", "02_DETR", "05_ViT"):
    pdf, zp = OLD / nm / "paper.pdf", OLD / nm / "code.zip"
    rj = OLD / nm / "results.json"
    if pdf.exists() and zp.exists():
        CASES.append((f"旧·{nm}", pdf, zp, rj if rj.exists() else None))

# 理由归类: 关键词按 patch.py 里的闸门顺序排列（先匹配到的先算）
_KINDS = [
    ("① 结论类型不是「值不一致」", "不是「值不一致」"),
    ("② 结果指标（不是配置项）", "实验结果指标"),
    ("② 实现选择类（optimizer/scheduler/model）", "实现选择"),
    ("② 白名单外的配置项", "不在可改值白名单"),
    ("③ 论文侧有多个取值（多配置/多列）", "个不同的取值"),
    ("④ 追不出最终生效的赋值点", "无法确定代码里最终生效"),
    ("⑤ 根因路径格式异常", "根因路径格式异常"),
    ("⑥ 代码包里找不到该文件", "在代码包里找不到"),
    ("⑥ 行号超出文件范围", "超出文件行数"),
    ("⑦ 论文值形态不干净（截断/带标点）", "形态不干净"),
    ("⑧ 单位不一致（迭代 vs 轮）", "迭代次数**，而这一行"),
    ("⑨ 目标行 type=int 却给浮点", "type=int"),
    ("⑩ 值无法转成代码字面量", "无法转成代码可用的字面量"),
    ("⑪ 该行找不到唯一的待替换值", "找不到唯一的待替换值"),
]


def kind_of(reason: str) -> str:
    for name, kw in _KINDS:
        if kw in reason:
            return name
    return "（未归类）"


rows: list[dict] = []
for name, pdf, zp, rj in CASES:
    res = json.loads(rj.read_text(encoding="utf-8")) if rj and rj.exists() else None
    audit, _ = run_audit(str(pdf), str(zp), res, plan_mode=True)
    traces = trace_findings(audit, max_items=8)
    patches = propose_patches(audit, traces, str(zp), max_items=8)
    n_ok = sum(1 for p in patches if p.is_proposed)
    print(f"{name}: 补丁 {len(patches)} 条（给方案 {n_ok}）")
    for p in patches:
        rows.append({"case": name, "status": p.status, "display": p.display,
                     "key": p.param_key, "reason": (p.refuse_reason or "").strip(),
                     "target": p.target, "before": (p.before or "").strip(),
                     "after": (p.after or "").strip(),
                     "paper": (p.evidence or {}).get("paper", {}),
                     "code": (p.evidence or {}).get("code", {}),
                     "conf": p.confidence})

cnt = Counter(kind_of(r["reason"]) for r in rows if r["status"] != "proposed")
n_prop = sum(1 for r in rows if r["status"] == "proposed")

out = ["# 补丁为什么被拒 —— 逐条理由清单", "",
       f"覆盖 {len(CASES)} 套样本（v2 六套 + 旧三套）；补丁结论共 **{len(rows)}** 条：",
       f"**给方案 {n_prop} 条 / 拒绝 {len(rows) - n_prop} 条**。",
       "全流程报告每样本只显示前 4 条摘要，这里是**全部**（上限 8 条/样本，与报告同口径）。", "",
       "## 一、拒绝理由分布", "", "| 闸门（按判定顺序） | 条数 |", "|---|---|"]
for k, v in cnt.most_common():
    out.append(f"| {k} | {v} |")
out += ["", "闸门顺序 = `paper2lab/patch.py` 的 `propose_patch()` 判定顺序：",
        "**结论类型 → 是否配置项 → 论文值是否唯一 → 能否定位唯一生效点 → 目标行核对"
        "（值形态 / 单位 / 类型 / token 唯一）**。任一关不过即拒绝，不给近似方案。", "",
        "## 二、逐条明细", ""]

for r in rows:
    if r["status"] == "proposed":
        out += [f"### ✅ 给方案 · {r['case']} · {r['display']}", "",
                f"- 目标: `{r['target']}`",
                f"- 论文值: `{r['paper'].get('value')}`（{r['paper'].get('location')}）",
                f"- 代码值: `{r['code'].get('value')}`（{r['code'].get('location')}）",
                f"- 原行: `{r['before']}`", f"- 改后: `{r['after']}`", ""]
    else:
        out += [f"### ⛔ {r['case']} · {r['display']}　—　**{kind_of(r['reason'])}**", "",
                f"- 理由: {r['reason']}"]
        if r["target"]:
            out.append(f"- 本来要改的行: `{r['target']}` ｜ `{r['before']}`")
        elif r["paper"].get("value"):
            out.append(f"- 论文侧取值: `{r['paper'].get('value')}`"
                       f"（{r['paper'].get('location')}）")
        out.append("")

OUT.write_text("\n".join(out), encoding="utf-8")
print(f"\n报告 -> {OUT}")
print("理由分布:")
for k, v in cnt.most_common():
    print(f"  {k}: {v}")
