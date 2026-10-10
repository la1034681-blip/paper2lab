"""诊断：消融对照里 03_NeRF 的"不一致"到底是什么。

背景（2026-09-29 全套回归）：`消融对照 经典vs计划 8套` exit=1，
报告显示 03_NeRF「结论签名 不同 / 就绪度 85 vs 87 / 不一致」，
但「不一致明细」那一节是**空的**（因为明细用的是集合差，而判定用的有序列表比较）。

两种可能，必须分清：
  A. **只是顺序不同** —— `llm_analyze` 走分片并发（4 路），findings 的返回顺序
     受线程调度影响。内容一样、顺序不同，判定就会假失败（这是对照脚本的脆弱点）。
  B. **内容真的不同 / 就绪度真的差 2 分** —— 那才是真问题，得往下查。
"""
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paper2lab.envfile import load_env          # noqa: E402

load_env()
from paper2lab.pipeline import run_audit         # noqa: E402

pdf, code = ROOT / "03_NeRF/paper.pdf", ROOT / "03_NeRF/code.zip"
print("跑两遍：经典模式 与 计划模式（都走真实 LLM 归因，与对照脚本同口径）…")
a_c, _ = run_audit(str(pdf), str(code), None, plan_mode=False)
a_p, _ = run_audit(str(pdf), str(code), None, plan_mode=True)

sc = [(f.param_key, f.status.value, f.risk.value) for f in a_c.findings]
sp = [(f.param_key, f.status.value, f.risk.value) for f in a_p.findings]
print(f"\nfindings 数：经典 {len(sc)} / 计划 {len(sp)}")
print(f"① 顺序是否相同：{sc == sp}")
print(f"② 集合是否相同：{sorted(sc) == sorted(sp)}")
if sorted(sc) != sorted(sp):
    print("   仅经典有：", [x for x in sc if x not in sp])
    print("   仅计划有：", [x for x in sp if x not in sc])
else:
    print("   → 内容完全一致，只是**顺序**不同（分片并发的返回顺序受线程调度影响）")

rc, rp = a_c.readiness or {}, a_p.readiness or {}
print("\n③ 就绪度字段差异（排除 llm_* / execution_log）：")
diff_any = False
for k in sorted(set(rc) | set(rp)):
    if k.startswith("llm_") or k == "execution_log":
        continue
    if rc.get(k) != rp.get(k):
        print(f"   {k}: 经典={rc.get(k)}  计划={rp.get(k)}")
        diff_any = True
if not diff_any:
    print("   （无差异）")
print(f"\n   total: 经典={rc.get('total')}  计划={rp.get('total')}")

c1 = rc.get("categories") or {}
c2 = rp.get("categories") or {}
print("\n④ 分类小分差异：")
d2 = False
for k in sorted(set(c1) | set(c2)):
    if c1.get(k) != c2.get(k):
        print(f"   {k}: 经典={c1.get(k)}  计划={c2.get(k)}")
        d2 = True
if not d2:
    print("   （无差异）")

print(f"\n⑤ 可信度: 经典={(a_c.coverage or {}).get('confidence_score')}"
      f" / 计划={(a_p.coverage or {}).get('confidence_score')}")
print(f"⑥ 执行/跳过（计划）: {(a_p.execution_log or {}).get('ran')}"
      f"/{(a_p.execution_log or {}).get('skipped')}")
