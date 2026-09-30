"""审计流水线编排——把 解析 -> 对齐 -> 归因 -> 自检 -> 就绪度 串成一条链。

供 CLI 与 Streamlit 共用; 每步有进度回调, 支撑演示进度条。
交叉审查设计: 归因之后、出报告之前必经"审计自检"(证据自证 + 结论回放)。

第二期（第一批）改造说明:
各步骤的**实现**已搬进 `toolbox`（工具箱），本模块只负责**调度与执行**——
- `plan_mode=False`（默认，经典模式）: 按固定全序执行全部工具，行为与改造前一致；
- `plan_mode=True`（计划模式）: 先由 `planner` 按材料实际情况排计划，再交 `runner` 执行。
两种模式调用的是**同一组工具函数**，不存在两套实现，因此不会代码漂移。

`STEPS` 由工具箱的工具顺序自动推导（节点/工具数随 `toolbox.TOOLS` 走，界面与报告都从它派生），
界面既有的十步进度条与 `from paper2lab.pipeline import STEPS` 无需改动。
"""

from __future__ import annotations

from typing import Callable, Optional

from .envfile import get as _env_get
from .memory import fingerprint as _fingerprint
from .runner import run_job
from .toolbox import STEPS, TOOLS, Job

__all__ = ["STEPS", "TOOLS", "run_audit"]


def run_audit(
    pdf_path: str,
    code_path: str,
    user_results: Optional[dict] = None,
    api_key: Optional[str] = None,
    llm_base_url: str = "",
    llm_model: str = "",
    force_mock: bool = False,
    progress: Optional[Callable[[int, str], None]] = None,
    vision_key: str = "",
    vision_base_url: str = "",
    vision_model: str = "",
    vision_source: str = "",
    vision_max_regions: Optional[int] = None,
    vision_budget_seconds: Optional[float] = None,
    enable_agent: bool = True,
    agent_budget: Optional[dict] = None,
    plan_mode: bool = False,
    llm_planner: bool = False,
    llm_patch: bool = False,
) -> tuple:
    """执行完整审计, 返回 (AuditResult, Markdown 报告)。

    进度回调 `progress(i, name)` 在**第 i 步真正完成时**触发, 因此它既适合
    驱动进度条(名称即为已完成步骤), 也直接给出各步骤耗时。
    计划模式下被跳过的步骤也会触发回调, 名称带「（计划跳过）」后缀。

    enable_agent=False 可关掉"抽取 Agent"(第一期), 用于做消融对比。
    plan_mode=True 启用"调度员排计划"(第二期第一批), 执行记录见
    `audit.execution_log`。
    llm_planner=True 让 **AI 排计划**（工具提议 + 程序盖章，见 planner._llm_refine）；
    llm_patch=True 让 **AI 给补丁提名目标**（提名必须落在已抽到的候选里，再由程序盖章，
    见 patch.propose_via_llm）。
    `llm_base_url` / `llm_model`：**模型 API 的端点与模型名**（2026-09-30 起页面可填），
    用于让用户换任意 OpenAI 兼容模型；留空则回落 .env / 环境变量 / DeepSeek 默认。
    **本函数的默认值是 False**（CLI 与验证脚本需要可预测的确定性基线）；
    **网页端默认 True** —— 界面就是 agent 入口：输入材料启动即由 AI 参与决定跑哪些环节
    （见 app.py 的「AI 参与决策」开关）。**规则版永远是兜底**：
    AI 不可用、想乱跳、提名越界，都会被程序挡回并留痕。
    """
    job = Job(
        fingerprint=_fingerprint(pdf_path, code_path),
        pdf_path=pdf_path,
        code_path=code_path,
        user_results=user_results,
        # LLM key 与归因引擎同一口径: 调用方没传就回落到 .env / 环境变量。
        # (否则 CLI 入口不传 key 时, 归因能自己兜底、但抽取 Agent 的 LLM 级会整级不可用)
        api_key=(api_key or _env_get("LLM_API_KEY")
                 or _env_get("DEEPSEEK_API_KEY") or ""),
        # 模型 API 的端点与模型名（页面可填）：留空则各调用点自己回落 .env / 默认，
        # 因此**不传参的老调用点行为完全不变**。
        llm_base_url=llm_base_url or "",
        llm_model=llm_model or "",
        force_mock=force_mock,
        vision_kwargs={"api_key": vision_key, "base_url": vision_base_url,
                       "model": vision_model,
                       # 让「审计可信度」页如实标注来源（"复用模型 API（多模态）"）；
                       # 传空则用 vision.py 自己的判定，行为不变。
                       "source_hint": vision_source,
                       "budget_seconds": vision_budget_seconds},
        vision_max_regions=vision_max_regions,
        enable_agent=enable_agent,
        agent_budget=dict(agent_budget or {}),
        llm_planner=bool(llm_planner),
        llm_patch=bool(llm_patch),
    )
    run_job(job, progress=progress, plan_mode=plan_mode)
    return job.audit, job.report
