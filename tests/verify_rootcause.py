"""验证根因追查（第三期 3.2）：对真实样本追查"多个赋值点里哪个最终生效"。"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import json
from pathlib import Path

from paper2lab.envfile import load_env
from paper2lab.pipeline import run_audit
from paper2lab.rootcause import trace_findings

load_env()
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
out: list[str] = []

for name in ("05_ViT", "02_DETR", "01_DDPM"):
    d = ROOT / name
    if not (d / "paper.pdf").exists():
        continue
    rf = d / "results.json"
    ur = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else None
    audit, _ = run_audit(str(d / "paper.pdf"), str(d / "code.zip"), ur, plan_mode=True)
    traces = trace_findings(audit)
    out.append("=" * 68)
    out.append(f"{name}：追查 {len(traces)} 个参数")
    out.append("=" * 68)
    for t in traces:
        out.append(f"▸ {t.display}　论文={t.paper_value or '—'}")
        out.append(f"   候选 {len(t.candidates)} 处 ｜ 置信 {t.confidence}")
        for c in t.candidates[:4]:
            out.append(f"     - {c.file}:{c.line} = {c.value}　[{c.kind} score={c.score}]")
        if len(t.candidates) > 4:
            out.append(f"     …… 其余 {len(t.candidates) - 4} 处")
        out.append(f"   结论：{('生效值 ' + t.verdict + ' @ ' + t.verdict_loc) if t.verdict else '无法定位（不猜）'}")
        out.append(f"   理由：{t.reason}")
        out.append("")

# 汇总
all_t = []
for name in ("05_ViT", "02_DETR", "01_DDPM"):
    pass
out.append("—— 汇总口径 ——")
out.append("  confidence=high/medium → 给出结论；none → 明确说'无法定位'，不猜")

Path("_rc.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
