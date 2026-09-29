"""审计的审计(selfcheck)——出具报告前的全量回放校验。

三条硬规则(交叉审查设计的"第二道防线"):
1. 证据自证: 每条证据的 snippet 必须真的包含其 raw_value
   (防止"页码对但值串了"这类抽取错位)
2. 位置可达: 论文页码必须在文档页数范围内; 代码行号必须在文件实际行数内
3. 结论可复算: 带双边证据的 finding, 用归一化重新比一遍,
   结论必须与 status 一致(防止程序 bug 导致"没核对却说核对过了")

结果写入 audit.selfcheck 与 audit.coverage, 并在报告中单列章节。
"""

from __future__ import annotations

import re
from typing import Optional

from .aligner import text_values_match
from .models import AuditResult, Evidence, Status
from .synonyms import normalize_number, values_equal

# 非数值形态的证据值(运行时确定/文本描述), 不做数值回查
_NON_LITERAL = re.compile(r"变量|运行时|动态|未提供|未找到")

# 状态中文名(覆盖清单用)
_STATUS_ZH = {
    Status.CONSISTENT: "一致",
    Status.INCONSISTENT: "不一致",
    Status.MISSING_IN_CODE: "代码未找到",
    Status.MISSING_IN_PAPER: "论文未声明",
    Status.NOT_FIXED: "未固定",
    Status.UNVERIFIABLE: "动态确定",
    Status.INTERNAL_INCONSISTENT: "内部不一致",
}

_PAGE_RE = re.compile(r"Page\s*(\d+)")
_LINE_RE = re.compile(r":(\d+)\s*$")


def _snippet_contains(snippet: str, raw_value: str) -> bool:
    """snippet 中是否真的能找到该值。

    数值容错: 1e-4 与 0.0001 视为同一; 数字分隔符 10_000 / 10,000 也视为 10000。
    """
    if not snippet or not raw_value:
        return False
    if raw_value in snippet:
        return True
    # 去掉代码里的数字分隔符后重试(10_000 -> 10000, 10,000 -> 10000)
    clean = re.sub(r"(?<=\d)[_,](?=\d)", "", snippet)
    if raw_value in clean:
        return True
    target = normalize_number(raw_value)
    if target is None:
        # 文本值: 忽略大小写/空格/连字符后比对
        s = re.sub(r"[\s_\-]+", "", clean.lower())
        v = re.sub(r"[\s_\-]+", "", raw_value.lower())
        return bool(v) and v in s
    # 数值: 抽取 snippet 里的所有数字逐个归一化比对
    for m in re.finditer(r"\d+\.?\d*(?:[eE][+-]?\d+)?", clean):
        got = normalize_number(m.group(0))
        if got is not None and got == target:
            return True
    return False


def _check_evidence(ev: Optional[Evidence], audit: AuditResult) -> tuple[bool, str]:
    """校验单条证据(自证 + 位置可达)。"""
    if ev is None:
        return True, ""
    if _NON_LITERAL.search(ev.raw_value or ""):
        return True, "动态值, 跳过自证"
    if not _snippet_contains(ev.snippet, ev.raw_value):
        return False, f"自证失败: 原文片段中未找到值 `{ev.raw_value}` ({ev.location})"
    m = _PAGE_RE.search(ev.location)
    if ev.source == "paper" and m:
        if int(m.group(1)) > max(audit.paper.page_count, 1):
            return False, f"页码越界: {ev.location} 超出 {audit.paper.page_count} 页"
    lm = _LINE_RE.search(ev.location)
    if ev.source == "code" and lm:
        fname = ev.location[: lm.start()]
        total = audit.code.file_lines.get(fname)
        if total is not None and int(lm.group(1)) > total:
            return False, f"行号越界: {ev.location} 超出该文件 {total} 行"
    return True, ""


def run_selfcheck(audit: AuditResult) -> dict:
    """对全部 finding 做证据自证 + 结论回放。"""
    checked = passed = 0
    failures: list[dict] = []

    for f in audit.findings:
        checked += 1
        problems: list[str] = []
        for ev in [f.paper, f.code] + list(f.extra):
            ok, why = _check_evidence(ev, audit)
            if not ok:
                problems.append(why)

        # 结论可复算: 双边都有静态值时, 用与对齐引擎同一套比较逻辑重新比一遍
        if (f.paper and f.code and f.paper.normalized is not None
                and f.status in (Status.CONSISTENT, Status.INCONSISTENT)):
            same = values_equal(f.paper.raw_value, f.code.raw_value) \
                or text_values_match(f.paper, f.code)
            expect = Status.CONSISTENT if same else Status.INCONSISTENT
            if expect != f.status:
                problems.append(f"结论不可复算: 重新比较得 {expect.value}, 与结论 {f.status.value} 不符")

        f.verified = not problems
        f.verify_note = "；".join(problems)
        if problems:
            failures.append({"param": f.display_name, "reasons": problems})
        else:
            passed += 1

    audit.selfcheck = {
        "checked": checked,
        "passed": passed,
        "failed": len(failures),
        "failures": failures,
    }
    return audit.selfcheck


def build_manual_check(audit: AuditResult) -> list[dict]:
    """汇总"需要人工核查 / 未参与审计"的条目, 供报告与界面共用。

    每项: {level, kind, item, why, action}
    level: 高(可能影响结论) / 中(需补充确认) / 低(知情即可)
    """
    cov = audit.coverage or {}
    out: list[dict] = []

    # 1) 证据自证未通过的结论
    for f in audit.findings:
        if not f.verified:
            out.append({"level": "高", "kind": "证据自证未通过",
                        "item": f.display_name,
                        "why": f.verify_note or "原文片段与所声明值不一致",
                        "action": "打开报告逐项详情, 按证据位置(论文页码·章节 / 代码文件:行号)"
                                  "回原文核对后再采信该结论"})

    # 2) AI 读图结论(未经文本层验证)
    for f in audit.findings:
        if any(ev and ev.parser == "vlm" for ev in (f.paper, f.code)):
            out.append({"level": "中", "kind": "AI 读图结论(未验证)",
                        "item": f.display_name,
                        "why": f"值由视觉模型从 {f.paper.location if f.paper else '图像'} 读出, "
                               "未经文本层校验, 且不计入就绪度评分",
                        "action": "人工核对原图; 若重要, 请以论文正文/表格值为准"})

    # 3) 代码动态确定 / 内部矛盾
    for f in audit.findings:
        if f.status == Status.UNVERIFIABLE:
            out.append({"level": "中", "kind": "代码动态确定·无法静态验证",
                        "item": f.display_name,
                        "why": (f.code.raw_value if f.code else "") or "取值由运行时变量决定",
                        "action": "查看实际运行配置/日志(如命令行参数、环境变量)确认真实取值"})
        elif f.status == Status.INTERNAL_INCONSISTENT:
            out.append({"level": "中", "kind": "多处声明自相矛盾",
                        "item": f.display_name,
                        "why": f.note or "同一载体内部出现多个不同取值",
                        "action": "确认哪一处是实际采用的配置; 若属灵敏度分析/分组实验可忽略"})

    # 4) 图像区域未读(未启用 / 超预算)
    img = cov.get("image") or {}
    if img.get("regions") and not img.get("enabled"):
        out.append({"level": "中", "kind": "图像区域未读(未配置视觉模型)",
                    "item": f"{img['regions']} 个图片/扫描区域",
                    "why": "这些区域的内容未参与本次审计",
                    "action": "配置视觉模型 key(DASHSCOPE_API_KEY / ZHIPUAI_API_KEY / .env)后重跑, "
                              "或人工阅读这些页面"})
    if img.get("enabled") and img.get("regions_read", 0) < img.get("regions", 0):
        out.append({"level": "低", "kind": "图像区域未读(超出耗时预算)",
                    "item": f"{img.get('regions')} 个区域中读了 {img.get('regions_read')} 个",
                    "why": "为控制耗时暂停读图, 剩余区域内容未参与审计",
                    "action": "调大 PAPER2LAB_VISION_BUDGET_SECONDS 后重跑"})

    # 5) 未参与解析的载体
    for fl in cov.get("code_failed_list") or []:
        out.append({"level": "中", "kind": "代码文件解析失败",
                    "item": fl["file"], "why": fl["reason"],
                    "action": "人工查看该文件是否含训练配置"})
    for u in cov.get("unsupported") or []:
        out.append({"level": "低", "kind": "格式暂不支持",
                    "item": f"{u['file']} ({u['lang']})", "why": "本期未解析该语言",
                    "action": "人工查看, 或用多语言通道覆盖的语言重写关键配置"})
    if cov.get("thin_page_list"):
        _tread = cov.get("thin_pages_read") or []
        _tunread = cov.get("thin_pages_unread") or []
        if _tunread:
            _why = ("页面文字极少(图片/公式/扫描区), 文本通道无法解析"
                    + (f"; 其中第 {', '.join(map(str, _tread))} 页已由图像通道读图覆盖"
                       if _tread else "")
                    + f"; 第 {', '.join(map(str, _tunread))} 页未读图 —— "
                    + (cov.get("thin_unread_reason") or "未参与审计"))
            out.append({"level": "中", "kind": "文本稀薄页(未完全覆盖)",
                        "item": f"第 {', '.join(map(str, cov['thin_page_list']))} 页",
                        "why": _why,
                        "action": ("在页面「高级设置」把「读图区域上限」调大(或设环境变量 "
                                   "PAPER2LAB_VISION_MAX_REGIONS)后重跑, 即可读图这些页面; "
                                   "读图结果按图缓存, 已读过的不会重复计费")
                        if (cov.get("image") or {}).get("enabled")
                        else "配置视觉模型 key 后重跑, 这些页面即可自动读图"})
        else:
            out.append({"level": "低", "kind": "文本稀薄页(已由读图覆盖)",
                        "item": f"第 {', '.join(map(str, cov['thin_page_list']))} 页",
                        "why": "页面文字极少, 文本通道无法解析, 但已由视觉模型读图覆盖",
                        "action": "无需处理; 如需核对读图结论, 见对应结论卡的「图中原文」片段"})

    # 6) 提到但没抽到值的参数种类(任一通道取到即不再计入)
    if cov.get("kinds_unmatched"):
        _via = cov.get("kinds_by_channel") or {}
        _extra = []
        if _via.get("vision"):
            _extra.append("读图" + "/".join(_via["vision"][:4]))
        if _via.get("table"):
            _extra.append("表格" + "/".join(_via["table"][:4]))
        out.append({"level": "中", "kind": "论文提到但未取到数值",
                    "item": "、".join(cov["kinds_unmatched"]),
                    "why": "所有通道都没取到这些参数的值(正文句式未匹配、表格/图片里也没有; "
                           "或该参数只在正文被提及而取值依赖外部代码)",
                    "action": "翻原文对应表格/公式/图片人工补录后再比对代码; "
                              "若确属图片区域, 可调大读图上限重跑"
                              + (f"。另: 本次已从{('、'.join(_extra))}通道取到其它参数的值" if _extra else "")})

    # 7) 被拒收的错位抽取(示众)
    for rj in cov.get("rejected") or []:
        out.append({"level": "低", "kind": "抽取被拒收(疑似错位)",
                    "item": f"{rj['key']} = {rj['value']} @ {rj['location']}",
                    "why": rj["reason"],
                    "action": "确认该数值是否真的属于该参数(用于评估规则库精度)"})

    # 8) 单边缺失项(代码有论文无 / 论文有代码无)
    for f in audit.findings:
        if f.status == Status.MISSING_IN_PAPER:
            out.append({"level": "低", "kind": "论文未声明但代码有值",
                        "item": f.display_name,
                        "why": f"代码 `{f.code.location if f.code else '—'}` 中存在该配置, "
                               "论文未提及(实验记录完整度扣分)",
                        "action": "若该配置对复现重要, 需向作者确认或补充记录"})
        elif f.status == Status.MISSING_IN_CODE:
            out.append({"level": "中", "kind": "论文声明但代码未找到",
                        "item": f.display_name,
                        "why": f"论文声明 `{f.paper.raw_value if f.paper else '—'}`, "
                               "静态扫描未在代码中找到对应实现",
                        "action": "确认该设置是否由框架默认值/外部配置注入, 或确实被遗漏"})

    order = {"高": 0, "中": 1, "低": 2}
    out.sort(key=lambda x: order.get(x["level"], 3))
    return out


def build_param_matrix(audit: AuditResult) -> list[dict]:
    """参数覆盖清单: 每个已知参数在两载体上"抽到了 / 没抽到 / 为什么没抽到"。

    这是"解析透明度"的核心表 —— 让用户一眼看出系统到底看清了什么、漏在哪、
    以及漏的原因是什么(论文没提 / 提到但值在表格或图片里 / 代码里只有测试文件出现等)。
    """
    from .synonyms import PARAM_SYNONYMS

    paper, code = audit.paper, audit.code
    cov = audit.coverage or {}
    paper_kinds = set(paper.alias_kinds or [])
    aidx = {f.param_key: f for f in audit.findings}
    test_only = getattr(code, "aux_only_keys", set()) or set()
    rows: list[dict] = []

    for key, (disp, _al) in PARAM_SYNONYMS.items():
        p_ev = paper.params.get(key)
        c_ev = (code.params.get(key) or [None])[0]
        if not p_ev and not c_ev and key not in paper_kinds and key not in aidx:
            continue          # 两载体都没出现过的参数不占版面
        f = aidx.get(key)
        # 论文侧说明
        if p_ev:
            p_txt = f"{p_ev.raw_value}　@ {p_ev.location}"
        elif key in paper_kinds:
            p_txt = "— (论文提到该参数词, 但未取到数值: 可能在表格/公式/图片里)"
        else:
            p_txt = "— (论文正文未出现该参数)"
        # 代码侧说明
        if c_ev:
            c_txt = f"{c_ev.raw_value}　@ {c_ev.location}"
        elif key in test_only:
            c_txt = "— (仅出现在测试/示例文件, 不作为实现依据)"
        else:
            c_txt = "— (代码中未见该参数名)"
        if p_ev or c_ev:
            how = "✓ 已进入比对"
        elif key in paper_kinds or key in test_only:
            how = "⚠ 未进入比对(见上方说明)"
        else:
            how = "— 两侧均未出现"
        rows.append({
            "参数": disp,
            "论文侧": p_txt,
            "代码侧": c_txt,
            "是否进入比对": how,
            "状态": (_STATUS_ZH.get(f.status, f.status.value) if f else "—"),
            "风险": (f.risk.value if f else "—"),
        })
    return rows


def compute_coverage(audit: AuditResult) -> dict:
    """解析覆盖率汇总(把"抽没抽到"变成可量化指标)。"""
    pages = audit.paper.page_coverage or []
    total_pages = len(pages) or audit.paper.page_count or 0
    thin_pages = [p for p in pages if p.get("status") == "thin"]
    ok_pages = [p for p in pages if p.get("status") == "ok"]

    # 稀薄页与图像通道的对照: 哪些稀薄页真的被读图覆盖了、哪些没有、为什么
    _img_meta = audit.paper.image_meta or {}
    _read_cnt = int(_img_meta.get("regions_read") or 0)
    _read_pages = {r.get("page") for r in (_img_meta.get("region_list") or [])[:_read_cnt]}
    thin_page_list = [p["page"] for p in thin_pages]
    thin_read = sorted(p for p in thin_page_list if p in _read_pages)
    thin_unread = sorted(p for p in thin_page_list if p not in _read_pages)
    thin_reason = ""
    if thin_unread:
        if not _img_meta.get("enabled"):
            thin_reason = "图像通道未启用(未配置视觉模型 key), 这些页面整体未参与审计"
        elif _img_meta.get("hard_capped"):
            thin_reason = (f"候选区域数超过内部安全上限, 本次只读了前 "
                           f"{_img_meta.get('max_regions')} 个")
        elif _img_meta.get("skipped_by_cap"):
            thin_reason = (f"本次设定了「读图区域上限 = {_img_meta.get('max_regions')} 个」，"
                           f"候选区域按「更可能含参数」排序后择优读取, 这些页未进入本次读图"
                           f"（把上限设为 0 即可全部读取）")
        else:
            thin_reason = "超出读图耗时预算(把「读图耗时预算」设为 0 即可不限时)"

    matched = sum(len(v) for v in (audit.paper.params_all or {}).values())
    decl_total = audit.paper.decl_total or 0

    # 参数种类覆盖: 正文提到过的参数种类中, 有多少真正取到了值
    # 取值来自**任一通道**都算数(正文正则 / PDF 表格 / 视觉读图), 并记录来源——
    # 早期版本只看正文 params_all, 会把"读图已取到"的种类误报为"未取到"。
    seen = set(audit.paper.alias_kinds or [])
    obtained: dict[str, set] = {}

    def _channel(parser: str) -> str:
        p = parser or "text"
        if p.startswith("agent"):
            return "agent"          # 抽取 Agent 补回来的(含否定式/LLM 提议/聚焦读图)
        if p == "vlm":
            return "vision"
        if p == "table":
            return "table"
        return "text"

    def _note_channel(kind: str, parser: str):
        obtained.setdefault(kind, set()).add(_channel(parser))

    for k, evs in (audit.paper.params_all or {}).items():
        for e in evs:
            _note_channel(k, e.parser)
    for k, e in (audit.paper.params or {}).items():
        _note_channel(k, e.parser)
    for k, evs in (audit.paper.image_params or {}).items():
        for e in evs:
            _note_channel(k, e.parser)

    valued = set(obtained)
    kinds_seen = len(seen)
    kinds_valued = len(valued & seen) if seen else len(valued)
    kinds_ratio = round(kinds_valued / kinds_seen, 3) if kinds_seen else None
    unmatched_kinds = sorted(seen - set(obtained))

    # 各通道贡献的种类(供报告与界面说明"这个值是从哪儿来的")
    kinds_by_channel = {
        "text": sorted(k for k, ch in obtained.items() if ch & {"text", "ast"}),
        "table": sorted(k for k, ch in obtained.items() if "table" in ch),
        "vision": sorted(k for k, ch in obtained.items() if "vlm" in ch),
        "agent": sorted(k for k, ch in obtained.items() if "agent" in ch),
    }

    code_failed = audit.code.failed_files or []
    unsupported = audit.code.unsupported or []
    code_total = audit.code.python_files or 0
    code_ok = max(code_total - len(code_failed), 0)
    code_ratio = round(code_ok / code_total, 3) if code_total else None

    # 审计可信度(高/中/低): 由覆盖率与解析失败共同决定, 规则透明不调参
    score = 100
    notes: list[str] = []
    if total_pages:
        # 页面覆盖要按**所有通道**算: 文本层可解析的 + 由视觉读图覆盖的薄页。
        # (只算文本层会把已读图的扫描/图片页当成"没覆盖", 从而误扣可信度——早期版本的缺陷)
        pages_covered = len(ok_pages) + len(thin_read)
        page_ratio = pages_covered / total_pages
        text_ratio = len(ok_pages) / total_pages
        if page_ratio < 0.6:
            score -= 25
            notes.append(f"论文内容覆盖仅 {page_ratio:.0%}"
                         f"(文本层 {text_ratio:.0%} + 读图 {len(thin_read)} 页; 可能含扫描页/图表附录)")
        elif page_ratio < 0.8:
            score -= 12
            notes.append(f"论文内容覆盖 {page_ratio:.0%}"
                         f"(文本层 {text_ratio:.0%} + 读图 {len(thin_read)} 页)")
        elif len(thin_read) and text_ratio < 0.8:
            notes.append(f"文本层仅覆盖 {text_ratio:.0%}, 其余 {len(thin_read)} 页薄页已由视觉读图覆盖, "
                         f"合计内容覆盖 {page_ratio:.0%}")
    if code_failed:
        score -= min(10 * len(code_failed), 30)
        notes.append(f"{len(code_failed)} 个代码文件解析失败(内容未参与审计)")
    if unsupported:
        notes.append(f"{len(unsupported)} 个文件为暂不支持的格式(未参与审计)")
    if kinds_ratio is not None and kinds_ratio < 0.4:
        score -= 10
        notes.append(f"论文提到 {kinds_seen} 类参数, 仅 {kinds_valued} 类取到数值"
                     f"(参数可能以表格/公式形式给出)")
    if audit.selfcheck.get("failed"):
        score -= 20
        notes.append(f"{audit.selfcheck['failed']} 条发现的证据自证未通过, 需人工复核")
    score = max(score, 10)
    level = "高" if score >= 85 else ("中" if score >= 65 else "低")

    coverage = {
        "pages_total": total_pages,
        "pages_parsed": len(ok_pages),
        "pages_covered": pages_covered,
        "pages_covered_by_vision": len(thin_read),
        "pages_cover_ratio": round(pages_covered / total_pages, 3) if total_pages else None,
        "pages_thin": len(thin_pages),
        "thin_page_list": [p["page"] for p in thin_pages][:20],
        "thin_pages_read": thin_read,
        "thin_pages_unread": thin_unread,
        "thin_unread_reason": thin_reason,
        "decl_total": decl_total,
        "decl_matched": matched,
        "kinds_seen": kinds_seen,
        "kinds_valued": kinds_valued,
        "kinds_ratio": kinds_ratio,
        "kinds_unmatched": unmatched_kinds[:15],
        "kinds_by_channel": kinds_by_channel,
        "code_files": code_total,
        "code_ok": code_ok,
        "code_failed": len(code_failed),
        "code_failed_list": code_failed[:20],
        "multilang": audit.code.multilang_files or [],
        "image": audit.paper.image_meta or {},
        "agent": audit.paper.agent_meta or {},
        "unsupported": unsupported[:20],
        "rejected": (audit.paper.rejected or []) + (audit.code.rejected or []),
        "confidence_score": score,
        "confidence_level": level,
        "confidence_notes": notes,
    }
    audit.coverage = coverage
    return coverage
