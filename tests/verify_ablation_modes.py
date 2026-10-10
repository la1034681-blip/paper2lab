"""消融对照：**经典模式 vs 计划模式**，八套样本逐项比对。

这是"经典模式留着有什么用"的直接答案 —— 要证明「调度员没有改变任何结论」，
必须有一个固定全跑的对照组。本脚本就是那个对照。

比对三项（任一不一致即判失败）:
  ① 结论签名（参数 / 状态 / 风险 / 论文取值 / 代码取值，逐条）
  ② 就绪度核心字段（排除 llm_* 这类与调度无关的运行态字段）
  ③ 审计可信度分数

用法: .venv\\Scripts\\python.exe verify_ablation_modes.py
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
from pathlib import Path

from paper2lab.envfile import load_env
from paper2lab.pipeline import run_audit

load_env()
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
HERE = Path(__file__).resolve().parent.parent

CASES = [
    ("01_DDPM", ROOT / "01_DDPM/paper.pdf", ROOT / "01_DDPM/code.zip", None, True),
    ("02_DETR", ROOT / "02_DETR/paper.pdf", ROOT / "02_DETR/code.zip", None, True),
    ("03_NeRF", ROOT / "03_NeRF/paper.pdf", ROOT / "03_NeRF/code.zip", None, True),
    ("04_PointNet", ROOT / "04_PointNet/paper.pdf", ROOT / "04_PointNet/code.zip", None, True),
    ("05_ViT", ROOT / "05_ViT/paper.pdf", ROOT / "05_ViT/code.zip",
     ROOT / "05_ViT/results.json", True),
    ("demo", HERE / "demo/paper.pdf", HERE / "demo/project.zip", None, False),
    ("D题", HERE / "demo/D题论文.pdf", HERE / "demo/D题代码.zip", None, False),
    ("E题", Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"),
     Path(r"C:\Users\lijiahui\Desktop\E题作答.zip"), None, False),
]


def sig(a) -> list:
    """结论签名（**排序后**，可安全比较）。

    ⚠️ 必须排序（2026-09-29 修）：`llm_analyze` 走**分片并发**（4 路），findings 的返回
    顺序受线程调度影响 —— 不排序的话，"内容完全一样、只是顺序不同"也会被判成不一致，
    制造**假失败**（实测 03_NeRF 就这样失败过一次，而重跑立刻一致）。
    findings 是集合语义，顺序本身没有含义，所以排序才是正确口径。
    取值统一转字符串：避免 None 与 str 在排序时比较报错。
    """
    return sorted(
        (str(f.param_key), f.status.value, f.risk.value,
         str(f.paper.raw_value) if f.paper else "",
         str(f.code.raw_value) if f.code else "")
        for f in a.findings)


def rd_core(a) -> dict:
    """就绪度核心字段: 排除 llm_* / execution_log 这类运行态。"""
    return {k: v for k, v in (a.readiness or {}).items()
            if not k.startswith("llm_") and k != "execution_log"}


out: list[str] = []
out.append("# 消融对照报告：经典模式（固定全跑） vs 计划模式（调度员排计划）")
out.append("")
out.append("用途：证明**调度员没有改变任何结论**——这正是经典模式不能被删掉的首要理由。")
out.append("")
out.append("| 样本 | 结论数(经典/计划) | 结论签名 | 就绪度(经典/计划) | 就绪度字段 | "
           "可信度(经典/计划) | 执行/跳过(计划) | 判定 |")
out.append("|---|---|---|---|---|---|---|---|")

bad = 0
for name, pdf, code, res, real in CASES:
    ur = json.loads(Path(res).read_text(encoding="utf-8")) if res else None
    a_c, _ = run_audit(str(pdf), str(code), ur, force_mock=not real, plan_mode=False)
    a_p, _ = run_audit(str(pdf), str(code), ur, force_mock=not real, plan_mode=True)

    ok_sig = sig(a_c) == sig(a_p)
    ok_rd = rd_core(a_c) == rd_core(a_p)
    ok_conf = ((a_c.coverage or {}).get("confidence_score")
               == (a_p.coverage or {}).get("confidence_score"))
    ok = ok_sig and ok_rd and ok_conf
    if not ok:
        bad += 1

    ex = a_p.execution_log or {}
    out.append(
        f"| {name} | {len(a_c.findings)}/{len(a_p.findings)} | "
        f"{'一致 ✅' if ok_sig else '**不同 ⚠**'} | "
        f"{a_c.readiness.get('total')}/{a_p.readiness.get('total')} | "
        f"{'一致 ✅' if ok_rd else '**不同 ⚠**'} | "
        f"{(a_c.coverage or {}).get('confidence_score')}/"
        f"{(a_p.coverage or {}).get('confidence_score')} | "
        f"{ex.get('ran')}/{ex.get('skipped')} | "
        f"{'一致 ✅' if ok else '**不一致 ⚠**'} |")

out.append("")
out.append(f"**结论：{len(CASES) - bad}/{len(CASES)} 套样本两种模式完全一致**"
           + ("（调度员未改变任何结论）" if bad == 0 else "——有样本不一致，需排查！"))
out.append("")
if bad:
    out.append("## 不一致明细")
    out.append("")
    for name, pdf, code, res, real in CASES:
        ur = json.loads(Path(res).read_text(encoding="utf-8")) if res else None
        a_c, _ = run_audit(str(pdf), str(code), ur, force_mock=not real, plan_mode=False)
        a_p, _ = run_audit(str(pdf), str(code), ur, force_mock=not real, plan_mode=True)
        only_c = [x for x in sig(a_c) if x not in sig(a_p)]
        only_p = [x for x in sig(a_p) if x not in sig(a_c)]
        if only_c or only_p or rd_core(a_c) != rd_core(a_p):
            out.append(f"### {name}")
            out.append("")
            if only_c or only_p:
                out.append(f"- 仅经典模式有：{only_c}")
                out.append(f"- 仅计划模式有：{only_p}")
            # 就绪度**字段级** diff —— 只报"85 vs 87"没法定位，得指到具体字段上
            rc2, rp2 = rd_core(a_c), rd_core(a_p)
            for k in sorted(set(rc2) | set(rp2)):
                if rc2.get(k) != rp2.get(k):
                    out.append(f"- 就绪度字段 `{k}`：经典={rc2.get(k)} vs 计划={rp2.get(k)}")
            out.append("")

OUT = ROOT / "ablation_modes_report.md"
OUT.write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
print(f"\n报告: {OUT}")
if bad:
    raise SystemExit(1)
