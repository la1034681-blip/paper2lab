"""全流程演示：把第一期 / 第二期 / 第三期做出来的能力全部走一遍。

用法:
    python demo_full_flow.py          # 快档（默认）: 2 套代表样本, 供回归使用
    python demo_full_flow.py --all    # 全量: 8 套样本（五套真实论文 + 三套中文集）

快档选样理由（回归必须够快，否则端到端那项会被拖到十几分钟）:
  · 05_ViT   —— 结论最多 + 带实测结果（唯一能做结果核验与 Agent 补回的样本）
  · 01_DDPM  —— 图表区域最多（最能体现读图调度）

每个案例依次展示:
  ① 执行计划(2.1)   ② 分片调度(2.4)   ③ 跨任务记忆(2.3)   ④ 抽取 Agent(1)
  ⑤ 审计结论        ⑥ 待确认问题(2.2)  ⑦ 根因追查(3.2)     ⑧ 补丁草案(3.3)  ⑨ 复现清单(3.1)

输出: Paper2Lab测试集/full_flow_demo.md（--all 时为 full_flow_all_cases.md）
      + 每个案例的完整审计报告与 REPRO 清单
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import sys
import time
from pathlib import Path

from paper2lab import memory
from paper2lab.envfile import load_env
from paper2lab.inquiry import KIND_LABEL, build_questions, summarize
from paper2lab.pipeline import run_audit
from paper2lab.repro import build_repro_pack

load_env()

HERE = Path(__file__).resolve().parent.parent
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")

# (名称, pdf, code, results, 走真实API?, 入选理由)
_REAL = [
    ("01_DDPM", ROOT / "01_DDPM/paper.pdf", ROOT / "01_DDPM/code.zip", None, True,
     "图表区域最多 —— 最能体现读图调度"),
    ("02_DETR", ROOT / "02_DETR/paper.pdf", ROOT / "02_DETR/code.zip", None, True,
     "跨论文参数最多 —— 根因追查最吃力（多个赋值点）"),
    ("03_NeRF", ROOT / "03_NeRF/paper.pdf", ROOT / "03_NeRF/code.zip", None, True,
     "只有收敛范围没给设定值 —— 最能体现「宁可不报」"),
    ("04_PointNet", ROOT / "04_PointNet/paper.pdf", ROOT / "04_PointNet/code.zip", None,
     True, "含 keep ratio 语义陷阱 —— 最能体现闸门"),
    ("05_ViT", ROOT / "05_ViT/paper.pdf", ROOT / "05_ViT/code.zip",
     ROOT / "05_ViT/results.json", True,
     "结论最多 + 带实测结果 —— 唯一能做结果核验与 Agent 补回的样本"),
]
_CN = [
    ("demo", HERE / "demo/paper.pdf", HERE / "demo/project.zip", None, False,
     "受控中文样例（埋了 3 个已知问题）"),
    ("D题", HERE / "demo/D题论文.pdf", HERE / "demo/D题代码.zip", None, False,
     "中文数学建模论文 —— 正文含图号/章节号干扰"),
    ("E题", Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"),
     Path(r"C:\Users\lijiahui\Desktop\E题作答.zip"), None, False,
     "中文论文 + 独立代码包"),
]

ALL = "--all" in sys.argv
if ALL:
    CASES = _REAL + _CN
    OUT_NAME = "full_flow_all_cases.md"
    TITLE = "全流程演示（全量 8 套）"
else:
    CASES = [c for c in _REAL if c[0] in ("01_DDPM", "05_ViT")]
    OUT_NAME = "full_flow_demo.md"
    TITLE = "全流程端到端演示（快档 2 套，供回归使用）"

out: list[str] = [f"# {TITLE}", ""]
summary: list[dict] = []

for name, pdf, code, results_path, real_api, why in CASES:
    pdf, code = Path(pdf), Path(code)
    if not pdf.exists() or not code.exists():
        out += [f"（跳过 {name}：材料缺失 pdf={pdf.exists()} code={code.exists()}）", ""]
        continue

    ur = None
    if results_path is not None and Path(results_path).exists():
        ur = json.loads(Path(results_path).read_text(encoding="utf-8"))

    out += ["=" * 76,
            f"■ 样本 {name} —— {why}",
            f"  通道: {'真实 LLM / 真实视觉' if real_api else '确定性 mock（可复现）'}",
            "=" * 76]

    t0 = time.time()
    try:
        audit, report = run_audit(str(pdf), str(code), ur,
                                  force_mock=not real_api, plan_mode=True)
    except Exception as e:  # noqa: BLE001
        out += [f"  ✗ 审计失败: {type(e).__name__}: {e}", ""]
        summary.append({"name": name, "err": f"{type(e).__name__}: {e}"})
        continue
    dt = time.time() - t0

    cov = audit.coverage or {}
    sc = audit.selfcheck or {}

    # ---------- ① 执行计划（第二期第一批）----------
    ex = audit.execution_log or {}
    out.append(f"【① 执行计划】模式={ex.get('mode')} ｜ 执行 {ex.get('ran')} / "
               f"跳过 {ex.get('skipped')} ｜ 全流程 {dt:.1f}s")
    for s in ex.get("steps", []):
        mark = {"done": "跑", "skipped": "跳", "failed": "失败"}.get(s["status"], "?")
        tail = f" —— {s['reason']}" if s["reason"] else ""
        out.append(f"    [{mark}] {s['title']}（{s['seconds']}s）{tail}")

    # ---------- ② 分片调度（第二期第四批）----------
    sh = (audit.readiness or {}).get("llm_shards") or {}
    if sh and sh.get("total"):
        out.append(f"【② AI 归因调度】{sh.get('mode')}（{sh.get('workers')} 路）｜ "
                   f"{sh.get('total')} 条 ｜ {sh.get('seconds')}s ｜ 失败 {sh.get('failed')}")
    im = cov.get("image") or {}
    vsh = im.get("shard") or {}
    if vsh and vsh.get("total"):
        out.append(f"【② 读图调度】{vsh.get('mode')}（{vsh.get('workers')} 路）｜ "
                   f"{vsh.get('total')} 个区域 ｜ {vsh.get('seconds')}s ｜ 失败 {vsh.get('failed')}")
    if im.get("candidates"):
        out.append(f"    读图覆盖: 候选 {im.get('candidates')} → 实读 {im.get('regions_read')}"
                   f" ｜ 采信 {im.get('kept')} ｜ 丢弃 {im.get('dropped')}")
    for n in (im.get("notes") or [])[:2]:
        out.append(f"    · {str(n)[:150]}")

    # ---------- ③ 跨任务记忆（第二期第三批）----------
    fp = memory.fingerprint(str(pdf), str(code))
    hlines = memory.hint_lines(fp)
    out.append(f"【③ 跨任务记忆】论文指纹 {fp} ｜ 记忆库 {memory.size()} 条明细")
    for ln in hlines:
        out.append(f"    · {ln}")
    if not hlines:
        out.append("    · （首次见到这篇论文，尚无历史线索）")

    # ---------- ④ 抽取 Agent（第一期）----------
    am = audit.paper.agent_meta or {}
    filled = am.get("filled") or {}
    steps = am.get("steps") or []
    out.append(f"【④ 抽取 Agent】待补 {len(am.get('targets') or [])} 类 ｜ "
               f"补回 {len(filled)} 类 ｜ 尝试 {len(steps)} 步 ｜ "
               f"提示 {len(am.get('hints') or [])} 条")
    for k, v in filled.items():
        out.append(f"    ✅ 补回 {k} = {v}")
    for s in steps:
        st = s.get("status")
        if st == "rejected":
            out.append(f"    🛡 挡下 {s.get('tool')} 提议 {s.get('value')} —— "
                       f"{str(s.get('note'))[:66]}")
        elif st == "hinted":
            out.append(f"    💬 仅提示 {s.get('tool')}（第 {s.get('page')} 页）—— "
                       f"{str(s.get('note'))[:66]}")
    if not steps:
        out.append("    · （无待补目标：决定性内核已抽全）")

    # ---------- ⑤ 审计结论 ----------
    issues = [f for f in audit.findings if f.status.value != "consistent"]
    _tot = audit.readiness.get("total")
    out.append(f"【⑤ 审计结论】共 {len(audit.findings)} 条（风险 {len(issues)} 条）｜ "
               f"就绪度 {'—' if _tot is None else _tot}/100 ｜ "
               f"本次审计可信度 {cov.get('confidence_level')}"
               f"（{cov.get('confidence_score')}/100）")
    _unv = (audit.readiness or {}).get("unverified") or {}
    if _unv:
        out.append("    未核验维度（不计入总分）："
                   + "；".join(f"{k} —— {v}" for k, v in _unv.items()))
    out.append(f"    证据自证 {sc.get('passed')}/{sc.get('checked')} ｜ "
               f"解析覆盖 论文 {cov.get('pages_covered')}/{cov.get('pages_total')} 页、"
               f"代码 {cov.get('code_ok')}/{cov.get('code_files')} 文件 ｜ "
               f"拒收 {len(cov.get('rejected') or [])} ｜ 不支持 {len(cov.get('unsupported') or [])}")
    for f in issues[:6]:
        out.append(f"    · [{f.risk.value}] {f.display_name} —— {f.status.value}")
    if len(issues) > 6:
        out.append(f"    …… 其余 {len(issues) - 6} 条见完整报告")

    # ---------- ⑥ 待确认问题（第二期第二批）----------
    qs = build_questions(audit)
    out.append(f"【⑥ 待确认问题】{len(qs)} 条 ｜ 构成 {summarize(qs)['by_kind']}")
    for q in qs[:4]:
        out.append(f"    ? [{KIND_LABEL.get(q.kind, q.kind)}] {q.title}")
    if len(qs) > 4:
        out.append(f"    …… 其余 {len(qs) - 4} 条见报告")

    # ---------- ⑦ 根因追查 ⑧ 补丁草案（第三期 3.2 / 3.3）----------
    # 这两件事现在由**流水线自己的两站**产出（toolbox 的 rootcause / patch），
    # 本脚本只负责展示 —— 早先每个调用方各拼一遍，已经在三处漂移。
    traces = list(getattr(audit, "rootcause", None) or [])
    locatable = [t for t in traces if t.confidence in ("high", "medium")]
    out.append(f"【⑦ 根因追查】处理 {len(traces)} 项 ｜ 可定位 {len(locatable)} 项 ｜ "
               f"无法定位 {len(traces) - len(locatable)} 项")
    for t in traces[:5]:
        if t.confidence in ("high", "medium"):
            out.append(f"    ↗ {t.display}: 最终生效 {t.verdict} @ {t.verdict_loc}"
                       f"（置信 {t.confidence}，{len(t.candidates)} 处候选）")
        else:
            out.append(f"    ⚠ {t.display}: 无法定位 —— {t.reason[:60]}")
    if len(traces) > 5:
        out.append(f"    …… 其余 {len(traces) - 5} 项见明细")

    patches = list(getattr(audit, "patches", None) or [])
    proposed = [p for p in patches if p.is_proposed]
    refused = [p for p in patches if not p.is_proposed]
    out.append(f"【⑧ 补丁草案】给方案 {len(proposed)} 条 ｜ 拒绝 {len(refused)} 条 "
               f"（只改值、不落盘）")
    for p in proposed[:4]:
        out.append(f"    ✅ {p.display} @ {p.target}")
        out.append(f"         {p.before.strip()[:78]}")
        out.append(f"      →  {p.after.strip()[:78]}")
    for p in refused[:4]:
        out.append(f"    ⛔ {p.display} —— {str(p.refuse_reason)[:64]}")

    # ---------- ⑨ 复现清单（第三期 3.1）----------
    pack = build_repro_pack(audit)
    envp = pack.env or {}
    out.append(f"【⑨ 复现清单】超参对照 {len(pack.params)} 行 ｜ "
               f"Python 依赖 {len(envp.get('python_deps') or {})} 项 ｜ "
               f"数据准备 {len(pack.data_notes)} 条 ｜ 待确认 {len(pack.must_confirm)} 条 ｜ "
               f"已知风险 {len(pack.risks)} 条")
    (ROOT / f"REPRO_{name}.md").write_text(pack.to_markdown(), encoding="utf-8")

    out.append("")
    (ROOT / f"full_flow_{name}.md").write_text(report, encoding="utf-8")

    summary.append({
        "name": name, "sec": round(dt, 1),
        "findings": len(audit.findings), "issues": len(issues),
        "readiness": audit.readiness.get("total"),
        "conf": cov.get("confidence_score"),
        "filled": len(filled), "blocked": sum(1 for s in steps if s.get("status") == "rejected"),
        "questions": len(qs), "traced": len(locatable),
        "patch": len(proposed), "patch_ref": len(refused),
    })

# ================= 汇总 =================
out += ["=" * 76, f"■ 汇总（{len(summary)} 套案例）", "=" * 76, ""]
out += ["| 样本 | 耗时 | 结论 | 风险 | 就绪度 | 可信度 | Agent补回 | 挡下 | 待确认 | "
        "根因可定位 | 补丁给/拒 |",
        "|---|---|---|---|---|---|---|---|---|---|---|"]
for s in summary:
    if "err" in s:
        out.append(f"| {s['name']} | — | ✗ {s['err'][:30]} | | | | | | | | |")
        continue
    out.append(
        f"| {s['name']} | {s['sec']}s | {s['findings']} | {s['issues']} | {s['readiness']} | "
        f"{s['conf']} | {s['filled']} | {s['blocked']} | {s['questions']} | "
        f"{s['traced']} | {s['patch']}/{s['patch_ref']} |")

out += ["", "## 判读要点", "",
        "- **可信度**：论文内容覆盖率打分（读图通道启用后大幅提升）；",
        "- **Agent 补回 / 挡下**：补回 = 论文写了但内核没抽到、被 Agent 找回；"
        "挡下 = Agent 提议了但被闸门判定不可信（宁可不报）；",
        "- **根因可定位**：代码里有唯一/明显生效点时才能定位，定位不了会明说「无法定位」，绝不猜；",
        "- **补丁给/拒**：给方案 = 能安全改值；拒绝 = 语义不当（如实现选择）或无法定位。",
        ""]

(ROOT / OUT_NAME).write_text("\n".join(out), encoding="utf-8")
print("done ->", ROOT / OUT_NAME)
