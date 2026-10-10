"""全流程实测(指定本地文件)——用于真实数据不在测试集目录时的场景。"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import sys
import time
from pathlib import Path

from paper2lab.pipeline import run_audit

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
name, pdf, zipf = sys.argv[1], sys.argv[2], sys.argv[3]

marks: list[float] = []
t0 = time.time()


def progress(i: int, step: str):
    marks.append(time.time() - t0)


audit, report = run_audit(pdf, zipf, None, force_mock=True, progress=progress)
total = time.time() - t0
cov = audit.coverage
img = cov.get("image", {})
vlm = [f for f in audit.findings if f.paper and f.paper.parser == "vlm"]

log = [f"# 全流程实测 — {name}", "",
       f"- 论文: `{pdf}`", f"- 代码: `{zipf}`", f"- 总耗时: **{total:.1f}s**", "",
       "## 各步耗时", ""]
prev = 0.0
for i, ts in enumerate(marks):
    log.append(f"{i + 1}. 第 {i + 1} 步 — 累计 {ts:.1f}s (+{ts - prev:.1f}s)")
    prev = ts
log += ["", "## 解析通道", "",
        f"- 论文页: {cov.get('pages_parsed')}/{cov.get('pages_total')} 可解析, "
        f"薄页(图片/扫描页) {cov.get('pages_thin')}",
        f"- 参数种类覆盖: {cov.get('kinds_valued')}/{cov.get('kinds_seen')} 类",
        f"- 代码: {cov.get('code_ok')}/{cov.get('code_files')} 成功, "
        f"多语言通道 {len(cov.get('multilang') or [])} 个, "
        f"无法处理 {len(cov.get('unsupported') or [])} 个",
        f"- 图像通道: 区域 {img.get('regions')} 个, 读图 {img.get('regions_read')} 个, "
        f"采信 {img.get('kept')} 条, 丢弃 {img.get('dropped')} 条 "
        f"(模型 {img.get('model') or '—'}, 来源 {img.get('source') or '—'})",
        f"- 审计可信度: {cov.get('confidence_level')}({cov.get('confidence_score')})",
        "", "## 审计结论", "",
        f"- 就绪度: **{audit.readiness.get('total')}** / 100",
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
        log.append(f"- {f.display_name}: 读图 `{f.paper.raw_value}` @ {f.paper.location}"
                   f" → {f.status.value} (置信 {f.confidence.value})")
for n in img.get("notes", []):
    log.append(f"- 图像提示: {n}")

(OUT / f"full_flow_{name}.md").write_text("\n".join(log), encoding="utf-8")
print("\n".join(log))
