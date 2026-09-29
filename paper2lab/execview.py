"""执行视图的派生文案 —— 把「某件工具这一次实际做出了什么」从审计结果里算出来。

**为什么单独成模块**（而不是写在 `app.py` 里）：
界面里「执行记录」表的"结果"列若只写「✅ 执行」，经典模式与计划模式就都成了一排
"✅ 执行"，用户自然看不出两者在跑不同的东西。所以要用**产出**说话。这段派生逻辑
必须能被单元验证覆盖，而 `app.py` 一 import 就会跑整个 Streamlit 脚本、测不了，
因此抽到这里。

**口径提醒**：本模块只做**展示派生**，不参与任何判定——它读的都是审计结果里已有的字段。
"""
from __future__ import annotations


def agent_panel_title(cov: dict) -> str:
    """「抽取 Agent」面板的标题 —— **必须带会随材料变的数字**。

    踩过的坑（用户实测反馈"换什么材料这面板都没变"）：标题原先只写
    「N 步尝试 · 补回 M 类参数」，而"决定性内核已抽全"的样本恒为「0 步 · 0 类」——
    于是 demo、01_DDPM 这类材料折叠时看到的**一字不差**，面板看起来永远是同一句。
    因此标题固定带上「待补 X 类」（这个数会随材料变），展开后再给细节。
    """
    ag = (cov or {}).get("agent") or {}
    targets = len(ag.get("targets") or [])
    filled = len(ag.get("filled") or {})
    steps = len(ag.get("steps") or [])
    return (f"🤖 抽取 Agent（第 3 环节内部）｜ 待补 {targets} 类 → "
            f"补回 {filled} 类 ｜ {steps} 步尝试")


def tool_outcome(audit, key: str) -> str:
    """某件工具**这一次实际做出了什么**。取不到信息时返回 "—"，绝不编。"""
    cov = audit.coverage or {}
    sc = audit.selfcheck or {}
    try:
        if key == "parse_paper":
            thin = cov.get("thin_page_list") or []
            ev = sum(len(v) for v in (audit.paper.params_all or {}).values())
            # 注: 这里用「取到值的参数种类 / 提到过的参数种类」这个**真比率**，
            # 而不是 coverage 里的 decl_matched/decl_total —— 那两个量不是分子分母关系
            # （前者=抽取到的参数证据条数，后者=正文里"xx = 1.5"式疑似声明句式数）。
            return (f"解析 {cov.get('pages_parsed', 0)}/{cov.get('pages_total', 0)} 页 · "
                    f"取到值的参数种类 {cov.get('kinds_valued', 0)}/"
                    f"{cov.get('kinds_seen', 0)} · 参数证据 {ev} 处"
                    + (f" · {len(thin)} 页文字层稀薄待读图" if thin else ""))
        if key == "analyze_images":
            im = cov.get("image") or {}
            if not im.get("enabled"):
                notes = im.get("notes") or []
                why = str(notes[0])[:40] if notes else "未配置读图通道"
                return f"未启用读图 —— {why}"
            return (f"读图 {im.get('regions_read', 0)}/{im.get('candidates', 0)} 个区域 · "
                    f"采信 {im.get('kept', 0)} 条 · 丢弃 {im.get('dropped', 0)} 条")
        if key == "fill_missing":
            am = audit.paper.agent_meta or {}
            targets = am.get("targets") or []
            filled = am.get("filled") or {}
            steps = am.get("steps") or []
            if not targets:
                return f"无待补目标 · {am.get('stopped_reason') or '参数种类已全覆盖'}"
            blocked = sum(1 for s in steps if s.get("status") == "rejected")
            return (f"待补 {len(targets)} 类 → 补回 {len(filled)} 类 · 共尝试 {len(steps)} 步"
                    + (f" · 挡下 {blocked} 条不可信候选" if blocked else ""))
        if key == "analyze_code":
            ok, total = cov.get("code_ok", 0), cov.get("code_files", 0)
            failed = len(cov.get("code_failed_list") or [])
            unsup = len(cov.get("unsupported") or [])
            return (f"扫描 {total} 个文件 · 成功 {ok}"
                    + (f" · 失败 {failed}" if failed else "")
                    + (f" · 暂不支持 {unsup} 个" if unsup else ""))
        if key == "align":
            risky = sum(1 for f in audit.findings if f.status.value != "consistent")
            return f"产出 {len(audit.findings)} 条结论（风险 {risky} 条）"
        if key == "llm_analyze":
            sh = (audit.readiness or {}).get("llm_shards") or {}
            if not sh or not sh.get("total"):
                return "无待归因结论"
            return (f"归因 {sh.get('total', 0)} 条 · {sh.get('mode')}"
                    f"（{sh.get('workers', '—')} 路）· 失败 {sh.get('failed', 0)}")
        if key == "selfcheck":
            return (f"证据自证 {sc.get('passed', 0)}/{sc.get('checked', 0)} 通过 · "
                    f"审计可信度 {cov.get('confidence_score', '—')}/100")
        if key == "rootcause":
            tr = list(getattr(audit, "rootcause", None) or [])
            if not tr:
                return "无待追查的项"
            located = sum(1 for t in tr
                          if getattr(t, "confidence", "none") != "none")
            return (f"追查 {len(tr)} 项 · 可定位 {located} 项"
                    + (f" · 其余 {len(tr) - located} 项明说「无法定位」"
                       if located < len(tr) else ""))
        if key == "patch":
            ps = list(getattr(audit, "patches", None) or [])
            if not ps:
                return "无待出补丁的结论"
            ok = sum(1 for p in ps if getattr(p, "status", "") == "proposed")
            return (f"给方案 {ok} 条 / 拒绝 {len(ps) - ok} 条"
                    "（拒绝理由进报告与本面板）")
        if key == "report":
            return (f"报告含 {len(audit.findings)} 条结论"
                    + (" + 人工确认记录" if getattr(audit, "clarifications", None) else ""))
    except Exception:      # noqa: BLE001
        return "—"
    return "—"
