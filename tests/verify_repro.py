"""验证复现准备清单（第三期 3.1）：用真实样本生成 REPRO.md 并自检。"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import json
from pathlib import Path

from paper2lab.envfile import load_env
from paper2lab.pipeline import run_audit
from paper2lab.repro import build_repro_pack, write_repro_pack

load_env()
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
d = ROOT / "05_ViT"
ur = json.loads((d / "results.json").read_text(encoding="utf-8"))

audit, _ = run_audit(str(d / "paper.pdf"), str(d / "code.zip"), ur, plan_mode=True)
path = write_repro_pack(audit, str(ROOT / "REPRO_05_ViT.md"))
pack = build_repro_pack(audit)

out: list[str] = []
out.append(f"生成文件: {path}")
out.append(f"论文标题: {pack.title or '（未识别）'}")
out.append(f"参数对照 {len(pack.params)} 行 ｜ 待确认 {len(pack.must_confirm)} 条 ｜ "
           f"风险 {len(pack.risks)} 条 ｜ 环境依赖 {len(pack.env.get('python_deps') or {})} 项")
out.append("")

out.append("—— 自检 1: 每个数值是否都附了出处（第几页 / 哪个文件）——")
no_src = [p["name"] for p in pack.params
          if (p["paper"] != "—" and not p["paper_src"])
          or (p["code"] != "—" and not p["code_src"])]
out.append(f"  缺出处的项：{len(no_src)} {no_src[:6]}")

out.append("")
out.append("—— 自检 2: 不一致项是否都给了建议且未替用户拍板 ——")
bad_advice = [p["name"] for p in pack.params
              if p["status"] != "consistent" and not p["advice"]]
says_confirm = sum(1 for p in pack.params if "需你确认" in p["advice"])
out.append(f"  无建议的项：{len(bad_advice)} ｜ 明确写「需你确认」的项：{says_confirm}")

out.append("")
out.append("—— 自检 3: 待确认问题是否被承接 ——")
out.append(f"  条数：{len(pack.must_confirm)}")
for q in pack.must_confirm[:4]:
    out.append(f"    · [{q.get('label')}] {q.get('title')}")

out.append("")
out.append("—— 抽样看几行对照表 ——")
for p in pack.params[:5]:
    out.append(f"  {p['name']:<20} 论文={p['paper']:<12} 代码={p['code']:<12} {p['status_label']}")

Path("_repro.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
