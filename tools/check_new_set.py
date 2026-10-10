"""校验: 旧目录是否已清空 + 每个新样本 zip 是否为有效仓库包。"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
print("=== 目录现状 ===")
for p in sorted(ROOT.iterdir()):
    print(f"  {p.name}{'/' if p.is_dir() else ''}")

print("\n=== 样本包校验 ===")
for d in sorted(ROOT.iterdir()):
    if not d.is_dir() or not (d / "code.zip").exists():
        continue
    z = d / "code.zip"
    try:
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            tops = sorted({n.split('/')[0] for n in names})
            py = sum(1 for n in names if n.endswith(".py"))
            ipynb = sum(1 for n in names if n.endswith(".ipynb"))
            others = sorted({Path(n).suffix.lower() for n in names
                             if Path(n).suffix.lower() not in (".py", ".ipynb", "")})[:12]
            print(f"{d.name}: 文件 {len(names)} 个 | py {py} | ipynb {ipynb} | "
                  f"其他后缀 {others} | 顶层目录 {tops[:3]}")
    except Exception as e:
        print(f"{d.name}: ❌ 不是有效 zip — {type(e).__name__}: {e}")
