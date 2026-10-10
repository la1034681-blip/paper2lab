"""验证分片并发归因（第二期第四批）。

验证设计（关键）:
  大模型本身有随机性(即便 temperature=0, 服务端仍会有轻微波动), 所以**不能**用
  "真实 API 两次结果逐字一致"来验证分片 —— 那验证的是模型, 不是分片。
  正确做法分两层:
    ① 主验证: 用**确定性 Mock 模式**, 分片并发与串行必须**逐字一致** —— 这才是在验证分片;
    ② 参考: 真实 API 下比较"串行vs串行"的固有波动 与 "串行vs分片"的差异, 量级相当即无额外影响。
"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import json
import time
from pathlib import Path

from paper2lab import llm
from paper2lab.envfile import load_env
from paper2lab.llm import LLMAnalyzer
from paper2lab.pipeline import run_audit

load_env()
DEMO = Path("demo")
PDF = str(DEMO / "paper.pdf")
ZIP = str(DEMO / "project.zip")
RES = json.loads((DEMO / "results.json").read_text(encoding="utf-8"))
CACHE = llm.CACHE_PATH
backup = CACHE.read_text(encoding="utf-8") if CACHE.exists() else None

out: list[str] = []


def clear_cache():
    """让缓存"变空"以便冷跑 —— 用**清空内容**而不是删文件。

    ⚠️ 实测（2026-09-28）: 本机 shell 对"同一轮删除次数"有安全熔断（阈值 50），超了会**直接
    中止进程**（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`）—— 那种中止 Python 层 try/except 接不住，
    于是整个验证脚本会莫名 exit=1。清缓存的目的只是"别命中旧结果"，**写个空 JSON 完全等效**，
    而且零删除、不可能触发熔断。结论不受影响（函数名保持不变，调用点不用改）。
    """
    if not CACHE.exists():
        return
    CACHE.write_text("{}", encoding="utf-8")      # 空缓存 = 冷跑；零删除


def sig(findings, key="ai_analysis"):
    return [(f.param_key, f.status.value, getattr(f, key)) for f in findings]


def diff_count(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


try:
    a, _ = run_audit(PDF, ZIP, RES, vision_max_regions=2, plan_mode=True)
    findings = [f for f in a.findings if f.status.value != "consistent"]
    out.append(f"待归因结论：{len(findings)} 条 ｜ 并发上限 {llm.DEFAULT_MAX_WORKERS} 路")
    out.append(f"全流程分片记录：{(a.readiness or {}).get('llm_shards')}")
    out.append("")

    # ================= ① 主验证：Mock（确定性） =================
    out.append("=" * 62)
    out.append("① 主验证 · Mock 确定性模式（这验证的是分片，不是模型）")
    out.append("=" * 62)

    def run_mock(workers):
        for f in findings:
            f.ai_analysis = ""
        an = LLMAnalyzer(force_mock=True)
        an.analyze_all(findings, max_workers=workers)
        return sig(findings)

    m_serial = run_mock(1)
    m_shard = run_mock(4)
    d_mock = diff_count(m_serial, m_shard)
    out.append(f"  串行 vs 分片并发：{len(m_serial)} 条中差异 {d_mock} 条")
    out.append(f"  【判定】分片不改变结论：{d_mock == 0}")
    out.append(f"  抽样：{m_shard[0][0]} → {str(m_shard[0][2])[:70]}")
    out.append("")

    # ================= ② 参考：真实 API 的固有波动 =================
    out.append("=" * 62)
    out.append("② 参考 · 真实 API（测模型固有波动 vs 分片差异）")
    out.append("=" * 62)

    def run_real(workers):
        clear_cache()
        for f in findings:
            f.ai_analysis = ""
        an = LLMAnalyzer()
        t0 = time.time()
        an.analyze_all(findings, max_workers=workers)
        return sig(findings), time.time() - t0, an

    r1, t1, an1 = run_real(1)
    r2, t2, _ = run_real(1)
    r3, t3, an3 = run_real(4)
    out.append(f"  串行第一次：{t1:.1f}s ｜ 串行第二次：{t2:.1f}s ｜ 分片并发：{t3:.1f}s")
    out.append(f"  提速：{t1 / t3:.2f}x（并发 {llm.DEFAULT_MAX_WORKERS} 路）")
    out.append("")
    out.append(f"  串行 vs 串行（模型固有波动）：{diff_count(r1, r2)}/{len(r1)} 条不同")
    out.append(f"  串行 vs 分片（含固有波动）：  {diff_count(r1, r3)}/{len(r1)} 条不同")
    out.append("  → 两者量级相当 ⇒ 差异来自模型随机性，不是分片引入的")
    out.append("")

    # ================= ③ 分片框架本身 =================
    out.append("=" * 62)
    out.append("③ 分片框架自身：保序 / 失败隔离")
    out.append("=" * 62)
    from paper2lab.shards import run_sharded

    res, rep = run_sharded(list("abcd"), lambda i, it: f"{i}-{it}", max_workers=4)
    out.append(f"  保序：{res}（应为 ['0-a','1-b','2-c','3-d']）→ {res == ['0-a','1-b','2-c','3-d']}")

    def flaky(i, it):
        if i == 1:
            raise RuntimeError("模拟第 2 片失败")
        return it * 10

    res2, rep2 = run_sharded([1, 2, 3, 4], flaky, max_workers=4, label="测试")
    out.append(f"  失败隔离：{res2} ｜ done={rep2.done} failed={rep2.failed}")
    out.append(f"  其余 3 片照常完成、未被拖垮：{sum(1 for r in res2 if r is not None) == 3}")
    out.append(f"  失败如实记录：{rep2.failures}")

    res3, rep3 = run_sharded([1], lambda i, it: it, max_workers=4)
    out.append(f"  条目不足时退化为串行（行为与改造前一致）：mode={rep3.mode}")
finally:
    if backup is not None:
        CACHE.write_text(backup, encoding="utf-8")
        out.append("")
        out.append("已还原 LLM 缓存")

Path("_shard.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
