"""第二期第二、三批的案例实测: 待确认问题（澄清反问）+ 跨任务记忆。"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import json
import re
from pathlib import Path

from paper2lab import memory
from paper2lab.envfile import load_env
from paper2lab.inquiry import (KIND_LABEL, apply_clarifications, build_questions,
                               summarize)
from paper2lab.pipeline import run_audit
from paper2lab.report import generate_report

load_env()
DEMO = Path("demo")
PDF = str(DEMO / "paper.pdf")
ZIP = str(DEMO / "project.zip")
RES = json.loads((DEMO / "results.json").read_text(encoding="utf-8"))

FLOAT_RE = re.compile(r"\b\d+\.\d+\b")
VALUE_RE = re.compile(r"0[.]1|1e-4|\b32\b")

out: list[str] = []
out.append("=" * 66)
out.append("【第二批 · 澄清反问】demo 受控样例（计划模式）")
out.append("=" * 66)

a, _ = run_audit(PDF, ZIP, RES, vision_max_regions=2, plan_mode=True)
qs = build_questions(a)
s = summarize(qs)
out.append(f"生成待确认问题 {s['total']} 条，构成：{s['by_kind']}")
out.append("")
for i, q in enumerate(qs, 1):
    out.append(f"{i}. [{KIND_LABEL.get(q.kind, q.kind)}] {q.title}")
    out.append(f"   为什么问：{q.basis[:70]}")
    for e in q.evidence[:1]:
        out.append(f"   依据：{e[:90]}")
    out.append(f"   可选答复：{' / '.join(q.suggestions)}")
    out.append(f"   不回答的影响：{q.impact}")
    out.append("")

tgt = qs[0]
rec = apply_clarifications(a, {tgt.qid: "以论文声明为准"})
rep = generate_report(a)
out.append(f"模拟用户答复 1 条 → 人工确认记录 {len(rec)} 条")
out.append(f"报告含「执行计划」章节：{'执行计划' in rep}")
out.append(f"报告含「待确认问题」章节：{'待确认问题' in rep}")
out.append(f"报告含「人工确认记录」章节：{'人工确认记录' in rep}")

out.append("")
out.append("=" * 66)
out.append("【第三批 · 跨任务记忆】")
out.append("=" * 66)

fp = memory.fingerprint(PDF, ZIP)
out.append(f"论文指纹：{fp}")
out.append(f"记忆库条目数：{memory.size()}")
rec1 = memory.recall(fp)
out.append(f"本次是否命中记忆：{bool(rec1)}")
if rec1:
    out.append(f"  本机累计审计 {rec1.get('runs')} 次（含自动化回归），"
               f"上次 {rec1.get('last_seen')}")
    out.append(f"  未解参数（线索）：{rec1.get('unresolved')}")
    out.append(f"  候选页（线索）：{rec1.get('page_hints')}")
    out.append(f"  取值通道（线索）：{rec1.get('where')}")
out.append("")
out.append("给用户看的提示行：")
for ln in memory.hint_lines(fp):
    out.append(f"  · {ln}")
out.append("跨任务统计：")
for ln in memory.cross_task_stats():
    out.append(f"  · {ln}")

out.append("")
out.append("—— 边界自查：记忆里绝不能出现『参数取值』——")
raw = memory.MEM_PATH.read_text(encoding="utf-8") if memory.MEM_PATH.exists() else ""
out.append(f"记忆文件：{memory.MEM_PATH}（{len(raw)} 字符）")
out.append(f"文件中的浮点数（应仅为页码/计数，不含参数取值）：{FLOAT_RE.findall(raw)[:10]}")
out.append(f"是否含明显参数取值（0.1 / 32 / 1e-4）：{bool(VALUE_RE.search(raw))}")

out.append("")
out.append("=" * 66)
out.append("【第二批补充 · 真实论文案例】论文提到、却没取到确定值的参数")
out.append("=" * 66)
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
for _name in ("02_DETR", "03_NeRF"):
    _d = ROOT / _name
    if not (_d / "paper.pdf").exists():
        continue
    a2, _ = run_audit(str(_d / "paper.pdf"), str(_d / "code.zip"), None,
                      vision_max_regions=2, plan_mode=True)
    qs2 = build_questions(a2)
    out.append(f"{_name}：{len(qs2)} 条，构成 {summarize(qs2)['by_kind']}")
    for q in qs2[:6]:
        out.append(f"  · [{KIND_LABEL.get(q.kind, q.kind)}] {q.title}")
        for e in q.evidence[:1]:
            out.append(f"      依据：{e[:96]}")
    out.append("")

out.append("跨任务记忆库现状：")
out.append(f"  条目数（累计审过的论文）：{memory.size()}")
for ln in memory.cross_task_stats():
    out.append(f"  · {ln}")

Path("_p23.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
