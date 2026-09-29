"""多语言通用参数抽取通道——不写 N 套解析器, 用语言无关的赋值句式覆盖。

设计取舍(答辩可讲):
- Python/notebook 走 AST 精确解析(带作用域语义, 天然忽略注释与字符串);
- 其他语言走本模块的"通用通道": 逐行识别赋值句式, 抓不到语义但能抓取值与位置;
- 通用通道的结论一律标注 parser="regex"、置信度降级, 且照旧受合理性先验与证据自证约束。

支持: MATLAB / R / Julia / C-C++-CUDA / Java / Fortran / Shell / YAML / INI / TOML
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .models import Evidence
from .synonyms import canonical_key, is_plausible, normalize_number

# 扩展名 -> 语言名(用于报告展示)
LANG_BY_EXT: dict[str, str] = {
    ".m": "MATLAB", ".r": "R", ".jl": "Julia",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".c": "C", ".h": "C/C++头文件",
    ".cu": "CUDA", ".java": "Java", ".f90": "Fortran", ".f": "Fortran",
    ".sh": "Shell", ".bash": "Shell", ".ps1": "PowerShell",
    ".yaml": "YAML", ".yml": "YAML", ".ini": "INI", ".cfg": "INI",
    ".toml": "TOML", ".txt": "文本配置",
}

# 行内注释前缀(按语言大致通用): 去掉注释再匹配, 避免注释里的数值干扰
_COMMENT = re.compile(r"(?<![:\"'#/])//|(?<![:\"'#/])#|(?<!%)%(?![0-9a-zA-Z])|(?<!\w)--(?!\w)")

# 赋值句式: name = 1e-4 / name <- 0.05 (R) / name := 3 / name: 0.02 (YAML)
_ASSIGN = re.compile(
    r"^\s*(?:[-*]\s+)?"                                  # YAML 列表项
    r"([A-Za-z_][A-Za-z0-9_\.]{1,40})"                   # 参数名(允许 obj.field)
    r"\s*(?:=|<-|:=|:\s)\s*"                             # 赋值符
    r"('(?:[^']*)'|\"(?:[^\"]*)\"|[-+]?\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+|"
    r"true|false|True|False)"                            # 取值
    r"\s*(?:[,;\)\]]|$)",
)

# 命令行参数: --lr 0.0002 / --lr=0.0002 / --model pix2pix
# (仓库里的 train_*.sh、notebook 中的 !python train.py ... 常把超参数写在这里)
_CLI_FLAG = re.compile(
    r"--([A-Za-z_][A-Za-z0-9_\-]{1,30})"                 # 参数名(去掉前导 --)
    r"(?:\s*=\s*|\s+)"
    r"('(?:[^']*)'|\"(?:[^\"]*)\"|[-+]?\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+"
    r"|[A-Za-z_][A-Za-z0-9_\-\.]{0,30})"                 # 取值(数值或短标识)
)

_TEXT_VALUED_KEYS = {"optimizer", "scheduler", "dataset", "model"}


def _strip_comment(line: str) -> str:
    m = _COMMENT.search(line)
    return line[: m.start()] if m else line


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    return v


def _add(found: dict[str, list[Evidence]], name: str, rhs: str,
         filename: str, lineno: int, raw_line: str) -> None:
    """类型门禁 + 合理性先验, 通过则记入证据。"""
    key = canonical_key(name.split(".")[-1]) or canonical_key(name)
    if key is None:
        return
    rhs = _unquote(rhs)
    if not rhs.strip():
        return
    if key in _TEXT_VALUED_KEYS:
        if not re.match(r"^[A-Za-z_][\w \-\.]{1,40}$", rhs):
            return
        norm: object = re.sub(r"\s+", "", rhs.lower())
    else:
        if rhs.lower() in ("true", "false"):
            return
        norm = normalize_number(rhs)
        if norm is None or is_plausible(key, rhs) is False:
            return
    found.setdefault(key, []).append(Evidence(
        source="code",
        location=f"{filename}:{lineno}",
        snippet=raw_line.strip()[:200],
        raw_value=rhs,
        normalized=norm,
        parser="regex",
    ))


def extract_params(filename: str, text: str) -> dict[str, list[Evidence]]:
    """从任意语言的源码/配置文本中抽取参数证据(通用通道)。

    覆盖两类写法: ① `name = value` / `name <- value` / `name: value` 赋值句式;
    ② `--name value` / `--name=value` 命令行参数(训练脚本与 notebook 命令里最常见)。
    """
    found: dict[str, list[Evidence]] = {}
    for i, raw_line in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw_line)
        if "=" not in line and "<-" not in line and ":" not in line and "--" not in line:
            continue
        m = _ASSIGN.match(line)
        if m:
            _add(found, m.group(1), m.group(2), filename, i, raw_line)
        for cm in _CLI_FLAG.finditer(line):
            _add(found, cm.group(1), cm.group(2), filename, i, raw_line)
    return found


def language_of(filename: str) -> Optional[str]:
    return LANG_BY_EXT.get(Path(filename).suffix.lower())
