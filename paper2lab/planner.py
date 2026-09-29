"""调度员（第二期第一批）——规则版。

职责: 看着手上的材料, 排一份"本次要跑哪些工具、跳过哪些"的计划,
并给**每条决策留下理由**。

为什么第一版用规则而不是大模型:
- 可解释: 每条跳过都能当场说清依据, 答辩时可逐条复核;
- 零成本、零延迟、可复现(同一份材料永远排出同一份计划);
- 大模型调度可以后续叠加, 但**规则必须留作兜底** —— 否则"调度员乱排"
  会成为新的不可控点。这与第一期"宁可不报, 也不报可能错的值"是同一条原则。

调度员只决定"做不做", 绝不碰"怎么做"; 工具的抽取/比对逻辑一概不参与。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .toolbox import TOOLS, Job

# 论文规模阈值: 决定 Agent 补漏的耗时预算(页数少则收紧, 页数多则放宽)
_SHORT_PAPER_PAGES = 8
_LONG_PAPER_PAGES = 40


@dataclass
class PlanDecision:
    """一条调度决策。"""
    tool: str          # 工具 key
    title: str
    action: str        # run | skip
    reason: str
    # 这条决策**谁定的**（2026-09-28 加）:
    #   rule   —— 材料事实（没代码包就没法扫代码），或核心步骤不许跳
    #   llm    —— AI 的成本判断（允许它决定"值不值得跑"）
    #   veto   —— AI 想这么定，被程序按硬规则否决了（理由里写清怎么否决的）
    source: str = "rule"


@dataclass
class Plan:
    """一次执行的计划。"""
    mode: str = "classic"                 # classic | planned
    order: tuple = ()                     # 要执行的工具 key(按顺序)
    decisions: list = field(default_factory=list)   # [PlanDecision]
    notes: list = field(default_factory=list)       # 面向用户的范围说明
    agent_budget: dict = field(default_factory=dict)  # 调度员可调整 Agent 预算
    planner: str = "rule"                 # rule | llm（谁排的这份计划）

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "planner": self.planner,
            "order": list(self.order),
            "decisions": [{"tool": d.tool, "title": d.title,
                           "action": d.action, "reason": d.reason,
                           "source": d.source}
                          for d in self.decisions],
            "notes": list(self.notes),
            "agent_budget": dict(self.agent_budget),
            "ran": sum(1 for d in self.decisions if d.action == "run"),
            "skipped": sum(1 for d in self.decisions if d.action == "skip"),
        }


def _page_count(pdf_path: str) -> int:
    """只读页数(不解析正文), 用于规模判断。"""
    try:
        import pymupdf
        with pymupdf.open(pdf_path) as doc:
            return doc.page_count
    except Exception:      # noqa: BLE001
        return 0


def make_plan(job: Job, *, plan_mode: bool = True,
              use_llm: bool = False, proposal: Optional[dict] = None) -> Plan:
    """排计划。

    · `plan_mode=False` → 经典全序计划（不看材料，行为与改造前一致）；
    · `plan_mode=True`  → 规则版计划（**默认**，可解释、零成本、可复现）；
    · `use_llm=True`    → 让 AI 先提议一份计划，再由程序按硬规则盖章（见 `_llm_refine`）。
      `proposal` 可直接注入一份提案，用于**不调 API 的确定性测试**。
    """
    base = _rule_plan(job, plan_mode=plan_mode)
    if not (plan_mode and use_llm):
        return base
    return _llm_refine(job, base, proposal=proposal)


def _rule_plan(job: Job, *, plan_mode: bool = True) -> Plan:
    """规则版计划（原 make_plan 的逻辑，逐行搬运，行为不变）。"""
    if not plan_mode:
        return Plan(
            mode="classic",
            planner="rule",
            order=tuple(t.key for t in TOOLS),
            decisions=[PlanDecision(t.key, t.title, "run", "经典模式：按固定顺序执行")
                       for t in TOOLS],
            notes=[f"经典模式：按固定顺序执行全部 {len(TOOLS)} 个工具（与改造前一致）"],
            agent_budget={},
        )

    # ---- 材料勘察（只看"有没有", 不解析内容）
    has_code = bool(job.code_path) and Path(job.code_path).exists()
    has_results = bool(job.user_results)
    # 读图通道是否可用, 必须与图像通道**同一口径**: 页面传了 key, 或者 .env/环境变量里配了。
    # (早期版本只看传入的 key, 导致 CLI 入口明明在 .env 配了 key 却被判"未配置"而白白跳过读图)
    try:
        from .tools import vision_ready
        has_vision = vision_ready(job.vision_kwargs)
    except Exception:      # noqa: BLE001
        has_vision = bool(job.vision_kwargs.get("api_key"))
    has_llm = bool(job.api_key)
    pages = _page_count(job.pdf_path)

    decisions: list = []
    order: list = []
    notes: list = []

    for t in TOOLS:
        if t.core:
            decisions.append(PlanDecision(t.key, t.title, "run", "核心步骤，不可跳过"))
            order.append(t.key)
            continue

        if t.key == "analyze_code" and not has_code:
            decisions.append(PlanDecision(
                t.key, t.title, "skip",
                "未提供代码包 —— 本次只能做论文侧自查，代码侧比对整体缺席"))
            continue

        # 根因追查 / 补丁草案也要读代码: 没有代码包时它们无事可做（不是"跑了没结果", 是"无从追起"）。
        # 注意补丁还依赖根因, 所以这一条一起盖住两站, 避免出现"根因被跳过、补丁却跑了"的错序。
        if t.key in ("rootcause", "patch") and not has_code:
            decisions.append(PlanDecision(
                t.key, t.title, "skip",
                "未提供代码包 —— 追根因要读代码，没有代码就无从追起（补丁草案随之跳过）"))
            continue

        if t.key == "analyze_images":
            if not has_vision:
                decisions.append(PlanDecision(
                    t.key, t.title, "skip",
                    "未配置读图通道 —— 图片/扫描页里的参数不参与本次审计"))
                continue
            if pages and pages <= 2:
                decisions.append(PlanDecision(
                    t.key, t.title, "skip", f"论文仅 {pages} 页，无图区预期"))
                continue

        if t.key == "fill_missing" and not has_llm:
            decisions.append(PlanDecision(
                t.key, t.title, "run",
                "未配置 LLM —— 补漏阶梯仅剩本地三级（同句/近邻/否定式），LLM 级自动跳过"))
            order.append(t.key)
            continue

        if t.key == "llm_analyze" and not has_llm:
            decisions.append(PlanDecision(
                t.key, t.title, "run",
                "未配置 LLM —— 归因改走内置模板（只影响解释文字，不影响结论）"))
            order.append(t.key)
            continue

        decisions.append(PlanDecision(t.key, t.title, "run", "材料齐备，按计划执行"))
        order.append(t.key)

    # ---- Agent 预算按论文规模微调（用户显式给定的值优先, 不覆盖）
    budget = dict(job.agent_budget or {})
    if pages:
        if pages <= _SHORT_PAPER_PAGES and "max_seconds" not in budget:
            budget["max_seconds"] = 30.0
            notes.append(f"论文 {pages} 页（短），Agent 补漏耗时上限收紧到 30s")
        elif pages >= _LONG_PAPER_PAGES and "max_seconds" not in budget:
            budget["max_seconds"] = 90.0
            notes.append(f"论文 {pages} 页（长），Agent 补漏耗时上限放宽到 90s")

    if not has_results:
        notes.append("未提供实测结果 —— 结果一致性维度不在本次评估范围内")
    if not has_code:
        notes.append("未提供代码包 —— 报告中「代码未找到」类结论源于缺材料，不代表论文有问题")
    if not notes:
        notes.append("材料齐备，未触发任何跳过规则")

    # 跨任务记忆命中的线索(只提示, 不影响上面的任何决策)
    for ln in (job.memory_lines or []):
        notes.insert(0, ln)

    return Plan(mode="planned", planner="rule", order=tuple(order), decisions=decisions,
                notes=notes, agent_budget=budget)


# ---------------------------------------------------------------- AI 排计划（可选的第二层）

# 「材料在就必须做」的五件（AI 不可跳过）。
# 划这条线的理由：跳过这五件**不是"值不值得"，而是"还算不算一次审计"** ——
# 不解析论文、不扫代码、不做对齐、不做自检、不出报告，剩下的产出没有意义。
# 其余五件（读图 / Agent 补漏 / AI 归因 / 根因追查 / 补丁草案）是"尽力而为"的增益项，
# 交给 AI 判断值不值得，但**必须在决策表里写明理由**，可复核。
_MUST_RUN = {"parse_paper", "analyze_code", "align", "selfcheck", "report"}


def _llm_prompt(job: Job, base: Plan) -> str:
    facts = {
        "有代码包": bool(job.code_path),
        "有实测结果": bool(job.user_results),
        "可读图": any(d.tool == "analyze_images" and d.action == "run" for d in base.decisions),
        "论文页数": _page_count(job.pdf_path),
    }
    tools = [{"key": t.key, "名称": t.title, "成本": t.cost,
              "需要产物": list(t.needs), "产出": list(t.gives),
              "核心步骤(不可跳过)": t.core}
             for t in TOOLS]
    return (
        "你在给一个『论文↔代码一致性审计』流水线排计划。下面是工具清单与材料情况。\n"
        "请判断**哪些工具本次不值得跑**（只跳「不值」，不要跳「材料没有」——那些已经处理好了）。\n"
        "例如：论文很短且没有代码包时，读图收益低；材料齐备时不该乱跳。\n"
        "拿不准就选 run。**核心步骤不可跳过**。\n\n"
        f"材料: {json.dumps(facts, ensure_ascii=False)}\n"
        f"工具: {json.dumps(tools, ensure_ascii=False)}\n"
        f"当前规则版计划: {json.dumps(base.to_dict()['decisions'], ensure_ascii=False)}\n\n"
        "只输出 JSON，格式："
        '{"decisions":[{"tool":"工具key","action":"run|skip","reason":"一句话理由"}],'
        '"notes":["一句总说明"]}'
    )


def _llm_refine(job: Job, base: Plan, *, proposal: Optional[dict] = None) -> Plan:
    """AI 提议 → **程序盖章**。盖章后的计划才生效。

    三条硬规则（AI 不得违背，违背即被程序否决，并在决策里标 `veto`）:
      1. **核心步骤必须跑**（parse/align/selfcheck/report 这类不参与取舍）；
      2. **材料上不可能的工具必须跳过**（没代码包 → 代码扫描/根因/补丁）；
      3. **依赖级联**：被跳过的工具，其下游（needs 里含它的 gives）一并跳过 ——
         避免出现「根因没跑、补丁却跑了」这种错序。
    其余取舍是**成本判断**，允许 AI 自主（标 `llm`），但必须给理由。

    AI 不可用 / 返回不合法 → **原样回退规则版**，并如实写进 notes（"AI 这次没参与"是要告诉用户的信息）。
    """
    from .llm import ask_json
    note = "已注入提案（测试模式）"
    if proposal is None:
        proposal, note = ask_json(_llm_prompt(job, base), job.api_key,
                                  mode="plan", max_tokens=900,
                                  force_mock=job.force_mock)
    if not isinstance(proposal, dict) or not isinstance(proposal.get("decisions"), list):
        base.notes.insert(0, f"🧠 AI 排计划未生效（{note}）—— 已回退规则版计划")
        return base

    said = {}
    for d in proposal["decisions"]:
        if isinstance(d, dict) and d.get("tool"):
            said[str(d["tool"])] = d

    by_key = {t.key: t for t in TOOLS}
    decisions: list = []
    veto: list[str] = []
    for d in base.decisions:
        tool = by_key[d.tool]
        want = said.get(d.tool) or {}
        want_action = str(want.get("action") or "run").lower()
        want_reason = str(want.get("reason") or "").strip()
        if d.action == "skip":
            # 规则版已经因**材料事实**跳过 —— 这条不是 AI 能改的
            decisions.append(PlanDecision(d.tool, d.title, "skip", d.reason, "rule"))
            if want_action == "run":
                veto.append(f"{d.title}：AI 想跑，但{d.reason}")
            continue
        if tool.core and want_action == "skip":
            decisions.append(PlanDecision(d.tool, d.title, "run", "核心步骤，不可跳过", "veto"))
            veto.append(f"{d.title}：AI 想跳过，但这是核心步骤")
            continue
        if d.tool in _MUST_RUN and want_action == "skip":
            # 有代码包时,"扫代码"不是可选项 —— 跳过它等于放弃整个代码侧
            decisions.append(PlanDecision(
                d.tool, d.title, "run",
                "材料在就必须做：跳过它审计本身就不成立（不参与取舍）", "veto"))
            veto.append(f"{d.title}：AI 想跳过，但材料在就必须做这一步")
            continue
        if want_action == "skip" and want_reason:
            decisions.append(PlanDecision(
                d.tool, d.title, "skip", f"AI 判断：{want_reason}", "llm"))
            continue
        if want_action == "skip":
            # AI 想跳过却**没给理由**。两种沉默都不行 ——
            # 默默跳过是"无凭据的决策"，默默执行却把它记成"AI 未提出跳过"则是**措辞不实**
            # （明明提了）。所以：保持执行 + 如实记下"它提了、但没理由"。
            decisions.append(PlanDecision(
                d.tool, d.title, "run",
                "AI 想跳过但未给理由 —— 无凭据的跳过不予采纳，保持执行", "veto"))
            veto.append(f"{d.title}：AI 想跳过但没给理由")
            continue
        decisions.append(PlanDecision(d.tool, d.title, "run", "AI 未提出跳过（默认执行）", "llm"))

    # ---- 依赖级联：上游没跑，下游就得跟着跳
    # ⚠️ 这里踩过一次坑（2026-09-28，靠自查发现）: 最初按"被跳过的工具 gives 集合"直接判定缺失，
    #    但 `fill_missing` 与 `parse_paper` **都产出 paper** —— 于是 AI 一跳"补漏"，
    #    读图就被误判成"上游产物缺失"跟着跳过，**理由还是错的**。
    #    正确口径：某产物**缺失 ⟺ 它的所有生产者都不跑**（只要还有一个会跑，产物就在）。
    producers: dict = {}
    for t in TOOLS:
        for g in t.gives:
            producers.setdefault(g, set()).add(t.key)
    changed = True
    while changed:
        changed = False
        ran = {d.tool for d in decisions if d.action == "run"}
        missing = {g for g, ps in producers.items() if not (ps & ran)}
        for d in decisions:
            t = by_key[d.tool]
            if d.action == "skip" or t.core or d.tool in _MUST_RUN:
                continue
            lack = set(t.needs) & missing
            if lack:
                d.action = "skip"
                d.source = "veto"
                d.reason = (f"上游产物缺失（需要 {'/'.join(sorted(lack))}）"
                            "—— 本步无从执行，随上游一并跳过")
                veto.append(f"{d.title}：{d.reason}")
                changed = True

    order = tuple(d.tool for d in decisions if d.action == "run")
    notes = list(base.notes)
    n_ai = sum(1 for d in decisions if d.source == "llm" and d.action == "skip")
    if n_ai:
        notes.insert(0, f"🧠 AI 排计划：AI 判定 {n_ai} 个工具本次不值得跑（理由见决策表）")
    else:
        notes.insert(0, "🧠 AI 排计划：AI 未提出额外跳过 —— 本次执行集合与规则版相同")
    if veto:
        notes.insert(1, f"🛡 程序否决了 AI 的 {len(veto)} 条决策（"
                        + "；".join(veto[:3]) + ("…" if len(veto) > 3 else "") + "）")
    notes.append(f"排计划方式：{note}；**漏跑风险由程序兜底**（核心步骤与依赖级联不可被 AI 绕过）")
    return Plan(mode="planned", planner="llm", order=order, decisions=decisions,
                notes=notes, agent_budget=dict(base.agent_budget or {}))
