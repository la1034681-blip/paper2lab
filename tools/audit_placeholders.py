"""占位符审计：找出**非 f-string 里残留的 `{...}` 占位符**。

起因：app.py 里 `st.markdown(\"\"\"...{len(STEPS)}...\"\"\")` 漏了 `f` 前缀，
页面上就把 `{len(STEPS)}` 原样显示给用户看（线上实测抓到）。
这类 bug 编译器不报、静态检查也常漏，但**用户一眼就能看见**。

判定规则（只有全部满足才算真 bug）：
  1. 该字符串是**普通字符串字面量**（不是 f-string）；
  2. 它**不是**某个 f-string(JoinedStr) 的组成部分；
  3. 它**没有**被 `.format(...)` 兜住（那是有意留的模板）；
  4. 去掉白名单（CSS 选择器 `/` 空对象 `{}` / 双花括号 `{{}}`）后仍有 {名字} 形态的内容。

用法：  .venv\\Scripts\\python.exe audit_placeholders.py
退出码：0 = 干净，1 = 发现问题
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 2026-09-30 目录整理后：_publish / output / .trash_tmp 都收进了 _archive/，
# 所以扫描只需排除 _archive（否则会把历史副本里的旧代码也报一遍，纯噪音）。
SKIP_DIRS = {".venv", ".git", "deploy", "_archive", "docs", "node_modules",
             "__pycache__", "cache"}

# 匹配 {名字} / {名字.属性} / {名字[键]} / {名字(参数)} —— 例如 {len(STEPS)}
# 注意 `(参数)` 这一支是必须的：本项目真实的 bug 就是 {len(STEPS)}，
# 早期版本漏了它，导致**漏报了那个真 bug**（教训：判据要覆盖真实形态再信它）。
PLACEHOLDER = re.compile(
    r"\{[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[^\]]*\]|\([^()]*\))*\}"
)

# 已知的合法保留花括号形态（放行）
ALLOW_PATTERNS = [
    re.compile(r"\{\s*\}"),            # 空对象 {}
    re.compile(r"\{\{[^}]*\}\}"),      # {{ }} 双花括号（f-string 转义写法）
    re.compile(r"\{[^{}]*:[^{}]*\}"),  # CSS 选择器块 / 带冒号的模板
]

# 本文件自己的说明文字里必然出现 {占位符} 的例子，扫它只会制造噪音
SKIP_FILES = {"audit_placeholders.py"}

# 本检查器给出的**是候选清单，不是判决**。以下两类会被误报，需人工判读：
#   1. 字符串里存的是"要生成的代码/文档模板"，里面的 {x} 是模板自身的语法
#      （如 make_demo.py 的 DATASET_PY、make_new_set_meta.py 的 README_TMPL）；
#   2. 变量形式的模板字符串，稍后用 `某变量.format(...)` 填充
#      （如 paper2lab/llm.py 的 _MOCK_TEMPLATES、tools.py 的 _LLM_PROMPT）。
# 判断口诀：**这个 {x} 会不会被打印给用户看？** 会 —— 才是 bug。


def iter_py_files():
    for p in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in SKIP_FILES:
            continue
        yield p


def build_parents(tree: ast.AST) -> dict:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def escapes_via_format(node: ast.AST, parents: dict) -> bool:
    """判断这个字符串是否被 .format(...) 或 % 兜住（有意留的模板）。"""
    cur = node
    for _ in range(4):
        parent = parents.get(id(cur))
        if parent is None:
            return False
        if isinstance(parent, ast.JoinedStr):
            return True                       # 是 f-string 的一部分
        if isinstance(parent, ast.Call):
            fn = parent.func
            if isinstance(fn, ast.Attribute) and fn.attr == "format":
                return True                   # "...".format(...)
            if isinstance(fn, ast.Name) and fn.id in ("format", "gettext", "_"):
                return True
        if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Mod):
            return True                       # "..." % (...)
        if isinstance(parent, (ast.Expr, ast.Assign, ast.AnnAssign, ast.Return,
                               ast.Call, ast.keyword, ast.Dict, ast.List, ast.Tuple,
                               ast.Module, ast.FunctionDef, ast.ClassDef, ast.If,
                               ast.For, ast.While, ast.With, ast.JoinedStr)):
            cur = parent
            continue
        cur = parent
    return False


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:  # noqa: BLE001
        return []
    lines = src.splitlines()
    parents = build_parents(tree)
    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if "{" not in node.value:
            continue
        if escapes_via_format(node, parents):
            continue
        lineno = getattr(node, "lineno", 0)
        for i, seg in enumerate(node.value.splitlines()):
            m = PLACEHOLDER.search(seg)
            if not m:
                continue
            if any(p.search(seg) for p in ALLOW_PATTERNS):
                continue
            real_line = lineno + i
            ctx = lines[real_line - 1].strip() if 0 < real_line <= len(lines) else seg
            hits.append((real_line, m.group(0), ctx[:100]))
    return hits


def main() -> int:
    total = 0
    files = 0
    for p in iter_py_files():
        hits = scan_file(p)
        if not hits:
            continue
        files += 1
        print(f"\n== {p.relative_to(ROOT)} ==")
        for lineno, token, ctx in hits:
            total += 1
            print(f"  L{lineno}: {token}")
            print(f"        {ctx}")
    print("\n" + "=" * 60)
    if total:
        print(f"发现 {total} 处疑似遗漏 f 前缀的占位符，分布在 {files} 个文件。")
        print("修法：给该字符串加 f 前缀；若内含 CSS 花括号，改用 .replace() 注入。")
    else:
        print("干净：没有发现非 f-string 里残留的 {占位符}。")
    print("=" * 60)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
