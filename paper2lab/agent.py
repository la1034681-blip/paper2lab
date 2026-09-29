"""抽取 Agent（第一期）——只做一件事: 把"论文提到但没取到值"的参数补回来。

为什么只做这一件事: 它是当前系统最薄弱、也最容易被质疑的一环（漏抽）。
把它做成**有界重试闭环**, 既补上短板, 又不触碰确定性内核的风险。

循环形态（每个待补参数独立走一遍阶梯，从便宜到贵）:
    1) text-l1   同句紧邻（"100K iterations"）              —— 零成本
    2) text-l2   同句近距离（"Our 32 × 32 models ... res"） —— 零成本
    3) negation  论文明确"不使用该参数" → 记为 0            —— 零成本
    4) llm       LLM 提议取值 + 程序回原文核对               —— 1 次 LLM 调用
    5) vision    只读"提到该参数的页" + 两次取交集           —— 视觉调用

三道边界（缺一不可）:
    · **预算**: LLM / 视觉调用与总耗时三道上限。LLM 或视觉预算耗尽**只跳过对应那一级**,
      只有总耗时耗尽才整体停止; 所有停止都如实记录;
    · **闸门**: 任何候选都要过 gate()（回原文核对 + 取值在证据中 + 合理性先验 + 形状守卫）;
    · **轨迹**: 每一次尝试都记录"做了什么、结果如何、被拒原因", 可回放、可复核。
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from .models import Evidence, PaperInfo
from .synonyms import PARAM_SYNONYMS
from .tools import (Candidate, ToolResult, gate, tool_llm_propose, tool_negation,
                    tool_text_scan, tool_vision_read, vision_ready)

# 默认预算（都可在 pipeline 里覆盖）。抽取 Agent 只是"补漏助手", 不是第二遍完整审计,
# 因此预算刻意收紧: 一次审计最多 3 次 LLM 调用 / 2 次视觉调用 / 45 秒。
DEFAULT_MAX_LLM_CALLS = 3
DEFAULT_MAX_VISION_CALLS = 2
DEFAULT_MAX_SECONDS = 45.0
MAX_ATTEMPTS_PER_KIND = 5     # 每个参数最多尝试几次（=阶梯长度）


@dataclass
class AgentStep:
    """一次尝试的记录（轨迹的最小单元）。"""
    seq: int
    kind: str
    display: str
    tool: str
    status: str            # accepted | rejected | no_hit | skipped
    value: str = ""
    page: int = 0
    evidence: str = ""
    note: str = ""
    cost: dict = field(default_factory=dict)


@dataclass
class AgentReport:
    """Agent 一次补漏的完整结果。"""
    targets: list = field(default_factory=list)      # 待补参数种类
    filled: dict = field(default_factory=dict)       # kind -> Evidence（通过闸门的）
    hints: list = field(default_factory=list)        # 只作提示的发现(如"提及不使用该参数")
    steps: list = field(default_factory=list)        # AgentStep
    budget: dict = field(default_factory=dict)
    stopped_reason: str = ""
    llm_available: bool = False
    vision_available: bool = False

    def to_dict(self) -> dict:
        return {
            "targets": self.targets,
            "filled": {k: v.raw_value for k, v in self.filled.items()},
            "hints": self.hints,
            "steps": [asdict(s) for s in self.steps],
            "budget": self.budget,
            "stopped_reason": self.stopped_reason,
            "llm_available": self.llm_available,
            "vision_available": self.vision_available,
        }


def find_missing(paper: PaperInfo) -> list[str]:
    """待补目标: 正文提到过、但所有通道都没取到值的参数种类。"""
    seen = set(paper.alias_kinds or [])
    got = set(paper.params_all or {}) | set(paper.image_params or {})
    return sorted(seen - got)


def _to_evidence(cand: Candidate) -> Evidence:
    return Evidence(
        source="paper",
        location=(f"Page {cand.page}" if cand.page else "Page ?")
                 + f" · Agent补漏({cand.source})",
        snippet=cand.evidence_text[:300],
        raw_value=cand.value,
        normalized=None,
        parser=cand.parser,
    )


def fill_missing(paper: PaperInfo, pdf_path: str, *,
                 llm_api_key: str = "",
                 llm_model: str = "",
                 vision_kwargs: Optional[dict] = None,
                 max_llm_calls: int = DEFAULT_MAX_LLM_CALLS,
                 max_vision_calls: int = DEFAULT_MAX_VISION_CALLS,
                 max_seconds: float = DEFAULT_MAX_SECONDS,
                 enabled: bool = True) -> AgentReport:
    """对"提到但没取到值"的参数跑有界重试闭环。返回 AgentReport（不改动 paper）。"""
    targets = find_missing(paper) if enabled else []
    page_texts = list(paper.page_texts or [])
    vision_kwargs = dict(vision_kwargs or {})
    report = AgentReport(
        targets=targets,
        llm_available=bool(llm_api_key),
        vision_available=vision_ready(vision_kwargs),
    )
    if not enabled:
        report.stopped_reason = "Agent 未启用"
        report.budget = _budget(0, 0, 0, 0.0, max_llm_calls, max_vision_calls, max_seconds)
        return report
    if not targets:
        report.stopped_reason = "没有待补目标（参数种类已全覆盖）"
        report.budget = _budget(0, 0, 0, 0.0, max_llm_calls, max_vision_calls, max_seconds)
        return report

    t_start = time.time()
    used = {"llm": 0, "vision": 0}
    seq = 0

    def _stop_reason() -> str:
        """硬停止只认"总耗时"。

        LLM / 视觉预算耗尽**只跳过对应那一级**, 不影响其余级
        （否则前一个参数会挤占后一个参数的机会, 结果还受 targets 排序影响）。
        """
        if time.time() - t_start >= max_seconds:
            return f"总耗时预算已用尽({int(max_seconds)}s)"
        return ""

    for kind in targets:
        display = PARAM_SYNONYMS.get(kind, (kind, []))[0]
        attempts = 0
        for attempt in range(MAX_ATTEMPTS_PER_KIND):
            stop = _stop_reason()
            if stop:
                seq += 1
                report.steps.append(AgentStep(
                    seq=seq, kind=kind, display=display, tool="(停止)",
                    status="skipped", note=stop))
                report.stopped_reason = stop
                break
            attempts += 1
            skipped_for_budget = False

            # ---- 阶梯: 从便宜到贵
            if attempt == 0:
                tr = tool_text_scan(kind, page_texts, level=1)
            elif attempt == 1:
                tr = tool_text_scan(kind, page_texts, level=2)
            elif attempt == 2:
                tr = tool_negation(kind, page_texts)
            elif attempt == 3:
                if used["llm"] >= max_llm_calls:
                    tr = ToolResult(ok=False, note="LLM 调用预算不足, 本级跳过")
                    skipped_for_budget = True
                else:
                    tr = tool_llm_propose(kind, page_texts, llm_api_key, llm_model)
                    used["llm"] += int(tr.cost.get("llm_calls", 0))
            else:
                if used["vision"] >= max_vision_calls:
                    tr = ToolResult(ok=False, note="视觉调用预算不足, 本级跳过")
                    skipped_for_budget = True
                else:
                    tr = tool_vision_read(kind, pdf_path, page_texts, vision_kwargs)
                    used["vision"] += int(tr.cost.get("vision_calls", 0))

            seq += 1
            tool_name = ("text-l1", "text-l2", "negation", "llm", "vision")[attempt]
            if not tr.ok or tr.candidate is None:
                report.steps.append(AgentStep(
                    seq=seq, kind=kind, display=display, tool=tool_name,
                    status="skipped" if skipped_for_budget else "no_hit",
                    note=tr.note, cost=tr.cost))
                continue

            ok, why, hint = gate(tr.candidate, page_texts)
            if tr.candidate.note_only:
                # 只作提示(如"论文提到不使用该参数"): 进轨迹与人工核查, 不进结论
                report.hints.append({
                    "kind": kind, "display": display, "page": tr.candidate.page,
                    "note": tr.candidate.note, "evidence": tr.candidate.evidence_text[:200],
                })
                report.steps.append(AgentStep(
                    seq=seq, kind=kind, display=display, tool=tool_name,
                    status="hinted", page=tr.candidate.page,
                    evidence=tr.candidate.evidence_text[:160],
                    note=tr.candidate.note, cost=tr.cost))
                continue
            if not ok:
                if hint:
                    report.hints.append({
                        "kind": kind, "display": display,
                        "page": tr.candidate.page, "note": hint,
                        "evidence": tr.candidate.evidence_text[:200],
                    })
                report.steps.append(AgentStep(
                    seq=seq, kind=kind, display=display, tool=tool_name,
                    status="rejected", value=tr.candidate.value,
                    page=tr.candidate.page,
                    evidence=tr.candidate.evidence_text[:160],
                    note=why, cost=tr.cost))
                continue

            ev = _to_evidence(tr.candidate)
            report.filled[kind] = ev
            report.steps.append(AgentStep(
                seq=seq, kind=kind, display=display, tool=tool_name,
                status="accepted", value=tr.candidate.value, page=tr.candidate.page,
                evidence=tr.candidate.evidence_text[:160],
                note=tr.candidate.note or why, cost=tr.cost))
            break
        else:
            seq += 1
            report.steps.append(AgentStep(
                seq=seq, kind=kind, display=display, tool="(穷尽)",
                status="no_hit",
                note=f"已走完 {attempts} 级阶梯仍未取到可信取值, 保持「未取到」"
                     "（宁可不报, 也不报可能错的）"))

    report.budget = _budget(len(report.steps), used["llm"], used["vision"],
                            time.time() - t_start,
                            max_llm_calls, max_vision_calls, max_seconds)
    if not report.stopped_reason:
        report.stopped_reason = "已完成全部待补目标"
    return report


def _budget(steps: int, llm: int, vision: int, seconds: float,
            max_llm: int, max_vision: int, max_seconds: float) -> dict:
    return {
        "steps": steps,
        "llm_calls": llm, "max_llm_calls": max_llm,
        "vision_calls": vision, "max_vision_calls": max_vision,
        "seconds": round(seconds, 2), "max_seconds": max_seconds,
    }
