"""核心数据结构定义。

Day 1 必做项(三轮评审结论): 全项目统一的数据结构,
对齐引擎(Day 3)与前端(Day 5)都以此为准, 不允许各写各的。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------- 枚举

class Status(str, Enum):
    """参数一致性状态。"""
    CONSISTENT = "consistent"            # 一致
    INCONSISTENT = "inconsistent"        # 不一致
    MISSING_IN_CODE = "missing_in_code"  # 论文有, 代码未找到
    MISSING_IN_PAPER = "missing_in_paper"  # 代码有, 论文未声明
    NOT_FIXED = "not_fixed"              # 论文要求固定(如 seed), 代码未固定
    UNVERIFIABLE = "unverifiable"        # 代码中以变量/表达式动态确定, 无法静态验证
    INTERNAL_INCONSISTENT = "internal_inconsistent"  # 论文或代码内部多处声明互相矛盾


class Confidence(str, Enum):
    """置信等级(只做两级, 评审结论: 砍掉 Probable)。"""
    CONFIRMED = "confirmed"  # 规则直接验证
    INFERRED = "inferred"    # AI 推断


class Risk(str, Enum):
    """风险等级。"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Category(str, Enum):
    """审计分类(对应就绪度面板五个维度)。"""
    ENV = "env"        # 环境一致性
    DATA = "data"      # 数据集一致性（只管数据集/数据声明，不管参数与实验结果）
    PARAM = "param"    # 参数一致性
    RECORD = "record"  # 实验记录完整度
    RESULT = "result"  # 结果一致性


# ---------------------------------------------------------------- 证据

@dataclass
class Evidence:
    """一条可追溯证据(证据链的最小单元)。

    例: source="paper", location="Page 6 · Training Setup",
        snippet="learning rate = 1e-4", raw_value="1e-4"
    例: source="code",  location="train.py:42",
        snippet="lr = 0.001", raw_value="0.001"
    """
    source: str          # "paper" | "code" | "result"
    location: str        # "Page N · Section" 或 "file.py:行号"
    snippet: str         # 原文片段
    raw_value: str       # 原始值(未归一化)
    normalized: Any = None  # 归一化后的值(float / str / None)
    # 该处出现在灵敏度/分组/扩展语境中(有意为之的不同取值, 不参与内部不一致判定)
    context_excluded: bool = False
    # 抽取通道: ast(Python 精确) | regex(多语言通用) | table(PDF 表格) | ocr/vlm(图像)
    parser: str = "ast"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- 审计发现

@dataclass
class Finding:
    """一条审计发现——全项目最核心的数据结构。

    字段在第 2 轮/第 3 轮评审中定稿:
    参数名、论文值+页码、代码值+文件+行号、状态、置信级、风险级、AI归因文字。
    """
    param_key: str                 # 规范化参数名, 如 "learning_rate"
    display_name: str              # 展示名, 如 "Learning Rate"
    category: Category             # 审计分类
    status: Status                 # 一致性状态
    confidence: Confidence         # 置信等级
    risk: Risk                     # 风险等级
    paper: Optional[Evidence] = None   # 论文证据(可能缺失)
    code: Optional[Evidence] = None    # 代码证据(可能缺失)
    extra: list = field(default_factory=list)  # 附加证据(内部不一致的第二处及以后)
    ai_analysis: str = ""          # LLM 归因文字(由 llm.py 填充)
    note: str = ""                 # 补充说明(如内部不一致的两处来源)
    risk_reason: str = ""          # 风险分级理由(为什么是这一级, 由 risk.py 给出)
    verified: bool = True          # 证据自证是否通过(审计的审计)
    verify_note: str = ""          # 自证细节(未通过原因)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        d["status"] = self.status.value
        d["confidence"] = self.confidence.value
        d["risk"] = self.risk.value
        return d

    @staticmethod
    def from_dict(d: dict) -> "Finding":
        paper = Evidence(**d["paper"]) if d.get("paper") else None
        code = Evidence(**d["code"]) if d.get("code") else None
        return Finding(
            param_key=d["param_key"],
            display_name=d["display_name"],
            category=Category(d["category"]),
            status=Status(d["status"]),
            confidence=Confidence(d["confidence"]),
            risk=Risk(d["risk"]),
            paper=paper,
            code=code,
            extra=[Evidence(**e) for e in d.get("extra", [])],
            ai_analysis=d.get("ai_analysis", ""),
            note=d.get("note", ""),
            verified=d.get("verified", True),
            verify_note=d.get("verify_note", ""),
        )


# ---------------------------------------------------------------- 解析结果容器

@dataclass
class PaperInfo:
    """论文解析结果。"""
    title: str = ""
    abstract: str = ""
    # 论文中声明的参数: param_key -> Evidence(含页码)
    params: dict = field(default_factory=dict)
    # 每个参数的全部声明位置(交叉审查用): param_key -> [Evidence, ...]
    params_all: dict = field(default_factory=dict)
    # 论文中声明的实验结果: 指标名 -> Evidence, 如 {"accuracy": Evidence(...94.3%)}
    results: dict = field(default_factory=dict)
    page_count: int = 0
    # 页级覆盖图: [{page, chars, images, status}], status: "ok" | "thin"
    page_coverage: list = field(default_factory=list)
    # 疑似参数声明总数(含数字的赋值句式, 参考指标)
    decl_total: int = 0
    # 正文中出现过(但未必取到值)的参数种类: canonical_key 列表(覆盖率分母)
    alias_kinds: list = field(default_factory=list)
    # 合理性校验被拒的抽取: [{key, value, location, reason}]
    rejected: list = field(default_factory=list)
    # 图像通道读到的参数(parser="vlm", 未参与文本层验证, 单列展示)
    image_params: dict = field(default_factory=dict)
    # 图像通道元信息: {regions, enabled, mode, model, kept, dropped, notes, region_list}
    image_meta: dict = field(default_factory=dict)
    # 各页正文文本 [(page_no, text), ...]——抽取 Agent 需要按句/按页回原文核对
    page_texts: list = field(default_factory=list)
    # 抽取 Agent(第一期): 补漏轨迹与预算消耗, 供报告/界面展示
    agent_trace: list = field(default_factory=list)
    agent_meta: dict = field(default_factory=dict)


@dataclass
class CodeInfo:
    """代码静态分析结果。"""
    # 代码中找到的参数: param_key -> [Evidence, ...](可能多处出现, 都保留)
    params: dict = field(default_factory=dict)
    # 环境依赖: 包名 -> 版本(可空字符串)
    requirements: dict = field(default_factory=dict)
    python_files: int = 0
    # seed 是否被固定
    seed_fixed: bool = False
    seed_evidence: Optional[Evidence] = None
    # 解析失败文件清单(失败示众, 禁止静默跳过): [{file, reason, lines}]
    failed_files: list = field(default_factory=list)
    # 识别到但本期不支持的代码格式(MATLAB/R/Julia 等), 明确告知而非假装没代码
    unsupported: list = field(default_factory=list)
    # 多语言通用通道解析的文件: [{file, lang, params}]
    multilang_files: list = field(default_factory=list)
    # 只在测试/示例文件里出现的参数名(不作为实现依据, 但在覆盖清单里如实说明)
    aux_only_keys: set = field(default_factory=set)
    # 代码侧被合理性校验拒收的抽取: [{key, value, location, reason}]
    rejected: list = field(default_factory=list)
    # 文件 -> 总行数(证据自证时校验行号真实存在)
    file_lines: dict = field(default_factory=dict)


@dataclass
class AuditResult:
    """一次完整审计的最终产物。"""
    paper: PaperInfo
    code: CodeInfo
    findings: list = field(default_factory=list)  # List[Finding]
    readiness: dict = field(default_factory=dict)  # readiness.py 填充
    user_results: dict = field(default_factory=dict)  # 用户上传的实验结果
    # 比对日志(审计的审计): 每次程序比较的完整记录, 进报告附录
    compare_log: list = field(default_factory=list)
    # 证据自证结果(selfcheck.py 填充): {checked, passed, failed, failures:[...]}
    selfcheck: dict = field(default_factory=dict)
    # 解析覆盖汇总(selfcheck.py 填充): 页级/声明级/代码级覆盖率与清单
    coverage: dict = field(default_factory=dict)
    # 执行记录(第二期第一批): 本次执行了哪些工具、跳过了哪些、各自为什么
    execution_log: dict = field(default_factory=dict)
    # 人工确认记录(第二期第二批): 用户对"待确认问题"的答复(不改变任何结论)
    clarifications: list = field(default_factory=list)
    # 根因追查(第三期 3.2) 与 补丁草案(3.3): 由工具箱的 rootcause / patch 两站写入。
    # 放在 AuditResult 上(而不是只留在调用方的局部变量里)是关键 ——
    # 报告与界面只拿得到 audit, 否则这两件事永远是"报告之外的独立脚本动作"。
    rootcause: list = field(default_factory=list)   # List[TraceResult]
    patches: list = field(default_factory=list)     # List[PatchProposal]

    def to_json(self) -> str:
        return json.dumps(
            {
                "findings": [f.to_dict() for f in self.findings],
                "readiness": self.readiness,
            },
            ensure_ascii=False,
            indent=2,
        )
