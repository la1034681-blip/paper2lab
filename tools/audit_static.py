"""全面静态检查（不是功能验证，是"每一处都编译得过、导得进来、没留死代码"）。

跑法: .venv\\Scripts\\python.exe audit_static.py
"""
from __future__ import annotations

import ast
import importlib
import re
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
print(f"项目根: {HERE}\n")

# ---------- ① 编译检查：所有 .py 都要能编译 ----------
# 用**内存编译**（`compile()`），不落任何 .pyc 临时文件 —— 一开始写成 py_compile + 事后 unlink，
# 于是每跑一次要删近百个文件；实测（2026-09-28）本机 shell 对"同一轮删除次数"有安全熔断
# （阈值 50，超了就直接中止进程，Python 层 try/except 接不住），我自己的检查脚本反倒成了
# 触发熔断的元凶。零删除就没这问题。
targets: list[Path] = sorted((HERE / "paper2lab").rglob("*.py"))
targets += sorted(p for p in HERE.glob("*.py") if p.is_file())
bad: list[str] = []
for p in targets:
    try:
        compile(p.read_text(encoding="utf-8", errors="replace"), str(p), "exec")
    except Exception as ex:      # noqa: BLE001
        bad.append(f"{p.relative_to(HERE)}: {type(ex).__name__}: {ex}")
print(f"① 编译检查: {len(targets)} 个 .py（内存编译，不落 .pyc）, 失败 {len(bad)}")
for b in bad:
    print("   ✗", b)

# ---------- ② 导入检查：paper2lab 每个模块都要能 import ----------
sys.path.insert(0, str(HERE))
imp_bad: list[str] = []
mods = ["paper2lab." + p.stem for p in sorted((HERE / "paper2lab").glob("*.py"))
        if p.stem != "__init__"]
for m in mods:
    try:
        importlib.import_module(m)
    except Exception:      # noqa: BLE001
        imp_bad.append(f"{m}\n{traceback.format_exc(limit=2)}")
print(f"② 导入检查: paper2lab {len(mods)} 个模块, 失败 {len(imp_bad)}")
for b in imp_bad:
    print("   ✗", b)

# ---------- ③ 死代码 / 未使用的模块级常量 ----------
# 上一版把"同文件内使用"也报成未引用（假阳性 120 条），这版改成**全项目引用计数**：
# 定义处算 1 次，其余全为 0 才算死代码。
print("③ 未被任何地方引用的模块级常量:")
src_all = {}
for p in list((HERE / "paper2lab").glob("*.py")) + list(HERE.glob("*.py")):
    src_all[p] = p.read_text(encoding="utf-8", errors="replace")
dead: list[str] = []
for p, text in src_all.items():
    if p.parent.name != "paper2lab":
        continue
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and re.fullmatch(r"_?[A-Z][A-Z0-9_]+", t.id):
                    n = sum(len(re.findall(rf"\b{t.id}\b", s)) for s in src_all.values())
                    if n <= 1:                     # 只有定义处那一次
                        dead.append(f"{p.name}: {t.id}")
print(f"   {len(dead)} 个" + ("：" if dead else "（无）"))
for d in dead:
    print("   ⚠", d)

# ---------- ④ 假断言扫描：形如 `... or True` / `check(True, ...)` ----------
print("④ 恒真断言（会让测试假装通过）:")
fake: list[str] = []
for p, text in src_all.items():
    if not p.name.startswith(("verify_", "probe_", "check_", "ui_", "audit_")):
        continue
    if p.name == Path(__file__).name:      # 扫自己会命中注释，跳过
        continue
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.strip().startswith("#"):
            continue
        if re.search(r"\bor\s+True\b", ln) or re.search(r"check\(\s*True\s*,", ln):
            fake.append(f"{p.name}:{i}: {ln.strip()[:100]}")
print(f"   {len(fake)} 处" + ("：" if fake else "（无）"))
for f in fake:
    print("   ⚠", f)

# ---------- ⑤ 工具/环节口径自洽 ----------
from paper2lab.toolbox import STEPS, TOOLS      # noqa: E402
print(f"⑤ 工具箱: {len(TOOLS)} 件工具 / {len(STEPS)} 个环节")
keys = [t.key for t in TOOLS]
print(f"   工具 key 唯一: {len(keys) == len(set(keys))}")
print(f"   环节名唯一:   {len(STEPS) == len(set(STEPS))}")
dups = [k for k in set(keys) if keys.count(k) > 1]
if dups:
    print("   ✗ 重复 key:", dups)

print("")
print("静态检查完成" + ("（有需要修的地方，见上）" if (bad or imp_bad or dead or fake)
                     else "（全绿）"))
