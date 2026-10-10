"""验证「读图语境守卫」: 结论是否与改造前一致（只该省成本, 不该改结论）。

对比基准 = 守卫上线前那一轮（八套样本）:
  DDPM 15/74、DETR 16/72、NeRF 9/80、PointNet 14/70、ViT 24/81、
  demo 11/78、D题 7/72、E题 4/69
"""
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
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
HERE = Path(r"C:\Users\lijiahui\Desktop\比赛")

# 名称 -> (pdf, code, results, 真实API, 基准(结论数, 就绪度))
BASE = {
    "01_DDPM": (15, 74), "02_DETR": (16, 72), "03_NeRF": (9, 80),
    "04_PointNet": (14, 70), "05_ViT": (24, 81),
    "demo": (11, 78), "D题": (7, 72), "E题": (4, 69),
}
CASES = [
    ("01_DDPM", ROOT / "01_DDPM/paper.pdf", ROOT / "01_DDPM/code.zip", None, True),
    ("02_DETR", ROOT / "02_DETR/paper.pdf", ROOT / "02_DETR/code.zip", None, True),
    ("03_NeRF", ROOT / "03_NeRF/paper.pdf", ROOT / "03_NeRF/code.zip", None, True),
    ("04_PointNet", ROOT / "04_PointNet/paper.pdf", ROOT / "04_PointNet/code.zip", None, True),
    ("05_ViT", ROOT / "05_ViT/paper.pdf", ROOT / "05_ViT/code.zip",
     ROOT / "05_ViT/results.json", True),
    ("demo", HERE / "demo/paper.pdf", HERE / "demo/project.zip", None, False),
    ("D题", HERE / "demo/D题论文.pdf", HERE / "demo/D题代码.zip", None, False),
    ("E题", Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"),
     Path(r"C:\Users\lijiahui\Desktop\E题作答.zip"), None, False),
]

out: list[str] = []
out.append("| 样本 | 结论数(前→后) | 就绪度(前→后) | 可信度 | 读图 候选→实读 | 页覆盖(文本+读图) | 判定 |")
out.append("|---|---|---|---|---|---|---|")

bad = 0
for name, pdf, code, res, real in CASES:
    ur = json.loads(Path(res).read_text(encoding="utf-8")) if res else None
    a, _ = run_audit(str(pdf), str(code), ur, force_mock=not real, plan_mode=True)
    cov = a.coverage or {}
    im = cov.get("image") or {}
    n_before, r_before = BASE[name]
    n_after = len(a.findings)
    r_after = a.readiness.get("total")
    ok = (n_before == n_after) and (r_before == r_after)
    if not ok:
        bad += 1
    out.append(
        f"| {name} | {n_before}→{n_after} | {r_before}→{r_after} | "
        f"{cov.get('confidence_score')} | {im.get('candidates')}→{im.get('regions_read')} | "
        f"{cov.get('pages_covered')}/{cov.get('pages_total')}"
        f"(读图 {cov.get('pages_covered_by_vision') or 0}) | "
        f"{'一致 ✅' if ok else '**变了 ⚠**'} |")

out.append("")
out.append(f"结论与就绪度**完全一致**的样本: {len(CASES) - bad}/{len(CASES)}")
(HERE / "_vision_guard_check.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
