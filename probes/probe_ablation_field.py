"""诊断：03_NeRF「经典 vs 计划」的间歇性不一致，到底差在哪个字段。

已知两条线索：
  · 同一配置（经典）连跑 3 次**稳定** → 不是"单次运行不确定"；
  · 但整套消融跑时偶发 87 vs 85，重跑明细又一致 → 差异出在**两次相邻运行之间**。

这里交替跑 5 轮（经典 / 计划），逐轮对比**每个分类小分与未核验状态**，
找出差异第一次出现在哪个字段上 —— 而不是只看 total。
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


bad = 0
for i in range(5):
    a_c, _ = run_audit(str(pdf), str(code), None, plan_mode=False)
    a_p, _ = run_audit(str(pdf), str(code), None, plan_mode=True)
    tc, tp = a_c.readiness.get("total"), a_p.readiness.get("total")
    same = (tc == tp) and (sig(a_c) == sig(a_p))
    print(f"第 {i + 1} 轮：经典 {tc} / 计划 {tp}　"
          f"结论 {len(a_c.findings)}/{len(a_p.findings)}　"
          f"{'一致' if same else '**不一致**'}")
    if not same:
        bad += 1
        cc = a_c.readiness.get("categories") or {}
        cp = a_p.readiness.get("categories") or {}
        print("    分类小分：")
        for k in sorted(set(cc) | set(cp)):
            mark = "   ← **差异**" if cc.get(k) != cp.get(k) else ""
            print(f"      {k}: 经典={cc.get(k)}　计划={cp.get(k)}{mark}")
        uc = list((a_c.readiness.get("unverified") or {}))
        up = list((a_p.readiness.get("unverified") or {}))
        print(f"    未核验维度: 经典={uc}　计划={up}")
        only_c = [x for x in sig(a_c) if x not in sig(a_p)]
        only_p = [x for x in sig(a_p) if x not in sig(a_c)]
        for x in only_c[:4]:
            print("      · 仅经典有：", x)
        for x in only_p[:4]:
            print("      · 仅计划有：", x)
        # 其他运行态字段（排除 llm_*）
        rc, rp = a_c.readiness or {}, a_p.readiness or {}
        print("    其它字段差异：")
        for k in sorted(set(rc) | set(rp)):
            if k.startswith("llm_") or k in ("categories", "unverified", "total", "dominant_issues"):
                continue
            if rc.get(k) != rp.get(k):
                print(f"      {k}: 经典={rc.get(k)}　计划={rp.get(k)}")

print(f"\n5 轮里出现 {bad} 轮不一致")
if bad:
    print("→ 差异字段见上；若落在「分类小分」，说明是**结论的 risk/status 不同**；")
    print("  若只有「其它字段」，说明是运行态统计波动（不该进比对）。")
else:
    print("→ 本轮 5 次全一致（问题为间歇性，需在整套消融里复现）")
