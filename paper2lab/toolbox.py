"""工具箱（第二期第一批）——把审计流水线的每一站登记成可单独调用的工具。

三条设计原则:
1. **工具只描述能力, 不含调度**: "怎么做"写在工具里, "做不做、按什么顺序做"
   交给调度员(planner)。工具函数本身不判断该不该跑。
2. **进度节点向后兼容**: 每个工具声明它覆盖的进度节点(checkpoints),
   `STEPS` 由工具顺序自动推导, 界面既有的十步进度条与 `pipeline.STEPS` 零改动。
3. **经典模式与计划模式共用同一份实现**: 两条路径调用的是同一组工具函数,
   避免代码漂移(否则"等价重构"就无从谈起)。

关于"十二个进度节点、十个工具":
"参数归一化 / 交叉匹配 / 实验结果核验"在实现上是 `aligner.align` 的三段职责,
一次遍历同时产出; 硬拆成三个工具只会重复计算, 因此登记为一个工具、覆盖三个节点。
这一点在界面的「执行计划」里如实标注, 不做粉饰。

**第三期两站为什么也登记进来**（2026-09-28 补）:
「根因追查 → 补丁草案」是一条**动作链的前后两半**, 少一半就不成立。早先它俩只在
报告之外的独立脚本里跑, 后果是三重的: ① 每个调用方自己拼一遍, 实测已漂移成三份
(`run_new_set` / `demo_full_flow` / `verify_patch`); ② 调度员管不到 —— 没有代码包时
本该跳过, 却没人知道该跳过; ③ 报告与界面完全看不到, 用户问"补丁为什么被拒"时
产品答不上来。现在它们与其它站同权: 结论落在 `AuditResult.rootcause / .patches`,
报告有专节、界面有面板、执行记录里看得见去向了。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .agent import fill_missing
from .aligner import align
from .code_analyzer import analyze_code
from .llm import LLMAnalyzer
from .models import AuditResult, CodeInfo, PaperInfo
from .paper_parser import parse_paper
from .readiness import compute_readiness
from .report import generate_report
from .selfcheck import (build_manual_check, build_param_matrix, compute_coverage,
                        run_selfcheck)
from .vision import analyze_images


@dataclass
class Job:
    """一次审计任务的输入与中间产物——工具箱与执行器共用的载体。

    执行器只负责"调用工具、传递 Job、记录状态", 所有中间产物都挂在 Job 上,
    因此工具之间不需要互相知道对方的存在。
    """
    # ---- 输入
    pdf_path: str = ""
    code_path: str = ""
    user_results: Optional[dict] = None
    api_key: str = ""
    force_mock: bool = False
    vision_kwargs: dict = field(default_factory=dict)
    vision_max_regions: Optional[int] = None
    enable_agent: bool = True
    agent_budget: dict = field(default_factory=dict)
    # 让 AI 排计划: 规则版仍是兜底，见 planner._llm_refine。
    # 字段默认 False（CLI 与验证脚本需要可预测的确定性基线）；
    # **网页端默认 True**（agent 模式，见 app.py 的「AI 参与决策」开关）。
    llm_planner: bool = False
    # 让 AI 给补丁"提名目标": 只在"值可信、缺的只是选哪个"时启用，
    # 提名必须落在已抽到的候选里，再由程序盖章，产出标 proposed-llm（需人工确认）。
    # 同上：字段默认 False，网页端默认 True。
    llm_patch: bool = False
    # ---- 产物
    paper: Optional[PaperInfo] = None
    code: Optional[CodeInfo] = None
    audit: Optional[AuditResult] = None
    report: str = ""
    agent_report: object = None          # AgentReport（第一期）
    rootcause: list = field(default_factory=list)   # [TraceResult]（第三期 3.2）
    patches: list = field(default_factory=list)     # [PatchProposal]（第三期 3.3）
    llm_mode: str = ""
    llm_real_calls: int = 0
    llm_cache_hits: int = 0
    llm_error: str = ""
    llm_shard: dict = field(default_factory=dict)      # 归因的分片并发记录
    execution_log: dict = field(default_factory=dict)
    fingerprint: str = ""                                # 论文指纹(跨任务记忆索引)
    memory_lines: list = field(default_factory=list)      # 记忆命中的线索(只提示)


# ---------------------------------------------------------------- 工具执行体
# 以下函数由 pipeline.run_audit 的既有步骤**逐行搬运**而来, 行为不变。

def _run_parse_paper(job: Job, tick: Callable[[str], None]) -> None:
    job.paper = parse_paper(job.pdf_path)
    tick("论文解析")


def _run_analyze_images(job: Job, tick: Callable[[str], None]) -> None:
    job.paper.image_params, job.paper.image_meta = analyze_images(
        job.pdf_path, max_regions=job.vision_max_regions, **job.vision_kwargs)
    tick("图像解析")


def _run_fill_missing(job: Job, tick: Callable[[str], None]) -> None:
    """抽取 Agent（第一期成果）——原样保留, 预算与闸门逻辑不变。"""
    _agent = fill_missing(
        job.paper, job.pdf_path,
        llm_api_key=job.api_key or "",
        vision_kwargs=dict(job.vision_kwargs),
        enabled=job.enable_agent, **dict(job.agent_budget or {}))
    for k, ev in _agent.filled.items():
        job.paper.params_all.setdefault(k, []).append(ev)
        job.paper.params.setdefault(k, ev)
    job.paper.agent_trace = _agent.to_dict()
    job.paper.agent_meta = _agent.to_dict()
    job.agent_report = _agent
    tick("Agent 补漏抽取")


def _run_analyze_code(job: Job, tick: Callable[[str], None]) -> None:
    job.code = analyze_code(job.code_path)
    tick("代码扫描")


def _run_align(job: Job, tick: Callable[[str], None]) -> None:
    """归一化 + 交叉匹配 + 结果核验: 一次遍历同时产出, 覆盖三个进度节点。"""
    job.audit = align(job.paper, job.code, job.user_results)
    tick("参数归一化")
    tick("交叉匹配")
    tick("实验结果核验")


def _run_llm_analyze(job: Job, tick: Callable[[str], None]) -> None:
    analyzer = LLMAnalyzer(api_key=job.api_key, force_mock=job.force_mock)
    analyzer.analyze_all(job.audit.findings)
    job.llm_mode = analyzer.mode
    job.llm_real_calls = analyzer.real_calls
    job.llm_cache_hits = analyzer.cache_hits
    job.llm_error = analyzer.last_error
    job.llm_shard = dict(getattr(analyzer, "shard_report", {}) or {})
    tick("AI 风险归因")


def _run_selfcheck(job: Job, tick: Callable[[str], None]) -> None:
    run_selfcheck(job.audit)        # 证据自证 + 结论回放
    compute_coverage(job.audit)     # 解析覆盖率与审计可信度
    job.audit.coverage["manual_check"] = build_manual_check(job.audit)
    job.audit.coverage["param_matrix"] = build_param_matrix(job.audit)

    compute_readiness(job.audit)
    job.audit.readiness["llm_mode"] = job.llm_mode
    job.audit.readiness["llm_real_calls"] = job.llm_real_calls
    job.audit.readiness["llm_cache_hits"] = job.llm_cache_hits
    job.audit.readiness["llm_error"] = job.llm_error
    job.audit.readiness["llm_shards"] = dict(job.llm_shard or {})
    tick("审计自检")


def _run_rootcause(job: Job, tick: Callable[[str], None]) -> None:
    """根因追查（第三期 3.2）：从多个赋值点里找出**最终生效**的那一个（只读代码）。"""
    from .rootcause import trace_findings
    traces = trace_findings(job.audit, max_items=8)
    job.rootcause = traces
    job.audit.rootcause = traces
    tick("根因追查")


def _run_patch(job: Job, tick: Callable[[str], None]) -> None:
    """补丁草案（第三期 3.3）：基于根因给出 diff 草案 —— **只展示，绝不落盘**。

    `job.llm_patch=True` 时额外开一条「AI 提名目标 + 程序盖章」通道（见 patch.propose_via_llm）。
    """
    from .patch import propose_patches
    patches = propose_patches(job.audit, job.rootcause or [], job.code_path,
                              max_items=8, llm=job.llm_patch,
                              api_key=job.api_key, force_mock=job.force_mock)
    job.patches = patches
    job.audit.patches = patches
    tick("补丁草案")


def _run_report(job: Job, tick: Callable[[str], None]) -> None:
    job.report = generate_report(job.audit)
    tick("生成审计报告")


# ---------------------------------------------------------------- 工具登记表

@dataclass
class Tool:
    """一个可单独调用的工具。

    needs / gives 描述的是**产物依赖**, 调度员据此判断能否跳过;
    checkpoints 是它在界面进度条上覆盖的节点(顺序执行)。
    """
    key: str
    title: str
    checkpoints: tuple
    needs: tuple
    gives: tuple
    cost: str
    run: Callable
    core: bool = False        # 核心工具: 无论材料多残缺都必须执行


TOOLS: tuple = (
    Tool(key="parse_paper", title="论文解析",
         checkpoints=("论文解析",), needs=(), gives=("paper",),
         cost="本地解析", run=_run_parse_paper, core=True),
    Tool(key="analyze_images", title="图像解析",
         checkpoints=("图像解析",), needs=("paper",), gives=("image_params",),
         cost="按区域读图", run=_run_analyze_images),
    Tool(key="fill_missing", title="Agent 补漏抽取",
         checkpoints=("Agent 补漏抽取",), needs=("paper",), gives=("paper",),
         cost="最多 3 次 LLM / 2 次读图", run=_run_fill_missing),
    Tool(key="analyze_code", title="代码扫描",
         checkpoints=("代码扫描",), needs=(), gives=("code",),
         cost="本地解析", run=_run_analyze_code),
    Tool(key="align", title="参数对齐与结果核验",
         checkpoints=("参数归一化", "交叉匹配", "实验结果核验"),
         needs=("paper", "code"), gives=("findings",),
         cost="本地比对", run=_run_align, core=True),
    Tool(key="llm_analyze", title="AI 风险归因",
         checkpoints=("AI 风险归因",), needs=("findings",), gives=("ai_analysis",),
         cost="每次归因 1 次 LLM", run=_run_llm_analyze),
    Tool(key="selfcheck", title="审计自检",
         checkpoints=("审计自检",), needs=("findings",),
         gives=("selfcheck", "coverage", "readiness"),
         cost="本地校验", run=_run_selfcheck, core=True),
    Tool(key="rootcause", title="根因追查",
         checkpoints=("根因追查",), needs=("code", "findings"),
         gives=("rootcause",), cost="只读代码", run=_run_rootcause),
    Tool(key="patch", title="补丁草案",
         checkpoints=("补丁草案",), needs=("rootcause",),
         gives=("patches",), cost="只读代码、绝不落盘", run=_run_patch),
    Tool(key="report", title="生成审计报告",
         checkpoints=("生成审计报告",), needs=("findings",), gives=("report",),
         cost="本地渲染", run=_run_report, core=True),
)

TOOL_BY_KEY: dict = {t.key: t for t in TOOLS}

# 进度节点: 由工具顺序自动推导, 保证与 pipeline.STEPS 完全一致
STEPS: list = [cp for t in TOOLS for cp in t.checkpoints]
