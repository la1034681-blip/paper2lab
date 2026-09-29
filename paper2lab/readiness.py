"""复现就绪度评分——纯展示层映射(评审结论: 不做评分算法论证)。

固定规则: 起始 100, 高风险 -15, 中风险 -8, 低风险 -3。
命名"复现就绪度", 不是"论文质量评分"。

**「未核验」是显式状态**(2026-09-28 修正)
------------------------------------------------
一个维度只有在**真的做了比对**时才给分; 没有可比对象时标注「未核验」,
**不给分、不进总分**。判定条件:

| 维度 | 何时核验 | 何时未核验 |
| --- | --- | --- |
| 参数一致性 / 数据集一致性 | 正文与代码两侧都有可比对的内容 | 本次两侧都没有该类内容 |
| 环境一致性 | 提供了代码包 | 未提供代码包 —— 无从核对环境依赖 |
| 实验记录完整度 | 提供了实测结果 | 未提供实测结果 |
| 结果一致性 | 提供了实测结果且论文声明了可对照指标 | 二者缺一 |

**为什么必须显式**(实证, 2026-09-28): 从前"没提供实测结果"时
① 「结果一致性」走默认值显示 **100 分(绿色)** —— 一次核验都没做却像"核验过且通过",
比"没有这个维度"更容易误导;
② 「实验记录完整度」固定给 **60 分** —— 这 40 分差与论文质量无关, 只反映
"本次审计有没有拿到实测结果", 等于**把用户没上传算成论文的问题**。
两者都违反本项目的"如实"原则; 且方向是反的——做了核验反而该维度更低分
(因为如实报出了差异), 不做则白得满分。
"""

from __future__ import annotations

from .models import AuditResult, Category, Finding, Risk, Status

_PENALTY = {Risk.HIGH: 15, Risk.MEDIUM: 8, Risk.LOW: 3, Risk.NONE: 0}

_CATEGORY_LABELS = {
    Category.ENV: "环境一致性",
    # ⚠️ 叫「数据集一致性」而不是「数据一致性」（2026-09-29 改）:
    # 旧名字会让人以为它管"所有数据"，于是看到它"未核验"就以为参数和结果被漏算了
    # —— 实测用户原话："代码以及论文里的参数以及部分结果不算？"
    # 其实参数在「参数一致性」、实验结果在「结果一致性」，各有归属。
    Category.DATA: "数据集一致性",
    Category.PARAM: "参数一致性",
    Category.RECORD: "实验记录完整度",
    Category.RESULT: "结果一致性",
}

# 每个维度**到底管什么** —— 未核验时必须说清，否则用户无从判断"是不是漏算了"
_SCOPE = {
    Category.DATA: "数据集与数据相关声明（数据源 / 版本 / 划分 / 预处理）",
    Category.PARAM: "超参数与模型配置（学习率 / 批大小 / 轮数 / 网络结构等）",
}

# 「未核验」的取值标记: None = 本次没做核验(与"得分 0"语义完全不同)
UNVERIFIED = None


def _code_present(code) -> bool:
    """代码包是否真的提供了可核验的内容。

    注意与"代码包存在但全是不支持的格式"区分: 后者也算提供了代码包,
    只是核验不了 —— 那种情况由覆盖率里的 unsupported 如实交代。
    """
    return bool(code.python_files or code.file_lines or code.requirements
                or code.params or code.multilang_files or code.unsupported
                or code.failed_files)


def compute_readiness(audit: AuditResult) -> dict:
    """输出 {'total': int, 'categories': {标签: int|None}, 'unverified': {标签: 原因}}"""
    cat_scores: dict[Category, object] = {c: 100 for c in Category}
    cat_has_finding: dict[Category, bool] = {c: False for c in Category}
    cat_has_vlm: dict[Category, bool] = {c: False for c in Category}   # 只有读图结论的维度
    unverified: dict[str, str] = {}

    for f in audit.findings:
        # AI 读图得到的结论(未经文本层验证)不参与就绪度评分, 只作为线索呈现。
        # 但要**记下"该维度有内容、只是来自读图"** —— 否则下面会把它说成
        # "论文与代码里都没有可对照的内容"，那是**不实之词**（2026-09-29 发现并修）。
        if any(ev and getattr(ev, "parser", "") == "vlm" for ev in (f.paper, f.code)):
            cat_has_vlm[f.category] = True
            continue
        cat_has_finding[f.category] = True
        cat_scores[f.category] = max(0, cat_scores[f.category] - _PENALTY[f.risk])

    # ---- 环境: 要有代码包才谈得上"环境依赖信息是否完整"
    if _code_present(audit.code):
        cat_scores[Category.ENV] = 100 if audit.code.requirements else 60
    else:
        cat_scores[Category.ENV] = UNVERIFIED
        unverified[_CATEGORY_LABELS[Category.ENV]] = \
            "未提供代码包，无从核对环境依赖"

    # ---- 实验记录完整度 / 结果一致性: 两者都以"用户提供的实测结果"为前提
    if audit.user_results:
        cat_scores[Category.RECORD] = 100
        if not cat_has_finding[Category.RESULT]:
            cat_scores[Category.RESULT] = UNVERIFIED
            unverified[_CATEGORY_LABELS[Category.RESULT]] = \
                "已提供实测结果，但论文未声明可对照的指标（accuracy / loss 等），无可比对项"
    else:
        cat_scores[Category.RECORD] = UNVERIFIED
        unverified[_CATEGORY_LABELS[Category.RECORD]] = \
            "本次未提供实测结果，无从评估实验记录是否完整"
        cat_scores[Category.RESULT] = UNVERIFIED
        unverified[_CATEGORY_LABELS[Category.RESULT]] = \
            "本次未提供实测结果，结果一致性未核验"

    # ---- 参数 / 数据集: 一次比对都没做 -> 未核验
    # 注意: 真正比过的参数**会留下结论**(相同的也留, Status.CONSISTENT),
    # 所以"这个维度一条结论都没有"就等于"这个维度没有可比对项"。
    # 从前这种情况显示 100 分 —— 同样是"没核验却像满分"。
    #
    # 提示语必须**说清这个维度管什么**，否则用户看到"未核验"会以为"参数和结果被漏算了"
    # （2026-09-29 实测：用户就问过"代码以及论文里的参数以及部分结果不算？"）。
    # 并且要区分两种"没有结论"：**真的没有** vs **只有读图推断**（后者不能说"都没有"）。
    for _c in (Category.PARAM, Category.DATA):
        if cat_has_finding[_c] or cat_scores[_c] is UNVERIFIED:
            continue
        cat_scores[_c] = UNVERIFIED
        if cat_has_vlm[_c]:
            unverified[_CATEGORY_LABELS[_c]] = (
                f"该维度只比对{_SCOPE[_c]}；本次这类内容**只来自读图推断**，"
                "未经文本层验证、按规则不计入评分 —— 请核对原图确认")
        else:
            unverified[_CATEGORY_LABELS[_c]] = (
                f"该维度只比对{_SCOPE[_c]}；本次论文与代码里都没有这类内容，"
                "因此没有可比对的项（参数与实验结果另有专属维度，不在此处）")

    # 总分 = **已核验**维度取均值。未核验的维度既不进分子也不进分母,
    # 避免"没上传材料"被算成"论文的缺陷"。
    # 一条都没核验时总分为 None（界面显示「—」）—— 不能报 100, 那是凭空给分。
    active = [c for c in Category if cat_scores[c] is not UNVERIFIED]
    total = round(sum(cat_scores[c] for c in active) / len(active)) if active else None

    dominant = [
        f.display_name for f in audit.findings
        if f.risk in (Risk.HIGH, Risk.MEDIUM) and f.status != Status.CONSISTENT
    ][:3]

    readiness = {
        "total": total,
        "categories": {_CATEGORY_LABELS[c]: cat_scores[c] for c in Category},
        "unverified": unverified,
        "dominant_issues": dominant,
    }

    # 审计可信度(与就绪度严格区分): 就绪度评价被审对象, 可信度评价本次审计本身
    cov = audit.coverage or {}
    if cov:
        readiness["audit_confidence"] = {
            "level": cov.get("confidence_level", "未知"),
            "score": cov.get("confidence_score"),
            "notes": cov.get("confidence_notes", []),
        }

    audit.readiness = readiness
    return readiness
