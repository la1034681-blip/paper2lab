"""验证「分布参数守卫」的实际效果: D题 不再误补 seed, 其它样本结论不变。"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
from pathlib import Path

from paper2lab.envfile import load_env
from paper2lab.pipeline import run_audit

load_env()
HERE = Path(r"C:\Users\lijiahui\Desktop\比赛")
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")

out: list[str] = []
out.append("=" * 72)
out.append("修复后复测（对比 demo_full_flow 那一轮）")
out.append("=" * 72)

CASES = [
    ("D题", HERE / "demo/D题论文.pdf", HERE / "demo/D题代码.zip", None, False),
    ("demo", HERE / "demo/paper.pdf", HERE / "demo/project.zip", None, False),
    ("E题", Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"),
     Path(r"C:\Users\lijiahui\Desktop\E题作答.zip"), None, False),
    ("01_DDPM", ROOT / "01_DDPM/paper.pdf", ROOT / "01_DDPM/code.zip", None, True),
    ("02_DETR", ROOT / "02_DETR/paper.pdf", ROOT / "02_DETR/code.zip", None, True),
    ("03_NeRF", ROOT / "03_NeRF/paper.pdf", ROOT / "03_NeRF/code.zip", None, True),
    ("04_PointNet", ROOT / "04_PointNet/paper.pdf", ROOT / "04_PointNet/code.zip",
     None, True),
    ("05_ViT", ROOT / "05_ViT/paper.pdf", ROOT / "05_ViT/code.zip",
     ROOT / "05_ViT/results.json", True),
]

rows = []
for name, pdf, code, res_path, real in CASES:
    ur = None
    if res_path is not None and Path(res_path).exists():
        ur = json.loads(Path(res_path).read_text(encoding="utf-8"))
    a, _ = run_audit(str(pdf), str(code), ur, force_mock=not real, plan_mode=True)
    am = a.paper.agent_meta or {}
    filled = am.get("filled") or {}
    blocked = [s for s in (am.get("steps") or []) if s.get("status") == "rejected"]
    rows.append((name, len(a.findings),
                 sum(1 for f in a.findings if f.status.value != "consistent"),
                 a.readiness.get("total"), filled, len(blocked)))

    out.append("")
    out.append(f"--- {name} ---")
    out.append(f"  结论 {len(a.findings)} 条 | 就绪度 {a.readiness.get('total')}")
    out.append(f"  Agent 补回: {filled if filled else '（无）'}")
    for s in blocked:
        out.append(f"  🛡 挡下 [{s.get('kind')}] {s.get('value')!r} —— {str(s.get('note'))[:80]}")
    for f in a.findings:
        if f.param_key in ("seed", "random_seed", "dropout"):
            p = f.paper
            c = f.code
            out.append(f"  · {f.param_key}: paper={p.raw_value if p else None!r}"
                       f"({p.parser if p else '-'}) | "
                       f"code={c.raw_value if c else None!r} | {f.status.value}")

out.append("")
out.append("=" * 72)
out.append("汇总")
out.append("=" * 72)
out.append("| 样本 | 结论 | 风险 | 就绪度 | Agent 补回 | 挡下 |")
out.append("|---|---|---|---|---|---|")
for name, nf, ni, rd, filled, nb in rows:
    out.append(f"| {name} | {nf} | {ni} | {rd} | "
               f"{', '.join(f'{k}={v}' for k, v in filled.items()) or '—'} | {nb} |")

(HERE / "_after_fix.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
