"""审计报告生成——Markdown 模板(浏览器打印即 PDF)。

报告结构(含交叉审查章节):
就绪度 -> 解析覆盖与可信度 -> 审计概览 -> 逐项详情 -> 解析拒收清单
-> 审计自检(证据自证) -> 附录(比较日志)
"""

from __future__ import annotations

from datetime import datetime

from .models import AuditResult, Finding, Status
from .synonyms import PARAM_SYNONYMS

_DISPLAY = {k: v[0] for k, v in PARAM_SYNONYMS.items()}

_STATUS_ICON = {
    Status.CONSISTENT: "🟢",
    Status.INCONSISTENT: "🔴",
    Status.MISSING_IN_CODE: "🟡",
    Status.MISSING_IN_PAPER: "🟡",
    Status.NOT_FIXED: "🟠",
    Status.UNVERIFIABLE: "🔵",
    Status.INTERNAL_INCONSISTENT: "🟣",
}
_STATUS_ZH = {
    Status.CONSISTENT: "一致",
    Status.INCONSISTENT: "不一致",
    Status.MISSING_IN_CODE: "代码未找到",
    Status.MISSING_IN_PAPER: "论文未声明",
    Status.NOT_FIXED: "未固定",
    Status.UNVERIFIABLE: "动态确定·无法静态验证",
    Status.INTERNAL_INCONSISTENT: "内部不一致",
}
_CONF_ZH = {"confirmed": "🟢 Confirmed(规则验证)", "inferred": "🔵 Inferred(AI 推断)"}
_RISK_ZH = {"high": "高", "medium": "中", "low": "低", "none": "—"}

# 状态释义: 让读者不用查文档就知道这条结论意味着什么
_STATUS_MEANING = {
    Status.CONSISTENT: "论文声明值与代码实现值经归一化后相等, 规则验证通过。",
    Status.INCONSISTENT: "论文声明值与代码实现值经归一化后不相等——这是本次审计的核心风险, "
                         "通常会导致实验无法复现出论文指标。",
    Status.MISSING_IN_CODE: "论文明确声明了该参数, 但静态扫描未在代码中找到对应实现"
                            "(既非命名赋值也非内联判定)。可能由框架默认值/外部配置注入, 或确实被遗漏。",
    Status.MISSING_IN_PAPER: "代码中存在该配置, 但论文未声明——表现为实验记录不完整, "
                             "他人复现时无法得知该取值依据。",
    Status.NOT_FIXED: "论文要求固定该随机性来源, 但代码中未找到固定动作, 实验结果不可稳定复现。",
    Status.UNVERIFIABLE: "代码中的取值由运行时变量/外部输入决定, 无法静态验证; "
                         "系统如实标注而非猜测, 需查运行配置确认。",
    Status.INTERNAL_INCONSISTENT: "同一载体(论文或代码)内部出现多个不同取值, 存在自相矛盾; "
                                  "若属灵敏度分析/分组实验可忽略。",
}

# 结果类结论的释义(对照侧是"用户上传的实测结果", 不是代码实现)
_RESULT_MEANING = {
    Status.CONSISTENT: "论文声明的实验结果与上传的实测结果一致(相对差异 ≤1%), 复现结果可信。",
    Status.INCONSISTENT: "论文声明的实验结果与上传的实测结果存在明显差异——"
                         "说明实际复现未能达到论文指标, 需结合参数差异定位原因。",
}
_CHECK_HINT = {
    Status.CONSISTENT: "无需人工干预; 如需引用可将本项作为「已核对」证据。",
    Status.INCONSISTENT: "建议人工确认以哪一侧为准: 先看代码是否为论文对应的实验配置, "
                         "再决定修改代码还是修正论文描述。",
    Status.MISSING_IN_CODE: "建议在训练入口显式声明该参数并与论文对齐; "
                            "若确认由框架默认值提供, 请在论文/README 中注明。",
    Status.MISSING_IN_PAPER: "建议在论文或 README 中补充该配置, 便于他人复现。",
    Status.NOT_FIXED: "建议在训练入口显式固定随机种子(如 torch.manual_seed / random_state)。",
    Status.UNVERIFIABLE: "建议核对实际运行配置(命令行参数/环境变量/日志)后再判断是否一致。",
    Status.INTERNAL_INCONSISTENT: "建议确认哪一处是实际生效的配置; 若为多组实验请分别标注。",
}


def _finding_md(f: Finding) -> str:
    _is_result = f.param_key.startswith("result_")
    _meaning = (_RESULT_MEANING if _is_result else _STATUS_MEANING).get(f.status, "")
    lines = [f"### {_STATUS_ICON[f.status]} {f.display_name} — {_STATUS_ZH[f.status]}",
             "",
             f"**结论释义**: {_meaning}",
             "",
             f"**风险等级**: {_RISK_ZH[f.risk.value]}　"
             f"**置信**: {_CONF_ZH[f.confidence.value]}　"
             f"**证据自证**: {'✅ 通过' if f.verified else '❌ 未通过'}",
             ""]
    if f.risk_reason:
        lines += [f"**风险判定依据**: {f.risk_reason}", ""]
    lines += ["#### 证据链",
              ""]
    if f.paper:
        lines += [
            f"- **论文侧证据**: `{f.paper.location}`",
            f"  > {f.paper.snippet}",
            f"  - 声明值: `{f.paper.raw_value}`"
            + (f"　归一化后: `{f.paper.normalized}`" if f.paper.normalized is not None else ""),
        ]
    else:
        lines.append("- **论文侧证据**: 未声明(论文中未找到该参数的数值)")
    if f.code:
        if _is_result:
            lines += [
                f"- **对照侧证据(用户上传实测结果)**: `{f.code.location}`",
                f"  > {f.code.snippet}",
                f"  - 实测值: `{f.code.raw_value}`"
                + (f"　归一化后: `{f.code.normalized}`" if f.code.normalized is not None else ""),
            ]
        else:
            lines += [
                f"- **代码侧证据**: `{f.code.location}`",
                f"  > {f.code.snippet}",
                f"  - 实现值: `{f.code.raw_value}`"
                + (f"　归一化后: `{f.code.normalized}`" if f.code.normalized is not None else ""),
            ]
    else:
        lines.append("- **代码侧证据**: 未找到(静态扫描未命中)")
    for i, ev in enumerate(f.extra, 1):
        lines.append(f"- **附加证据 {i}**({ev.source}): `{ev.location}`"
                     f"　> {ev.snippet}　- 值: `{ev.raw_value}`")
    lines.append("")
    lines.append("#### 比对过程")
    lines.append("")
    if _is_result and f.paper and f.code:
        try:
            pv, av = float(f.paper.normalized), float(f.code.normalized)
            _d = abs(av - pv)
            _rel = _d / max(abs(pv), 1e-12)
            lines.append(f"- 结果核对: 论文声明 `{pv}` vs 实测 `{av}` → 绝对差异 `{_d:.4g}`、"
                         f"相对差异 `{_rel:.2%}`"
                         + ("（≤1% 视为一致）" if f.status == Status.CONSISTENT
                            else "（>1% 判定不一致）"))
        except (TypeError, ValueError):
            lines.append(f"- 结果核对: 论文声明 `{f.paper.raw_value}` "
                         f"vs 实测 `{f.code.raw_value}`")
    elif f.paper and f.code and f.status == Status.INCONSISTENT:
        lines.append(f"- 归一化对比: `{f.paper.normalized}` ≠ `{f.code.normalized}` "
                     f"→ 判定 **不一致**(差异见上表原文, 可直接复算)")
    elif f.paper and f.code and f.status == Status.CONSISTENT:
        lines.append(f"- 归一化对比: `{f.paper.normalized}` = `{f.code.normalized}` "
                     "→ 判定 **一致**(规则验证通过)")
    elif f.status == Status.UNVERIFIABLE:
        lines.append("- 代码侧取值由运行时变量决定, 静态分析无法给出确定值 → 标记为"
                     " **动态确定·无法静态验证**(不计入评分)")
    elif f.status == Status.INTERNAL_INCONSISTENT:
        lines.append("- 同一载体内出现多个不同取值 → 标记为 **内部不一致**"
                     "(灵敏度分析/分组实验为有意为之, 可忽略)")
    elif f.status == Status.MISSING_IN_CODE:
        lines.append("- 论文侧有值、代码侧无证据 → 标记为 **代码未找到**(中风险, 需人工确认)")
    elif f.status == Status.MISSING_IN_PAPER:
        lines.append("- 代码侧有值、论文侧无声明 → 标记为 **论文未声明**(实验记录完整度扣分)")
    elif f.status == Status.NOT_FIXED:
        lines.append("- 论文要求固定随机性、代码无固定动作 → 标记为 **未固定**")
    lines.append("")
    lines.append("#### 证据自证与人工核查")
    lines.append("")
    if f.verified:
        vfy_txt = "✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现"
    else:
        vfy_txt = f"❌ 未通过——{f.verify_note}"
    lines.append(f"- 证据自证: {vfy_txt}")
    lines.append(f"- **人工核查建议**: {_CHECK_HINT.get(f.status, '')}")
    if f.note:
        lines.append(f"- 系统说明: {f.note}")
    parsers = {ev.parser for ev in ([f.paper, f.code] + list(f.extra)) if ev}
    if parsers - {"ast"}:
        zh = {"ast": "Python AST 精确解析", "regex": "多语言通用通道(正则)",
              "table": "PDF 表格通道", "ocr": "图像 OCR", "vlm": "视觉模型读图",
              "text": "PDF 正文文本", "result": "用户上传实测结果"}
        lines.append("- 抽取通道: " + "、".join(zh.get(p, p) for p in sorted(parsers)))
    if f.ai_analysis:
        lines += ["", f"**AI 归因分析**: {f.ai_analysis}"]
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def generate_report(audit: AuditResult) -> str:
    """生成完整 Markdown 审计报告。"""
    r = audit.readiness or {}
    cats = r.get("categories", {})
    cov = audit.coverage or {}
    img = cov.get("image") or {}
    sc = audit.selfcheck or {}
    n_issue = sum(1 for f in audit.findings if f.status != Status.CONSISTENT)
    n_ok = len(audit.findings) - n_issue

    parts = [
        "# Paper2Lab 科研实验一致性审计报告",
        "",
        f"- 论文: **{audit.paper.title or '(未识别标题)'}**",
        f"- 审计时间: {datetime.now():%Y-%m-%d %H:%M}",
        f"- 论文页数: {audit.paper.page_count}　代码文件: {audit.code.python_files} 个(含 notebook cell)",
        f"- 本次审计可信度: **{cov.get('confidence_level', '—')}**"
        f"(得分 {cov.get('confidence_score', '—')}/100)",
        "",
        "---",
        "",
        f"## 复现就绪度: {'—' if r.get('total') is None else r.get('total')} / 100",
        "",
        "> 就绪度评价**被审对象**的可复现程度; 审计可信度评价**本次审计过程**的覆盖与可靠程度, 两者独立。",
        "",
        "| 维度 | 得分 |",
        "| --- | --- |",
    ]
    for k, v in cats.items():
        parts.append(f"| {k} | {'**未核验**' if v is None else v} |")
    parts += [""]
    unv = r.get("unverified") or {}
    if unv:
        parts.append("**「未核验」说明**: 该维度本次没有可比对的对象, **不计入总分**, "
                     "既不是扣分也不代表通过。")
        parts.append("")
        for k, why in unv.items():
            parts.append(f"- **{k}**：{why}")
        parts.append("")
    if r.get("dominant_issues"):
        parts.append("**当前阻碍复现的主要因素**: " + "、".join(r["dominant_issues"]))
        parts.append("")

    # ---- 解析覆盖与可信度(交叉审查: 明确"抽没抽到")
    parts += [
        "---",
        "",
        "## 解析覆盖与审计可信度",
        "",
        "| 项目 | 数值 |",
        "| --- | --- |",
        f"| 论文内容覆盖(全通道) | {cov.get('pages_covered', 0)} / {cov.get('pages_total', 0)}"
        f"({(cov.get('pages_cover_ratio') or 0):.0%})"
        + (f"，其中读图覆盖 {cov.get('pages_covered_by_vision')} 页"
           if cov.get("pages_covered_by_vision") else "") + " |",
        f"| 其中文本层可解析页 | {cov.get('pages_parsed', 0)} / {cov.get('pages_total', 0)} |",
        f"| 其中薄页(图表/公式/扫描区) | {cov.get('pages_thin', 0)} |",
        f"| 论文参数种类覆盖 | {cov.get('kinds_valued', 0)} / {cov.get('kinds_seen', 0)} 类"
        f"({(cov.get('kinds_ratio') or 0):.0%}) |",
        f"| 文中疑似声明句式(参考) | {cov.get('decl_total', 0)} 处, 结构化 {cov.get('decl_matched', 0)} 处 |",
        f"| 代码文件成功解析 | {cov.get('code_ok', 0)} / {cov.get('code_files', 0)} |",
        f"| 代码文件解析失败 | {cov.get('code_failed', 0)} |",
        f"| 多语言通用通道(非 Python) | {len(cov.get('multilang') or [])} 个文件 |",
        f"| 图像/扫描区域 | {img.get('regions', 0)} / 候选 {img.get('candidates', 0)} 个"
        + ("(该论文无位图/扫描区域, 图形均为矢量图, 文本层已覆盖)"
           if not img.get("candidates")
           else ("(已读图 " + str(img.get("regions_read", 0)) + " 个)"
                 if img.get("enabled") else "(图像通道未启用)"))
        + " |",
        f"| 文件格式无法处理 | {len(cov.get('unsupported') or [])} 个 |",
        "",
    ]
    # 各类参数的取值来自哪条通道(让"抽到了"也有出处, 不只是"没抽到"才说)
    kbc = cov.get("kinds_by_channel") or {}
    if any(kbc.values()):
        seg = []
        if kbc.get("text"):
            seg.append(f"正文/shell 等文本通道 {len(kbc['text'])} 类"
                       f"({', '.join(kbc['text'])})")
        if kbc.get("table"):
            seg.append(f"PDF 表格通道 {len(kbc['table'])} 类({', '.join(kbc['table'])})")
        if kbc.get("vision"):
            seg.append(f"视觉读图通道 {len(kbc['vision'])} 类({', '.join(kbc['vision'])})")
        if kbc.get("agent"):
            seg.append(f"**抽取 Agent 补漏** {len(kbc['agent'])} 类({', '.join(kbc['agent'])})")
        parts.append("**取值来源分布**: " + "; ".join(seg) + "。")
        parts.append("")
    if not img.get("regions"):
        pass
    elif not img.get("enabled"):
        parts.append("⚠️ **图像通道未启用**: 论文中发现 "
                     f"{img.get('regions')} 个图片/扫描区域, 但未配置视觉模型 key —— "
                     "这些区域的内容**未参与本次审计**。")
        parts.append("")
    else:
        parts.append(f"**图像通道**(视觉模型 {img.get('model', '—')}, 读图 "
                     f"{img.get('regions_read', 0)} 个区域; 采信 {img.get('kept', 0)} 条, "
                     f"丢弃 {img.get('dropped', 0)} 条):")
        parts.append("- AI 只提议: 读图结果必须附图中原文; 同一区域**两次独立读图取交集**, "
                     "只保留两次一致的值; 该通道结论标为 🔵 Inferred 且**不计入就绪度评分**。")
        for n in img.get("notes", []):
            parts.append(f"- 提示: {n}")
        parts.append("")

    # ---- 抽取 Agent 轨迹(第一期): 每一次尝试都留痕, 可回放
    ag = cov.get("agent") or {}
    if ag:
        steps = ag.get("steps") or []
        filled = ag.get("filled") or {}
        parts += ["**抽取 Agent(第一期)**: "
                  f"待补 {len(ag.get('targets') or [])} 类参数, 补回 {len(filled)} 类; "
                  f"共 {len(steps)} 步尝试, 消耗 LLM {ag.get('budget', {}).get('llm_calls', 0)} 次、"
                  f"耗时 {ag.get('budget', {}).get('seconds', 0)}s; "
                  f"结束原因: {ag.get('stopped_reason', '—')}",
                  "",
                  "> 机制: 每个待补参数按「文本紧邻 → 文本近邻 → 否定式 → LLM 提议 → 聚焦读图」"
                  "逐级尝试; **任一候选都必须过闸门**（回原文核对 + 取值在证据中 + 合理性先验）"
                  "才能入库, 否则丢弃并留痕。宁可不报, 也不报一个可能错的值。",
                  ""]
        if steps:
            parts += ["| # | 参数 | 工具 | 结果 | 取值 | 页 | 说明 |",
                      "| --- | --- | --- | --- | --- | --- | --- |"]
            for s in steps:
                parts.append(f"| {s.get('seq')} | {s.get('display')} | {s.get('tool')} | "
                             f"{s.get('status')} | {s.get('value') or '—'} | "
                             f"{s.get('page') or '—'} | "
                             f"{(s.get('note') or '').replace('|', '/')[:90]} |")
            parts.append("")
        if filled:
            parts.append("**Agent 补回的取值(均已过闸门)**:")
            for k, v in filled.items():
                parts.append(f"- `{k}` = `{v}`")
            parts.append("")

    if cov.get("multilang"):
        parts.append("**多语言通用通道解析的文件**(MATLAB/R/C++/Julia/Fortran/Shell/INI/TOML 等, "
                     "正则通道, 置信度降级):")
        for m in cov["multilang"]:
            parts.append(f"- `{m['file']}` ({m['lang']}) — 抽取参数 {m['params']} 处")
        parts.append("")
    if cov.get("confidence_notes"):
        parts.append("**可信度扣分原因**:")
        for n in cov["confidence_notes"]:
            parts.append(f"- {n}")
        parts.append("")
    if cov.get("kinds_unmatched"):
        parts.append(f"**论文提到但未取到数值的参数种类**: "
                     + "、".join(_DISPLAY.get(k, k) for k in cov["kinds_unmatched"]))
        parts.append("(这些种类的值在**所有通道**里都没取到: 正文句式未匹配、表格/图片里也没有。"
                     "若确认它们出现在图片区域, 可调大读图区域上限后重跑。)")
        parts.append("")
    if cov.get("thin_page_list"):
        parts.append(f"**文本稀薄页清单**: 第 {', '.join(map(str, cov['thin_page_list']))} 页"
                     "(文字层极少, 无法走文本解析)")
        _tread = cov.get("thin_pages_read") or []
        _tunread = cov.get("thin_pages_unread") or []
        if _tread:
            parts.append(f"- ✅ 已由**视觉读图**覆盖: 第 {', '.join(map(str, _tread))} 页")
        if _tunread:
            parts.append(f"- ⚠️ **未读图**: 第 {', '.join(map(str, _tunread))} 页 —— "
                         + (cov.get("thin_unread_reason") or "未参与审计"))
        parts.append("")
    if cov.get("code_failed_list"):
        parts.append("**解析失败文件(其内容未参与审计)**:")
        for ff in cov["code_failed_list"]:
            parts.append(f"- `{ff['file']}` — {ff['reason']}, {ff['lines']} 行")
        parts.append("")
    if cov.get("unsupported"):
        parts.append("**本期无法处理的格式(已识别, 未参与审计)**:")
        for u in cov["unsupported"]:
            parts.append(f"- `{u['file']}` ({u['lang']})")
        parts.append("")

    # ---- 审计概览
    parts += [
        "---",
        "",
        f"## 审计概览: 发现 {n_issue} 项复现风险, {n_ok} 项一致",
        "",
        "| 参数 | 论文 | 代码/实际 | 状态 | 风险 | 自证 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for f in audit.findings:
        pv = f.paper.raw_value if f.paper else "—"
        cv = f.code.raw_value if f.code else "—"
        parts.append(
            f"| {f.display_name} | `{pv}` | `{cv}` | "
            f"{_STATUS_ICON[f.status]} {_STATUS_ZH[f.status]} | {_RISK_ZH[f.risk.value]} | "
            f"{'✅' if f.verified else '❌'} |")

    # ---- 逐项详情
    parts += ["", "---", "", "## 逐项审计详情(含证据链)", "",
              f"本节对全部 {len(audit.findings)} 项审计发现逐条给出: 结论释义 · 双侧证据"
              "(论文页码·章节 / 代码文件:行号 · 原文片段) · 比对过程 · 证据自证 · 人工核查建议。", ""]
    for f in audit.findings:
        parts.append(_finding_md(f))

    # ---- 参数覆盖清单(解析透明度)
    pm = cov.get("param_matrix") or []
    if pm:
        hit = sum(1 for r in pm if str(r["是否进入比对"]).startswith("✓"))
        parts += ["---", "",
                  f"## 参数覆盖清单({len(pm)} 项已知参数: {hit} 项进入比对, "
                  f"{len(pm) - hit} 项未进入)", "",
                  "每一项写明「抽到了什么」或「为什么没抽到」, 不做「看起来都审过了」的假象:", "",
                  "| 参数 | 论文侧 | 代码侧 | 是否进入比对 | 状态 | 风险 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for r in pm:
            parts.append(f"| {r['参数']} | {r['论文侧']} | {r['代码侧']} | "
                         f"{r['是否进入比对']} | {r['状态']} | {r['风险']} |")
        parts.append("")

    # ---- 需人工核查清单
    mc = cov.get("manual_check") or []
    parts += ["---", "", f"## 需人工核查清单({len(mc)} 项)", "",
              "以下条目无法由程序单方面给出确定结论, 或存在未参与审计的内容 —— "
              "系统**不假装都已审过**, 请按下表逐项人工确认:", "",
              "| 级别 | 类别 | 对象 | 原因 | 建议动作 |",
              "| --- | --- | --- | --- | --- |"]
    for m in mc:
        parts.append(f"| {m['level']} | {m['kind']} | {m['item']} | {m['why']} | {m['action']} |")
    if not mc:
        parts.append("| — | — | — | 无 | 本次审计未产生需人工核查的条目 |")
    parts.append("")

    # ---- 未参与审计的部分(覆盖边界如实交代)
    not_covered: list[str] = []
    if img.get("regions") and not img.get("enabled"):
        not_covered.append(f"**图像/扫描区域 {img['regions']} 个**: 未配置视觉模型, 内容未参与审计")
    if img.get("enabled") and img.get("regions_read", 0) < img.get("regions", 0):
        not_covered.append(f"**图像区域 {img.get('regions', 0) - img.get('regions_read', 0)} 个**: "
                           "超出耗时预算未读图")
    for fl in cov.get("code_failed_list") or []:
        not_covered.append(f"**代码文件** `{fl['file']}`: {fl['reason']}")
    for u in cov.get("unsupported") or []:
        not_covered.append(f"**格式暂不支持** `{u['file']}` ({u['lang']})")
    if cov.get("thin_page_list"):
        _tread = cov.get("thin_pages_read") or []
        _tunread = cov.get("thin_pages_unread") or []
        not_covered.append(
            f"**论文文本稀薄页**: 第 {', '.join(map(str, cov['thin_page_list']))} 页"
            + (f"(其中第 {', '.join(map(str, _tread))} 页已由读图覆盖)" if _tread else "")
            + (f"; **未读图**: 第 {', '.join(map(str, _tunread))} 页 — "
               + (cov.get("thin_unread_reason") or "") if _tunread else ""))
    if cov.get("kinds_unmatched"):
        not_covered.append("**论文提到但未取到数值的参数种类**（所有通道均未取到）: "
                           + "、".join(_DISPLAY.get(k, k) for k in cov["kinds_unmatched"]))
    if cov.get("rejected"):
        not_covered.append(f"**被合理性校验拒收的抽取 {len(cov['rejected'])} 处**"
                           "(判定为错位抽取, 未纳入比对)")
    # ---- 执行计划与跨任务记忆(第二期)
    ex = getattr(audit, "execution_log", None) or {}
    if ex:
        _mode = ("计划模式(调度员按材料排计划)" if ex.get("mode") == "planned"
                 else "经典模式(固定全序执行)")
        parts += ["---", "", "## 执行计划", "",
                  f"- 执行模式: **{_mode}**",
                  f"- 执行 {ex.get('ran', 0)} 个工具 / 跳过 {ex.get('skipped', 0)} 个 / "
                  f"覆盖 {ex.get('nodes_total', 0)} 个进度节点 / 总耗时 {ex.get('seconds', 0)}s",
                  "",
                  "| 工具 | 结果 | 耗时 | 说明 |",
                  "| --- | --- | --- | --- |"]
        _mark = {"done": "执行", "skipped": "计划跳过", "failed": "失败"}
        for s in ex.get("steps", []):
            parts.append(f"| {s['title']} | {_mark.get(s['status'], s['status'])} "
                         f"| {s['seconds']}s | {s['reason'] or '—'} |")
        parts.append("")
        for n in ex.get("notes", []):
            parts.append(f"> {n}")
        if ex.get("notes"):
            parts.append("")
        from .toolbox import STEPS as _STEPS, TOOLS as _TOOLS
        parts.append(f"> {len(_STEPS)} 个进度节点由 {len(_TOOLS)} 件工具完成"
                     "——「参数归一化 / 交叉匹配 / 实验结果核验」"
                     "在实现上是同一次参数对齐的三个职责。")
        parts.append("")

    # ---- 分片并发记录(第二期第四批): 让"怎么调度"也可见
    sh = (audit.readiness or {}).get("llm_shards") or {}
    if sh and sh.get("total"):
        _mode = "分片并发" if sh.get("mode") == "sharded" else "串行"
        parts += [f"> **AI 归因调度**：{_mode}"
                  + (f"（{sh.get('workers')} 路）" if sh.get("mode") == "sharded" else "")
                  + f"，处理 {sh.get('total')} 条，耗时 {sh.get('seconds')}s"
                  + (f"，失败 {sh.get('failed')} 条" if sh.get("failed") else "")
                  + "。每片仍是一条独立调用（prompt 里只有该条自己的证据），"
                    "上下文互不干扰；结果**保序**，与串行逐字一致。", ""]

    # ---- 读图通道的分片记录(同上, 让"怎么调度"可见)
    _vsh = ((audit.coverage or {}).get("image") or {}).get("shard") or {}
    if _vsh and _vsh.get("total"):
        _vmode = "分片并发" if _vsh.get("mode") == "sharded" else "串行"
        parts += [f"> **读图调度**：{_vmode}"
                  + (f"（{_vsh.get('workers')} 路）" if _vsh.get("mode") == "sharded" else "")
                  + f"，处理 {_vsh.get('total')} 个区域，耗时 {_vsh.get('seconds')}s"
                  + (f"，失败 {_vsh.get('failed')} 个" if _vsh.get("failed") else "")
                  + "。每个区域仍是**两次独立读图取交集**，区域顺序与结果均保序。", ""]

    # ---- 待确认问题(第二期第二批): 把"系统说不清的地方"交回给用户
    try:
        from .inquiry import KIND_LABEL, build_questions
        qs = build_questions(audit)
    except Exception:      # noqa: BLE001
        qs = []
    if qs:
        parts += ["---", "", f"## 待确认问题({len(qs)} 项, 需要你判断)", "",
                  "> 这些问题系统**无法自行判断**，也不会替你猜答案。页面「待确认问题」面板"
                  "可直接填写答复，答复会作为**人工确认记录**附在本报告里"
                  "（只记录，不自动改写任何结论）。", ""]
        for i, q in enumerate(qs, 1):
            parts.append(f"**{i}. [{KIND_LABEL.get(q.kind, q.kind)}] {q.title}**")
            parts.append("")
            parts.append(f"- 为什么问: {q.basis}")
            for e in q.evidence:
                parts.append(f"- 依据: {e}")
            if q.suggestions:
                parts.append(f"- 可能的答复: {' / '.join(q.suggestions)}")
            parts.append(f"- 不回答的影响: {q.impact}")
            parts.append("")
    if getattr(audit, "clarifications", None):
        parts += ["### 人工确认记录", "",
                  "| 待确认问题 | 用户答复 | 记录时间 |", "| --- | --- | --- |"]
        for c in audit.clarifications:
            parts.append(f"| {c.get('question', '')} | {c.get('answer', '')} "
                         f"| {c.get('time', '')} |")
        parts.append("")

    parts += ["---", "", f"## 未参与本次审计的部分({len(not_covered)} 项)", "",
              "审计结论只覆盖**已成功解析**的内容; 以下部分未参与比对, 不应被视为「已核对」:", ""]
    if not_covered:
        for x in not_covered:
            parts.append(f"- {x}")
    else:
        parts.append("- 无: 本次审计的载体内容已全部纳入解析")
    parts.append("")

    # ---- 被拒收的抽取(合理性校验示众)
    if cov.get("rejected"):
        parts += ["---", "", "## 被合理性校验拒收的抽取", "",
                  "以下数值超出该参数的领域先验范围, 判定为错位抽取, 未纳入审计:",
                  ""]
        for rj in cov["rejected"]:
            parts.append(f"- `{rj['key']}` = `{rj['value']}` @ {rj['location']} — {rj['reason']}")
        parts.append("")

    # ---- 审计自检
    if sc:
        parts += [
            "---",
            "",
            "## 审计自检(证据自证与结论回放)",
            "",
            f"- 校验发现数: {sc.get('checked', 0)}",
            f"- 自证通过: {sc.get('passed', 0)}",
            f"- 自证未通过: {sc.get('failed', 0)}",
            "",
        ]
        if sc.get("failures"):
            parts.append("**未通过清单(结论需人工复核)**:")
            for fl in sc["failures"]:
                parts.append(f"- {fl['param']}: {'；'.join(fl['reasons'])}")
            parts.append("")
        else:
            parts.append("全部结论均通过证据自证与结论复算: 每条证据的原文片段中确实包含所声明的值, "
                         "且一致性结论可由归一化比较复现。")
            parts.append("")

    # ---- 根因追查 + 补丁草案（第三期 3.2 / 3.3）
    # 这两节由工具箱的 rootcause / patch 两站产出，是"报告的下一步"：
    # 用户看完结论的第一个问题就是"那到底该改哪一行"，而在此之前它俩只出现在 CLI 汇总里。
    traces = list(getattr(audit, "rootcause", None) or [])
    patches = list(getattr(audit, "patches", None) or [])
    if traces:
        located = [t for t in traces if getattr(t, "confidence", "none") != "none"]
        parts += [
            "---", "",
            f"## 根因追查（{len(located)} / {len(traces)} 项可定位）", "",
            "> 论文与代码不一致时，同一参数在代码里常有多处赋值。本节从这些赋值点中判断"
            "**最终生效**的那一个（**只读代码，不修改任何文件**）；判断不了的"
            "**明说「无法定位」，绝不猜**。", "",
            "| 参数 | 最终生效值 | 位置 | 置信 | 依据 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for t in traces:
            if getattr(t, "confidence", "none") == "none":
                parts.append(f"| {t.display} | — | — | **无法定位** | {t.reason} |")
            else:
                parts.append(f"| {t.display} | `{t.verdict}` | `{t.verdict_loc}` "
                             f"| {t.confidence} | {t.reason} |")
        parts.append("")
    if patches:
        def _is_prop(p) -> bool:
            # PatchProposal 是 dataclass，`p in list` 会走**逐字段相等**——
            # 两条内容相同的提案会被判成"同一个"，所以一律用 status 判定，不用成员测试。
            return bool(getattr(p, "is_proposed", getattr(p, "status", "") == "proposed"))
        proposed = [p for p in patches if _is_prop(p)]
        refused = [p for p in patches if not _is_prop(p)]
        n_ai = sum(1 for p in proposed if getattr(p, "source", "rule") == "llm")
        parts += [
            "---", "",
            f"## 补丁草案（给方案 {len(proposed)} 条 ｜ 拒绝 {len(refused)} 条）"
            + (f"　其中 **{n_ai} 条的目标由 AI 提名**（见标注，采纳前须人工确认）" if n_ai else ""),
            "",
            "> **只展示，绝不落盘**：本报告不会改动任何代码文件，是否采纳由你决定。"
            "只改**值**、且只对**配置项**；拿不准的一律拒绝并写明理由 —— "
            "宁可不给，也不给一个可能改错的方案。", "",
        ]
        for p in proposed:
            tag = ("### ⚠️ " if getattr(p, "source", "rule") == "llm" else "### ✅ ")
            parts += [f"{tag}{p.display} @ `{p.target}`", "",
                      "```diff", (p.diff or "").strip(), "```",
                      f"- 依据: {p.rationale}"]
            if getattr(p, "stamps", None):
                parts.append("- 程序盖章清单:")
                for s in p.stamps:
                    parts.append(f"  - {s}")
            parts.append("")
        if refused:
            parts += [f"**拒绝的补丁（{len(refused)} 条，逐条写明理由）**", ""]
            for p in refused:
                parts.append(f"- **{p.display}** —— {p.refuse_reason}")
            parts.append("")

    # ---- 附录
    if audit.compare_log:
        parts += ["---", "", "## 附录: 程序比较日志", "",
                  "所有一致性判定均由程序完成, 以下为完整比较记录(可逐条复核):", "",
                  "```text"]
        parts += audit.compare_log
        parts += ["```", ""]

    parts += [
        "---",
        "",
        "## 审计说明",
        "",
        "本报告由 Paper2Lab 自动生成。一致性判断由程序化规则验证完成"
        "(AST 静态分析 + 数值归一化比对), AI 仅负责风险解释与归因。"
        "报告中的每一条结论都经过: ① 合理性先验校验(拒收错位抽取) "
        "② 证据自证(原文片段必须包含所声明的值) ③ 结论复算(归一化比较可重现)。"
        "本期审计范围为可自动验证的数值/配置一致性, 语义级方法审计属于产品路线图。",
    ]
    return "\n".join(parts)
