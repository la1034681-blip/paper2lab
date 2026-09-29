"""澄清反问（第二期第二批）——把"系统说不清的地方"变成"问得出口的问题"。

第一期让系统学会"自己多试几条路"，但有些事系统**永远不该自己猜**：
论文到底写没写某个参数、论文与代码不一致时以谁为准、读图推断的值对不对。
这些问题的答案**只在你手里** —— 那就直接问。

三条设计原则:
1. **只问"用户能答、且答了对结论有实质帮助"的问题**: 不把系统自己能判断的事推给用户;
2. **每条问题都带依据**(哪一页、哪个文件、哪条证据), 用户不需要回去翻论文;
3. **系统从不替用户填答案**: 用户不答, 系统就保持"未取到/待核实", 绝不猜测。

用户答复只作为**人工确认记录**附进报告, 不自动改写任何结论 ——
避免出现"系统拿用户的随口一答当成事实"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .models import AuditResult, Risk, Status
from .synonyms import PARAM_SYNONYMS

KIND_LABEL = {
    "conflict": "结论待定",
    "missing_value": "缺值",
    "image_inferred": "待核对",
    "parse_failure": "解析失败",
}


@dataclass
class Question:
    """一条待用户确认的问题。"""
    qid: str
    kind: str
    priority: int              # 0 最高
    title: str
    basis: str                 # 为什么要问
    evidence: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)   # 常见答复, 供界面做快捷选项
    impact: str = ""           # 不回答会怎样

    def to_dict(self) -> dict:
        return {
            "qid": self.qid, "kind": self.kind, "priority": self.priority,
            "label": KIND_LABEL.get(self.kind, self.kind),
            "title": self.title, "basis": self.basis,
            "evidence": list(self.evidence),
            "suggestions": list(self.suggestions),
            "impact": self.impact,
        }


def _disp(key: str) -> str:
    return PARAM_SYNONYMS.get(key, (key, []))[0]


def build_questions(audit: AuditResult, *, max_conflicts: int = 5,
                    max_parse_failures: int = 5) -> list[Question]:
    """从审计结果里挑出"值得打扰用户"的问题。"""
    qs: list[Question] = []
    paper = audit.paper

    # ---- ① 论文与代码高风险不一致: 哪个才是实际用的, 只有用户知道
    conflicted = [f for f in audit.findings
                  if f.status == Status.INCONSISTENT and f.risk == Risk.HIGH]
    for f in conflicted[:max_conflicts]:
        ev = []
        if f.paper:
            ev.append(f"论文：{f.paper.raw_value}（{f.paper.location}）")
        if f.code:
            ev.append(f"代码：{f.code.raw_value}（{f.code.location}）")
        qs.append(Question(
            qid=f"conflict::{f.param_key}", kind="conflict", priority=0,
            title=f"『{f.display_name}』论文与代码不一致，以哪个为准？",
            basis="论文声明的值与代码实现的值不相等，系统**无法判断**哪个是实际使用的。",
            evidence=ev,
            suggestions=["以论文声明为准", "以代码实现为准", "两者都真实（不同实验设置）"],
            impact="该不一致的最终定性悬置，报告中保持「不一致」状态。"))

    # ---- ② 论文提到、但所有通道都没能取到确定值
    seen = set(paper.alias_kinds or [])
    got = set(paper.params_all or {}) | set(paper.image_params or {})
    agent_hints: dict = {}
    for h in (paper.agent_meta or {}).get("hints") or []:
        agent_hints.setdefault(h.get("kind"), []).append(h)
    for k in sorted(seen - got):
        hints = agent_hints.get(k) or []
        ev = [f"Page {h.get('page')}：{h.get('note')}" for h in hints[:2] if h.get("note")]
        qs.append(Question(
            qid=f"missing::{k}", kind="missing_value", priority=1,
            title=f"『{_disp(k)}』没能取到确定值，能否补充？",
            basis="论文正文里出现过该参数，但正文/表格/读图/Agent 补漏四条通道"
                  "都没能取到**可回原文核对**的确定值。系统宁可不报，也不猜一个值。",
            evidence=ev,
            suggestions=["论文确实没给具体取值", "取值在附录/补充材料里，稍后提供",
                         "以代码里的实现为准"],
            impact="该参数在报告中保持「未取到」，与之相关的一致性无法评估。"))

    # ---- ③ 读图推断的值: 图像无法用文本层验证, 必须人工核一眼
    # 注意: image_params 的值是**列表**(同一参数可能在多个区域被读到), 不是单个 Evidence
    for k, evs in (paper.image_params or {}).items():
        _evs = evs if isinstance(evs, list) else [evs]
        qs.append(Question(
            qid=f"vision::{k}", kind="image_inferred", priority=2,
            title=f"『{_disp(k)}』由读图推断，请核对原图",
            basis="该值来自视觉模型读图（两次独立读取取交集），图像内容无法用文本层验证。",
            evidence=[f"{getattr(e, 'location', '?')}："
                      f"{str(getattr(e, 'snippet', ''))[:110]} → "
                      f"{getattr(e, 'raw_value', '')}" for e in _evs[:2]],
            suggestions=["原图确认无误", "原图数值不同，需要修正", "该图与本次审计无关"],
            impact="读图结论标记为 Inferred，不参与就绪度评分。"))

    # ---- ④ 解析失败的文件: 失败示众, 问它是否影响结论
    for f in (audit.code.failed_files or [])[:max_parse_failures]:
        qs.append(Question(
            qid=f"parse::{f.get('file')}", kind="parse_failure", priority=3,
            title=f"文件解析失败：{f.get('file')}",
            basis="该文件未能解析，其内容**未参与**本次审计（系统不静默跳过）。",
            evidence=[f"{f.get('reason')}（{f.get('lines')} 行）"],
            suggestions=["不影响，可忽略", "该文件包含关键配置，需要人工检查"],
            impact="代码侧结论可能不完整。"))

    qs.sort(key=lambda q: (q.priority, q.qid))
    return qs


def summarize(questions: list) -> dict:
    """给界面/报告用的汇总。"""
    by_kind: dict = {}
    for q in questions:
        by_kind[q.kind] = by_kind.get(q.kind, 0) + 1
    return {
        "total": len(questions),
        "by_kind": by_kind,
        "labels": {k: KIND_LABEL.get(k, k) for k in by_kind},
    }


def apply_clarifications(audit: AuditResult, answers: Optional[dict]) -> list:
    """把用户的答复记成"人工确认记录"——**不改变任何结论**。

    返回记录列表; 同时写回 `audit.clarifications`。
    """
    rec: list = []
    for q in build_questions(audit):
        ans = ((answers or {}).get(q.qid) or "").strip()
        if not ans:
            continue
        rec.append({
            "qid": q.qid,
            "kind": q.kind,
            "label": KIND_LABEL.get(q.kind, q.kind),
            "question": q.title,
            "answer": ans,
            "time": f"{datetime.now():%Y-%m-%d %H:%M}",
        })
    audit.clarifications = rec
    return rec
