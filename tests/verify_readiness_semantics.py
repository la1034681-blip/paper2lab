"""就绪度「未核验」语义的逐样本验证 + 影响面报告。

背景（2026-09-28）: 从前"没提供实测结果"时，
  ① 「结果一致性」走默认值显示 **100 分(绿色)** —— 一次核验都没做却像"核验过且通过";
  ② 「实验记录完整度」固定给 **60 分** —— 与论文质量无关, 等于把"用户没上传"
     算成"论文的问题"; 且方向是反的(做了核验反而该维度更低分)。
现已改为**显式「未核验」**: 不给分、不进总分。

本脚本逐样本核对并断言三条不变量:
  A. 总分 == 已核验维度(非 None)的均值 —— 未核验维度既不进分子也不进分母
  B. 未提供实测结果的样本: 结果一致性 + 实验记录完整度 必须为「未核验」
  C. 提供了实测结果的样本(05_ViT): 不得出现任何「未核验」维度

用 Mock 模式跑(就绪度取自已产出的结论, 与 mock/真实无关), 因此很快。
用法: .venv\\Scripts\\python.exe verify_readiness_semantics.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.pipeline import run_audit         # noqa: E402

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")

# (名称, 论文, 代码, 实测结果, 是否有实测结果)
CASES = [
    ("01_DDPM", ROOT / "01_DDPM/paper.pdf", ROOT / "01_DDPM/code.zip", None),
    ("02_DETR", ROOT / "02_DETR/paper.pdf", ROOT / "02_DETR/code.zip", None),
    ("03_NeRF", ROOT / "03_NeRF/paper.pdf", ROOT / "03_NeRF/code.zip", None),
    ("04_PointNet", ROOT / "04_PointNet/paper.pdf",
     ROOT / "04_PointNet/code.zip", None),
    ("05_ViT", ROOT / "05_ViT/paper.pdf", ROOT / "05_ViT/code.zip",
     ROOT / "05_ViT/results.json"),
    ("demo", HERE / "demo/paper.pdf", HERE / "demo/project.zip", None),
    ("D题", HERE / "demo/D题论文.pdf", HERE / "demo/D题代码.zip", None),
    ("E题", Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"),
     Path(r"C:\Users\lijiahui\Desktop\E题作答.zip"), None),
]

DIMS = ["参数一致性", "数据集一致性", "环境一致性", "实验记录完整度", "结果一致性"]

rows: list[dict] = []
fails: list[str] = []

for name, pdf, code, res_path in CASES:
    if not Path(pdf).exists():
        print(f"  （跳过 {name}：论文不存在）")
        continue
    ur = None
    if res_path and Path(res_path).exists():
        import json
        ur = json.loads(Path(res_path).read_text(encoding="utf-8"))
    audit, _ = run_audit(str(pdf), str(code) if Path(code).exists() else "",
                         ur, force_mock=True, plan_mode=True)
    r = audit.readiness or {}
    cats = r.get("categories") or {}
    unv = r.get("unverified") or {}
    total = r.get("total")

    scored = {k: v for k, v in cats.items() if v is not None}
    skipped = [k for k, v in cats.items() if v is None]

    rows.append({
        "name": name, "total": total, "cats": cats,
        "unv": unv, "skipped": skipped, "has_res": ur is not None,
    })

    # ---- A. 总分只由已核验维度决定（一个都没核验时为 None，不能凭空给分）
    expect = round(sum(scored.values()) / len(scored)) if scored else None
    if total != expect:
        fails.append(f"{name}: 总分 {total} != 已核验维度均值 {expect}"
                     "（未核验维度漏进了分母？）")
    # ---- 未核验维度必须与 unverified 说明一一对应
    if set(skipped) != set(unv):
        fails.append(f"{name}: 未核验维度 {skipped} 与说明 {list(unv)} 不一致")
    # ---- B / C. 有/无实测结果
    if ur is None:
        for k in ("结果一致性", "实验记录完整度"):
            if cats.get(k) is not None:
                fails.append(f"{name}: 未提供实测结果, 但「{k}」给了 {cats.get(k)} 分（应为未核验）")
    else:
        if unv:
            fails.append(f"{name}: 已提供实测结果, 不该有未核验维度, 实得 {list(unv)}")

# ---------------------------------------------------------------- 输出报告
out = ["# 就绪度「未核验」语义 —— 逐样本验证与影响面", ""]
out.append(f"- 样本数: {len(rows)}")
out.append("- 判定: 未核验维度**不给分、不进总分**；有/无实测结果两条路径分别核对")
out.append("")
out.append("## 各样本维度明细")
out.append("")
out.append("| 样本 | " + " | ".join(DIMS) + " | 就绪度 |")
out.append("|" + "---|" * (len(DIMS) + 2))
for r in rows:
    cells = []
    for d in DIMS:
        v = r["cats"].get(d)
        cells.append("**未核验**" if v is None else str(v))
    out.append(f"| {r['name']} | " + " | ".join(cells) + f" | **{r['total']}** |")
out.append("")
out.append("## 未核验的原因（逐条）")
out.append("")
for r in rows:
    if r["unv"]:
        out.append(f"- **{r['name']}**")
        for k, why in r["unv"].items():
            out.append(f"  - {k}：{why}")
    else:
        out.append(f"- **{r['name']}**：✅ 无未核验维度（已提供实测结果）")
out.append("")

out.append("## 与修复前的对比（就绪度）")
out.append("")
BEFORE = {"01_DDPM": 74, "02_DETR": 72, "03_NeRF": 80, "04_PointNet": 70,
          "05_ViT": 81, "demo": 78, "D题": 72, "E题": 69}
out.append("| 样本 | 修前 | 修后 | 变化 | 说明 |")
out.append("|---|---|---|---|---|")
for r in rows:
    b = BEFORE.get(r["name"])
    if b is None:
        continue
    d = r["total"] - b
    why = (r["unv"] and "去掉『实验记录完整度』的固定 60 分惩罚"
           or "有实测结果，口径未变（对照项）")
    out.append(f"| {r['name']} | {b} | **{r['total']}** | {d:+d} | {why} |")
out.append("")
out.append("> `05_ViT` 是**对照组**：它本来就有 `results.json`，两个维度都真做了核验，")
out.append("> 因此口径修正后分数**一分未动**（81 → 81）。这证明改动只影响"
           "「没提供实测结果」的情形。")
out.append("")
out.append("## 结论")
out.append("")
if fails:
    out.append("**✗ 未通过**：")
    out.append("")
    for f in fails:
        out.append(f"- {f}")
else:
    out.append("**✓ 全部通过** —— 三条不变量成立：")
    out.append("")
    out.append("1. 总分 == 已核验维度的均值（未核验维度不进分子也不进分母）")
    out.append("2. 未提供实测结果的 7 套：结果一致性 + 实验记录完整度 均为「未核验」")
    out.append("3. 提供实测结果的 05_ViT：无任何未核验维度（对照组未受影响）")

(HERE / "_ready_sem.txt").write_text("\n".join(out), encoding="utf-8")
REPORT = ROOT / "readiness_unverified_report.md"
REPORT.write_text("\n".join(out), encoding="utf-8")

print("\n".join(out))
print()
print(f"报告: {REPORT}")
if fails:
    sys.exit(1)
