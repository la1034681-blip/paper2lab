"""诊断：「数据一致性」显示「本次没有可比对的项」到底是哪种情况。

用户的质疑：*"代码以及论文里的参数以及部分结果不算？"*

三种可能，必须分清：
  A. **真的没有** —— 论文与代码都没声明数据集相关内容（提示准确）；
  B. **有，但全部来自读图**（`parser == "vlm"`）—— 按规则读图结论不计入评分，
     可提示语却写成"论文与代码中都没有可对照的该项内容" —— 那是**不实之词**；
  C. **有且可核验，却被算成"没有"** —— 真 bug。

判据（readiness.compute_readiness）：
  遍历 findings 时，读图结论直接 `continue` —— 既不计分，也**不置 cat_has_finding**；
  于是"该维度只有读图结论"会被判成"没有可比对项"。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.envfile import load_env          # noqa: E402

load_env()
from paper2lab.models import Category            # noqa: E402
from paper2lab.pipeline import run_audit         # noqa: E402

CASES = [
    ("demo（内置演示数据）", HERE / "demo/paper.pdf", HERE / "demo/project.zip",
     HERE / "demo/results.json"),
    ("D题", HERE / "demo/D题论文.pdf", HERE / "demo/D题代码.zip", None),
]

for name, pdf, code, res in CASES:
    if not Path(pdf).exists() or not Path(code).exists():
        print(f"（{name} 材料缺失，跳过）")
        continue
    ur = (json.loads(Path(res).read_text(encoding="utf-8"))
          if res and Path(res).exists() else None)
    a, _ = run_audit(str(pdf), str(code), ur, plan_mode=True)

    print("=" * 66)
    print(f"{name}   结论共 {len(a.findings)} 条")
    print("=" * 66)

    by_cat: dict = {}
    for f in a.findings:
        by_cat.setdefault(f.category, []).append(f)

    for c in Category:
        fs = by_cat.get(c, [])
        vlm = [f for f in fs
               if any(ev and getattr(ev, "parser", "") == "vlm" for ev in (f.paper, f.code))]
        tag = f"（其中读图 {len(vlm)} 条）" if vlm else ""
        print(f"  {c.value:8} 结论 {len(fs)} 条{tag}")
        for f in fs[:8]:
            mark = "  ← 读图（不计分）" if f in vlm else ""
            print(f"        · {f.display_name} / {f.status.value}{mark}")

    print("  —— 未核验维度 ——")
    for k, v in (a.readiness.get("unverified") or {}).items():
        print(f"      {k}：{v}")
    print()
