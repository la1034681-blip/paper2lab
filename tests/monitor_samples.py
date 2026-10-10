"""真实论文测试集监控——逐套跑审计, 自动检查功能是否正常并输出测试报告。

用法: .venv\\Scripts\\python.exe monitor_samples.py
测试集目录: C:\\Users\\lijiahui\\Desktop\\Paper2Lab测试集
输出: 该目录下 test_report.md + 控制台摘要

注意: 产品默认是"全量读图"(读全部候选区域), 一篇 25 页论文冷缓存约 2 分钟;
本监控脚本跑 5 套会太慢, 因此**默认把读图上限压到 3 个区域**(仅用于回归),
需要按产品默认跑全量时: 设 PAPER2LAB_VISION_MAX_REGIONS=0 再执行。
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import os
import time
import traceback
from pathlib import Path

from paper2lab.models import Status
from paper2lab.pipeline import run_audit

# 回归用: 限制读图区域数, 避免 5 套样本 × 全量读图导致超时
os.environ.setdefault("PAPER2LAB_VISION_MAX_REGIONS", "3")

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")

# 期望项: 人工依据各仓库的公开实现给出的"理应能抓到"的参数(用于发现漏抽)
EXPECT = {
    "01_BERT": ["learning_rate", "batch_size", "epochs", "optimizer"],
    "02_pix2pix": ["learning_rate", "batch_size", "epochs", "momentum"],
    "03_TabNet": ["learning_rate", "batch_size", "epochs"],
    "04_SimSiam": ["learning_rate", "batch_size", "epochs", "momentum"],
    "05_SimCLR": ["learning_rate", "batch_size", "epochs"],
}

MD = []


def log(line: str = ""):
    print(line)
    MD.append(line)


def main():
    # 只把"含 paper.pdf + code.zip"的目录当样本, 跳过硬性要求的辅助目录
    samples = sorted(p for p in ROOT.iterdir()
                     if p.is_dir() and (p / "paper.pdf").exists() and (p / "code.zip").exists())
    log("# Paper2Lab 真实论文测试集 —— 功能测试报告")
    log()
    log(f"- 测试时间: {time.strftime('%Y-%m-%d %H:%M')}")
    log(f"- 样本数: {len(samples)}(arXiv 论文 PDF + GitHub 官方代码包)")
    log("- 监控方式: 逐套跑完整流水线, 自动记录参数抽取/证据自证/覆盖率/耗时, 并标记异常")
    log(f"- 读图区域上限: {os.environ.get('PAPER2LAB_VISION_MAX_REGIONS')}"
        "(回归模式压缩上限以控速; 产品页面默认为 0 = 全部读取)")
    log()

    summary_rows = []
    anomalies: list[str] = []

    for d in samples:
        name = d.name
        pdf = d / "paper.pdf"
        zipf = d / "code.zip"
        res_file = d / "results.json"
        user_results = json.loads(res_file.read_text(encoding="utf-8")) if res_file.exists() else None

        log(f"## {name}")
        log()
        if not pdf.exists() or not zipf.exists():
            log("- ❌ 样本文件缺失, 跳过")
            anomalies.append(f"{name}: 文件缺失")
            log()
            continue

        t0 = time.time()
        try:
            audit, report = run_audit(str(pdf), str(zipf), user_results, force_mock=True)
        except Exception:
            err = traceback.format_exc()
            log("- ❌ **流水线异常**")
            log("```text")
            log(err.strip())
            log("```")
            anomalies.append(f"{name}: 流水线抛出异常")
            log()
            continue
        elapsed = time.time() - t0

        cov = audit.coverage
        sc = audit.selfcheck
        issues = [f for f in audit.findings if f.status != Status.CONSISTENT]

        p_keys = set(audit.paper.params)
        c_keys = set(audit.code.params)
        log(f"- 耗时 **{elapsed:.1f}s** | 论文 {audit.paper.page_count} 页 | "
            f"代码 {audit.code.python_files} 个模块")
        log(f"- 论文抽出参数 {len(p_keys)} 个: {', '.join(sorted(p_keys)) or '(无)'}")
        log(f"- 代码抽出参数 {len(c_keys)} 个: {', '.join(sorted(c_keys)) or '(无)'}")
        log(f"- 就绪度 **{audit.readiness.get('total')}** | 审计可信度 "
            f"**{cov.get('confidence_level')}({cov.get('confidence_score')})**")
        log(f"- 解析覆盖: 页 {cov.get('pages_parsed')}/{cov.get('pages_total')}, "
            f"声明 {cov.get('decl_matched')}/{cov.get('decl_total')}, "
            f"代码 {cov.get('code_ok')}/{cov.get('code_files')}")
        log(f"- 证据自证: {sc.get('passed')}/{sc.get('checked')} 通过")
        log(f"- 审计发现 {len(audit.findings)} 条(其中风险 {len(issues)} 条)")

        if audit.findings:
            log()
            log("| 参数 | 论文 | 代码 | 状态 | 风险 | 自证 |")
            log("| --- | --- | --- | --- | --- | --- |")
            for f in audit.findings:
                pv = f.paper.raw_value if f.paper else "—"
                cv = f.code.raw_value if f.code else "—"
                log(f"| {f.display_name} | `{pv}` | `{cv}` | {f.status.value} | "
                    f"{f.risk.value} | {'✅' if f.verified else '❌'} |")
        log()

        # ---- 自动异常检查
        checks = []
        if not audit.findings:
            checks.append("零提取: 未抽到任何可审计项")
        if audit.code.failed_files:
            checks.append(f"代码解析失败 {len(audit.code.failed_files)} 个文件")
        if sc.get("failed"):
            checks.append(f"证据自证未通过 {sc['failed']} 条")
        missing = [k for k in EXPECT.get(name, []) if k not in p_keys and k not in c_keys]
        if missing:
            checks.append("期望项未抽到: " + ", ".join(missing))
        if cov.get("confidence_level") == "低":
            checks.append("审计可信度低")
        log(f"- 自动检查: {'⚠️ ' + '；'.join(checks) if checks else '✅ 全部通过'}")
        log()
        for c in checks:
            anomalies.append(f"{name}: {c}")

        (d / "audit_report.md").write_text(report, encoding="utf-8")
        summary_rows.append((name, audit.readiness.get("total"), cov.get("confidence_level"),
                             len(p_keys), len(c_keys), len(issues), elapsed))

    log("---")
    log()
    log("## 汇总")
    log()
    log("| 样本 | 就绪度 | 可信度 | 论文参数 | 代码参数 | 风险项 | 耗时 |")
    log("| --- | --- | --- | --- | --- | --- | --- |")
    for r in summary_rows:
        log(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]:.1f}s |")
    log()
    if anomalies:
        log("## 待关注项")
        log()
        for a in anomalies:
            log(f"- {a}")
    else:
        log("## 待关注项")
        log()
        log("- 无: 全部样本功能正常")

    (ROOT / "test_report.md").write_text("\n".join(MD), encoding="utf-8")
    print("\nTEST REPORT SAVED")


if __name__ == "__main__":
    main()
