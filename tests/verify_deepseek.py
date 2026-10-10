"""端到端验证：DeepSeek 真实归因是否生效（对照 Mock）。"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import time
from paper2lab.pipeline import run_audit

print("=== 真实 DeepSeek 归因 ===")
t0 = time.time()
audit, report = run_audit("demo/paper.pdf", "demo/project.zip", None)
r = audit.readiness
print(f"  llm_mode       = {r.get('llm_mode')}")
print(f"  真实调用条数   = {r.get('llm_real_calls')}")
print(f"  失败原因       = {r.get('llm_error') or '(无)'}")
print(f"  耗时           = {time.time()-t0:.1f}s")
print(f"  就绪度         = {r.get('total')} | 自检 {audit.selfcheck['passed']}/{audit.selfcheck['checked']}")

print("\n--- 归因文字样例（前 3 条非一致项）---")
n = 0
for f in audit.findings:
    if f.ai_analysis and n < 3:
        n += 1
        print(f"\n[{f.display_name} · {f.status.value} · {f.risk.value}]")
        print(f"  {f.ai_analysis[:200]}")

print("\n=== 对照: 强制 Mock(故意用内置模板做措辞对比, 不是异常) ===")
audit2, _ = run_audit("demo/paper.pdf", "demo/project.zip", None, force_mock=True)
r2 = audit2.readiness
print(f"  llm_mode = {r2.get('llm_mode')} | 真实调用 {r2.get('llm_real_calls')}")
for f in audit2.findings:
    if f.ai_analysis:
        print(f"  模板样例: {f.ai_analysis[:110]}")
        break

print("\n=== 结论 ===")
# 判定: 模式为 deepseek 且"真实调用 + 缓存命中" > 0 即说明真实 LLM 路径生效。
# 缓存命中不算失败——同一 prompt 已问过, 直接复用结果, 不重复计费。
_rc = r.get("llm_real_calls", 0)
_ch = r.get("llm_cache_hits", 0)
ok = (r.get("llm_mode") == "deepseek" and (_rc + _ch) > 0
      and any(f.ai_analysis for f in audit.findings))
print(f"  llm_mode={r.get('llm_mode')} 真实调用={_rc} 缓存命中={_ch}")
print("  ✅ DeepSeek 真实归因路径生效" if ok else "  ⚠️ 未走 DeepSeek(请检查 key/网络)")
raise SystemExit(0 if ok else 1)
