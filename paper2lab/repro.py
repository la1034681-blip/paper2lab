"""复现准备清单（第三期 3.1）——把审计结果整理成"照着做就能开始复现"的一份清单。

**为什么做这个**：审计报告回答的是"哪里有问题"，而拿到报告的人下一步要做的是**动手复现**。
两者之间隔着一堆琐碎工作——装什么依赖、按哪个值配、数据怎么准备、哪些事必须先问清楚。
这一步就是把这堆琐事一次性整理好。

**三条约束**：
1. **每个数值都附出处**（论文第几页 / 代码哪个文件第几行），不出现"无来源的断言"；
2. **不一致的项不替用户拍板**：给出默认建议（按论文声明，因为复现的目标是复现论文），
   同时说明"若你的目标是复现代码的实际行为，则按代码值"；
3. **未确认的事显式列出**：承接澄清反问的「待确认问题」，变成「复现前必须确认的事」，
   而不是悄悄略过 —— 这与第一期"宁可不报"同源：**宁可把不确定写出来，也不假装确定**。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import AuditResult, Risk, Status

# 状态 -> 复现建议（保守优先：拿不准就让用户确认，不替他拍板）
_ADVICE = {
    Status.CONSISTENT: "按此值配置即可（论文与代码一致）。",
    Status.INCONSISTENT: "**需你确认**：默认按**论文声明**配置；"
                         "若你的目标是复现代码的实际行为，则按代码值。",
    Status.MISSING_IN_CODE: "论文声明了但代码里没有 —— 复现时请手动补上该配置。",
    Status.MISSING_IN_PAPER: "代码里有但论文未声明 —— 可能是实现细节，建议保留。",
    Status.UNVERIFIABLE: "代码里是运行时变量，无法静态确认 —— 建议实际跑一次打印出来核对。",
    Status.INTERNAL_INCONSISTENT: "论文或代码内部多处声明互相矛盾 —— 需人工判断哪处是最终生效值。",
    Status.NOT_FIXED: "论文要求固定但代码未固定 —— 建议补上，否则结果不可复现。",
}


@dataclass
class ReproPack:
    title: str = ""
    env: dict = field(default_factory=dict)
    params: list = field(default_factory=list)
    data_notes: list = field(default_factory=list)
    must_confirm: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    confidence: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title, "env": self.env, "params": self.params,
            "data_notes": self.data_notes, "must_confirm": self.must_confirm,
            "risks": self.risks, "confidence": self.confidence,
            "notes": self.notes,
        }

    def to_markdown(self) -> str:
        e = self.env or {}
        c = self.confidence or {}
        md: list[str] = [
            f"# 复现准备清单 —— 《{self.title or '(未识别标题)'}》",
            "",
            "> 本清单由 Paper2Lab 从论文与代码自动整理。**每一个数值都附出处**；",
            "> 标 ⚠️ 的项表示论文与代码不一致，**需要你判断以哪个为准**（系统不替你拍板）。",
            "",
            "---",
            "",
            "## 一、环境准备",
            "",
        ]
        deps = e.get("python_deps") or {}
        if deps:
            md += ["| 依赖 | 版本 |", "| --- | --- |"]
            for k, v in deps.items():
                md.append(f"| {k} | {v or '未指定'} |")
            md.append("")
        else:
            md += ["- 代码中未发现 `requirements.txt` / `environment.yml`，依赖需自行确认。", ""]
        md += [
            f"- 代码规模：**{e.get('code_files', 0)}** 个可解析文件",
        ]
        if e.get("langs"):
            md.append(f"- 涉及语言：{'、'.join(e['langs'])}")
        if e.get("failed_files"):
            md.append(f"- ⚠️ **{len(e['failed_files'])} 个文件解析失败**（内容未参与审计）：")
            for f in e["failed_files"][:8]:
                md.append(f"  - `{f.get('file')}` —— {f.get('reason')}")
        if e.get("unsupported"):
            md.append(f"- ⚠️ {len(e['unsupported'])} 个文件格式暂不支持，未纳入审计。")
        md.append("")

        md += ["## 二、关键超参对照表", "",
               "| 参数 | 论文声明 | 代码实现 | 状态 | 复现建议 |",
               "| --- | --- | --- | --- | --- |"]
        for p in self.params:
            ps = f"`{p['paper']}`" + (f"<br><sub>{p['paper_src']}</sub>" if p.get("paper_src") else "")
            cs = f"`{p['code']}`" + (f"<br><sub>{p['code_src']}</sub>" if p.get("code_src") else "")
            flag = "⚠️ " if p.get("status") not in ("consistent",) else ""
            md.append(f"| {flag}{p['name']} | {ps} | {cs} | {p.get('status_label', p['status'])} "
                      f"| {p['advice']} |")
        md.append("")

        if self.data_notes:
            md += ["## 三、数据准备", ""] + [f"- {n}" for n in self.data_notes] + [""]

        md += ["## 四、复现前必须确认的事", ""]
        if self.must_confirm:
            for q in self.must_confirm:
                md.append(f"- [ ] **{q.get('title')}** —— {q.get('basis', '')[:90]}")
            md.append("")
            md.append("> 这些是系统**无法自行判断**的问题。你确认后，清单里的建议取值才最终确定；"
                      "系统不会替你猜答案。")
        else:
            md.append("- 无。材料齐备，未发现需要人工判断的问题。")
        md.append("")

        md += ["## 五、已知风险（按严重程度排序）", ""]
        if self.risks:
            md += ["| 风险 | 参数 | 状态 | 说明 |", "| --- | --- | --- | --- |"]
            for r in self.risks[:15]:
                md.append(f"| {r['risk']} | {r['name']} | {r['status_label']} | {r['note']} |")
            if len(self.risks) > 15:
                md.append(f"| … | | | 其余 {len(self.risks) - 15} 条见完整审计报告 |")
        else:
            md.append("- 无。")
        md.append("")

        md += ["## 六、本次审计的可信度", "",
               f"- 论文内容覆盖：{c.get('pages_covered', 0)} / {c.get('pages_total', 0)} 页"
               f"（其中读图覆盖 {c.get('pages_covered_by_vision', 0)} 页）",
               f"- 代码文件成功解析：{c.get('code_ok', 0)} / {c.get('code_files', 0)}",
               f"- 证据自证：{c.get('selfcheck_passed', 0)} / {c.get('selfcheck_checked', 0)} 通过",
               f"- 审计可信度：**{c.get('level', '—')}**（{c.get('score', '—')}/100）",
               ""]
        if self.notes:
            md += ["---", "", "## 说明", ""] + [f"- {n}" for n in self.notes]
        return "\n".join(md)


_STATUS_LABEL = {
    "consistent": "一致",
    "inconsistent": "不一致",
    "missing_in_code": "代码缺",
    "missing_in_paper": "论文缺",
    "unverifiable": "不可静态验证",
    "internal_inconsistent": "内部矛盾",
    "not_fixed": "未固定",
}


def _finding_row(f) -> dict:
    return {
        "name": f.display_name,
        "paper": f.paper.raw_value if f.paper else "—",
        "paper_src": f.paper.location if f.paper else "",
        "code": f.code.raw_value if f.code else "—",
        "code_src": f.code.location if f.code else "",
        "status": f.status.value,
        "status_label": _STATUS_LABEL.get(f.status.value, f.status.value),
        "risk": f.risk.value,
        "note": (f.risk_reason or f.ai_analysis or "")[:70] or "—",
        "advice": _ADVICE.get(f.status, "需人工判断。"),
    }


def _merge_rows(fs: list) -> dict:
    """把同一参数的多条结论合并成一行。

    复现清单是**给人照着做**的，同一参数出现好几行会让人困惑；
    但合并不能丢信息 —— 状态与建议都要保留（去重后并列展示）。
    """
    pri = {Status.INCONSISTENT: 0, Status.MISSING_IN_CODE: 1, Status.NOT_FIXED: 2,
           Status.INTERNAL_INCONSISTENT: 3, Status.UNVERIFIABLE: 4,
           Status.MISSING_IN_PAPER: 5, Status.CONSISTENT: 6}
    fs = sorted(fs, key=lambda f: pri.get(f.status, 9))
    labels: list = []
    advices: list = []
    for f in fs:
        lab = _STATUS_LABEL.get(f.status.value, f.status.value)
        if lab not in labels:
            labels.append(lab)
        a = _ADVICE.get(f.status, "需人工判断。")
        if a not in advices:
            advices.append(a)
    row = _finding_row(fs[0])
    row["status_label"] = " + ".join(labels) + (f"（共 {len(fs)} 条结论）" if len(fs) > 1 else "")
    row["advice"] = " ".join(advices)
    row["n_findings"] = len(fs)
    return row


def build_repro_pack(audit: AuditResult) -> ReproPack:
    """从审计结果整理出复现准备清单。"""
    code = audit.code
    cov = audit.coverage or {}
    sc = audit.selfcheck or {}
    # 同一参数可能有多条结论（状态各异），合并成一行
    grouped: dict = {}
    for f in audit.findings:
        grouped.setdefault(f.param_key, []).append(f)
    rows = [_merge_rows(grouped[k]) for k in sorted(grouped)]

    # 环境
    langs = sorted({m.get("lang") for m in (code.multilang_files or []) if m.get("lang")})
    env = {
        "python_deps": dict(code.requirements or {}),
        "code_files": code.python_files,
        "failed_files": list(code.failed_files or []),
        "unsupported": list(code.unsupported or []),
        "langs": langs,
    }

    # 数据准备: 从 dataset 相关结论里提取
    data_notes: list[str] = []
    for r in rows:
        if "ataset" in r["name"] or "数据" in r["name"]:
            data_notes.append(
                f"**{r['name']}**：论文声明 `{r['paper']}`"
                + (f"（{r['paper_src']}）" if r["paper_src"] else "")
                + f"，代码实现 `{r['code']}`"
                + (f"（{r['code_src']}）" if r["code_src"] else "")
                + f" —— {r['advice']}")
    if audit.paper.page_count:
        data_notes.append(f"论文共 {audit.paper.page_count} 页；"
                          f"本次审计覆盖 {cov.get('pages_covered', 0)} 页"
                          + (f"（另有 {cov.get('pages_covered_by_vision', 0)} 页由读图覆盖）"
                             if cov.get("pages_covered_by_vision") else ""))
    if (code.requirements or {}):
        data_notes.append("数据版本请按上表 `Dataset` 一项确认后再下载。")

    # 待确认问题（承接第二期第二批）
    must_confirm: list = []
    try:
        from .inquiry import build_questions
        must_confirm = [q.to_dict() for q in build_questions(audit)]
    except Exception:      # noqa: BLE001
        must_confirm = []

    # 风险（高中优先）
    order = {Risk.HIGH.value: 0, Risk.MEDIUM.value: 1, Risk.LOW.value: 2}
    risks = sorted([r for r in rows if r["risk"] in order],
                   key=lambda r: (order[r["risk"]], r["name"]))

    confidence = {
        "pages_covered": cov.get("pages_covered", 0),
        "pages_total": cov.get("pages_total", 0),
        "pages_covered_by_vision": cov.get("pages_covered_by_vision", 0),
        "code_ok": cov.get("code_ok", 0),
        "code_files": cov.get("code_files", 0),
        "selfcheck_passed": sc.get("passed", 0),
        "selfcheck_checked": sc.get("checked", 0),
        "level": cov.get("confidence_level", "—"),
        "score": cov.get("confidence_score", "—"),
    }

    notes = [
        "本清单的取值**全部来自审计证据**，每条都能回原文/原代码核对；"
        "不一致项由你决定以哪一方为准，系统不替你拍板。",
        "标 ⚠️ 的项与「复现前必须确认的事」直接相关，建议先处理它们再动手。",
    ]
    if not (code.requirements or {}):
        notes.append("未从代码里发现依赖清单，环境准备一节需要你补充。")

    return ReproPack(
        title=audit.paper.title or "",
        env=env, params=rows, data_notes=data_notes,
        must_confirm=must_confirm, risks=risks,
        confidence=confidence, notes=notes,
    )


def write_repro_pack(audit: AuditResult, out_path: str) -> str:
    """生成并落盘 REPRO.md，返回路径。"""
    pack = build_repro_pack(audit)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pack.to_markdown(), encoding="utf-8")
    return str(p)
