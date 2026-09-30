"""Paper2Lab —— 科研实验智能一致性审计平台 (产品网站风格 UI · 横向布局)。

运行: .venv/Scripts/python -m streamlit run app.py
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import streamlit as st

from paper2lab.envfile import get as env_get
from paper2lab.envfile import load_env
from paper2lab.execview import agent_panel_title as _agent_panel_title
from paper2lab.execview import tool_outcome as _tool_outcome
from paper2lab.housekeeping import format_report as _purge_report
from paper2lab.housekeeping import purge_run_state as _purge_run_state
from paper2lab.models import Confidence, Finding, Status
from paper2lab.pipeline import STEPS, TOOLS, run_audit

load_env()   # 读取项目根目录 .env(API key 等本地私有配置)

BASE_DIR = Path(__file__).resolve().parent
DEMO_DIR = BASE_DIR / "demo"

st.set_page_config(page_title="Paper2Lab · 科研一致性审计平台",
                   page_icon="🔬", layout="wide",
                   initial_sidebar_state="collapsed")

# ================================================================ 访问口令门
# 部署到公网时用环境变量 PAPER2LAB_ACCESS_CODE 设一道统一口令: 拿到链接 ≠ 能跑审计
# （审计会消耗 API 额度）。**不设这个变量就完全不生效** —— 本地照旧一字不差。
from paper2lab.access import configured_code as _gate_code   # noqa: E402
from paper2lab.access import verify_code as _gate_verify     # noqa: E402

if _gate_code() and not st.session_state.get("_access_ok"):
    st.markdown(
        "<div style='max-width:420px;margin:14vh auto 0;text-align:center'>"
        "<div style='font-size:34px'>🔒</div>"
        "<div style='font-size:20px;font-weight:800;color:#0f172a;margin:.4rem 0'>"
        "Paper2Lab · 访问口令</div>"
        "<div style='color:#5a6b88;font-size:13px'>本演示链接仅向评审开放，请输入邀请码</div>"
        "</div>", unsafe_allow_html=True)
    _c1, _c2, _c3 = st.columns([1, 1.2, 1])
    with _c2:
        _entered = st.text_input("访问口令", type="password", key="_gate_input",
                                 placeholder="请输入邀请码", label_visibility="collapsed")
        if st.button("进 入", type="primary", use_container_width=True):
            if _gate_verify(_entered):
                st.session_state["_access_ok"] = True
                st.rerun()
            else:
                st.error("口令不正确。")
    st.caption("　")
    st.stop()

# ================================================================ 全局样式
st.markdown("""
<style>
/* ---- 去 Streamlit 表单感, 逼近真实网站 ---- */
.stApp {background: #f5f7fa;}
.block-container {padding: 0 3rem 2rem 3rem; max-width: 1280px;}
#MainMenu, footer, header {visibility: hidden;}
div[data-testid="stVerticalBlock"] {gap: .55rem;}

/* ---- 顶部导航栏(仿产品官网) ---- */
.navbar {
    position: sticky; top: 0; z-index: 999;
    margin: 0 -3rem; padding: 0 3rem; height: 56px;
    display: flex; align-items: center; justify-content: space-between;
    background: rgba(13,27,48,.96); backdrop-filter: blur(8px);
    border-bottom: 1px solid rgba(255,255,255,.08);
}
.nav-logo {color: #fff; font-size: 18px; font-weight: 800; letter-spacing: .5px;}
.nav-logo b {color: #5b8cff;}
.nav-links span {color: #93a4c4; font-size: 13px; margin-left: 22px; font-weight: 600;}
.nav-cta {
    color: #fff !important; font-size: 12px; font-weight: 700; margin-left: 22px;
    background: linear-gradient(90deg,#2563eb,#7c3aed); border-radius: 8px; padding: 6px 14px;
}

/* ---- Hero ---- */
.hero {
    margin: 0 -3rem; padding: 44px 3rem 34px 3rem;
    background:
      radial-gradient(800px 300px at 15% 0%, rgba(59,91,219,.35), transparent 60%),
      radial-gradient(700px 280px at 85% 20%, rgba(124,58,237,.30), transparent 60%),
      #0d1b30;
    border-bottom: 1px solid #1e2c48;
}
.hero-kicker {color:#5b8cff; font-size:12px; font-weight:800; letter-spacing:3px;}
.hero-title {color:#fff; font-size:40px; font-weight:900; margin:6px 0 8px 0; letter-spacing:.5px;}
.hero-title em {font-style:normal; background:linear-gradient(90deg,#5b8cff,#a78bfa);
                -webkit-background-clip:text; -webkit-text-fill-color:transparent;}
.hero-sub {color:#a8b8d8; font-size:15px; max-width:720px; line-height:1.7;}
.hero-stats {display:flex; gap:36px; margin-top:24px;}
.hero-stat b {color:#fff; font-size:22px; font-weight:800;}
.hero-stat span {color:#7f92b8; font-size:12px; display:block; margin-top:2px;}

/* ---- 区块标题 ---- */
.sec {display:flex; align-items:baseline; gap:12px; margin:26px 0 12px 0;}
.sec-h {font-size:19px; font-weight:800; color:#16223a;}
.sec-n {font-size:12px; font-weight:800; color:#5b8cff; letter-spacing:2px;}
.sec-sub {color:#7a8aa5; font-size:12.5px;}

/* ---- 三个上传入口(横向) ---- */
.entry {
    background:#fff; border:1px solid #e4e9f2; border-radius:14px;
    padding:16px 16px 6px 16px; box-shadow:0 1px 4px rgba(20,40,80,.05);
    border-top:4px solid var(--c); transition: box-shadow .2s, transform .2s;
}
.entry:hover {box-shadow:0 8px 24px rgba(20,40,80,.12); transform: translateY(-2px);}
.entry-head {display:flex; align-items:center; gap:10px;}
.entry-ic {width:38px;height:38px;border-radius:10px;background:var(--c);color:#fff;
           display:flex;align-items:center;justify-content:center;font-size:19px;}
.entry-t {font-size:15px;font-weight:800;color:#16223a;}
.entry-tag {font-size:10px;font-weight:700;color:var(--c);background:var(--cl);
            border-radius:99px;padding:2px 8px;margin-left:auto;}
.entry-d {font-size:12px;color:#7a8aa5;line-height:1.6;margin:8px 0 6px 0;}

/* ---- 主按钮 / 下载按钮 ---- */
div.stButton > button[kind="primary"] {
    background: linear-gradient(90deg,#2563eb,#7c3aed); border:none;
    font-size:16px; font-weight:800; padding:.6rem 0; border-radius:10px;
    box-shadow: 0 4px 16px rgba(79,70,229,.35); letter-spacing:1px;
}
div.stButton > button[kind="primary"]:hover {filter:brightness(1.08);}
div.stDownloadButton > button {
    background: linear-gradient(90deg,#059669,#10b981); color:#fff; border:none;
    font-weight:800; border-radius:10px; padding:.55rem 1.2rem;
    box-shadow: 0 4px 14px rgba(16,185,129,.35);
}

/* ---- 横向流程步骤条 ---- */
.stepper {display:flex; align-items:flex-start; margin:6px 0 4px 0;}
.step {flex:1; text-align:center; position:relative;}
.step::before {content:""; position:absolute; top:13px; left:-50%; width:100%;
               height:2px; background:#dbe4f0; z-index:0;}
.step:first-child::before {display:none;}
.step.done::before {background:linear-gradient(90deg,#2563eb,#7c3aed);}
.step-dot {width:26px;height:26px;border-radius:50%;margin:0 auto;position:relative;z-index:1;
           background:#fff;border:2px solid #dbe4f0;color:#9fb0cc;font-size:12px;
           font-weight:800;display:flex;align-items:center;justify-content:center;}
.step.done .step-dot {background:linear-gradient(135deg,#2563eb,#7c3aed);border-color:transparent;color:#fff;}
.step-t {font-size:11px;color:#7a8aa5;margin-top:6px;font-weight:600;}
.step.done .step-t {color:#3b5bdb;}
/* ---- 计划模式: 被调度员跳过的环节(没做) ---- */
.step.skipped::before {background:repeating-linear-gradient(90deg,#e6dfd5 0 5px,transparent 5px 9px);}
.step.skipped .step-dot {background:#fff;border-color:#e8b98a;color:#c2703a;border-style:dashed;}
.step.skipped .step-t {color:#a9855f;}
.step-tag {font-size:10px;color:#b4552a;background:#fff3e8;border:1px solid #f5d3b0;
           border-radius:4px;padding:1px 5px;display:inline-block;margin-top:3px;font-weight:700;}
.step.failed .step-dot {background:#fee2e2;border-color:#f0a6a6;color:#c02b2b;}
.step.failed .step-t {color:#c02b2b;}

/* ---- 就绪度横向面板 ---- */
.ready-band {
    background: linear-gradient(120deg,#0f2540,#1d3a6b 60%,#3b2f8f);
    border-radius:16px; padding:22px 28px; display:flex; align-items:center; gap:34px;
    box-shadow:0 8px 28px rgba(15,37,64,.35);
}
.ready-score {text-align:center; min-width:150px;}
.ready-num {font-size:52px; font-weight:900; line-height:1;}
.ready-num small {font-size:18px; color:rgba(255,255,255,.45); font-weight:600;}
.ready-lab {color:rgba(255,255,255,.65); font-size:12px; font-weight:700; letter-spacing:2px; margin-top:4px;}
.ready-conf {display:inline-block;margin-top:9px;font-size:11px;font-weight:800;
             border:1px solid;border-radius:99px;padding:3px 11px;background:rgba(255,255,255,.06);}
.ready-dims {flex:1; display:grid; grid-template-columns:repeat(5,1fr); gap:14px;}
.rdim {background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.12);
       border-radius:12px; padding:12px 12px 10px 12px;}
.rdim-n {color:rgba(255,255,255,.65); font-size:11px; font-weight:700;}
.rdim-v {color:#fff; font-size:22px; font-weight:800; margin:3px 0 7px 0;}
.rdim-bar {height:5px;border-radius:3px;background:rgba(255,255,255,.15);overflow:hidden;}
.rdim-bar > div {height:100%;border-radius:3px;}
.rdim-v.rdim-na {color:rgba(255,255,255,.45); font-size:15px; font-weight:700;}
.rdim-na-bar {width:100%;height:100%;background:transparent;
              border:1px dashed rgba(255,255,255,.35); box-sizing:border-box;}

/* ---- 审计发现(横向卡片: 顶部结论行 + 三列证据, 信息密度优先) ---- */
.finding {
    background:#fff; border:1px solid #e7ecf4; border-radius:14px;
    padding:14px 18px 16px 18px; margin-bottom:12px;
    box-shadow:0 1px 4px rgba(20,40,80,.05);
}
.risk-bar {height:4px;border-radius:14px 14px 0 0;margin:-14px -18px 12px -18px;
           background:var(--rc);}
.f-head {display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:11px;}
.f-name {font-size:19px;font-weight:800;color:#16223a;margin-right:2px;}
.chip {display:inline-block;font-size:12.5px;font-weight:700;border-radius:99px;
       padding:4px 12px;color:#fff;background:var(--cc,#888);}
.chip-ghost {background:#eef2f9;color:#46587a;}
.f-evi {display:grid;grid-template-columns:1.15fr 1.15fr 0.9fr;gap:10px;}
.evi {background:#f8fafd;border:1px solid #e7edf5;border-radius:10px;
      padding:10px 13px;font-size:14px;line-height:1.5;color:#26334d;}
.evi-loc {font-size:12.5px;font-weight:800;color:#3d63dd;margin-bottom:5px;}
.evi-val {margin-top:6px;font-size:13.5px;color:#3a4a6b;}
.evi-none {color:#94a2bd;}
.evi b {font-weight:800;}
.ai-box {background:linear-gradient(90deg,#eef4ff,#f3efff);
         border:1px solid #d9e4ff;border-radius:10px;padding:10px 14px;
         font-size:14px;color:#2c3a63;margin-top:10px;line-height:1.6;}
.vfy {margin-top:10px;font-size:13.5px;font-weight:700;border-radius:8px;padding:8px 14px;}
.vfy-ok {background:#eaf7ef;border:1px solid #bfe6cd;color:#1f7a45;}
.vfy-bad {background:#fdeeee;border:1px solid #f5c2c2;color:#a32d2d;}
.mc-item {background:#fff;border:1px solid #e7ecf4;border-left:4px solid var(--mc,#f76b15);
          border-radius:10px;padding:10px 14px;margin-bottom:8px;}
.mc-head {font-size:14px;font-weight:800;color:#16223a;}
.mc-line {font-size:13.5px;color:#4a5b7a;margin-top:4px;line-height:1.55;}
.why {margin-top:10px;background:#fff9ec;border:1px solid #f3e0b5;border-radius:8px;
      padding:8px 13px;font-size:13.5px;color:#6b5320;line-height:1.55;}
@media (max-width:1150px){ .f-evi{grid-template-columns:1fr;} }
</style>
""", unsafe_allow_html=True)

# ================================================================ 常量
STATUS_ICON = {
    Status.CONSISTENT: "🟢", Status.INCONSISTENT: "🔴",
    Status.MISSING_IN_CODE: "🟡", Status.MISSING_IN_PAPER: "🟡",
    Status.NOT_FIXED: "🟠", Status.UNVERIFIABLE: "🔵",
    Status.INTERNAL_INCONSISTENT: "🟣",
}
STATUS_ZH = {
    Status.CONSISTENT: "一致", Status.INCONSISTENT: "不一致",
    Status.MISSING_IN_CODE: "代码未找到", Status.MISSING_IN_PAPER: "论文未声明",
    Status.NOT_FIXED: "未固定", Status.UNVERIFIABLE: "动态确定·无法静态验证",
    Status.INTERNAL_INCONSISTENT: "内部不一致",
}
RISK_META = {"high": ("高风险", "#e5484d"), "medium": ("中风险", "#f76b15"),
             "low": ("低风险", "#3d63dd"), "none": ("通过", "#30a46c")}
CONF_ZH = {Confidence.CONFIRMED: "🟢 Confirmed · 规则验证",
           Confidence.INFERRED: "🔵 Inferred · AI 推断"}


# ================================================================ 工具
def _save_upload(uploaded, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(uploaded.getbuffer())
    return path


def _score_color(v: int) -> str:
    return "#34d399" if v >= 85 else ("#fbbf24" if v >= 70 else "#f87171")


def _step_status_map(ex: dict) -> dict:
    """环节名 → (状态, 说明)。一个工具可能覆盖多个环节, 逐个摊开。"""
    out: dict = {}
    for s in (ex or {}).get("steps", []):
        for cp in (s.get("checkpoints") or []):
            out[cp] = (s.get("status") or "", s.get("reason") or "")
    return out


def _attr(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") \
                       .replace('"', "&quot;").replace("'", "&#39;")


def _stepper_html(execution_log: dict | None = None) -> str:
    """流程进度条（节点数由 `STEPS` 决定，**不写死数字**）。

    **按实际执行渲染**：做过的打 ✓；被调度员跳过的**标「未执行」并给出理由**（悬停可见）。
    只有经典模式（不看材料、固定全跑）才是满勾——这正是两种模式在流程面板上的差别。

    注：早先这里写死"十环节"，2026-09-28 把「根因追查 / 补丁草案」也登记成工具后
    （节点 10 → 12）就地对不上了。现一律改用 `len(STEPS)`/`len(TOOLS)` 派生，
    数字随工具箱自动走，杜绝再次漂移。
    """
    st_map = _step_status_map(execution_log or {})
    parts: list[str] = []
    for s in STEPS:
        status, reason = st_map.get(s, ("", ""))
        if not st_map:
            cls, mark, tag, tip = "done", "✓", "", ""
        elif status == "skipped":
            cls, mark, tag, tip = "skipped", "—", "未执行", reason or "计划跳过"
        elif status == "failed":
            cls, mark, tag, tip = "failed", "!", "执行失败", reason or "执行失败"
        else:
            cls, mark, tag, tip = "done", "✓", "", ""
        title = f" title='{_attr(tip)}'" if tip else ""
        tag_html = f"<div class='step-tag'>{tag}</div>" if tag else ""
        parts.append(
            f"<div class='step {cls}'{title}>"
            f"<div class='step-dot'>{mark}</div>"
            f"<div class='step-t'>{s}</div>{tag_html}</div>")
    return f"<div class='stepper'>{''.join(parts)}</div>"


def _ready_band(total, cats: dict, conf: dict | None = None) -> str:
    """就绪度横条。`total=None` 表示**一个维度都没核验**(显示「—」, 不凭空给分)。
    `cats` 里值为 None 的维度同样表示「未核验」——不给分、不给彩色进度条。
    """
    dims = ""
    for name, v in cats.items():
        if v is None:
            # 未核验: 不给分、不给彩色进度条(避免被读成"核验过且通过")
            dims += (f"<div class='rdim'><div class='rdim-n'>{name}</div>"
                     f"<div class='rdim-v rdim-na'>未核验</div>"
                     f"<div class='rdim-bar'><div class='rdim-na-bar'></div></div></div>")
            continue
        c = _score_color(v)
        dims += (f"<div class='rdim'><div class='rdim-n'>{name}</div>"
                 f"<div class='rdim-v' style='color:{c}'>{v}</div>"
                 f"<div class='rdim-bar'><div style='width:{v}%;background:{c}'></div></div></div>")
    conf = conf or {}
    level = conf.get("level", "—")
    conf_color = {"高": "#34d399", "中": "#fbbf24", "低": "#f87171"}.get(level, "#94a3b8")
    if total is None:
        num_html = "<div class='ready-num' style='color:#94a3b8'>—<small> /100</small></div>"
    else:
        num_html = (f"<div class='ready-num' style='color:{_score_color(total)}'>"
                    f"{total}<small> /100</small></div>")
    return f"""
    <div class="ready-band">
      <div class="ready-score">
        {num_html}
        <div class="ready-lab">综合复现就绪度</div>
        <div class="ready-conf" style="border-color:{conf_color};color:{conf_color}">
          审计可信度 {level}　{conf.get('score', '—')}/100</div>
      </div>
      <div class="ready-dims">{dims}</div>
    </div>"""


def _render_finding(f: Finding):
    zh, color = RISK_META[f.risk.value]
    paper_html = (f"<div class='evi-loc'>📄 {f.paper.location}</div>{f.paper.snippet}"
                  f"<div class='evi-val'>声明值 <b>{f.paper.raw_value}</b>"
                  + (f"　·　归一化 <b>{f.paper.normalized}</b>" if f.paper.normalized is not None else "")
                  + "</div>"
                  if f.paper else
                  "<div class='evi-loc'>📄 论文侧</div><span class='evi-none'>论文中未声明该参数</span>")
    code_html = (f"<div class='evi-loc'>💻 {f.code.location}</div>{f.code.snippet}"
                 f"<div class='evi-val'>实现值 <b>{f.code.raw_value}</b>"
                 + (f"　·　归一化 <b>{f.code.normalized}</b>" if f.code.normalized is not None else "")
                 + "</div>"
                 if f.code else
                 "<div class='evi-loc'>💻 代码侧</div><span class='evi-none'>静态扫描未命中该参数</span>")
    # 第三列: 比对过程(让卡片右侧不留空白)
    if f.paper and f.code:
        if f.status == Status.INCONSISTENT:
            norm_html = (f"<div class='evi-loc'>🔍 比对结论</div>"
                         f"<b>{f.paper.normalized}</b> ≠ <b>{f.code.normalized}</b>"
                         f"<div class='evi-val'>判定 <b>不一致</b> · 差异可直接复算</div>")
        else:
            norm_html = (f"<div class='evi-loc'>🔍 比对结论</div>"
                         f"<b>{f.paper.normalized}</b> = <b>{f.code.normalized}</b>"
                         f"<div class='evi-val'>判定 <b>一致</b> · 规则验证通过</div>")
    elif f.status == Status.UNVERIFIABLE:
        norm_html = ("<div class='evi-loc'>🔍 比对结论</div>代码为运行时变量"
                     "<div class='evi-val'>判定 <b>动态确定</b> · 无法静态验证</div>")
    elif f.status == Status.INTERNAL_INCONSISTENT:
        norm_html = ("<div class='evi-loc'>🔍 比对结论</div>同一载体内多个取值"
                     "<div class='evi-val'>判定 <b>内部不一致</b></div>")
    elif f.status == Status.MISSING_IN_CODE:
        norm_html = ("<div class='evi-loc'>🔍 比对结论</div>论文有值 / 代码无证据"
                     "<div class='evi-val'>判定 <b>代码未找到</b></div>")
    elif f.status == Status.MISSING_IN_PAPER:
        norm_html = ("<div class='evi-loc'>🔍 比对结论</div>代码有值 / 论文未声明"
                     "<div class='evi-val'>判定 <b>论文未声明</b></div>")
    elif f.status == Status.NOT_FIXED:
        norm_html = ("<div class='evi-loc'>🔍 比对结论</div>论文要求固定 / 代码无固定动作"
                     "<div class='evi-val'>判定 <b>未固定</b></div>")
    else:
        norm_html = "<div class='evi-loc'>🔍 比对结论</div><span class='evi-none'>单侧证据</span>"
    ai_html = f"<div class='ai-box'>🤖 <b>AI 归因</b>　{f.ai_analysis}</div>" if f.ai_analysis else ""
    extra_html = ""
    for i, ev in enumerate(f.extra, 1):
        extra_html += (f"<div class='evi' style='margin-top:8px'><div class='evi-loc'>"
                       f"➕ 附加证据 {i} · {ev.location}</div>{ev.snippet}"
                       f"<div class='evi-val'>值 <b>{ev.raw_value}</b></div></div>")
    verify_html = ("<div class='vfy vfy-ok'>🛡️ 证据自证通过 · 原文片段确含该值，结论可复算</div>"
                   if f.verified else
                   f"<div class='vfy vfy-bad'>🛡️ 证据自证未通过 · {f.verify_note}　"
                   f"→ 请人工核对原位置后再采信</div>")
    evidence = [ev for ev in ([f.paper, f.code] + list(f.extra)) if ev]
    parsers = {ev.parser for ev in evidence} - {"ast"}
    chan_html = ""
    if parsers:
        _pname = {"regex": "🔧 通用通道", "table": "📊 表格通道",
                  "ocr": "🖼️ 图像 OCR", "vlm": "👁️ 视觉读图"}
        chan_html = "".join(f"<span class='chip chip-ghost'>{_pname.get(pp, pp)}</span>"
                            for pp in sorted(parsers))
    note_html = (f"<div class='evi-val' style='margin-top:8px'>ℹ️ {f.note}</div>"
                 if f.note else "")
    why_html = (f"<div class='why'>📐 <b>风险判定依据</b>：{f.risk_reason}</div>"
                if f.risk_reason else "")
    vfy_chip = "🛡️ 已自证" if f.verified else "⚠️ 待人工复核"
    # 用 st.html 渲染(纯 HTML, 不经过 Markdown 解析, 避免缩进/空行把标签截断成文本)
    st.html(f"""<div class="finding" style="--rc:{color}">
      <div class="risk-bar"></div>
      <div class="f-head"><span class="f-name">{STATUS_ICON[f.status]} {f.display_name}</span>
        <span class="chip" style="--cc:{color}">{zh}</span>
        <span class="chip chip-ghost">{STATUS_ZH[f.status]}</span>
        <span class="chip chip-ghost">{CONF_ZH[f.confidence]}</span>
        <span class="chip chip-ghost">{vfy_chip}</span>{chan_html}</div>
      <div class="f-evi"><div class="evi">{paper_html}</div><div class="evi">{code_html}</div><div class="evi">{norm_html}</div></div>
      {why_html}{extra_html}{ai_html}{verify_html}{note_html}
    </div>""")


def _render_trust_panel(audit):
    """审计可信度面板: 解析覆盖 + 合理性校验拒收 + 证据自证 + 比较日志。"""
    cov = audit.coverage or {}
    sc = audit.selfcheck or {}
    level = cov.get("confidence_level", "—")
    lv_color = {"高": "#30a46c", "中": "#f76b15", "低": "#e5484d"}.get(level, "#888")

    st.html(
        f"<div style='background:#fff;border:1px solid #e7ecf4;border-radius:12px;"
        f"padding:14px 20px;margin-bottom:12px'>"
        f"<div style='font-size:15px;font-weight:800;color:#16223a'>"
        f"本次审计可信度：<span style='color:{lv_color}'>{level}</span> "
        f"<span style='color:#8a99b5;font-size:12px'>({cov.get('confidence_score', '—')}/100)</span></div>"
        f"<div style='font-size:12.5px;color:#5a6b88;margin-top:6px'>"
        f"就绪度＝被审对象；可信度＝本次审计过程。</div></div>")

    c1, c2, c3 = st.columns(3)
    with c1:
        _pvb = cov.get("pages_covered_by_vision") or 0
        st.metric("论文内容覆盖（全通道）",
                  f"{cov.get('pages_covered', 0)} / {cov.get('pages_total', 0)}",
                  delta=(f"含读图覆盖 {_pvb} 页" if _pvb else None),
                  delta_color="off")
        st.metric("其中文本层可解析",
                  f"{cov.get('pages_parsed', 0)} / {cov.get('pages_total', 0)}")
        st.metric("论文参数种类覆盖",
                  f"{cov.get('kinds_valued', 0)} / {cov.get('kinds_seen', 0)} 类")
    with c2:
        st.metric("代码文件成功解析", f"{cov.get('code_ok', 0)} / {cov.get('code_files', 0)}")
        st.metric("多语言通道 / 完全无法处理",
                  f"{len(cov.get('multilang') or [])} / {len(cov.get('unsupported') or [])}")
    with c3:
        st.metric("证据自证通过", f"{sc.get('passed', 0)} / {sc.get('checked', 0)}")
        st.metric("被合理性校验拒收", len(cov.get("rejected") or []))

    img = cov.get("image") or {}
    if img.get("regions"):
        if img.get("enabled"):
            st.info(f"👁️ **图像通道已启用**（{img.get('model', '—')}）："
                    f"区域 {img.get('regions')} 个 · 读图 {img.get('regions_read')} 个 · "
                    f"采信 {img.get('kept')} 条 · 丢弃 {img.get('dropped')} 条"
                    "（读图结论标 🔵 Inferred，不计入就绪度）")
            for n in img.get("notes", []):
                st.caption(f"提示：{n}")
            with st.expander(f"🖼️ 读图的区域清单（{len(img.get('region_list') or [])} 个）"):
                st.dataframe([{"页码": r["page"],
                               "类型": "整页(扫描/图片页)" if r["kind"] == "page" else "内嵌图片",
                               "判定依据": r["reason"]}
                              for r in (img.get("region_list") or [])],
                             use_container_width=True, hide_index=True)
        else:
            st.warning(f"👁️ **图像通道未启用**：{img.get('regions')} 个图片/扫描区域"
                       "未参与本次审计（未配置视觉模型 key）")
            with st.expander(f"🖼️ 未读图的区域清单（{len(img.get('region_list') or [])} 个）"):
                st.dataframe([{"页码": r["page"],
                               "类型": "整页(扫描/图片页)" if r["kind"] == "page" else "内嵌图片",
                               "判定依据": r["reason"]}
                              for r in (img.get("region_list") or [])],
                             use_container_width=True, hide_index=True)

    if cov.get("multilang"):
        with st.expander(f"🔧 多语言通用通道解析的文件（{len(cov['multilang'])} 个："
                         f"MATLAB/R/C++/Julia/Fortran/Shell/INI/TOML 等）"):
            st.caption("语言无关的赋值抽取通道（带 文件:行号 证据）；"
                       "结论标 `🔧 通用通道`，置信度低于 Python AST。")
            st.dataframe([{"文件": m["file"], "语言": m["lang"], "抽取参数": m["params"]}
                          for m in cov["multilang"]],
                         use_container_width=True, hide_index=True)

    if cov.get("confidence_notes"):
        st.warning("**可信度扣分原因**\n\n" + "\n".join(f"- {n}" for n in cov["confidence_notes"]))

    if cov.get("kinds_unmatched"):
        st.info("📌 **论文提到但未取到的参数种类**：" + "、".join(cov["kinds_unmatched"])
                + "（正文、表格、图片三条通道都没取到）")

    _kbc = cov.get("kinds_by_channel") or {}
    if any(_kbc.values()):
        _seg = []
        if _kbc.get("text"):
            _seg.append(f"📄 正文等文本通道 {len(_kbc['text'])} 类（{'、'.join(_kbc['text'])}）")
        if _kbc.get("table"):
            _seg.append(f"📊 PDF 表格通道 {len(_kbc['table'])} 类（{'、'.join(_kbc['table'])}）")
        if _kbc.get("vision"):
            _seg.append(f"👁️ 视觉读图通道 {len(_kbc['vision'])} 类（{'、'.join(_kbc['vision'])}）")
        if _kbc.get("agent"):
            _seg.append(f"🤖 抽取 Agent 补漏 {len(_kbc['agent'])} 类（{'、'.join(_kbc['agent'])}）")
        st.info("🔎 取值来源分布：\n\n- " + "\n- ".join(_seg))

    _ag = cov.get("agent") or {}
    if _ag:
        _ag_steps = _ag.get("steps") or []
        _ag_filled = _ag.get("filled") or {}
        _ag_budget = _ag.get("budget") or {}
        _ag_targets = _ag.get("targets") or []
        # 标题里必须放**会随材料变**的数字（待补 N 类）；生成逻辑在 execview 里，
        # 便于用数据层断言守住（见 verify_execview.py）。
        with st.expander(
                _agent_panel_title(cov),
                expanded=bool(_ag_filled) or bool(_ag_targets)):
            st.caption("阶梯：文本紧邻 → 文本近邻 → 否定式 → LLM 提议 → 聚焦读图；"
                       "任一候选都要过闸门才入库，否则丢弃并留痕。")

            if _ag_targets:
                _tl = "、".join(str(t) for t in _ag_targets[:8])
                if len(_ag_targets) > 8:
                    _tl += " 等"
                st.caption(
                    f"待补目标 {len(_ag_targets)} 类（{_tl}）｜ "
                    f"补回 {len(_ag_filled)} 类 ｜ "
                    f"消耗 LLM {_ag_budget.get('llm_calls', 0)}/"
                    f"{_ag_budget.get('max_llm_calls', '—')} 次 · "
                    f"耗时 {_ag_budget.get('seconds', 0)}s ｜ "
                    f"结束：{_ag.get('stopped_reason', '—')}")
            else:
                # 没待补目标时不能只显示一排 0 —— 要说清"内核到底覆盖了什么",
                # 否则不同材料看到的是同一句"0 类"，等于没信息。
                _kbc = cov.get("kinds_by_channel") or {}
                _got = sorted({k for ch in ("text", "table", "vision", "agent")
                               for k in (_kbc.get(ch) or [])})
                st.info(
                    f"**本次无需补漏** —— 决定性内核已抽到 "
                    f"{cov.get('kinds_valued', 0)}/{cov.get('kinds_seen', 0)} 类参数，"
                    "没有「论文提到但没取到值」的参数。"
                    + (f"\n\n已取到：{'、'.join(_got)}" if _got else "")
                    + f"\n\n结束原因：{_ag.get('stopped_reason', '—')}")
            if _ag_steps:
                st.dataframe([{
                    "#": s.get("seq"), "参数": s.get("display"), "工具": s.get("tool"),
                    "结果": s.get("status"), "取值": s.get("value") or "—",
                    "页": s.get("page") or "—", "说明": s.get("note") or "",
                } for s in _ag_steps], use_container_width=True, hide_index=True)
            if _ag_filled:
                st.success("Agent 补回（均已过闸门）："
                           + "、".join(f"{k} = {v}" for k, v in _ag_filled.items()))

    if cov.get("thin_page_list"):
        _tread = cov.get("thin_pages_read") or []
        _tunread = cov.get("thin_pages_unread") or []
        _all = ", ".join(map(str, cov["thin_page_list"]))
        _msg = (f"📄 **文本稀薄页：第 {_all} 页**（文字层极少，无法走文本解析）")
        if _tread:
            _msg += f"\n\n- ✅ 已由**视觉读图**覆盖：第 {', '.join(map(str, _tread))} 页"
        if _tunread:
            _msg += (f"\n- ⚠️ **未读图**：第 {', '.join(map(str, _tunread))} 页 —— "
                     + (cov.get("thin_unread_reason") or "未参与审计"))
        st.warning(_msg)
        _img_on = bool((cov.get("image") or {}).get("enabled"))
        if _tunread and _img_on:
            st.caption("👉 想覆盖更多页面：在「⚙️ 高级设置」把**读图区域上限**调大"
                       "（或设 `PAPER2LAB_VISION_MAX_REGIONS`）后重跑；"
                       "读图结果按图缓存，已读过的不会重复计费。")
    if cov.get("code_failed_list"):
        with st.expander(f"❌ 代码解析失败文件（{len(cov['code_failed_list'])} 个，内容未参与审计）"):
            st.dataframe([{"文件": x["file"], "原因": x["reason"], "行数": x["lines"]}
                          for x in cov["code_failed_list"]],
                         use_container_width=True, hide_index=True)
    if cov.get("unsupported"):
        with st.expander(f"⚠️ 已识别但暂不支持分析的格式（{len(cov['unsupported'])} 个）"):
            st.dataframe([{"文件": x["file"], "语言": x["lang"]} for x in cov["unsupported"]],
                         use_container_width=True, hide_index=True)
    if cov.get("rejected"):
        with st.expander(f"🚫 被合理性校验拒收的抽取（{len(cov['rejected'])} 处，超领域先验范围）"):
            st.caption("以下数值被判定为错位抽取（如把年份当学习率），已拒收且不参与审计：")
            st.dataframe([{"参数": x["key"], "抽取值": x["value"],
                           "位置": x["location"], "原因": x["reason"]}
                          for x in cov["rejected"]],
                         use_container_width=True, hide_index=True)

    with st.expander(f"🛡️ 审计自检（证据自证 + 结论复算）："
                     f"{sc.get('passed', 0)}/{sc.get('checked', 0)} 通过",
                     expanded=bool(sc.get("failures"))):
        if sc.get("failures"):
            for fl in sc["failures"]:
                st.error(f"**{fl['param']}** — " + "；".join(fl["reasons"]))
        else:
            st.success(f"全部结论通过自检（{sc.get('passed', 0)}/{sc.get('checked', 0)}）")
        st.caption("自检两项：① 证据自证 —— 证据片段中确实出现所声明的值；"
                   "② 结论复算 —— 用同一套归一化逻辑重比一遍，与结论一致。")

    # ---- 未参与本次审计的部分(覆盖边界, 如实交代)
    not_cov: list[str] = []
    if img.get("regions") and not img.get("enabled"):
        not_cov.append(f"图像/扫描区域 {img.get('regions', 0)} 个"
                       f"（共发现候选 {img.get('candidates', img.get('regions', 0))} 个）："
                       "未配置视觉模型 key，内容未参与审计")
    if img.get("enabled") and img.get("regions_read", 0) < img.get("regions", 0):
        not_cov.append(f"图像区域 {img.get('regions', 0) - img.get('regions_read', 0)} 个："
                       "超出耗时预算未读图")
    if img.get("enabled") and img.get("skipped_by_cap"):
        not_cov.append(f"图像候选区域 {img['skipped_by_cap']} 个：超出「读图区域上限 "
                       f"{img.get('max_regions')}」（共发现候选 {img.get('candidates')} 个，"
                       "按「更可能含参数」排序择优读取）")
    for x in cov.get("code_failed_list") or []:
        not_cov.append(f"代码文件 `{x['file']}`：{x['reason']}")
    for x in cov.get("unsupported") or []:
        not_cov.append(f"格式暂不支持 `{x['file']}`（{x['lang']}）")
    if cov.get("thin_page_list"):
        _tread = cov.get("thin_pages_read") or []
        _tunread = cov.get("thin_pages_unread") or []
        not_cov.append(
            f"论文文本稀薄页：第 {', '.join(map(str, cov['thin_page_list']))} 页"
            + (f"（其中第 {', '.join(map(str, _tread))} 页已由读图覆盖）" if _tread else "")
            + (f"；**未读图**：第 {', '.join(map(str, _tunread))} 页" if _tunread else ""))
    if cov.get("kinds_unmatched"):
        not_cov.append("论文提到但未取到数值的参数种类（所有通道均未取到）："
                       + "、".join(cov["kinds_unmatched"]))
    if cov.get("rejected"):
        not_cov.append(f"被合理性校验拒收的抽取 {len(cov['rejected'])} 处（判定为错位抽取）")
    st.markdown(f"**🚧 未参与本次审计的部分（{len(not_cov)} 项）**：")
    if not_cov:
        for x in not_cov:
            st.markdown(f"- {x}")
    else:
        st.success("本次审计的载体内容已全部纳入解析，无遗漏部分。")

    # ---- 参数覆盖清单(解析透明度: 抽到什么 / 没抽到什么 / 为什么)
    pm = cov.get("param_matrix") or []
    hit = sum(1 for r in pm if str(r["是否进入比对"]).startswith("✓"))
    st.markdown(f"**📋 参数覆盖清单（{len(pm)} 项已知参数：{hit} 项已进入比对，"
                f"{len(pm) - hit} 项未进入）**：")
    if pm:
        st.dataframe([{"参数": r["参数"], "论文侧": r["论文侧"], "代码侧": r["代码侧"],
                       "是否进入比对": r["是否进入比对"], "状态": r["状态"], "风险": r["风险"]}
                      for r in pm],
                     use_container_width=True, hide_index=True)

    # ---- 需人工核查清单(统一数据源, 与报告一致)
    mc = cov.get("manual_check") or []
    lv_color_mc = {"高": "#e5484d", "中": "#f76b15", "低": "#8a99b5"}
    st.markdown(f"**🙋 需人工核查清单（{len(mc)} 项）**：")
    if mc:
        for m in mc:
            st.html(
                f"<div class='mc-item' style='--mc:{lv_color_mc.get(m['level'], '#8a99b5')}'>"
                f"<div class='mc-head'>[{m['level']}] {m['kind']}　·　{m['item']}</div>"
                f"<div class='mc-line'>原因：{m['why']}</div>"
                f"<div class='mc-line'>建议：{m['action']}</div></div>")
    else:
        st.success("无：本次审计未产生需人工核查的条目。")

    with st.expander(f"📜 程序比较日志（全部 {len(audit.compare_log)} 条，逐条可复核）",
                     expanded=True):
        st.caption("全部判定由程序完成，以下为完整比较记录：")
        if audit.compare_log:
            st.code("\n".join(f"{i:>3}. {line}"
                              for i, line in enumerate(audit.compare_log, 1)),
                    language="text")
        else:
            st.info("本次审计没有产生比较日志")


# ================================================================ 导航栏 + Hero
# 注意这个 f 前缀是必需的：下方 hero-stat 里有 {len(STEPS)}。漏了它页面会
# 原样显示「{len(STEPS)} 步」给用户看（线上实测抓到过，audit_placeholders.py 可复查）。
st.markdown(f"""
<div class="navbar">
  <div class="nav-logo">🔬 Paper<b>2</b>Lab</div>
  <div class="nav-links">
    <span>审计输入</span><span>就绪度</span><span>风险项</span><span>审计报告</span>
    <a class="nav-cta" href="#" style="text-decoration:none">开始审计</a>
  </div>
</div>
<div class="hero">
  <div class="hero-kicker">REPRODUCIBILITY READINESS AUDIT</div>
  <div class="hero-title">论文—代码—实验结果 <em>智能一致性审计</em></div>
  <div class="hero-sub">
    面向科研复现场景的审计流水线:AST 全量静态分析 × 数值归一化比对 × 证据链追溯。
    确定性问题交给程序验证,复杂归因交给 AI——让每一篇论文,更快从「读懂」走向「复现」。
  </div>
  <div class="hero-stats">
    <div class="hero-stat"><b>{len(STEPS)} 步</b><span>审计流水线(含 Agent 补漏与自检)</span></div>
    <div class="hero-stat"><b>3 载体</b><span>论文 · 代码 · 结果交叉核验</span></div>
    <div class="hero-stat"><b>100%</b><span>发现均可追溯至页码与行号</span></div>
    <div class="hero-stat"><b>3 道</b><span>合理性校验 · 证据自证 · 结论复算</span></div>
  </div>
</div>
""", unsafe_allow_html=True)

# ================================================================ ① 审计输入(横向三入口)
st.markdown("""<div class="sec"><span class="sec-n">01</span>
<span class="sec-h">审计输入</span>
<span class="sec-sub">上传三个载体,系统自动交叉核验</span></div>""",
            unsafe_allow_html=True)

use_demo = st.toggle("✨ 使用内置演示数据（受控样例：埋了 3 个已知问题）", value=True,
                     help="上传自己的文件后，系统会优先使用上传的数据")
use_planner = not st.toggle(
    "⚠️ 兜底开关：强制跑完全部环节（关闭调度员）", value=False,
    help="**默认：由调度员按材料排计划**——论文数据齐全时它照样跑完全流程，"
         "不齐全时只跑对应环节并说明理由。日常用它即可。\n\n"
         f"打开这个开关 = 经典模式：**不看材料齐不齐，固定跑完 {len(STEPS)} 个环节**"
         f"（{len(TOOLS)} 件工具全执行）。"
         "它不是「另一种用法」，而是三个用途的兜底口子：\n"
         "① **消融对照**——要证明「调度员没有改变任何结论」，必须有个对照组；\n"
         "② **逃生开关**——若怀疑调度员误判跳过了该跑的环节，用它强制全跑；\n"
         "③ **回归基准**——每次改动的等价性都是拿它比对出来的。\n\n"
         "想看两种模式在界面上的差别：只上传论文 PDF、不上传代码 ZIP —— "
         "调度员会跳过「代码扫描」并在流程面板上标「未执行」，经典模式则照跑一遍。")
# 🧠 AI 参与决策（两项：排计划 + 给补丁提名目标）—— **不设开关，恒开**。
# 口径（2026-09-29 用户定）：网页端就是 agent 入口 —— 输入材料、点启动，AI 一开始就参与
# 决定**跑哪些环节**；它判定不值得跑的环节，在流程面板标「未执行」并逐条给出理由。
# 所以"要不要 AI"不该是一个选项：**AI 参与就是默认行为本身**。
# 若 AI 不可用（未配 key / 调用失败），自动回退规则版**并如实说明**（不会假装 AI 排过）。
# 想关闭 AI 做对照：用下面的「兜底开关」（经典模式），或 CLI 走 run_audit(llm_planner=False)。
_AI_ON = True

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("""<div class="entry" style="--c:#3d63dd;--cl:#e8efff">
      <div class="entry-head"><div class="entry-ic">📄</div>
      <div class="entry-t">论文 PDF</div><span class="entry-tag">必需</span></div>
      <div class="entry-d">提取方法、超参数与实验结果声明,证据定位精确到页码与章节</div>
    </div>""", unsafe_allow_html=True)
    pdf_file = st.file_uploader("论文", type=["pdf"], label_visibility="collapsed")
with c2:
    st.markdown("""<div class="entry" style="--c:#30a46c;--cl:#e6f7ef">
      <div class="entry-head"><div class="entry-ic">💻</div>
      <div class="entry-t">代码 ZIP</div><span class="entry-tag">可选</span></div>
      <div class="entry-d">AST 全量扫描训练配置与依赖环境,参数定位精确到文件与行号；不传则只做论文侧自查</div>
    </div>""", unsafe_allow_html=True)
    code_file = st.file_uploader("代码", type=["zip"], label_visibility="collapsed")
with c3:
    st.markdown("""<div class="entry" style="--c:#f76b15;--cl:#fff0e5">
      <div class="entry-head"><div class="entry-ic">📊</div>
      <div class="entry-t">实验结果 JSON</div><span class="entry-tag">可选</span></div>
      <div class="entry-d">回传实际跑出的指标,用于结果一致性核验与差异归因</div>
    </div>""", unsafe_allow_html=True)
    result_file = st.file_uploader("结果", type=["json"], label_visibility="collapsed")

# 上传优先于演示开关: 只要有论文就用上传的数据(代码 ZIP 可选)
has_pdf = bool(pdf_file)
has_upload = has_pdf
if has_upload and use_demo:
    st.info("📌 使用你上传的数据（演示开关自动失效）", icon="ℹ️")
elif not has_upload and not use_demo:
    st.caption("请上传论文 PDF（代码 ZIP 可选），或打开演示数据开关")

with st.expander("⚙️ 高级设置 · LLM 归因引擎 与 图像通道"):
    # ---- 密钥状态: 如实说明「.env 里配了什么、当前实际会用什么」
    _vk = env_get("VISION_API_KEY") or env_get("DASHSCOPE_API_KEY") or env_get("ZHIPUAI_API_KEY")
    _vu = env_get("VISION_BASE_URL")
    _vm = env_get("VISION_MODEL")
    _dk = env_get("DEEPSEEK_API_KEY")
    if not _vm and _vu:
        _vm = {"xiaomimimo": "mimo-v2.5", "bigmodel": "glm-4v-plus",
               "dashscope": "qwen-vl-max"}.get(
            next((s for s in ("xiaomimimo", "bigmodel", "dashscope") if s in _vu), ""), "")
    # 通道状态统一挪到下面两个 key 输入框之后渲染 —— 因为"已配置"与否必须把
    # **页面输入**也算进去。只读环境变量会漏报：2026-09-30 实测页面填了 key、
    # 审计确实读了图（可信度页显示"图像通道已启用（mimo-v2.5）"），
    # 这里却显示"未配置"，两处自相矛盾。
    st.caption(
        f"归因引擎：DeepSeek · "
        f"{(env_get('DEEPSEEK_MODEL') or 'deepseek-chat') if _dk else '未配置，用内置模板'}"
        f"（只生成解释文字，不影响结论）")

    # 安全：两个 key 输入框**刻意恒为空**（不预填服务端已配置的 key）。
    # 理由：一旦写 value=<真key>，这个值就会随页面发到浏览器 —— 链接公开后，
    # 任何人打开开发者工具（或点"眼睛"图标）都能直接读走你的 key。
    # 留空不影响功能：下面 `api_key or None` 会回落到服务端环境变量
    # （pipeline.py 里的 _env_get("DEEPSEEK_API_KEY")）。
    api_key = st.text_input("DeepSeek API Key（留空即用服务端配置；都没有则用内置模板归因）",
                            type="password", value="")
    st.caption(
        "服务端 DeepSeek key："
        + ("已配置 ✅（出于安全不在页面显示，你也不需要在页面填）"
           if _dk else "未配置 ⚠️（留空即用内置模板，演示不中断）"))
    st.caption("视觉模型 key（留空则图像通道关闭）：")
    vision_key = st.text_input("视觉模型 API Key（小米 MiMo / 通义千问 VL / 智谱 GLM-4V）",
                               type="password", value="")
    if _vk:
        st.caption("服务端视觉 key：已配置 ✅（同样不在页面显示）")
    vc1, vc2 = st.columns(2)
    with vc1:
        vision_base_url = st.text_input("Base URL（可留空，按 key 自动识别）",
                                        value=_vu)
    with vc2:
        vision_model = st.text_input("模型名（可留空）", value=_vm)

    # 通道状态：必须把**页面输入**也算进来，否则会与「审计可信度」页自相矛盾。
    # 优先级与 paper2lab/vision.py 一致：页面输入 > .env / 环境变量 / Secrets。
    _vk_eff = (vision_key or "").strip() or _vk
    _vm_eff = (vision_model or "").strip() or _vm
    _vu_eff = (vision_base_url or "").strip() or _vu
    if _vk_eff:
        _vendor = ("小米 MiMo" if "xiaomimimo" in (_vu_eff or "")
                   or _vk_eff.startswith(("sk-", "tp-", "ttp-")) else "视觉大模型")
        _from_page = bool((vision_key or "").strip())
        st.success(
            f"**视觉读图通道：已配置 ✅**　{_vendor} · `{_vm_eff or '自动识别'}`"
            f"　来源：{'页面输入' if _from_page else '.env / 环境变量 / Secrets'}",
            icon="✅")
    else:
        st.warning("**视觉读图通道：未配置 ⚠️**　图片表格 / 扫描页不参与审计"
                   "（未读区域会在「审计可信度」页列出）", icon="⚠️")
    st.caption("读图上限与耗时预算（默认 0 = 全部读取、不限时；已读过的走缓存不重复计费）：")
    vd1, vd2 = st.columns(2)
    with vd1:
        _mr = env_get("PAPER2LAB_VISION_MAX_REGIONS") or "0"
        try:
            _mr_def = max(0, int(_mr))
        except ValueError:
            _mr_def = 0
        vision_max_regions = st.number_input(
            "读图区域上限（0 = 全部读取）", min_value=0,
            max_value=500, value=_mr_def, step=1,
            help="默认 0：论文里所有图片/扫描区域全部读图，包括全部文本稀薄页。")
    with vd2:
        _bs = env_get("PAPER2LAB_VISION_BUDGET_SECONDS") or "0"
        try:
            _bs_def = max(0, int(float(_bs)))
        except ValueError:
            _bs_def = 0
        vision_budget = st.number_input(
            "读图耗时预算（秒，0 = 不限）", min_value=0,
            max_value=3600, value=_bs_def, step=10,
            help="默认 0：不设上限，把所有候选区域读完为止。")

# 通道状态（只报功能名与状态，不解释机制）
st.caption(
    f"读图通道：{'已就绪（' + (_vm_eff or '自动识别') + '）' if _vk_eff else '未配置'}"
    f"　｜　归因引擎："
    f"{'DeepSeek · ' + (env_get('DEEPSEEK_MODEL') or 'deepseek-chat') if _dk else '内置模板'}"
    f"　｜　决策引擎："
    f"{'AI 参与排计划（agent 模式）' if _dk else '未配置 LLM，将回退规则版'}")

run = st.button("🚀 开 始 科 研 审 计", type="primary", use_container_width=True)

# ================================================================ 执行
if run:
    # ---- 先清掉**上一轮的运行态**, 防止新审计失败时残留旧数据。
    #      清的边界(见 paper2lab/housekeeping.py, 那里写死了口径, 界面与日志共用同一句):
    #        · 运行缓存 cache/llm_cache.json / vision_cache.json —— 上一轮的中间结果,
    #          清了只是本轮重新调用 API(慢一点、有费用), 不影响任何结论;
    #        · 上一轮上传并落盘的临时文件(PDF / 代码 ZIP)。
    #      留的边界:
    #        · 跨任务记忆 cache/audit_memory.json —— 它是**记忆不是缓存**: 记的是
    #          "这篇论文哪些参数没给确定值""参数出现在哪几页", 跨轮次跨任务复用,
    #          删了下一轮就把它当新论文从头来。**不清**。
    _purge = _purge_run_state(st.session_state.pop("_tmp_uploads", None) or [])
    for _stale in ("audit", "report", "meta", "clar_done"):
        st.session_state.pop(_stale, None)
    _new_uploads: list = []

    if has_upload:
        # 上传优先: 用用户自己的数据(代码 ZIP 可选——不传时只做论文侧自查)
        pdf_bytes = pdf_file.getvalue()
        pdf_path = _save_upload(pdf_file, ".pdf")
        _new_uploads.append(pdf_path)
        if code_file:
            code_bytes = code_file.getvalue()
            code_path = _save_upload(code_file, ".zip")
            _new_uploads.append(code_path)
        else:
            code_bytes = b""
            code_path = ""
        user_results = (json.loads(result_file.getvalue().decode("utf-8"))
                        if result_file else None)
        fingerprint = hashlib.sha1(pdf_bytes + code_bytes).hexdigest()[:10]
        meta = {"source": "用户上传",
                "files": f"{pdf_file.name}"
                         + (f" + {code_file.name}" if code_file else "（未提供代码）")
                         + (f" + {result_file.name}" if result_file else ""),
                "fingerprint": fingerprint}
    elif use_demo:
        if not (DEMO_DIR / "paper.pdf").exists():
            st.error("演示数据不存在，请先运行: python make_demo.py")
            st.stop()
        pdf_path = str(DEMO_DIR / "paper.pdf")
        code_path = str(DEMO_DIR / "project.zip")
        user_results = json.loads((DEMO_DIR / "results.json").read_text(encoding="utf-8"))
        fingerprint = hashlib.sha1(
            (DEMO_DIR / "paper.pdf").read_bytes()
            + (DEMO_DIR / "project.zip").read_bytes()).hexdigest()[:10]
        meta = {"source": "内置演示数据(受控样例)",
                "files": "demo/paper.pdf + demo/project.zip + demo/results.json",
                "fingerprint": fingerprint}
    else:
        st.warning("请上传论文 PDF（代码 ZIP 可选），或打开演示数据开关")
        st.stop()

    bar = st.progress(0, text="准备中…")

    def on_progress(i: int, name: str):
        bar.progress(int((i + 1) / len(STEPS) * 100), text=f"✅ {name}")

    audit, report_md = run_audit(pdf_path, code_path, user_results,
                                 api_key=api_key or None, progress=on_progress,
                                 vision_key=vision_key or "",
                                 vision_base_url=vision_base_url or "",
                                 vision_model=vision_model or "",
                                 vision_max_regions=int(vision_max_regions),
                                 vision_budget_seconds=float(vision_budget),
                                 plan_mode=use_planner,
                                 llm_planner=_AI_ON, llm_patch=_AI_ON)
    bar.empty()
    st.session_state["audit"] = audit
    st.session_state["report"] = report_md
    st.session_state["meta"] = meta
    # 记住本轮上传落盘的位置 + 本轮开始前清掉了什么 —— 下一轮开始时会用到/会显示
    st.session_state["_tmp_uploads"] = _new_uploads
    st.session_state["_purge"] = _purge

# ================================================================ 结果
if "audit" in st.session_state:
    audit = st.session_state["audit"]
    report_md = st.session_state["report"]
    meta = st.session_state.get("meta", {})
    r = audit.readiness
    issues = [f for f in audit.findings if f.status != Status.CONSISTENT]

    # ---- 当前审计对象(防止"结果对不上数据"的困惑)
    st.html(
        f"<div style='background:#eef4ff;border:1px solid #d9e4ff;border-radius:10px;"
        f"padding:10px 16px;font-size:13px;color:#2c3a63;margin-top:14px'>"
        f"🗂️ <b>当前审计对象</b>：{meta.get('source', '—')}　|　"
        f"📁 {meta.get('files', '—')}　|　"
        f"🔑 数据指纹 <code>{meta.get('fingerprint', '—')}</code>　|　"
        f"📄 论文《{audit.paper.title or '未识别标题'}》</div>")

    # ---- 清理回执（一行功能名 + 事实；说理不占界面，见 housekeeping.format_report）
    _pr = st.session_state.get("_purge")
    if _pr:
        st.caption("🧹 清理：" + _purge_report(_pr))

    # ---- ② 横向流程步骤条 + 就绪度横向面板
    _ex0 = getattr(audit, "execution_log", None) or {}
    _n_skip0 = _ex0.get("skipped", 0)
    if _ex0.get("mode") == "planned":
        _step_sub = (f"{len(STEPS)} 环节 · 调度员排计划（跳过 {_n_skip0} 个工具）" if _n_skip0
                     else f"{len(STEPS)} 环节 · 调度员排计划（本次无跳过）")
    else:
        _step_sub = f"{len(STEPS)} 环节 · 强制全跑（兜底模式）"
    st.markdown(f"""<div class="sec"><span class="sec-n">02</span>
    <span class="sec-h">审计流水线</span>
    <span class="sec-sub">{_step_sub}</span></div>""", unsafe_allow_html=True)
    st.html(_stepper_html(_ex0))

    # ---- 第二期第一批: 执行记录（两种模式各自如实交代"跑了什么、跳了什么、为什么"）
    _ex = getattr(audit, "execution_log", None) or {}
    if _ex:
        _planned = _ex.get("mode") == "planned"
        _skipped = _ex.get("skipped", 0)
        _planner_kind = (_ex.get("plan") or {}).get("planner", "rule")
        _tag = ("🧭 计划模式" if _planned else "📐 经典模式")
        if _planned and _planner_kind == "llm":
            _tag = "🧠 AI 排计划"
        # 两种模式的差别只在"跑哪些"；材料齐备时二者执行集合相同 —— 如实说明，别让人以为没区别
        if _planned and not _skipped:
            _verdict = "执行集合与经典模式相同"
        elif _planned:
            _verdict = f"跳过 {_skipped} 个工具"
        else:
            _verdict = f"经典模式：强制全跑 {len(STEPS)} 个环节、{len(TOOLS)} 件工具"
        with st.expander(
                f"{_tag} · 执行记录（执行 {_ex.get('ran', 0)} 个工具 / "
                f"跳过 {_skipped} 个 / 覆盖 {_ex.get('nodes_total', 0)} 个环节 · "
                f"{_ex.get('seconds', 0)}s）", expanded=True):
            st.caption(_verdict)

            # 计划模式: 把调度员**看了什么、据此下了什么决策**摊开
            if _planned:
                _plan = _ex.get("plan") or {}
                _dec = _plan.get("decisions") or []
                if _dec:
                    st.markdown("**调度员的决策**"
                                + ("　（来源：材料事实 / AI 判断 / 程序否决 AI）"
                                   if _planner_kind == "llm" else ""))
                    st.dataframe(
                        [{"工具": d.get("title"),
                          "决策": "▶️ 执行" if d.get("action") == "run" else "⏭️ 跳过",
                          "来源": {"rule": "材料事实", "llm": "AI 判断",
                                   "veto": "程序否决 AI"}.get(d.get("source"), "—"),
                          "理由": d.get("reason") or "—"}
                         for d in _dec],
                        use_container_width=True, hide_index=True)

            st.markdown("**实际执行**")
            st.dataframe(
                [{"环节": " → ".join(_s.get("checkpoints") or []) or "—",
                  "工具": _s["title"],
                  "结果": {"done": "✅ 执行", "skipped": "⏭️ 计划跳过",
                           "failed": "❌ 失败"}.get(_s["status"], _s["status"]),
                  "这次实际做出了什么": (_s["reason"]
                                     if _s["status"] != "done"
                                     else _tool_outcome(audit, _s["key"])),
                  "耗时": f"{_s['seconds']}s"}
                 for _s in _ex.get("steps", [])],
                use_container_width=True, hide_index=True)
            for _n in _ex.get("notes", []):
                st.caption(f"· {_n}")
            st.caption(f"{len(STEPS)} 环节 / {len(TOOLS)} 工具"
                       "（参数归一化 · 交叉匹配 · 结果核验 合为一个工具）")

    # ---- 第二期第二批: 待确认问题（可直接填写答复, 答复只作为人工确认记录）
    try:
        from paper2lab.inquiry import (KIND_LABEL, apply_clarifications,
                                       build_questions)
        _qs = build_questions(audit)
    except Exception:      # noqa: BLE001
        _qs = []
    if _qs:
        _answered = len(audit.clarifications or [])
        with st.expander(
                f"❓ 待确认问题（{len(_qs)} 项，需要你判断"
                + (f" · 已确认 {_answered} 项" if _answered else "") + "）"):
            st.caption("答复写进报告作为人工确认记录：只记录，不自动改写结论。")
            _answers = {}
            for _q in _qs:
                st.markdown(f"**[{KIND_LABEL.get(_q.kind, _q.kind)}] {_q.title}**")
                st.caption(f"为什么问：{_q.basis}")
                for _e in _q.evidence:
                    st.caption(f"依据：{_e}")
                _answers[_q.qid] = st.text_input(
                    "你的答复", key=f"clar_{_q.qid}",
                    placeholder=" / ".join(_q.suggestions) if _q.suggestions else "")
                st.caption(f"不回答的影响：{_q.impact}")
                st.divider()
            if st.button("📝 应用澄清（重新生成报告）", key="apply_clar"):
                _rec = apply_clarifications(audit, _answers)
                if _rec:
                    from paper2lab.report import generate_report
                    st.session_state["report"] = generate_report(audit)
                    st.session_state["clar_done"] = len(_rec)
                    st.rerun()
                else:
                    st.info("尚未填写任何答复。")
            if st.session_state.get("clar_done"):
                st.success(f"已记录 {st.session_state.pop('clar_done')} 条人工确认，"
                           f"报告已同步更新。", icon="✅")

    # ---- 第三期: 根因追查 + 补丁草案（2026-09-28 起由流水线里的两站产出）
    # 之前这两件事只在 CLI 汇总脚本里算、界面一个字都没有 —— 用户问「补丁为什么被拒」时
    # 产品答不上来。现在它们与其它环节同权：这里能看结论、看 diff、看每一条拒绝理由。
    _tr = list(getattr(audit, "rootcause", None) or [])
    _pt = list(getattr(audit, "patches", None) or [])
    if _tr or _pt:
        _p_ok = [p for p in _pt if p.is_proposed]
        _p_no = [p for p in _pt if not p.is_proposed]
        _p_ai = sum(1 for p in _p_ok if getattr(p, "source", "rule") == "llm")
        _loc = sum(1 for t in _tr if getattr(t, "confidence", "none") != "none")
        with st.expander(
                f"🔧 根因追查与补丁草案（可定位 {_loc}/{len(_tr)} · "
                f"补丁给方案 {len(_p_ok)} / 拒绝 {len(_p_no)}"
                + (f" · 其中 {_p_ai} 条目标由 AI 提名" if _p_ai else "") + "）："):
            st.caption("补丁只展示、**绝不落盘**；只改配置项的值，拿不准的一律拒绝并写明理由。")
            if _tr:
                st.markdown("**根因追查**（只读代码，追不出就明说「无法定位」）")
                st.dataframe(
                    [{"参数": t.display,
                      "最终生效值": (t.verdict
                                     if getattr(t, "confidence", "none") != "none" else "—"),
                      "位置": (t.verdict_loc or "—"),
                      "置信": t.confidence,
                      "依据": (t.reason or "")[:120]}
                     for t in _tr],
                    use_container_width=True, hide_index=True)
            if _p_ok:
                st.markdown("**给方案的补丁**（原行与改后行都由程序生成，是否采纳由你定）")
                for _p in _p_ok:
                    _ai = getattr(_p, "source", "rule") == "llm"
                    st.markdown(("⚠️ " if _ai else "") + f"`{_p.target}`　**{_p.display}**"
                                + ("　—　**目标由 AI 提名，采纳前须人工确认**" if _ai else ""))
                    st.code(_p.diff or "", language="diff")
                    st.caption(_p.rationale)
                    for _s in (getattr(_p, "stamps", None) or []):
                        st.caption(f"　程序盖章：{_s}")
            if _p_no:
                st.markdown(f"**拒绝的补丁（{len(_p_no)} 条，逐条写明理由）**")
                for _p in _p_no:
                    st.caption(f"⛔ {_p.display} —— {_p.refuse_reason}")

    _lm = r.get("llm_mode")
    if _lm == "deepseek":
        _rc, _ch = r.get("llm_real_calls", 0), r.get("llm_cache_hits", 0)
        _llm_label = f"DeepSeek API（真实调用 {_rc} 条" + (
            f" · 缓存命中 {_ch} 条）" if _ch else "）")
    elif _lm == "fallback":
        _llm_label = (f"内置模板（DeepSeek 调用失败已降级："
                      f"{r.get('llm_error') or '未知原因'}）")
    else:
        _llm_label = "内置模板（未配置 API key）"
    st.html(f"""<div class="sec"><span class="sec-n">03</span>
    <span class="sec-h">复现就绪度</span>
    <span class="sec-sub">发现 <b style="color:#e5484d">{len(issues)}</b> 项复现风险 ·
    归因引擎 {_llm_label}</span></div>""")
    st.html(_ready_band(r.get("total", 0), r.get("categories", {}),
                        r.get("audit_confidence")))
    st.caption("就绪度＝被审对象；审计可信度＝本次审计过程。")
    _unv = r.get("unverified") or {}
    if _unv:
        st.info("未核验维度（不计入总分）：\n\n"
                + "\n".join(f"- **{k}**：{v}" for k, v in _unv.items()), icon="⚪")
    if r.get("dominant_issues"):
        st.warning("⚠️ 当前阻碍复现的主要因素：**" + "、".join(r["dominant_issues"]) + "**")

    # ---- ④ 风险与报告
    st.markdown("""<div class="sec"><span class="sec-n">04</span>
    <span class="sec-h">审计发现</span>
    <span class="sec-sub">无论是否发现风险, 每项结论均附证据链: 论文页码·章节 + 代码文件:行号</span></div>""",
                unsafe_allow_html=True)

    # ---- 证据链总览表(一致项同样可追溯)
    ok_count = len(audit.findings) - len(issues)
    overview_rows = []
    for f in audit.findings:
        zh, _c = RISK_META[f.risk.value]
        overview_rows.append({
            "参数 / 指标": f.display_name,
            "论文声明值": f.paper.raw_value if f.paper else "—",
            "📄 论文出处": f.paper.location if f.paper else "未声明",
            "代码实现值": f.code.raw_value if f.code else "—",
            "💻 代码位置": f.code.location if f.code else "未找到",
            "状态": f"{STATUS_ICON[f.status]} {STATUS_ZH[f.status]}",
            "风险": zh,
            "证据自证": "✅" if f.verified else "❌",
        })
    with st.expander(f"🔗 证据链总览（{len(audit.findings)} 项：{len(issues)} 项风险 + {ok_count} 项一致，全部可追溯）",
                     expanded=True):
        st.dataframe(overview_rows, use_container_width=True, hide_index=True)
        env = audit.code.requirements
        if env:
            env_str = "　".join(f"`{k}{'==' + v if v else ''}`" for k, v in list(env.items())[:8])
            st.caption(f"🧰 环境依赖证据（出处: requirements.txt）: {env_str}")

    consistent = [f for f in audit.findings if f.status == Status.CONSISTENT]

    # 一条审计项都没有 ≠ 全部通过: 说明提取失败, 必须明确警示
    if not audit.findings:
        st.error(
            "⚠️ **未能从论文/代码中提取到任何可审计的参数**——这不是「全部通过」。\n\n"
            "可能原因：① 论文为扫描版/图片型 PDF，文字无法提取；"
            "② 参数以表格或图片形式存在；③ 参数表述句式超出当前规则库覆盖范围；"
            "④ 代码中未找到训练配置（如在 notebook 或二进制文件中）。\n\n"
            "建议：换用文字型 PDF 重试，或将该样本反馈给开发组补充解析规则。")
        st.stop()

    tab_risk, tab_ok, tab_trust, tab_report = st.tabs(
        [f"⚠️ 风险项 ({len(issues)})", f"✅ 一致性证据 ({ok_count})",
         "🔎 审计可信度", "📑 审计报告"])
    with tab_trust:
        _render_trust_panel(audit)
    with tab_risk:
        if not issues:
            st.success(f"✅ 未发现复现风险：{ok_count} 项审计项全部通过规则验证")
            st.markdown("👉 请切换到 **「✅ 一致性证据」** 标签页查看所有通过项的完整证据链"
                        "（论文页码·章节 + 代码文件:行号 + 归一化验证）")
        for f in issues:
            _render_finding(f)
    with tab_ok:
        if not consistent:
            st.info("本期没有一致性项")
        st.caption("以下审计项经程序规则验证一致，证据链同样完整可追溯：")
        for f in consistent:
            _render_finding(f)
    with tab_report:
        _rc1, _rc2 = st.columns(2)
        with _rc1:
            st.download_button("⬇️ 下载审计报告 (Markdown)", report_md,
                               file_name="paper2lab_audit_report.md",
                               mime="text/markdown", use_container_width=True)
        with _rc2:
            _repro_md = ""
            try:
                from paper2lab.repro import build_repro_pack
                _repro_md = build_repro_pack(audit).to_markdown()
            except Exception:      # noqa: BLE001
                _repro_md = ""
            if _repro_md:
                st.download_button("📋 下载复现准备清单 (Markdown)", _repro_md,
                                   file_name="paper2lab_repro_pack.md",
                                   mime="text/markdown", use_container_width=True)
            else:
                st.caption("（复现准备清单生成失败）")
        st.caption("复现准备清单：环境依赖、超参对照（带出处）、待确认事项、已知风险。")
        st.markdown(report_md)
else:
    st.info("👆 选择输入后点击「开始科研审计」", icon="💡")
    with st.expander("ℹ️ 平台工作原理"):
        # 流水线用 STEPS 派生，不写死 —— 之前这里硬编码了 7 步（早过期了）
        st.markdown(f"**审计流水线（{len(STEPS)} 环节 / {len(TOOLS)} 工具）**："
                    + " → ".join(STEPS) + "\n\n"
                    "- 🔧 一致性判断由**程序化规则验证**完成"
                    "（AST 静态分析 + 数值归一化比对，如 `1e-4 = 0.0001`）\n"
                    "- 🤖 AI 只负责**风险解释与归因**，并可提议（排计划 / 挑补丁目标）"
                    "—— 但提议必须经程序盖章\n"
                    "- 🔗 每条审计发现均附**证据链**：论文页码·章节 + 代码文件:行号，可追溯、可复核\n")
