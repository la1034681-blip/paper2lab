"""验证计划模式(第二期第一批):
① 材料齐备时, 计划模式结果必须与经典模式一致;
② 缺材料(未提供代码)时, 计划模式应正确跳过, 且结论不应因"跳过"而变坏。
"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import json
from pathlib import Path

from paper2lab.envfile import load_env
from paper2lab.pipeline import run_audit

load_env()
DEMO = Path("demo")
PDF = str(DEMO / "paper.pdf")
ZIP = str(DEMO / "project.zip")
RES = json.loads((DEMO / "results.json").read_text(encoding="utf-8"))
CAP = 2

out: list[str] = []


def sig(a):
    return [(f.param_key, f.status.value, f.risk.value,
             f.paper.raw_value if f.paper else None,
             f.code.raw_value if f.code else None) for f in a.findings]


def readiness_core(a):
    return {k: v for k, v in a.readiness.items() if not k.startswith("llm_")}


def describe(log, indent="   "):
    lines = [f"{indent}模式={log.get('mode')} 跑 {log.get('ran')} 个 / 跳 {log.get('skipped')} 个 "
             f"/ 进度节点 {log.get('nodes_total')} (跳过 {log.get('nodes_skipped')})"]
    for s in log.get("steps", []):
        mark = {"done": "跑", "skipped": "跳", "failed": "失败"}[s["status"]]
        tail = f" —— {s['reason']}" if s["reason"] else ""
        lines.append(f"{indent}  [{mark}] {s['title']} ({s['seconds']:.1f}s){tail}")
    for n in log.get("notes", []):
        lines.append(f"{indent}  · {n}")
    return lines


# ---- ① 材料齐备
out.append("=" * 60)
out.append("① 材料齐备（论文 + 代码 + 实测结果）")
a_c, _ = run_audit(PDF, ZIP, RES, vision_max_regions=CAP, plan_mode=False)
a_p, _ = run_audit(PDF, ZIP, RES, vision_max_regions=CAP, plan_mode=True)
same_sig = sig(a_c) == sig(a_p)
same_rd = readiness_core(a_c) == readiness_core(a_p)
out.append(f"   结论一致: {same_sig}（{len(sig(a_c))} 条） | 就绪度核心字段一致: {same_rd}")
out.append(f"   经典模式就绪度={a_c.readiness.get('score')} / 计划模式={a_p.readiness.get('score')}")
out += describe(a_p.execution_log)

# ---- ② 缺代码包
out.append("")
out.append("=" * 60)
out.append("② 未提供代码包（只给论文 + 实测结果）")
a_nc_c, _ = run_audit(PDF, "", RES, vision_max_regions=CAP, plan_mode=False)
a_nc_p, _ = run_audit(PDF, "", RES, vision_max_regions=CAP, plan_mode=True)
out.append(f"   经典模式: {len(a_nc_c.findings)} 条结论, 就绪度={a_nc_c.readiness.get('score')}")
out.append(f"   计划模式: {len(a_nc_p.findings)} 条结论, 就绪度={a_nc_p.readiness.get('score')}")
out.append(f"   两者结论是否一致: {sig(a_nc_c) == sig(a_nc_p)}")
out += describe(a_nc_p.execution_log)

Path("_plan_verify.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
