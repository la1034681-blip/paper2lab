"""全流程实测——对一套真实论文/代码跑完整流水线(视觉通道走真实模型)。

用法: .venv\\Scripts\\python.exe run_full_real.py [样本目录名] [--mock]
默认走真实 LLM 归因(.env 里配了 DEEPSEEK_API_KEY 时); 加 --mock 则强制内置模板。
输出: 控制台逐步耗时 + 测试集目录下 full_flow_<样本>.md
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import sys
import time
from pathlib import Path

from paper2lab.pipeline import STEPS, run_audit

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
USE_MOCK = "--mock" in sys.argv
name = args[0] if args else "05_SimCLR"
d = SAMPLES / name
res_file = d / "results.json"

marks: list[tuple[str, float]] = []
t_start = time.time()


def progress(i: int, step: str):
    marks.append((step, time.time() - t_start))


import json

# 实验结果文件(可选): 论文声明结果 vs 实际结果 的核验需要它
user_results = None
if res_file.exists():
    try:
        user_results = json.loads(res_file.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ results.json 解析失败(已忽略): {e}")

audit, report = run_audit(str(d / "paper.pdf"), str(d / "code.zip"),
                          user_results, force_mock=USE_MOCK, progress=progress)
total = time.time() - t_start

log = [f"# 全流程实测 — {name}", "",
       f"- 论文: `{d / 'paper.pdf'}`", f"- 代码: `{d / 'code.zip'}`",
       f"- 实验结果数据: "
       + (f"`{res_file}` → {user_results}" if user_results else "(未提供, 跳过结果核验)"),
       f"- 总耗时: **{total:.1f}s**", "", "## 各步耗时", ""]
for i, (step, ts) in enumerate(marks):
    prev = marks[i - 1][1] if i else 0.0
    log.append(f"{i + 1}. {step} — 完成后累计 {ts:.1f}s (本步 {ts - prev:.1f}s)")

cov = audit.coverage
img = cov.get("image", {})
vlm = [f for f in audit.findings if f.paper and f.paper.parser == "vlm"]
_cap = ("全量读取" if img.get("unlimited")
        else f"上限 {img.get('max_regions')} 个")
_tread = cov.get("thin_pages_read") or []
_tunread = cov.get("thin_pages_unread") or []
if not img.get("candidates"):
    _img_line = "- 图像通道: 候选 0 个(该论文无位图/扫描区域, 图形均为矢量图, 文本层已覆盖)"
elif img.get("enabled"):
    _img_line = (f"- 图像通道: 候选 {img.get('candidates')} 个 → 读图 {img.get('regions_read')} 个"
                 f"（{_cap}）, 采信 {img.get('kept')} 条, 丢弃 {img.get('dropped')} 条 "
                 f"(模型 {img.get('model', '—')}, 来源 {img.get('source', '—')})")
else:
    _img_line = (f"- 图像通道: 候选 {img.get('candidates')} 个, **未启用**(未配置视觉模型 key)"
                 " —— 其内容未参与审计")
log += ["", "## 解析通道", "",
        f"- 论文内容覆盖: {cov.get('pages_covered')}/{cov.get('pages_total')}"
        f"({(cov.get('pages_cover_ratio') or 0):.0%})"
        + (f" —— 文本层 {cov.get('pages_parsed')} 页 + 读图 {cov.get('pages_covered_by_vision')} 页"
           if cov.get("pages_covered_by_vision") else f" —— 全部来自文本层"),
        f"- 文本层可解析页: {cov.get('pages_parsed')}/{cov.get('pages_total')}, "
        f"薄页 {cov.get('pages_thin')}",
        f"- 参数种类覆盖: {cov.get('kinds_valued')}/{cov.get('kinds_seen')} 类",
        f"- 代码: {cov.get('code_ok')}/{cov.get('code_files')} 成功, "
        f"多语言通道 {len(cov.get('multilang') or [])} 个文件, "
        f"无法处理 {len(cov.get('unsupported') or [])} 个",
        _img_line,
        f"- 稀薄页覆盖: 共 {cov.get('pages_thin')} 页, 已读图 {len(_tread)} 页"
        + (f", 未读图 {_tunread}" if _tunread else "（全覆盖）"),
        f"- 取值来源分布: {cov.get('kinds_by_channel')}",
        f"- 审计可信度: {cov.get('confidence_level')}({cov.get('confidence_score')})",
        f"- AI 归因引擎: {audit.readiness.get('llm_mode')} "
        f"(真实调用 {audit.readiness.get('llm_real_calls', 0)} 条"
        f" · 缓存命中 {audit.readiness.get('llm_cache_hits', 0)} 条"
        + (f", 失败原因 {audit.readiness.get('llm_error')}" if audit.readiness.get("llm_error") else "")
        + ")",
        "", "## 审计结论", "",
        f"- 就绪度: **{audit.readiness.get('total')}** / 100",
        f"- 发现 {len([f for f in audit.findings if f.status.value != 'consistent'])} 条风险, "
        f"{len([f for f in audit.findings if f.status.value == 'consistent'])} 条一致",
        f"- 证据自证: {audit.selfcheck.get('passed')}/{audit.selfcheck.get('checked')} 通过",
        f"- 程序比较日志: {len(audit.compare_log)} 条", "",
        "| 参数 | 论文 | 代码 | 状态 | 风险 | 置信 | 自证 |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
for f in audit.findings:
    log.append(f"| {f.display_name} | `{f.paper.raw_value if f.paper else '—'}` | "
               f"`{f.code.raw_value if f.code else '—'}` | {f.status.value} | "
               f"{f.risk.value} | {f.confidence.value} | {'✅' if f.verified else '❌'} |")
if vlm:
    log += ["", "**图像通道(读图)结论**:"]
    for f in vlm:
        log.append(f"- {f.display_name}: 读图 `{f.paper.raw_value}` "
                   f"@ {f.paper.location} vs 代码 "
                   f"`{f.code.raw_value if f.code else '—'}` → {f.status.value}")
if img.get("notes"):
    log += ["", "**图像通道提示**:"]
    for n in img["notes"]:
        log.append(f"- {n}")

(SAMPLES / f"full_flow_{name}.md").write_text("\n".join(log), encoding="utf-8")
(d / "audit_report.md").write_text(report, encoding="utf-8")
print("\n".join(log[:60]))
print(f"\n报告: {SAMPLES / f'full_flow_{name}.md'}")
