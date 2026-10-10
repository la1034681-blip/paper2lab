"""探针: **只给论文、不给代码**时, 全流程的下游模块是否都扛得住。

为什么单独探这条路径（此前从未覆盖）:
  `demo_full_flow.py` 一直用"论文 + 代码"齐备的材料跑, 所以
  `repro` / `rootcause` / `patch` / `inquiry` 四个下游模块**从未见过
  `audit.code` 为空的审计结果**。而"只传论文"现在是页面上的常规用法
  （代码 ZIP 已改为可选）, 所以这条路径必须验证。

对八套样本逐套：
  ① 计划模式下应跳过「代码扫描」;  ② 四个下游模块都能产出且不抛异常;
  ③ 复现清单/补丁草案不应因为"没有代码"而给出荒唐内容。
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import traceback
from pathlib import Path

from paper2lab.envfile import load_env
from paper2lab.inquiry import build_questions, summarize
from paper2lab.patch import propose_patches
from paper2lab.pipeline import run_audit
from paper2lab.repro import build_repro_pack
from paper2lab.rootcause import trace_findings

load_env()
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
HERE = Path(__file__).resolve().parent.parent

CASES = [
    ("01_DDPM", ROOT / "01_DDPM/paper.pdf", None, True),
    ("02_DETR", ROOT / "02_DETR/paper.pdf", None, True),
    ("03_NeRF", ROOT / "03_NeRF/paper.pdf", None, True),
    ("04_PointNet", ROOT / "04_PointNet/paper.pdf", None, True),
    ("05_ViT", ROOT / "05_ViT/paper.pdf", ROOT / "05_ViT/results.json", True),
    ("demo", HERE / "demo/paper.pdf", None, False),
    ("D题", HERE / "demo/D题论文.pdf", None, False),
    ("E题", Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"), None, False),
]

out: list[str] = []
out.append("# 探针：只给论文（无代码）时的全流程健壮性")
out.append("")
out.append("| 样本 | 计划跳过代码扫描 | 结论数 | 就绪度 | 复现清单 | 根因追查 | 补丁草案 | 待确认 | 判定 |")
out.append("|---|---|---|---|---|---|---|---|---|")

problems: list[str] = []
for name, pdf, res, real in CASES:
    if not pdf.exists():
        out.append(f"| {name} | — | — | — | — | — | — | — | 材料缺失，跳过 |")
        continue
    ur = json.loads(Path(res).read_text(encoding="utf-8")) if res else None

    row = {"name": name}
    try:
        a, report = run_audit(str(pdf), "", ur, force_mock=not real, plan_mode=True)
    except Exception as e:  # noqa: BLE001
        problems.append(f"{name}: run_audit 抛异常 {type(e).__name__}: {e}")
        out.append(f"| {name} | ✗ | — | — | — | — | — | — | **审计就崩了** |")
        continue

    ex = a.execution_log or {}
    skipped = [s["title"] for s in ex.get("steps", []) if s["status"] == "skipped"]

    # ---- 下游模块逐个试, 任何一个抛异常都记下来 ----
    def try_call(label, fn):
        try:
            return True, fn()
        except Exception as e:  # noqa: BLE001
            problems.append(f"{name}: {label} 抛异常 {type(e).__name__}: {e}")
            return False, None

    ok_repro, pack = try_call("repro", lambda: build_repro_pack(a))
    ok_rc, traces = try_call("rootcause", lambda: trace_findings(a, max_items=8))
    ok_patch, patches = try_call(
        "patch", lambda: propose_patches(a, traces or [], "", max_items=8))
    ok_q, qs = try_call("inquiry", lambda: build_questions(a))

    # 报告生成是否也不炸
    ok_rep = bool(report)

    repro_n = len(pack.params) if ok_repro and pack else "✗"
    rc_n = len(traces) if ok_rc and traces is not None else "✗"
    patch_n = (f"{sum(1 for p in patches if p.is_proposed)}/"
               f"{sum(1 for p in patches if not p.is_proposed)}"
               if ok_patch and patches is not None else "✗")
    q_n = len(qs) if ok_q and qs is not None else "✗"

    ok = ("代码扫描" in skipped) and ok_repro and ok_rc and ok_patch and ok_q and ok_rep
    # 没代码时不该给出任何补丁(改无可改)
    if ok and ok_patch and any(p.is_proposed for p in (patches or [])):
        problems.append(f"{name}: 没有代码包却给出了补丁草案")
        ok = False

    out.append(
        f"| {name} | {'✅ 是' if '代码扫描' in skipped else '**✗ 未跳过**'} | "
        f"{len(a.findings)} | {a.readiness.get('total')} | {repro_n} | {rc_n} | "
        f"{patch_n} | {q_n} | {'一致 ✅' if ok else '**有问题 ⚠**'} |")

    if ok_rc and traces:
        for t in traces:
            if t.confidence in ("high", "medium") and t.verdict_loc:
                problems.append(f"{name}: 无代码却定位到根因 {t.display} @ {t.verdict_loc}")
                break

out.append("")

# ---------------- 记忆索引口径: 同一篇论文传不传代码必须算同一篇 ----------------
# 实测(2026-09-28)踩过的坑: 指纹里含代码包 -> 同一篇论文因为「这次有没有传代码」
# 被拆成两条记忆记录, 八套样本全部重复, "已审计 N 次"的连续性也被切断。
out.append("## 记忆索引: 同一篇论文传不传代码, 必须命中同一条记录")
out.append("")
import json as _json  # noqa: E402

from paper2lab import memory as _memory  # noqa: E402

demo_pdf = HERE / "demo/paper.pdf"
demo_zip = HERE / "demo/project.zip"
fp_with = _memory.fingerprint(str(demo_pdf), str(demo_zip))
fp_without = _memory.fingerprint(str(demo_pdf), "")
out.append(f"- demo 传代码指纹 `{fp_with}`，不传代码指纹 `{fp_without}`")
if fp_with != fp_without:
    problems.append("记忆指纹仍随代码包变化（同一篇论文会被拆成两条记录）")
    out.append("- **✗ 两者不同** —— 同一篇论文会被拆成两条记录")
else:
    out.append("- ✅ 两者相同 —— 同一篇论文始终命中同一条记忆")

_memfile = HERE / "cache/audit_memory.json"
# 用 memory.entries()（已按口径版本过滤）而非直接读文件：
# 文件里可能残留旧口径的键，那些键系统永远取不到，直接读会误判成"同标题多指纹"。
_eff = _memory.entries()
if _eff:
    _titles: dict = {}
    for _k, _v in _eff.items():
        _titles.setdefault((_v or {}).get("title") or "(无标题)", []).append(_k)
    _dup = {t: k for t, k in _titles.items() if len(k) > 1}
    out.append(f"- 记忆库有效明细 {len(_titles)} 篇；标题重复的：{len(_dup)} 篇")
    if _dup:
        problems.append(f"记忆库存在同标题多指纹: {list(_dup)[:3]}")
        out.append(f"  - **✗** {_dup}")
    else:
        out.append("  - ✅ 无同标题多指纹")
out.append("")

# ---------------- 结论（必须放在所有检查之后）----------------
if problems:
    out.append("## 发现的问题")
    out.append("")
    for p in problems:
        out.append(f"- {p}")
else:
    out.append("**未发现问题**：八套样本在「只给论文」路径下，计划正确跳过代码扫描，"
               "四个下游模块均正常产出、未凭空给出补丁；记忆索引也已按论文收敛。")
out.append("")

(HERE / "_nocode.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
if problems:
    raise SystemExit(1)
