"""AI 参与决策的两条通道：**提议在 AI、盖章在程序**。

用法: .venv\\Scripts\\python.exe verify_llm_planner.py        （不调 API，全部用注入的提案）

覆盖:
  ① AI 排计划 —— 注入一份"乱来"的提案，程序必须按硬规则否决（核心步骤不许跳、
     有代码包就必须扫、依赖级联不许漏跑），其余"成本判断"才允许 AI 说了算；
  ② AI 提名补丁目标 —— 提名**不在已抽到候选里**时盖章不过；提名合法时走**同一套机械闸门**
     产出 `proposed-llm`（需人工确认），且理由里必须写明"程序没验证它属于哪套配置"；
  ③ 无 AI 时两条通道都**回退确定性路径**，并如实说明"AI 这次没参与"。

为什么用注入而不是真调 API: 要断言的是**程序盖章的正确性**（确定性），
不是模型今天答得怎么样。真调 API 的波动会掩盖盖章是否生效。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.planner import make_plan          # noqa: E402
from paper2lab.toolbox import TOOLS, Job         # noqa: E402

OLD = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
fails: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}")
    if not ok:
        fails.append(label)


def dmap(plan) -> dict:
    return {d.tool: d for d in plan.decisions}


print("① AI 排计划：程序盖章（硬规则不可被 AI 绕过）")
# 这份 Job 刻意配上一个假读图 key: 否则规则版本来就会跳过读图（无读图通道），
# 那样就测不出"AI 的成本判断被采纳"这一条了。
JOB = Job(pdf_path=str(OLD / "01_DDPM/paper.pdf"), code_path=str(OLD / "01_DDPM/code.zip"),
          api_key="", force_mock=True, vision_kwargs={"api_key": "fake-for-planning"})

# 一份"乱来"的提案：跳核心步骤、跳代码扫描（但有代码包）、跳根因（补丁却没跳）、跳归因
BOGUS = {"decisions": [
    {"tool": "parse_paper", "action": "skip", "reason": "省点时间"},
    {"tool": "analyze_code", "action": "skip", "reason": "不想扫"},
    {"tool": "llm_analyze", "action": "skip", "reason": "解释文字可以省掉"},
    {"tool": "rootcause", "action": "skip", "reason": "结论够清楚了"},
    {"tool": "patch", "action": "run", "reason": ""},
], "notes": ["注入用例"]}
p = make_plan(JOB, plan_mode=True, use_llm=True, proposal=BOGUS)
d = dmap(p)
print(f"     排计划方式={p.planner} 执行={p.to_dict()['ran']} 跳过={p.to_dict()['skipped']}")
for x in p.decisions:
    print(f"       {x.action:4} {x.source:5} {x.tool:14} {x.reason[:52]}")
check(p.planner == "llm", "确认走的是 AI 排计划通道")
check(d["parse_paper"].action == "run" and d["parse_paper"].source == "veto",
      "AI 想跳论文解析 -> 被程序否决（核心步骤）")
check(d["analyze_code"].action == "run" and d["analyze_code"].source == "veto",
      "AI 想跳代码扫描 -> 被程序否决（有代码包就必须扫）")
check(d["llm_analyze"].action == "skip" and d["llm_analyze"].source == "llm",
      "AI 跳归因 -> 采纳为「AI 判断」（这是允许它决定的成本项）")
check(d["patch"].action == "skip" and d["patch"].source == "veto",
      "AI 跳了根因却想跑补丁 -> 被依赖级联挡住")
check(any("程序否决" in n for n in p.notes), "否决情况写进了 notes（可复核）")

# 产物"多生产者"的坑：`fill_missing` 与 `parse_paper` 都产出 paper。
# AI 跳过补漏时，**读图不该被误判成"上游缺失"**（paper 仍在）。
SHARED = {"decisions": [{"tool": "fill_missing", "action": "skip",
                         "reason": "内核已抽全，补漏收益低"}], "notes": []}
p_shared = make_plan(JOB, plan_mode=True, use_llm=True, proposal=SHARED)
d_shared = dmap(p_shared)
check(d_shared["fill_missing"].action == "skip" and d_shared["fill_missing"].source == "llm",
      "AI 跳过「Agent 补漏」-> 采纳")
check(d_shared["analyze_images"].action == "run",
      "补漏被跳过**不会**让读图跟着跳（paper 由论文解析产出，产物并未缺失）")

# 合理提案：AI 认为"论文太短、读图没收益" —— 应被采纳
OK_PROP = {"decisions": [{"tool": "analyze_images", "action": "skip",
                          "reason": "论文 8 页且正文已给全参数，读图收益低"}],
           "notes": []}
p2 = make_plan(JOB, plan_mode=True, use_llm=True, proposal=OK_PROP)
d2 = dmap(p2)
check(d2["analyze_images"].source == "llm" and d2["analyze_images"].action == "skip",
      "AI 的成本判断（短论文不值得读图）-> 采纳")

# AI 想跳过却**没给理由**：不许默默跳过（无凭据的决策），也不许记成"AI 未提出跳过"
# —— 那是措辞不实（明明提了）。正确做法：保持执行 + 如实记下"提了、但没理由"。
NO_REASON = {"decisions": [{"tool": "analyze_images", "action": "skip", "reason": ""}],
             "notes": []}
p_nr = make_plan(JOB, plan_mode=True, use_llm=True, proposal=NO_REASON)
d_nr = dmap(p_nr)
check(d_nr["analyze_images"].action == "run" and d_nr["analyze_images"].source == "veto",
      "AI 想跳过但没给理由 -> 保持执行，且记为程序否决")
check("未给理由" in d_nr["analyze_images"].reason,
      "决策表措辞准确：它是「提了但没理由」，不是「未提出跳过」")

print("")
print("② 无 AI：两条通道都必须回退确定性路径，并如实说明")
p3 = make_plan(JOB, plan_mode=True, use_llm=True)      # 无 key + force_mock
check(any("AI 排计划未生效" in n for n in p3.notes), "排计划回退规则版，且写明原因")
# 回退必须是**逐条等价**，不只是"看起来像规则版"
p4 = make_plan(JOB, plan_mode=True, use_llm=False)
_sig = lambda pl: [(d.tool, d.action, d.source) for d in pl.decisions]   # noqa: E731
check(_sig(p3) == _sig(p4), "回退后的计划与规则版**逐条一致**（工具/动作/来源都相同）")
check(p4.planner == "rule", "默认（use_llm=False）就是规则版，行为与从前一致")

print("")
print("③ AI 提名补丁目标：只在「值可信、缺的只是选哪个」时启用，且必须过盖章清单")
from paper2lab.pipeline import run_audit          # noqa: E402
from paper2lab.patch import propose_patches       # noqa: E402
from paper2lab.rootcause import trace_findings    # noqa: E402

DETR_PDF = OLD / "02_DETR/paper.pdf"
DETR_ZIP = OLD / "02_DETR/code.zip"
_detr_res = OLD / "02_DETR/results.json"
audit, _ = run_audit(str(DETR_PDF), str(DETR_ZIP),
                     (json.loads(_detr_res.read_text(encoding="utf-8"))
                      if _detr_res.exists() else None),
                     force_mock=True, plan_mode=True)
traces = trace_findings(audit, max_items=8)
rule_only = propose_patches(audit, traces, str(DETR_ZIP), max_items=8)
print(f"     确定性通道：给方案 {sum(1 for x in rule_only if x.is_proposed)} / "
      f"拒绝 {sum(1 for x in rule_only if not x.is_proposed)}；"
      f"拒绝类型={[x.refuse_kind for x in rule_only if not x.is_proposed]}")
check(all(x.status == "proposed" for x in rule_only if x.is_proposed),
      "确定性通道给方案的那几条，status 仍是 proposed（没被 AI 通道改写）")

elig = next((x.param_key for x in rule_only
             if not x.is_proposed and x.refuse_kind in ("multi_value", "no_rootcause")), None)
if elig is None:
    print("     （本例没有可交给 AI 复判的拒绝类型，跳过 ③）")
else:
    print(f"     可交给 AI 复判的参数：{elig}（拒绝类型={[x.refuse_kind for x in rule_only if x.param_key == elig][0]}）")
    t_obj = next((t for t in traces if t.param_key == elig), None)
    pans = list((getattr(audit.paper, "params_all", {}) or {}).get(elig) or [])
    c0 = (t_obj.candidates or [None])[0] if t_obj else None

    # (a) 越界提名：报一个不存在的论文值 -> 盖章不过
    forged = {elig: {"ok": True, "paper_value": "99999",
                     "code_loc": (f"{c0.file}:{c0.line}" if c0 else "main.py:1"),
                     "why": "测试：越界提名"}}
    got = next(x for x in propose_patches(audit, traces, str(DETR_ZIP), max_items=8,
                                          proposals=forged) if x.param_key == elig)
    print(f"     (a) 越界提名 -> status={got.status} kind={got.refuse_kind}｜{got.refuse_reason[:70]}")
    check(not got.is_proposed, "(a) 提名的值不在已抽候选里 -> 盖章不过，仍不给补丁")

    # (b) 合法提名：值取自论文候选、位置取自根因候选点 -> 应产出 proposed-llm（仍需人工确认）
    if pans and c0 is not None:
        good = {elig: {"ok": True, "paper_value": str(pans[0].raw_value),
                       "code_loc": f"{c0.file}:{c0.line}",
                       "why": "测试：合法提名（取自候选）"}}
        g2 = next(x for x in propose_patches(audit, traces, str(DETR_ZIP), max_items=8,
                                             proposals=good) if x.param_key == elig)
        print(f"     (b) 合法提名 -> status={g2.status} target={g2.target} stamps={len(g2.stamps)}")
        check(g2.source == "llm", "(b) 确实走了 AI 提名通道")
        if g2.is_proposed:
            check(g2.status == "proposed-llm" and g2.needs_human,
                  "(b) 产出标为 proposed-llm 且 needs_human（采纳前必须人工确认）")
            check(bool(g2.stamps) and "没有" in g2.rationale,
                  "(b) 盖章清单非空，且理由里写明「程序没有验证它属于哪套配置」")
        else:
            check("机械闸门" in g2.refuse_reason,
                  "(b) 若被拒，必须是**盖章清单里某一条**不过（而非原判定）")
    else:
        print("     （缺候选，跳过 (b) 合法提名用例）")

print("")
if fails:
    print(f"未通过 {len(fails)} 项：")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("全部通过（AI 只提议、程序盖章；两条通道都能被程序挡回）")
