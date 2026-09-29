"""代码静态分析器——AST 分析 zip/目录中的 Python 项目。

证据链要求: 每条参数都带 "file.py:行号"。
AST 天然忽略注释与字符串里的干扰值(对比正则的优势, 答辩可讲)。
"""

from __future__ import annotations

import ast
import io
import json
import re
import warnings
import zipfile
from pathlib import Path
from typing import Optional, Union

import yaml

from .models import CodeInfo, Evidence
from .multilang import extract_params, language_of
from .synonyms import (PARAM_SYNONYMS, canonical_key, is_plausible,
                       normalize_number)

# seed 固定调用的特征
_SEED_CALLS = {
    ("torch", "manual_seed"), ("torch", "manual_seed_all"),
    ("random", "seed"), ("seed",),
    ("np", "random", "seed"), ("numpy", "random", "seed"),
    ("tf", "random", "set_seed"), ("torch", "cuda", "manual_seed"),
    ("torch", "cuda", "manual_seed_all"),
    ("pl", "seed_everything"), ("set_seed",), ("seed_everything",),
    # NumPy 新式随机数生成器: np.random.default_rng(2026) / np.random.RandomState(42)
    ("np", "random", "default_rng"), ("numpy", "random", "default_rng"),
    ("default_rng",),
    ("np", "random", "RandomState"), ("numpy", "random", "RandomState"),
    ("RandomState",),
}

# 优化器/调度器类名 -> (canonical 参数, 归一化取值)
# 含 PyTorch 与 TensorFlow 两套命名(TF1 的 AdamOptimizer 等);
# MomentumOptimizer 实为"带动量的 SGD", 归一化到 sgd 以免误报不一致。
_OPTIMIZER_CLASSES = {
    "Adam": "adam", "AdamW": "adamw", "SGD": "sgd", "RMSprop": "rmsprop",
    "Adagrad": "adagrad", "AdaDelta": "adadelta", "Adamax": "adamax",
    "Lamb": "lamb", "NAdam": "nadam",
    "AdamOptimizer": "adam", "AdamWeightDecayOptimizer": "adam",
    "GradientDescentOptimizer": "sgd", "MomentumOptimizer": "sgd",
    "RMSPropOptimizer": "rmsprop", "AdagradOptimizer": "adagrad",
    "AdadeltaOptimizer": "adadelta", "FtrlOptimizer": "ftrl",
}
_SCHEDULER_CLASSES = {
    "CosineAnnealingLR": "cosine annealing",
    "CosineAnnealingWarmRestarts": "cosine annealing",
    "StepLR": "step lr", "MultiStepLR": "multistep",
    "ExponentialLR": "exponential", "ReduceLROnPlateau": "plateau",
    "ExponentialDecay": "exponential", "PolynomialDecay": "polynomial",
    "CosineDecay": "cosine annealing", "WarmUpCosineDecay": "cosine annealing",
}


def _attr_chain(node: ast.AST) -> tuple:
    """把 a.b.c(...) 的调用对象还原成 ('a','b','c')。"""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return tuple(reversed(parts))


class _ParamVisitor(ast.NodeVisitor):
    """在单个文件的 AST 中收集参数证据。"""

    def __init__(self, filename: str, source: str):
        self.filename = filename
        self.lines = source.splitlines()
        self.found: dict[str, list[Evidence]] = {}
        self.rejected: list[dict] = []
        self.seed_fixed = False
        self.seed_evidence: Optional[Evidence] = None

    # -- 工具
    def _line_text(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1].strip()
        return ""

    def _span_text(self, node_or_lineno, end_lineno: Optional[int] = None) -> str:
        """证据片段: 跨行语句取完整语句(否则单行取值),
        避免多行调用(TabNetClassifier(\\n batch_size=1024\\n))的片段里看不到值。"""
        if isinstance(node_or_lineno, ast.AST):
            lineno = getattr(node_or_lineno, "lineno", 0)
            end_lineno = getattr(node_or_lineno, "end_lineno", lineno) or lineno
        else:
            lineno = node_or_lineno
            end_lineno = end_lineno or lineno
        if not (1 <= lineno <= len(self.lines)):
            return ""
        chunk = " ".join(l.strip() for l in self.lines[lineno - 1:end_lineno] if l.strip())
        return chunk[:240]

    def _literal(self, node: ast.AST):
        """提取字面量值(数/字符串/负号)。"""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) \
                and isinstance(node.operand, ast.Constant):
            return -node.operand.value
        return None

    def _record(self, name: str, value, node, source_label: str = ""):
        # 单字母变量(k/x/i 等)在代码里多为临时变量, 跳过防误报
        if len(name) <= 1 and name.isascii():
            return
        key = canonical_key(name)
        if key is None or value is None:
            return
        # 取值类型门禁: 文本型参数(优化器/调度器/数据集/模型)只收字符串;
        # 其余参数必须是可解析的数值(挡掉 `--epoch latest`、`dropout=True` 这类噪声)
        if key in _TEXT_VALUED_KEYS:
            if not isinstance(value, str):
                return
            if not value.strip():        # 空字符串(占位默认值)不作为证据
                return
        else:
            if isinstance(value, bool) or normalize_number(value) is None:
                return
        lineno = node.lineno if isinstance(node, ast.AST) else node
        # 合理性校验: 超出领域先验范围的值拒收并示众(防错位抽取)
        if is_plausible(key, value) is False:
            self.rejected.append({
                "key": key, "value": str(value),
                "location": source_label or f"{self.filename}:{lineno}",
                "reason": "超出领域先验范围, 疑似错位抽取",
            })
            return
        norm = normalize_number(value)
        if norm is None and isinstance(value, str):
            norm = re.sub(r"\s+", "", value.lower())
        ev = Evidence(
            source="code",
            location=f"{self.filename}:{lineno}",
            snippet=self._span_text(node),
            raw_value=str(value),
            normalized=norm if norm is not None else str(value).lower(),
        )
        self.found.setdefault(key, []).append(ev)

    def _record_variable(self, name: str, var_name: str, node):
        """记录变量引用形式的参数(如 n_clusters=k), 标记为动态确定。"""
        if len(name) <= 1 and name.isascii():
            return
        key = canonical_key(name)
        if key is None:
            return
        lineno = node.lineno if isinstance(node, ast.AST) else node
        self.found.setdefault(key, []).append(Evidence(
            source="code",
            location=f"{self.filename}:{lineno}",
            snippet=self._span_text(node),
            raw_value=f"变量 {var_name}(运行时确定)",
            normalized=None,
        ))

    def visit_Compare(self, node: ast.Compare):
        """total_score >= 0.4 这类内联阈值判定: 值与判定逻辑在一起,
        没有命名赋值, 但仍是"代码实现了该阈值"的有效证据。"""
        if len(node.ops) == 1 and isinstance(
                node.ops[0], (ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq)):
            name = val = None
            left, right = node.left, node.comparators[0]
            if isinstance(right, ast.Constant) and isinstance(right.value, (int, float)):
                val = right.value
                if isinstance(left, ast.Name):
                    name = left.id
                elif isinstance(left, ast.Attribute):
                    name = left.attr
            elif isinstance(left, ast.Constant) and isinstance(left.value, (int, float)):
                val = left.value
                if isinstance(right, ast.Name):
                    name = right.id
                elif isinstance(right, ast.Attribute):
                    name = right.attr
            if name and val is not None and not isinstance(val, bool):
                if canonical_key(name):
                    self._record(name, val, node)
                elif re.search(r"(score|thresh|cutoff|limit)", name, re.IGNORECASE):
                    # 得分/阈值类变量的判定值 -> threshold 候选证据
                    self.found.setdefault("threshold", []).append(Evidence(
                        source="code",
                        location=f"{self.filename}:{node.lineno}",
                        snippet=self._span_text(node),
                        raw_value=str(val),
                        normalized=normalize_number(val),
                    ))
        self.generic_visit(node)

    # -- AST 钩子
    def visit_Assign(self, node: ast.Assign):
        """lr = 0.001 / self.batch_size = 32"""
        val = self._literal(node.value)
        if val is not None:
            for t in node.targets:
                name = None
                if isinstance(t, ast.Name):
                    name = t.id
                elif isinstance(t, ast.Attribute):
                    name = t.attr
                if name:
                    self._record(name, val, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        """lr: float = 0.001"""
        if node.value is not None:
            val = self._literal(node.value)
            if val is not None:
                t = node.target
                name = t.id if isinstance(t, ast.Name) else (
                    t.attr if isinstance(t, ast.Attribute) else None)
                if name:
                    self._record(name, val, node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Adam(params, lr=0.001) / DataLoader(ds, batch_size=32) /
        add_argument('--lr', default=1e-3) / torch.manual_seed(42)"""
        chain = _attr_chain(node.func)

        # seed 固定检测
        if chain in _SEED_CALLS and node.args:
            self.seed_fixed = True
            val = self._literal(node.args[0])
            if self.seed_evidence is None:
                if val is not None:
                    raw, norm = str(val), normalize_number(val)
                elif isinstance(node.args[0], ast.Name):
                    # 种子值来自变量(如 torch.manual_seed(args.seed)): 记录为动态值
                    raw = f"变量 {node.args[0].id}(运行时确定)"
                    norm = None
                else:
                    raw, norm = "(未提供静态值)", None
                self.seed_evidence = Evidence(
                    source="code",
                    location=f"{self.filename}:{node.lineno}",
                    snippet=self._span_text(node),
                    raw_value=raw,
                    normalized=norm,
                )

        # 优化器/调度器类实例化: torch.optim.Adam(...) / CosineAnnealingLR(...)
        # 证据值写实际类名(自证可查), 归一化值写 canonical 标签(比对用)
        if chain:
            cls = chain[-1]
            if cls in _OPTIMIZER_CLASSES:
                self.found.setdefault("optimizer", []).append(Evidence(
                    source="code",
                    location=f"{self.filename}:{node.lineno}",
                    snippet=self._span_text(node),
                    raw_value=cls,
                    normalized=_OPTIMIZER_CLASSES[cls],
                ))
            elif cls in _SCHEDULER_CLASSES:
                self.found.setdefault("scheduler", []).append(Evidence(
                    source="code",
                    location=f"{self.filename}:{node.lineno}",
                    snippet=self._span_text(node),
                    raw_value=cls,
                    normalized=_SCHEDULER_CLASSES[cls],
                ))

        # 关键字参数: lr=..., batch_size=...(字面量)
        for kw in node.keywords:
            if kw.arg:
                val = self._literal(kw.value)
                if val is not None:
                    self._record(kw.arg, val, node)
                elif isinstance(kw.value, ast.Name):
                    # n_clusters=k 这类变量引用: 记录为"动态确定, 无法静态验证"的证据
                    self._record_variable(kw.arg, kw.value.id, node)

        # argparse: add_argument('--lr', default=0.001)
        if chain and chain[-1] == "add_argument" and node.args:
            first = self._literal(node.args[0])
            if isinstance(first, str):
                pname = first.lstrip("-")
                for kw in node.keywords:
                    if kw.arg == "default":
                        val = self._literal(kw.value)
                        if val is not None:
                            self._record(pname, val, node)

        self.generic_visit(node)


# ---------------------------------------------------------------- 配置/依赖文件

def _parse_config_text(filename: str, text: str) -> dict[str, list[Evidence]]:
    """解析 yaml/json 配置中的参数。"""
    found: dict[str, list[Evidence]] = {}
    try:
        if filename.endswith((".yaml", ".yml")):
            data = yaml.safe_load(text)
        elif filename.endswith(".json"):
            data = json.loads(text)
        else:
            return found
    except Exception:
        return found
    if not isinstance(data, dict):
        return found

    def walk(d, prefix=""):
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v, prefix + str(k) + ".")
            elif isinstance(v, (int, float, str)):
                key = canonical_key(str(k))
                if key:
                    norm = normalize_number(v)
                    if norm is None and isinstance(v, str):
                        norm = re.sub(r"\s+", "", v.lower())
                    found.setdefault(key, []).append(Evidence(
                        source="code",
                        location=f"{filename}(config)",
                        snippet=f"{prefix}{k}: {v}",
                        raw_value=str(v),
                        normalized=norm if norm is not None else str(v).lower(),
                    ))
    walk(data)
    return found


def _parse_requirements(text: str) -> dict[str, str]:
    reqs = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*(?:[=<>!~]=?\s*([\d\.]+))?", line)
        if m:
            reqs[m.group(1).lower()] = m.group(2) or ""
    return reqs


# ---------------------------------------------------------------- 入口

# 取值为文本的参数(只接受字符串值), 其余参数要求可解析为数值
_TEXT_VALUED_KEYS = {"optimizer", "scheduler", "dataset", "model"}


def _sanitize_cell(src: str) -> str:
    """清洗 notebook cell: 把 IPython 魔术命令与 shell 转义换成等价的 no-op 语句。

    要点: 必须保留原缩进并写成 `pass` 语句 —— 若只替换成注释,
    `if IN_COLAB:` 这类块的语句体会变空, 反而产生 IndentationError(假解析失败)。
    """
    out = []
    for line in src.splitlines():
        s = line.lstrip()
        if s.startswith(("!", "%", "?")) or s.startswith("get_ipython("):
            indent = line[: len(line) - len(s)]
            out.append(f"{indent}pass  # [notebook magic] {s}")
        else:
            out.append(line)
    text = "\n".join(out)
    # 行内魔术: x = %time foo(...) -> x = None  # [magic]
    text = re.sub(r"(?<![\w#])%(?:time|timeit|matplotlib|load_ext|reload_ext)\b[^\n]*",
                  "None  # [magic]", text)
    return text


def _notebook_cells(text: str, sanitize: bool = True) -> list[str]:
    """把 .ipynb 的 code cell 还原成源码片段(默认清洗魔术命令)。"""
    try:
        nb = json.loads(text)
    except Exception:
        return []
    cells = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        if not src.strip():
            continue
        if src.lstrip().startswith("%%"):   # cell 级魔术(%%bash 等)整块跳过
            continue
        cells.append(_sanitize_cell(src) if sanitize else src)
    return cells


def analyze_code(source: Union[str, Path]) -> CodeInfo:
    """分析代码目录或 zip 文件, 输出 CodeInfo。"""
    info = CodeInfo()
    info.aux_only_keys = set()   # 只在测试/示例文件里出现的参数(不作为实现依据, 但在清单里说明)
    py_sources: list[tuple[str, str]] = []   # (相对文件名, 源码)
    config_sources: list[tuple[str, str]] = []
    ml_sources: list[tuple[str, str, str]] = []   # (文件名, 语言, 文本) 多语言通用通道
    req_text: Optional[str] = None

    src = str(source)
    if not src.strip() or not Path(src).exists():
        # 空路径 / 不存在的路径: 明确返回"无代码", 绝不落到下面的目录分支。
        # 原因: Path("") 等于 Path(".") —— 会把**当前工作目录**(含 .venv、临时文件、
        # 甚至本项目的 .env) 当成"论文的代码"整目录扫描, 既产生荒唐结论,
        # 又有读到敏感文件的风险。2026-09-27 实测: 缺代码包时会扫出 5874 个 .py。
        return info

    def _collect(rel: str, low: str, text: str):
        nonlocal req_text
        if low.endswith(".py"):
            py_sources.append((rel, text))
        elif low.endswith(".ipynb"):
            # Jupyter Notebook: code cell 逐个当作源码分析
            for i, cell_src in enumerate(_notebook_cells(text)):
                py_sources.append((f"{rel}[cell{i + 1}]", cell_src))
            # notebook 里常用 `!python train.py --lr 5e-5` 这类命令传参,
            # 这类"命令行参数"交给多语言通用通道(按 cell 保持行号可追溯)
            for i, cell_src in enumerate(_notebook_cells(text, sanitize=False)):
                ml_sources.append((f"{rel}[cell{i + 1}]", "Notebook 命令", cell_src))
        elif low.endswith((".yaml", ".yml", ".json")) and \
                any(k in low for k in ("config", "setting", "param", "train")):
            config_sources.append((rel, text))
        elif Path(low).name in ("requirements.txt", "environment.yml", "environment.yaml"):
            req_text = text
        else:
            # 其余语言/配置: 走多语言通用通道(MATLAB/R/C++/Julia/Fortran/Shell/INI/TOML...)
            lang = language_of(rel)
            if lang:
                ml_sources.append((rel, lang, text))

    if src.lower().endswith(".zip"):
        with zipfile.ZipFile(src) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                low = name.lower()
                # 去掉 zip 内顶层目录前缀, 证据定位更干净
                rel = "/".join(name.split("/")[1:]) if name.count("/") >= 1 else name
                rel = rel or name
                try:
                    # utf-8-sig: 同时兼容带 BOM 与不带 BOM 的文件
                    # (带 BOM 的源码直接 ast.parse 会 SyntaxError 被静默跳过)
                    text = zf.read(name).decode("utf-8-sig", errors="replace")
                except Exception:
                    continue
                _collect(rel, low, text)
    else:
        root = Path(src)
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            low = p.name.lower()
            try:
                text = p.read_text(encoding="utf-8-sig", errors="replace")
            except Exception:
                continue
            _collect(str(p.relative_to(root)), low, text)

    info.python_files = len(py_sources)

    seed_evs: list[Evidence] = []
    for fname, text in py_sources:
        info.file_lines[fname] = len(text.splitlines())
        try:
            # 静默 SyntaxWarning(老代码里的无效转义如 '\.' 会刷屏, 与解析成败无关)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(text)
        except SyntaxError as e:
            # 失败示众: 禁止静默跳过, 未解析文件必须列入清单
            info.failed_files.append({
                "file": fname,
                "reason": f"SyntaxError: {e.msg} (line {e.lineno})",
                "lines": len(text.splitlines()),
            })
            continue
        visitor = _ParamVisitor(fname, text)
        visitor.visit(tree)
        for key, evs in visitor.found.items():
            info.params.setdefault(key, []).extend(evs)
        info.rejected.extend(visitor.rejected)
        if visitor.seed_fixed:
            info.seed_fixed = True
            if visitor.seed_evidence:
                seed_evs.append(visitor.seed_evidence)

    # 多处种子证据时挑最能代表实验的一处:
    # 求解/训练/模拟脚本优先, 图表/演示数据文件靠后
    def _seed_score(ev: Evidence) -> int:
        loc = ev.location.lower()
        s = 0
        if re.search(r"(solve|train|main|sim|montecarlo|mc_|_mc|q\d)", loc):
            s += 3
        if re.search(r"(chart|plot|fig|data|demo|vis)", loc):
            s -= 3
        return s

    if seed_evs:
        info.seed_evidence = max(seed_evs, key=_seed_score)

    for fname, text in config_sources:
        for key, evs in _parse_config_text(fname, text).items():
            info.params.setdefault(key, []).extend(evs)

    # ---- 多语言通用通道: MATLAB/R/C++/Julia/Fortran/Shell/INI/TOML 等
    for fname, lang, text in ml_sources:
        hits = extract_params(fname, text)
        # 无论有没有抽到参数都记录下来: 让报告如实体现"这些文件确实被看过"
        info.multilang_files.append({
            "file": fname, "lang": lang,
            "params": sum(len(v) for v in hits.values()),
        })
        for key, evs in hits.items():
            info.params.setdefault(key, []).extend(evs)

    if req_text:
        info.requirements = _parse_requirements(req_text)

    # 标记"只在测试/示例文件里出现"的参数: 不作为实现依据, 但要在覆盖清单里如实说明
    aux_re = re.compile(r"(^|[/\\_.\-])(test|tests|eval|demo|tmp|spec|example|examples|"
                        r"tutorial|sample|colab|benchmark|notebook)", re.IGNORECASE)
    for key, evs in info.params.items():
        if evs and all(aux_re.search(e.location) or "[cell" in e.location for e in evs):
            info.aux_only_keys.add(key)

    return info
