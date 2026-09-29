"""对齐引擎——论文↔代码↔实验结果 一致性审计核心(项目生死线)。

规则(评审定稿 + 交叉审查增强):
- 确定性比较全部由程序完成(数值归一化后比对)
- 训练相关文件(train*.py)中的参数优先级高于默认值/测试文件
- 风险规则内置, 不做权重论证
- 交叉审查: 同一载体多处声明互查(内部不一致) + 每次比较写入 compare_log 备查
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .models import (
    AuditResult, Category, CodeInfo, Confidence, Evidence, Finding,
    PaperInfo, Risk, Status,
)
from .risk import assess_risk
from .synonyms import PARAM_SYNONYMS, values_equal

# 取值为文本的参数(模型/优化器/调度器/数据集): 常由 CLI 或配置选择, 易有多个实现候选
_TEXT_VALUED_KEYS = {"optimizer", "scheduler", "dataset", "model"}

# 参数分类
_PARAM_CATEGORY = {
    "learning_rate": Category.PARAM, "batch_size": Category.PARAM,
    "epochs": Category.PARAM, "optimizer": Category.PARAM,
    "weight_decay": Category.PARAM, "momentum": Category.PARAM,
    "dropout": Category.PARAM, "warmup": Category.PARAM,
    "scheduler": Category.PARAM, "input_size": Category.PARAM,
    "seed": Category.PARAM, "dataset": Category.DATA,
    "model": Category.PARAM,
    "num_clusters": Category.PARAM, "threshold": Category.PARAM,
    "sigma_xy": Category.PARAM, "sigma_z": Category.PARAM,
    "kill_radius": Category.PARAM, "depth_est": Category.PARAM,
    "min_depth": Category.PARAM, "num_bombs": Category.PARAM,
}

# 不一致时的风险等级与理由, 统一由 risk.py 给出(见 _RISK_ON_MISMATCH 的迁移)


def _evidence_score(ev: Evidence) -> int:
    """代码证据可信度打分: 训练入口/配置文件 > 其他 > 测试/示例/教程。"""
    loc = ev.location.lower()
    s = 0
    if re.search(r"\btrain", loc):
        s += 4
    if "config" in loc or "option" in loc:
        s += 2
    # 测试/示例/教程路径降权(下划线开头的命名如 optimization_test.py 也要命中)
    if re.search(r"(^|[/\\_.\-])(test|tests|eval|demo|tmp|spec|example|examples|"
                 r"tutorial|sample|colab|benchmark|notebook)", loc) or "[cell" in loc:
        s -= 5
    if ev.normalized is not None:
        s += 2  # 字面量证据优先于变量引用证据
    return s


def _pick_best_code_evidence(evs: list[Evidence]) -> Optional[Evidence]:
    """多处出现时挑最可信的一处: train*.py > config > 库/主实现 > 示例教程。

    只来自测试/示例文件(打分 < 0)的证据不作为实现依据 —— 宁可报"未找到",
    也不拿单元测试里的假值去和论文比对。
    """
    if not evs:
        return None
    usable = [e for e in evs if _evidence_score(e) >= 0]
    if not usable:
        return None
    return max(usable, key=_evidence_score)


# 辅助脚本路径(测试/示例/教程/notebook): 其中的取值不代表项目配置,
# 不参与"代码内部不一致"判定(否则单元测试里的 0.2 会污染学习率的结论)
_AUX_PATH = re.compile(r"(^|[/\\_.\-])(test|tests|eval|demo|tmp|spec|example|examples|"
                       r"tutorial|sample|colab|benchmark|notebook)", re.IGNORECASE)


def text_values_match(a: Evidence, b: Evidence) -> bool:
    """文本型取值(优化器/调度器/数据集/模型)的宽松比对:
    归一化文本相等或互为包含即视为一致(如 cosine 与 cosine annealing、Adam 与 AdamW)。
    任一侧是数值型则不适用(返回 False, 交回数值比对)。"""
    if isinstance(a.normalized, (int, float)) or isinstance(b.normalized, (int, float)):
        return False

    def s(ev: Evidence) -> str:
        v = ev.normalized if isinstance(ev.normalized, str) else ev.raw_value
        return re.sub(r"[\s_\-]+", "", str(v).lower())

    sa, sb = s(a), s(b)
    if not sa or not sb:
        return False
    return sa == sb or sa in sb or sb in sa


def _distinct_values(evs: list[Evidence]) -> list[tuple[Any, Evidence]]:
    """按归一化值去重, 返回 [(值, 首个出现证据), ...](用于内部一致性核对)。"""
    seen: dict = {}
    out: list = []
    for ev in evs:
        if ev.normalized is None:
            continue  # 变量/动态确定不参与内部一致性核对
        key = str(ev.normalized)
        if key in seen:
            continue
        seen[key] = ev
        out.append((ev.normalized, ev))
    return out


def _internal_conflict(key: str, disp: str, category: Category,
                       hits: list[Evidence], side: str) -> Optional[Finding]:
    """同一载体(论文/代码)内部多处声明值不一致 -> 交叉审查发现。

    side: "paper" | "code"
    出现在灵敏度/分组/扩展语境中的取值(有意为之)不参与判定。
    分布在多个示例/教程文件时降为低风险(通常并非同一套实验配置)。
    """
    candidate = [ev for ev in hits if not ev.context_excluded]
    if side == "code":
        # 测试/示例/教程文件中的取值不算"实现配置", 排除后仍矛盾才算内部不一致
        candidate = [ev for ev in candidate
                     if not _AUX_PATH.search(ev.location) and "[cell" not in ev.location]
    distinct = _distinct_values(candidate)
    if len(distinct) < 2:
        return None
    first_val, first_ev = distinct[0]
    others = [ev for _v, ev in distinct[1:]]
    desc = "; ".join(f"{_v} @ {ev.location}" for _v, ev in distinct[:4])
    files = {ev.location.split(":")[0] for _v, ev in distinct}
    spread = len(files) > 1
    side_zh = "论文" if side == "paper" else "代码"
    note = f"{side_zh}内部多处声明互不一致: {desc}"
    if side == "paper":
        note += "　(交叉审查自动核对, 若属灵敏度分析/分组实验请人工确认)"
    elif spread:
        note += "　(分布在多个文件中, 可能并非同一套实验配置, 请人工确认)"
    else:
        note += "　(同一文件内自相矛盾, 通常说明配置被覆盖)"
    risk, reason = assess_risk(Status.INTERNAL_INCONSISTENT, key, side=side,
                               same_file=not spread)
    if side == "paper":
        return Finding(
            param_key=key, display_name=disp, category=category,
            status=Status.INTERNAL_INCONSISTENT, confidence=Confidence.CONFIRMED,
            risk=risk, risk_reason=reason, paper=first_ev, extra=others[:3], note=note,
        )
    return Finding(
        param_key=key, display_name=disp, category=category,
        status=Status.INTERNAL_INCONSISTENT, confidence=Confidence.CONFIRMED,
        risk=risk, risk_reason=reason, code=first_ev, extra=others[:3], note=note,
    )


def _align_param(key: str, paper: PaperInfo, code: CodeInfo,
                 log: list[str]) -> list[Finding]:
    """对齐单个参数: 内部一致性交叉核对 + 论文↔代码比对(两者都报, 不互相吞掉)。"""
    out: list[Finding] = []
    p_ev: Optional[Evidence] = paper.params.get(key)
    c_evs: list[Evidence] = code.params.get(key, [])
    c_ev = _pick_best_code_evidence(c_evs)
    category = _PARAM_CATEGORY.get(key, Category.PARAM)
    disp = PARAM_SYNONYMS.get(key, (key, []))[0]

    # ---- 交叉审查第一道: 同一载体多处声明互查(合并为一个发现, 不阻断后续比对)
    p_hits: list[Evidence] = list(paper.params_all.get(key) or [])
    if p_ev and not p_hits:
        p_hits = [p_ev]
    conf_p = _internal_conflict(key, disp, category, p_hits, "paper")
    conf_c = _internal_conflict(key, disp, category, c_evs, "code")
    if conf_p or conf_c:
        note = "；".join(x for x in [(conf_p.note if conf_p else ""),
                                     (conf_c.note if conf_c else "")] if x)
        # 取两侧中较严重的等级, 同时给出理由(优先用更严重那一侧的理由)
        _order = {"high": 0, "medium": 1, "low": 2, "none": 3}
        cands = [x for x in (conf_p, conf_c) if x]
        worst = min(cands, key=lambda x: _order[x.risk.value])
        merged = Finding(
            param_key=key, display_name=disp, category=category,
            status=Status.INTERNAL_INCONSISTENT, confidence=Confidence.CONFIRMED,
            risk=worst.risk, risk_reason=worst.risk_reason or "",
            paper=(conf_p.paper if conf_p else None),
            code=(conf_c.code if conf_c else None),
            extra=(list(conf_p.extra) if conf_p else []) + (list(conf_c.extra) if conf_c else []),
            note=note,
        )
        log.append(f"[内部核对] {key}: " + note)
        out.append(merged)

    # seed 特殊处理: 论文声明 vs 代码固定(random_state/manual_seed/default_rng 等)
    if key == "seed":
        seed_evs = list(c_evs)
        if code.seed_fixed and code.seed_evidence:
            seed_evs.append(code.seed_evidence)
        c_seed = _pick_best_code_evidence(seed_evs)
        if p_ev and not c_seed:
            log.append(f"[比较] {key}: 论文声明 {p_ev.raw_value} @ {p_ev.location}, 代码无固定证据 -> NOT_FIXED")
            _r, _why = assess_risk(Status.NOT_FIXED, key)
            out.append(Finding(
                param_key=key, display_name=disp, category=category,
                status=Status.NOT_FIXED, confidence=Confidence.CONFIRMED,
                risk=_r, risk_reason=_why, paper=p_ev, code=None,
            ))
            return out
        if p_ev and c_seed:
            if c_seed.normalized is None:
                log.append(f"[比较] {key}: 代码证据无静态值({c_seed.location}) -> UNVERIFIABLE")
                _r, _why = assess_risk(Status.UNVERIFIABLE, key)
                out.append(Finding(
                    param_key=key, display_name=disp, category=category,
                    status=Status.UNVERIFIABLE, confidence=Confidence.CONFIRMED,
                    risk=_r, risk_reason=_why, paper=p_ev, code=c_seed,
                ))
                return out
            same = values_equal(p_ev.raw_value, c_seed.raw_value)
            log.append(f"[比较] {key}: 论文 {p_ev.normalized} @ {p_ev.location} vs 代码 {c_seed.normalized} "
                       f"@ {c_seed.location} -> {'相等' if same else '不相等'}")
            _r, _why = assess_risk(Status.INCONSISTENT, key) if not same else (Risk.NONE, "")
            out.append(Finding(
                param_key=key, display_name=disp, category=category,
                status=Status.CONSISTENT if same else Status.INCONSISTENT,
                confidence=Confidence.CONFIRMED,
                risk=Risk.NONE if same else Risk.LOW, risk_reason=_why,
                paper=p_ev, code=c_seed,
            ))
            return out
        if not p_ev and c_seed:
            # 代码固定了随机种子但论文未声明(实验记录不完整, 但属加分项)
            log.append(f"[比较] {key}: 论文未声明, 代码固定 {c_seed.raw_value} @ {c_seed.location} -> MISSING_IN_PAPER")
            _r, _why = assess_risk(Status.MISSING_IN_PAPER, key)
            out.append(Finding(
                param_key=key, display_name=disp, category=category,
                status=Status.MISSING_IN_PAPER, confidence=Confidence.CONFIRMED,
                risk=_r, risk_reason=_why, paper=None, code=c_seed,
            ))
        return out

    # c_ev 可能为 None: 该参数只在测试/示例文件里出现 -> 视为代码侧无有效证据
    if p_ev is None and c_ev is None:
        return out
    if p_ev is None:
        log.append(f"[比较] {key}: 论文未声明, 代码 {c_ev.raw_value} @ {c_ev.location} -> MISSING_IN_PAPER")
        _r, _why = assess_risk(Status.MISSING_IN_PAPER, key)
        out.append(Finding(
            param_key=key, display_name=disp, category=category,
            status=Status.MISSING_IN_PAPER, confidence=Confidence.CONFIRMED,
            risk=_r, risk_reason=_why, paper=None, code=c_ev,
        ))
        return out
    if c_ev is None:
        log.append(f"[比较] {key}: 论文声明 {p_ev.raw_value} @ {p_ev.location}, 代码未找到 -> MISSING_IN_CODE")
        _r, _why = assess_risk(Status.MISSING_IN_CODE, key)
        out.append(Finding(
            param_key=key, display_name=disp, category=category,
            status=Status.MISSING_IN_CODE, confidence=Confidence.CONFIRMED,
            risk=_r, risk_reason=_why, paper=p_ev, code=None,
        ))
        return out

    # 代码中以变量/表达式动态确定: 无法静态验证(诚实标记, 不算不一致)
    if c_ev.normalized is None:
        log.append(f"[比较] {key}: 论文 {p_ev.raw_value}, 代码为动态确定({c_ev.snippet[:40]}) -> UNVERIFIABLE")
        _r, _why = assess_risk(Status.UNVERIFIABLE, key)
        out.append(Finding(
            param_key=key, display_name=disp, category=category,
            status=Status.UNVERIFIABLE, confidence=Confidence.CONFIRMED,
            risk=_r, risk_reason=_why, paper=p_ev, code=c_ev,
        ))
        return out

    if values_equal(p_ev.raw_value, c_ev.raw_value) or text_values_match(p_ev, c_ev):
        log.append(f"[比较] {key}: 归一化后 {p_ev.normalized} == {c_ev.normalized} "
                   f"({p_ev.location} vs {c_ev.location}) -> CONSISTENT")
        out.append(Finding(
            param_key=key, display_name=disp, category=category,
            status=Status.CONSISTENT, confidence=Confidence.CONFIRMED,
            risk=Risk.NONE, paper=p_ev, code=c_ev,
        ))
        return out
    log.append(f"[比较] {key}: 归一化后 {p_ev.normalized} != {c_ev.normalized} "
               f"({p_ev.location} vs {c_ev.location}) -> INCONSISTENT")
    note = ""
    # 代码里存在多个不同取值时的处理:
    # ① 文本型参数(模型/优化器/调度器/数据集)通常是"由 CLI/配置选择"的多实现,
    #    任取一个与论文对比都不足以定高风险 -> 降为低风险并列出全部候选;
    # ② 数值型参数只有在首选证据不是明确训练/配置文件时才降级。
    code_distinct = _distinct_values([e for e in c_evs if not e.context_excluded])
    ambiguous = (len(code_distinct) > 1
                 and (key in _TEXT_VALUED_KEYS or _evidence_score(c_ev) < 6))
    if ambiguous:
        note = ("代码中存在 " + str(len(code_distinct)) + " 个不同取值("
                + "; ".join(f"{v} @ {e.location}" for v, e in code_distinct[:3])
                + ")，本次取默认/首选实现比对；若该参数由命令行选项或外部配置决定，"
                  "请以实际运行配置为准")
    risk, reason = assess_risk(Status.INCONSISTENT, key, downgraded=ambiguous)
    out.append(Finding(
        param_key=key, display_name=disp, category=category,
        status=Status.INCONSISTENT, confidence=Confidence.CONFIRMED,
        risk=risk, risk_reason=reason, paper=p_ev, code=c_ev, note=note,
    ))
    return out


def _align_results(paper: PaperInfo, user_results: dict,
                   log: list[str]) -> list[Finding]:
    """论文声明结果 vs 用户上传的实际实验结果。"""
    findings = []
    for metric, p_ev in paper.results.items():
        if metric not in user_results:
            continue
        actual = user_results[metric]
        a_ev = Evidence(
            source="result", location="用户上传实验结果",
            snippet=f"{metric} = {actual}", raw_value=str(actual),
            normalized=float(actual) if isinstance(actual, (int, float)) else None,
            parser="result",
        )
        same = values_equal(p_ev.raw_value, actual)
        # 差异判定: 相对差异 <=1% 视为一致; >=2 个绝对点(或相对 >=5%) 为高风险
        rel = diff = None
        try:
            fv, fa = float(p_ev.normalized), float(actual)
            diff = abs(fa - fv)
            rel = diff / max(abs(fv), 1e-12)
        except (TypeError, ValueError):
            pass
        if same or (rel is not None and rel <= 0.01):
            log.append(f"[结果核对] {metric}: 论文 {p_ev.raw_value} vs 实际 {actual} "
                       f"(相对差异 {rel:.2%}) -> CONSISTENT" if rel is not None
                       else f"[结果核对] {metric}: 论文 {p_ev.raw_value} vs 实际 {actual} -> CONSISTENT")
            findings.append(Finding(
                param_key=f"result_{metric}", display_name=f"Result: {metric}",
                category=Category.RESULT, status=Status.CONSISTENT,
                confidence=Confidence.CONFIRMED, risk=Risk.NONE,
                paper=p_ev, code=a_ev,
            ))
        else:
            risk = Risk.HIGH if ((diff is not None and diff >= 2.0)
                                 or (rel is not None and rel >= 0.05)) else Risk.MEDIUM
            log.append(f"[结果核对] {metric}: 论文 {p_ev.raw_value} vs 实际 {actual} "
                       f"-> INCONSISTENT (相对差异 {rel:.2%})" if rel is not None
                       else f"[结果核对] {metric}: 论文 {p_ev.raw_value} vs 实际 {actual} -> INCONSISTENT")
            findings.append(Finding(
                param_key=f"result_{metric}", display_name=f"Result: {metric}",
                category=Category.RESULT, status=Status.INCONSISTENT,
                confidence=Confidence.CONFIRMED, risk=risk,
                paper=p_ev, code=a_ev,
            ))
    return findings


def _align_image_params(paper: PaperInfo, code: CodeInfo,
                        log: list[str]) -> list[Finding]:
    """图像通道读到的参数: 文本层没抽到、只有读图结果时才单列(标 Inferred, 不计入就绪度)。

    这类结论未经文本层验证, 只作为线索呈现, 必须人工核对。
    """
    out: list[Finding] = []
    for key, evs in (paper.image_params or {}).items():
        if key in paper.params or not evs:      # 文本层已抽到 -> 以文本层为准
            continue
        p_ev = evs[0]
        c_ev = _pick_best_code_evidence(code.params.get(key, []))
        disp = PARAM_SYNONYMS.get(key, (key, []))[0]
        category = _PARAM_CATEGORY.get(key, Category.PARAM)
        risk = Risk.LOW
        if c_ev and c_ev.normalized is not None:
            same = values_equal(p_ev.raw_value, c_ev.raw_value) \
                or text_values_match(p_ev, c_ev)
            log.append(f"[图像核对] {key}: AI 读图得 {p_ev.raw_value} @ {p_ev.location}, "
                       f"代码 {c_ev.normalized} @ {c_ev.location} -> "
                       f"{'一致' if same else '不一致'}(AI 读图, 未参与评分)")
            out.append(Finding(
                param_key=key, display_name=disp, category=category,
                status=Status.CONSISTENT if same else Status.INCONSISTENT,
                confidence=Confidence.INFERRED, risk=Risk.NONE if same else risk,
                paper=p_ev, code=c_ev,
                note="该论文值由 AI 读图获得(图像/扫描页), 未经文本层验证, 请人工核对原图",
            ))
        else:
            log.append(f"[图像核对] {key}: AI 读图得 {p_ev.raw_value} @ {p_ev.location} "
                       f"(代码无对应证据, AI 读图未参与评分)")
            out.append(Finding(
                param_key=key, display_name=disp, category=category,
                status=Status.MISSING_IN_CODE, confidence=Confidence.INFERRED,
                risk=risk, paper=p_ev, code=None,
                note="该论文值由 AI 读图获得(图像/扫描页), 未经文本层验证, 请人工核对原图",
            ))
    return out


def align(paper: PaperInfo, code: CodeInfo, user_results: Optional[dict] = None) -> AuditResult:
    """对齐主流程: 论文↔代码全参数审计 + 结果审计 + 内部一致性交叉核对。"""
    result = AuditResult(paper=paper, code=code, user_results=user_results or {})
    log: list[str] = result.compare_log

    all_keys = set(paper.params) | set(code.params) | set(paper.params_all)
    if code.seed_fixed or "seed" in paper.params:
        all_keys.add("seed")

    for key in sorted(all_keys):
        result.findings.extend(_align_param(key, paper, code, log))

    if user_results:
        result.findings.extend(_align_results(paper, user_results, log))

    # 图像通道(读图)结论: 单独一档, AI 只提议, 不计入就绪度评分
    result.findings.extend(_align_image_params(paper, code, log))

    # 排序: 高风险不一致在前, 一致在后
    order = {Risk.HIGH: 0, Risk.MEDIUM: 1, Risk.LOW: 2, Risk.NONE: 3}
    result.findings.sort(key=lambda f: (order[f.risk], f.param_key))
    return result
