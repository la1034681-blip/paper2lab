"""抽取 Agent（第一期）消融验证——同一批样本, Agent 开/关 对比。

指标: 论文"提到但未取到值"的参数种类数（越少越好）, 以及 Agent 的补漏轨迹与预算消耗。

成本控制（重要）:
- 主图像通道在消融时压到 2 个区域（否则 10 次全流程会因全量读图跑到十几分钟）;
- Agent 自身也有硬预算（LLM/视觉/秒数）, 超限即停并如实记录;
- 每跑完一套样本立刻落盘, 中途可看进度。

用法: .venv\\Scripts\\python.exe verify_agent.py [样本名 ...]
输出: Paper2Lab测试集/agent_report.md
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import sys
import time
from pathlib import Path

from paper2lab.envfile import get, load_env
from paper2lab.pipeline import run_audit

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
OUT = ROOT / "agent_report.md"
load_env()

VISION_CAP = 2          # 消融时主通道读图上限
AGENT_BUDGET = {"max_llm_calls": 2, "max_vision_calls": 2, "max_seconds": 60.0}


def say(s: str):
    print(s, flush=True)


def kinds_stats(audit):
    seen = set(audit.paper.alias_kinds or [])
    got = set(audit.paper.params_all or {}) | set(audit.paper.image_params or {})
    return len(seen), len(got & seen), sorted(seen - got)


def run_one(d: Path, enable: bool):
    rf = d / "results.json"
    ur = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else None
    t0 = time.time()
    audit, _ = run_audit(str(d / "paper.pdf"), str(d / "code.zip"), ur,
                         api_key=get("DEEPSEEK_API_KEY") or None,
                         enable_agent=enable,
                         vision_max_regions=VISION_CAP,
                         agent_budget=AGENT_BUDGET)
    return audit, time.time() - t0


def render(rows) -> str:
    log = ["# 抽取 Agent（第一期）消融验证报告", "",
           f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M')}",
           "- 口径: 同一份论文/代码, 只切换 `enable_agent`; 数字为『提到但未取到值』的参数种类数",
           "- Agent 阶梯: text-l1 → text-l2 → negation → llm（提议 + 程序回原文核对）→ vision（读图取交集）",
           f"- 消融预算: 主图像通道上限 {VISION_CAP} 个区域; Agent 预算 {AGENT_BUDGET}",
           "  —— 刻意比产品默认更严(产品默认 3 次 LLM / 45s), 用于压测预算边界", ""]
    if not rows:
        log.append("（尚无结果）")
        return "\n".join(log)
    tot_off = sum(r["off"] for r in rows)
    tot_on = sum(r["on"] for r in rows)
    log += ["## 汇总", "",
            "| 样本 | 未取到(Agent关) | 未取到(Agent开) | 补回 | 种类覆盖(开) | 耗时(开) |",
            "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        gained = "、".join(f"{a['display']}={a['value']}" for a in r["accepted"]) or "—"
        log.append(f"| {r['name']} | {r['off']} | {r['on']} | {gained} | "
                   f"{r['got_on']}/{r['seen']} | {r['t_on']:.1f}s |")
    log += ["", f"**合计未取到: {tot_off} 类 → {tot_on} 类**"
                + (f"（下降 {tot_off - tot_on} 类）" if tot_off else ""),
            "", "## 逐样本轨迹（每次尝试都留痕，可回放）", ""]
    for r in rows:
        log += [f"### {r['name']}", "",
                f"- 待补目标: {'、'.join(r['miss_off']) or '（无）'}",
                f"- 补回: {'、'.join(a['display'] + '=' + a['value'] for a in r['accepted']) or '（无）'}",
                f"- 仍未取到: {'、'.join(r['miss_on']) or '（无）'}",
                f"- 结束原因: {r['stop']}",
                f"- 预算消耗: {r['budget']}", "",
                "| # | 参数 | 工具 | 结果 | 取值 | 页 | 说明 |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for s in r["trace"]:
            log.append(f"| {s['seq']} | {s['display']} | {s['tool']} | {s['status']} | "
                       f"{s.get('value') or '—'} | {s.get('page') or '—'} | "
                       f"{(s.get('note') or '').replace('|', '/')[:80]} |")
        log.append("")
    return "\n".join(log)


def main():
    names = sys.argv[1:]
    samples = sorted(p for p in ROOT.iterdir()
                     if p.is_dir() and (p / "paper.pdf").exists()
                     and (p / "code.zip").exists()
                     and (not names or p.name in names))
    rows = []
    OUT.write_text(render(rows), encoding="utf-8")
    for i, d in enumerate(samples, 1):
        say(f"[{i}/{len(samples)}] {d.name}: Agent 关 …")
        off, t_off = run_one(d, False)
        s_off, g_off, miss_off = kinds_stats(off)
        say(f"    Agent 关: 未取到 {len(miss_off)} 类 {miss_off}  ({t_off:.1f}s)")
        say(f"    现在开 Agent …")
        on, t_on = run_one(d, True)
        s_on, g_on, miss_on = kinds_stats(on)
        tr = on.paper.agent_meta or {}
        accepted = [x for x in (tr.get("steps") or [])
                    if x.get("status") == "accepted"]
        say(f"    Agent 开: 未取到 {len(miss_on)} 类 {miss_on}; "
            f"补回 {[a['display'] + '=' + a['value'] for a in accepted]}  ({t_on:.1f}s)")
        rows.append({"name": d.name, "off": len(miss_off), "on": len(miss_on),
                     "seen": s_on, "got_on": g_on,
                     "accepted": accepted, "miss_off": miss_off, "miss_on": miss_on,
                     "trace": tr.get("steps") or [], "budget": tr.get("budget") or {},
                     "stop": tr.get("stopped_reason", ""), "t_on": t_on})
        OUT.write_text(render(rows), encoding="utf-8")   # 每套落盘, 便于中途查看
    print(f"\n报告: {OUT}")


if __name__ == "__main__":
    main()
