"""探查补丁链的两处潜在缺口（先证明它们真实存在，再决定是否修）。

缺口 A —— 改到注释、没改代码：
  `_replace_token` 在整行里找"唯一的待替换值"。若这一行是
      `WARMUP_EPOCHS = 20   # 1 epoch warmup`
  而根因追查给出来的值是 `1`（从注释里抽到的），它会**唯一命中注释里的那个 1**，
  于是产出一条"改了注释、没改任何生效值"的补丁 —— 看起来像修好了，实际毫无作用。

缺口 B —— 目录代码包的路径穿越：
  `_read_source` 在目录分支直接 `p / rel_file`。若 `rel_file` 里带 `../`，
  就能读到代码包**之外**的文件。
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import tempfile
from pathlib import Path

from paper2lab.patch import _read_source, _replace_token

print("① 缺口 A：待替换值落在行内注释里时，会不会生成假补丁？")
line = "WARMUP_EPOCHS = 20   # 1 epoch warmup as in section 3"
out = _replace_token(line, "1", "1500")
print(f"   原行  : {line}")
print(f"   改后行: {out}")
if out and "1500" in out.split("#", 1)[1]:
    print("   -> 缺口 A 存在：改的是注释，生效值 20 一动没动")
else:
    print("   -> 缺口 A 不存在（或已被挡）")

print()
print("② 缺口 B：目录型代码包能否被 `../` 读出包外的文件？")
tmp = Path(tempfile.mkdtemp())
(tmp / "outside_secret.txt").write_text("PACKAGE-EXTERNAL-SECRET", encoding="utf-8")
pkg = tmp / "pkg"
pkg.mkdir()
(pkg / "main.py").write_text("lr = 0.1\n", encoding="utf-8")

got_inside = _read_source(str(pkg), "main.py")
got_outside = _read_source(str(pkg), "../outside_secret.txt")
print(f"   包内文件正常读到: {got_inside is not None}")
print(f"   包外文件被读到  : {got_outside is not None}（内容={got_outside!r}）")
print("   -> 缺口 B 存在：`../` 可以读到代码包之外" if got_outside is not None
      else "   -> 缺口 B 不存在")
