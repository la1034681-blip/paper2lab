"""数据层断言: 「执行记录」表的两列内容是否真的算得出来。

为什么单独做: 界面里这张表用 `st.dataframe`（canvas 渲染），DOM 读不到单元格文本，
所以那两个关键列——「环节」与「这次实际做出了什么」——必须在这里以数据层断言覆盖：

  ① 每件工具、每个环节的映射完整（环节列不会是空的）；
  ② 每件工具都能算出**实际产出**文案（不是一排"✅ 执行"）；
  ③ 计划模式跳过某工具时, 那一行的"产出"位置给的是**跳过理由**。
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import sys
from pathlib import Path

from paper2lab.execview import agent_panel_title, tool_outcome
from paper2lab.pipeline import run_audit
from paper2lab.toolbox import STEPS, TOOLS

HERE = Path(__file__).resolve().parent.parent
fails: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}")
    if not ok:
        fails.append(label)


# ---------- 材料齐备（计划模式）----------
print("① 材料齐备：每件工具都应算得出实际产出")
audit, _ = run_audit(str(HERE / "demo/paper.pdf"), str(HERE / "demo/project.zip"),
                     None, force_mock=True, plan_mode=True)
ex = audit.execution_log or {}

# 环节映射
# 注: 2026-09-28 把「根因追查 / 补丁草案」也登记成工具后, 工具 8→10、环节 10→12。
# 断言改成**由工具箱派生**（工具数/环节数一致性 + 关键节点必须在），不再写死数字 ——
# 写死的代价上次已经付过一回（加两站就得改这里）。
_KEYS = {t.key for t in TOOLS}
_MUST = {"parse_paper", "analyze_images", "fill_missing", "analyze_code", "align",
         "llm_analyze", "selfcheck", "rootcause", "patch", "report"}
names = [cp for t in TOOLS for cp in t.checkpoints]
check(_MUST <= _KEYS, f"关键工具齐备（缺 {sorted(_MUST - _KEYS)}）")
check(len(names) == len(STEPS),
      f"环节数 = {len(names)}，STEPS = {len(STEPS)}（两者必须一致）")
check(names == list(STEPS), "工具声明的环节顺序与 STEPS 完全一致")
check("根因追查" in names and "补丁草案" in names,
      "「根因追查 / 补丁草案」已是流水线里的环节（不再是报告之外的独立脚本）")

print("")
print("  环节 → 工具 → 这次实际做出了什么")
ok_all = True
for t in TOOLS:
    out = tool_outcome(audit, t.key)
    marker = "■" if out == "—" else " "
    if out == "—":
        ok_all = False
    print(f"   {marker} {' → '.join(t.checkpoints):34s} | {t.title:12s} | {out}")
check(ok_all, "每件工具都算出了实际产出（没有出现占位的 —）")

steps = {s["key"]: s for s in ex.get("steps", [])}
check(len(steps) == len(TOOLS), f"执行记录覆盖全部工具（{len(steps)}/{len(TOOLS)}）")

# ---------- 缺代码：跳过行的产出位置应给理由 ----------
print("")
print("② 只给论文（无代码）：跳过的那一行应给出理由而不是产出")
audit2, _ = run_audit(str(HERE / "demo/paper.pdf"), "", None,
                      force_mock=True, plan_mode=True)
ex2 = audit2.execution_log or {}
skipped = [s for s in ex2.get("steps", []) if s["status"] == "skipped"]
print(f"   跳过 {len(skipped)} 个工具：")
for s in skipped:
    print(f"     ⏭ {s['title']} —— {s['reason'][:70]}")
check(bool(skipped), "无代码时确有工具被计划跳过")
check(any("代码" in s["reason"] for s in skipped), "跳过理由点明了是缺代码包")

# 同一输入下经典模式不跳过
audit3, _ = run_audit(str(HERE / "demo/paper.pdf"), "", None,
                      force_mock=True, plan_mode=False)
ex3 = audit3.execution_log or {}
n3 = sum(1 for s in ex3.get("steps", []) if s["status"] == "skipped")
print(f"   同一输入·经典模式：跳过 {n3} 个")
check(n3 == 0, "经典模式不看材料、固定全跑（跳过 0）")
check(len(ex2.get("steps", [])) == len(ex3.get("steps", [])),
      "两模式的执行记录都覆盖全部工具（差别只在状态）")

print("")
print("③ 「抽取 Agent」面板标题必须随材料变（不能是静态文案）")
# 用户实测反馈"换什么材料这面板描述都没变"：根因是标题只写"N 步尝试 · 补回 M 类"，
# 而内核已抽全的样本恒为 0 步 0 类 -> 不同材料折叠时看到的一字不差。
_titles: dict = {}
for name, pdf, zipf in [
    ("demo（内核已抽全）", HERE / "demo/paper.pdf", HERE / "demo/project.zip"),
    ("D题（3 类待补）", HERE / "demo/D题论文.pdf", HERE / "demo/D题代码.zip"),
    ("04_PointNet（2 类待补）", Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\04_PointNet\paper.pdf"),
     Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\04_PointNet\code.zip")),
]:
    if not pdf.exists() or not zipf.exists():
        print(f"   - {name}: 材料缺失，跳过")
        continue
    _a, _ = run_audit(str(pdf), str(zipf), None, force_mock=True, plan_mode=True)
    t = agent_panel_title(_a.coverage or {})
    _titles[name] = t
    print(f"   - {name}: {t}")

check(len(_titles) >= 2, "至少两套材料生成了标题")
check(len(set(_titles.values())) == len(_titles), "不同材料的面板标题互不相同")
check(all("待补" in t for t in _titles.values()), "标题里都带「待补 N 类」（会随材料变）")

print("")
if fails:
    print(f"未通过 {len(fails)} 项:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("全部通过")
