"""诊断：03_NeRF 的"不一致"到底是调度员改的，还是运行态波动。

背景（2026-09-29 实测）：消融对照两次报 03_NeRF 不一致（87 vs 85、结论签名不同），
但写明细时重跑一遍又一致了 —— 典型的"间歇性"。必须分清：

  A. **经典模式自己跑两次就不一样** → 是**运行态波动**（LLM 补漏 / 读图随机性），
     与调度员无关 —— 那问题在对照脚本没把输入固定住，**不是产品缺陷**；
  B. **经典与计划确实不同、且各自稳定** → 那才是调度员真的改了结论。

做法：同一个配置连跑 3 次，看就绪度与结论签名稳不稳定。
"""
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paper2lab.envfile import load_env          # noqa: E402

load_env()
from paper2lab.pipeline import run_audit         # noqa: E402

pdf, code = ROOT / "03_NeRF/paper.pdf", ROOT / "03_NeRF/code.zip"


def sig(a) -> list:
    return sorted(
        (str(f.param_key), f.status.value, f.risk.value,
         str(f.paper.raw_value) if f.paper else "",
         str(f.code.raw_value) if f.code else "")
        for f in a.findings)


print("=" * 66)
print("同一个配置（经典模式）连跑 3 次 —— 看它自己稳不稳定")
print("=" * 66)
runs = []
for i in range(3):
    a, _ = run_audit(str(pdf), str(code), None, plan_mode=False)
    runs.append((a.readiness.get("total"), len(a.findings), sig(a)))
    print(f"  第 {i + 1} 次：就绪度 {a.readiness.get('total')}"
          f" · 结论 {len(a.findings)} 条")

t = [r[0] for r in runs]
n = [r[1] for r in runs]
s = [r[2] for r in runs]
print(f"\n就绪度: {t}  → {'稳定' if len(set(t)) == 1 else '**波动**'}")
print(f"结论数: {n}  → {'稳定' if len(set(n)) == 1 else '**波动**'}")
print(f"结论签名: {'三次完全相同' if len(set(map(str, s))) == 1 else '**有差异**'}")

if len(set(map(str, s))) > 1:
    print("\n签名差异明细（第 1 次 vs 第 2 次）：")
    only1 = [x for x in s[0] if x not in s[1]]
    only2 = [x for x in s[1] if x not in s[0]]
    for x in only1[:6]:
        print("   仅第 1 次有：", x)
    for x in only2[:6]:
        print("   仅第 2 次有：", x)

print("\n判定:", "A —— **运行态波动**（与调度员无关，是对照脚本没固定住输入）"
      if len(set(map(str, s))) > 1 or len(set(t)) > 1
      else "B —— 同一配置稳定；若消融仍不一致，那就是**调度员真的改了结论**，需深查")
