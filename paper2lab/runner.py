"""执行器（第二期第一批）——按计划调用工具, 并如实记录每一步的去向。

记录三件事: 执行了什么、跳过了什么、为什么跳过。这是界面「执行计划」面板的数据源。

两个硬约束:
1. **跳过不等于缺产物**: 工具被跳过时, 由 `_fill_empty` 补一份语义正确的空产物,
   保证后面的工具不会因为"东西不在"而崩, 也不会凭空多出一条误导性结论;
2. **失败即中止**: 工具抛异常时如实记录后向上抛出, 与改造前 run_audit 的行为一致,
   不做静默吞掉。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .models import CodeInfo
from .planner import make_plan
from .toolbox import STEPS, TOOLS, Job


@dataclass
class StepRecord:
    key: str
    title: str
    status: str            # done | skipped | failed
    reason: str = ""
    seconds: float = 0.0
    checkpoints: tuple = ()


@dataclass
class ExecutionLog:
    """一次执行的完整记录。"""
    mode: str = "classic"
    steps: list = field(default_factory=list)     # [StepRecord]
    notes: list = field(default_factory=list)     # 面向用户的范围说明
    plan: dict = field(default_factory=dict)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "steps": [{"key": s.key, "title": s.title, "status": s.status,
                       "reason": s.reason, "seconds": round(s.seconds, 2),
                       "checkpoints": list(s.checkpoints)} for s in self.steps],
            "notes": list(self.notes),
            "plan": dict(self.plan),
            "seconds": round(self.seconds, 2),
            "ran": sum(1 for s in self.steps if s.status == "done"),
            "skipped": sum(1 for s in self.steps if s.status == "skipped"),
            "failed": sum(1 for s in self.steps if s.status == "failed"),
            "nodes_total": len(STEPS),
            "nodes_skipped": sum(len(s.checkpoints) for s in self.steps
                                 if s.status == "skipped"),
        }


def _fill_empty(job: Job, tool_key: str) -> None:
    """被跳过的工具留下的空产物 —— 语义要与"跑了但没结果"一致。"""
    if tool_key == "analyze_code":
        if job.code is None:
            job.code = CodeInfo()
    elif tool_key == "rootcause":
        # 被跳过 = 没有代码包。空列表的语义正是"没有可追的项", 不是"追了没追到"。
        job.rootcause = []
        if job.audit is not None:
            job.audit.rootcause = []
    elif tool_key == "patch":
        job.patches = []
        if job.audit is not None:
            job.audit.patches = []
    elif tool_key == "analyze_images":
        if job.paper is not None:
            job.paper.image_params = {}
            job.paper.image_meta = {
                "regions": 0, "enabled": False, "mode": "skipped", "model": "",
                "kept": 0, "dropped": 0, "region_list": [],
                "notes": ["计划跳过：未配置读图通道，图片/扫描页未读取"],
            }


def run_job(job: Job, *, progress: Optional[Callable[[int, str], None]] = None,
            plan_mode: bool = False) -> ExecutionLog:
    """按计划执行全部工具, 返回执行记录。"""
    # 跨任务记忆(第二期第三批): 只读"线索"用于提示, 不改变任何执行决策
    if job.fingerprint:
        try:
            from .memory import hint_lines
            job.memory_lines = hint_lines(job.fingerprint)
        except Exception:      # noqa: BLE001
            job.memory_lines = []

    plan = make_plan(job, plan_mode=plan_mode, use_llm=job.llm_planner)
    log = ExecutionLog(mode=plan.mode, notes=list(plan.notes),
                       plan=plan.to_dict())

    if plan.agent_budget:
        job.agent_budget = dict(plan.agent_budget)

    def _tick(name: str, suffix: str = "") -> None:
        if not progress:
            return
        try:
            idx = STEPS.index(name)
        except ValueError:
            return
        progress(idx, f"{name}{suffix}")

    action_of = {d.tool: d for d in plan.decisions}
    t_all = time.time()

    for tool in TOOLS:
        decision = action_of.get(tool.key)

        if decision is not None and decision.action == "skip":
            _fill_empty(job, tool.key)
            log.steps.append(StepRecord(
                key=tool.key, title=tool.title, status="skipped",
                reason=decision.reason, checkpoints=tool.checkpoints))
            for cp in tool.checkpoints:
                _tick(cp, "（计划跳过）")
            continue

        t0 = time.time()
        try:
            tool.run(job, _tick)
        except Exception as ex:      # noqa: BLE001
            log.steps.append(StepRecord(
                key=tool.key, title=tool.title, status="failed",
                reason=f"{type(ex).__name__}: {ex}",
                seconds=time.time() - t0, checkpoints=tool.checkpoints))
            log.seconds = time.time() - t_all
            job.execution_log = log.to_dict()
            if job.audit is not None:
                job.audit.execution_log = job.execution_log
            raise
        log.steps.append(StepRecord(
            key=tool.key, title=tool.title, status="done",
            seconds=time.time() - t0, checkpoints=tool.checkpoints))

    log.seconds = time.time() - t_all
    job.execution_log = log.to_dict()
    if job.audit is not None:
        job.audit.execution_log = job.execution_log

    # 写入记忆: **只写线索**(哪些参数出现在哪些页/哪条通道/哪些已确认无解), 不写任何取值
    if job.fingerprint and job.audit is not None:
        try:
            from .memory import remember
            remember(job.audit, job.fingerprint)
        except Exception:      # noqa: BLE001
            pass
    return log
