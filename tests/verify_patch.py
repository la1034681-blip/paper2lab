"""验证根因追查 + 补丁草案（第三期 3.2 / 3.3）。

重点自检：
  ① 补丁是否只在"能定位到唯一生效点"时才给（拿不准必须拒绝）；
  ② **绝不落盘** —— 跑完后代码包的文件数量与内容哈希必须与跑之前完全一致。
"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import hashlib
import json
import zipfile
from pathlib import Path

from paper2lab.envfile import load_env
from paper2lab.patch import _read_source, _replace_token, propose_patches
from paper2lab.pipeline import run_audit
from paper2lab.rootcause import trace_findings

load_env()
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")


def zip_digest(p: Path) -> str:
    """整个 zip 所有条目名+内容的哈希（用于证明"没被改过"）。"""
    h = hashlib.sha1()
    with zipfile.ZipFile(p) as zf:
        for n in sorted(zf.namelist()):
            h.update(n.encode("utf-8", "replace"))
            h.update(zf.read(n))
    return h.hexdigest()[:16]


def parses(line: str) -> bool:
    """生成的补丁行是否仍是合法 Python —— 防止把 Unicode 排版字符写进代码。"""
    import ast as _ast
    try:
        _ast.parse(line)
        return True
    except SyntaxError:
        try:                     # 可能是跨行语句的片段, 包一层再试
            _ast.parse("if True:\n    " + line)
            return True
        except SyntaxError:
            return False


out: list[str] = []
for name in ("02_DETR", "05_ViT", "01_DDPM"):
    d = ROOT / name
    if not (d / "paper.pdf").exists():
        continue
    zf = d / "code.zip"
    before_digest = zip_digest(zf)
    rf = d / "results.json"
    ur = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else None

    audit, _ = run_audit(str(d / "paper.pdf"), str(zf), ur, plan_mode=True)
    traces = trace_findings(audit)
    patches = propose_patches(audit, traces, str(zf))

    out.append("=" * 70)
    out.append(f"{name}")
    out.append("=" * 70)
    out.append(f"【根因追查】{len(traces)} 个参数")
    for t in traces:
        verdict = f"→ {t.verdict} @ {t.verdict_loc}" if t.verdict else "→ 无法定位（不猜）"
        out.append(f"  ▸ {t.display:<18} 候选 {len(t.candidates):>2} 处 ｜ "
                   f"置信 {t.confidence:<6} {verdict}")
    out.append("")
    out.append(f"【补丁草案】{len(patches)} 条")
    for p in patches:
        if p.is_proposed:
            ok = parses(p.after.strip())
            out.append(f"  {'✅' if ok else '❌'} {p.display} @ {p.target}")
            out.append(f"       原行: {p.before.strip()}")
            out.append(f"       改后: {p.after.strip()}")
            out.append(f"       语法自检: {'合法 ✅' if ok else '语法错误 ❌（不可提交给人用）'}")
            if getattr(p, "source", "rule") == "llm":
                out.append("       ⚠️ 目标由 AI 提名，需人工确认；程序盖章: "
                           + "；".join(getattr(p, "stamps", []) or []))
        else:
            out.append(f"  ⛔ {p.display} —— 拒绝（{p.refuse_kind}）：{p.refuse_reason[:78]}")
    proposed = [p for p in patches if p.is_proposed]
    refused = [p for p in patches if not p.is_proposed]
    out.append(f"  → 给方案 {len(proposed)} 条 / 拒绝 {len(refused)} 条")

    after_digest = zip_digest(zf)
    out.append("")
    out.append(f"【绝不落盘自检】代码包哈希 前={before_digest} 后={after_digest} "
               f"→ {'未被修改 ✅' if before_digest == after_digest else '被改了 ❌'}")
    out.append("")

# ================================================================ 缺口回归
# 这两处缺口 2026-09-29 在真实代码里被复现过（探针 probe_patch_gaps.py），修好后把断言
# 固定在这里，防止回退：
#   ① 待替换值落在**行内注释**里 -> 会生成"改了注释、生效值没动"的假补丁（最伤信任）；
#   ② 目录型代码包 -> `../` 可以读到包外文件（路径穿越）。
gaps: list[str] = []
_LINE = "WARMUP_EPOCHS = 20   # 1 epoch warmup as in section 3"
if _replace_token(_LINE, "1", "1500") is not None:
    gaps.append("① 行内注释里的数字仍会被当成待替换值（会产出「改注释」的假补丁）")
if _replace_token(_LINE, "20", "30") != "WARMUP_EPOCHS = 30   # 1 epoch warmup as in section 3":
    gaps.append("① 正常替换被误伤（生效值应能替换，注释必须原样保留）")

import tempfile as _tf       # noqa: E402
_tmp = Path(_tf.mkdtemp())
(_tmp / "outside_secret.txt").write_text("PACKAGE-EXTERNAL", encoding="utf-8")
_pkg = _tmp / "pkg"
_pkg.mkdir()
(_pkg / "main.py").write_text("lr = 0.1\n", encoding="utf-8")
if _read_source(str(_pkg), "../outside_secret.txt") is not None:
    gaps.append("② 目录型代码包可被 `../` 读出包外文件（路径穿越）")
if _read_source(str(_pkg), "main.py") != "lr = 0.1\n":
    gaps.append("② 防穿越误伤了包内文件的正常读取")

out.append("=" * 70)
out.append("【缺口回归】行内注释 / 路径穿越")
out.append("=" * 70)
out.append("  全部封住 ✅" if not gaps else "  ❌ " + "\n  ❌ ".join(gaps))
out.append("")

Path("_patch.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
if gaps:
    print("缺口回归未通过：")
    for g in gaps:
        print("  -", g)
    raise SystemExit(1)
