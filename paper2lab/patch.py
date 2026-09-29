"""修复补丁草案（第三期 3.3）——给出"建议改成什么"，但**绝不落盘**。

**这一期最容易出事的就是这里**，所以三条规定写得比代码还重要：

1. **只出方案，绝不写文件** —— 本模块只返回字符串，不调用任何写操作；
   应用与否由人决定。
2. **每个补丁必须绑定证据**：一条已确认的"值不一致"结论 + 一条可回溯的根因路径。
   拿不到根因就**不给补丁**，而不是"猜一个大概的位置"。
3. **只改"值"，不生成新代码**：本模块只做"把这一行的这个值换成那个值"。
   "建议补一段随机种子固定代码"这类**生成新逻辑**的事不做 ——
   审计系统擅长的是"两个值不一样"，不是"替你写实现"。

**拒绝（refuse）是一门正式能力**，不是失败。以下情形一律拒绝并说明理由：
    · 追查不出最终生效位置；
    · 不是"值不一致"类型（如"代码缺该参数"需要人补配置，不是改值）；
    · 目标行在代码包里找不到（可能已被改动过）；
    · 要替换的值在该行里不唯一（无法确定改哪一处）。
"""
from __future__ import annotations

import difflib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import Status
from .rootcause import TraceResult

# 允许出补丁的结论类型: 只有"值不一致"才谈得上"改成论文的值"
_PATCHABLE = {Status.INCONSISTENT}

# 只对这些**配置项**出"改值"补丁。
# 明确排除 optimizer / scheduler / model: 它们对应"实现选择", 不是"配置值"——
# 把 `resnet50` 改成 `DETR`、把 `StepLR` 改成 `cosine` 这类"修复"本身就没有意义
# （甚至有害）, 因此本模块一律不出补丁, 并在拒绝理由里说清楚。
_PATCHABLE_KEYS = {
    "learning_rate", "batch_size", "epochs", "iterations", "weight_decay",
    "dropout", "warmup", "input_size", "momentum", "seed", "threshold", "dataset",
}

_NUM_TOKEN = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

# ---- 「来源可信度」闸门用到的两条判据（2026-09-28 新增）
# 背景：既有闸门只保证**机械安全**（能定位到唯一一行、token 唯一、语法合法），
# 不保证**论文侧那个值本身可信**。拿新样本集测试时，正是这个缺口放出了 4 条错补丁：
#   · Swin  `_C.DATA.DATASET = 'imagenet'` → `'COCO'`   （COCO 来自检测章节）
#   · Swin  `WARMUP_EPOCHS = 20` → `1`                  （原文是 "1,500"，被截断成 1）
#   · ConvNeXt `default=224` → `2242.0`                 （原文 224² 上标丢失）
#   · DeiT  `--batch-size default=64` → `16`            （16 是 patch 尺寸）
# 因此补上「形态」与「出处」两道否决：**宁可不给补丁，也不给一个明显错的数字。**

# ① 形态不干净：尾部/首部是标点（句末句点、截断残留、千分位断了尾）
_MALFORMED_VALUE = re.compile(r"[.,;:，。、；]$|^[.,;:，。、]|^\s*$")

# ② 单位不一致（2026-09-28 新增，Swin 实测）：
#   论文证据 "…a linear warmup of 1,500 iterations…" 说的是**迭代次数**，
#   而目标变量是 `_C.TRAIN.WARMUP_EPOCHS`（**轮数**）——
#   两者差着"一轮有多少次迭代"这个系数，直接替换得到的代码一定是错的
#   （就这一处：1,500 次迭代 ≈ 1 轮多，而 20 轮 ≈ 两万多次迭代）。
#   注意这与 `_MALFORMED_VALUE` 不同：那个值本身**形态完全合法**，只有语义对不上。
_CODE_EPOCH = re.compile(r"(?<![A-Za-z])epochs?(?![A-Za-z])", re.IGNORECASE)
_CODE_ITER = re.compile(r"(?<![A-Za-z])(?:iterations?|iters?|steps?)(?![A-Za-z])",
                        re.IGNORECASE)
_EV_EPOCH = re.compile(r"\bepochs?\b", re.IGNORECASE)
_EV_ITER = re.compile(r"\b(?:iterations?|iters?|steps?)\b", re.IGNORECASE)
# 注: 代码侧刻意**不用 `\b`** —— `\b` 在 `WARMUP_EPOCHS` 里匹配不上(下划线算词字符),
# 而正是这一处漏判, 让 Swin 的 `WARMUP_EPOCHS 20 → 1500` 第一次跑没被拦住。


def _unit_conflict(code_line: str, evidence: str) -> str:
    """目标行与论文证据的**单位**是否明确冲突（轮 vs 次）。返回空串 = 不冲突。"""
    c_ep, c_it = bool(_CODE_EPOCH.search(code_line)), bool(_CODE_ITER.search(code_line))
    e_ep, e_it = bool(_EV_EPOCH.search(evidence)), bool(_EV_ITER.search(evidence))
    if c_ep and not c_it and e_it and not e_ep:
        return ("论文证据说的是**迭代次数**，而这一行是**训练轮数（epochs）**——"
                "两者之间差着「一轮包含多少次迭代」这个系数，直接替换必然错。")
    if c_it and not c_ep and e_ep and not e_it:
        return ("论文证据说的是**训练轮数（epochs）**，而这一行是**迭代次数**——"
                "两者之间差着「一轮包含多少次迭代」这个系数，直接替换必然错。")
    return ""


@dataclass
class PatchProposal:
    param_key: str = ""
    display: str = ""
    status: str = "refused"          # proposed | proposed-llm | refused
    refuse_reason: str = ""
    refuse_kind: str = ""            # 机器可读的拒绝类型（见 _K_* 常量）
    rationale: str = ""              # 为什么这么改（依据）
    diff: str = ""                   # unified diff 草案（仅供参考，不落盘）
    target: str = ""                 # 文件:行号
    before: str = ""
    after: str = ""
    evidence: dict = field(default_factory=dict)
    confidence: str = "none"
    source: str = "rule"             # rule = 确定性闸门推出; llm = AI 提名目标
    needs_human: bool = False        # True = 目标由 AI 选定，**采纳前必须人工确认**
    stamps: list = field(default_factory=list)   # 程序盖章清单（逐条：验证了什么）

    @property
    def is_proposed(self) -> bool:
        """是否给出了方案（含 AI 提名的那一类）。"""
        return self.status in ("proposed", "proposed-llm")

    def to_dict(self) -> dict:
        return {
            "param_key": self.param_key, "display": self.display,
            "status": self.status, "refuse_reason": self.refuse_reason,
            "refuse_kind": self.refuse_kind,
            "rationale": self.rationale, "diff": self.diff, "target": self.target,
            "before": self.before, "after": self.after,
            "evidence": self.evidence, "confidence": self.confidence,
            "source": self.source, "needs_human": self.needs_human,
            "stamps": list(self.stamps),
        }


# 拒绝类型（机器可读）—— 有了它，"哪些拒绝可以交给 AI 再试一次"是个**代码里的判断**，
# 而不是靠匹配中文关键字。只有"值可信、缺的只是『选哪个』"这两类才允许 AI 参与。
_K_NOT_INCONSISTENT = "not_inconsistent"     # 结论不是"值不一致"
_K_NOT_CONFIG = "not_config"                 # 不是配置项（结果指标/实现选择/白名单外）
_K_MULTI_VALUE = "multi_value"               # 论文侧有多个取值（多配置/多列对比表）
_K_NO_ROOTCAUSE = "no_rootcause"             # 代码里追不出最终生效点
_K_NO_PAPER_VALUE = "no_paper_value"
_K_MALFORMED = "malformed"
_K_LITERAL = "literal"
_K_BAD_TARGET = "bad_target"
_K_UNIT = "unit"
_K_TYPE_INT = "type_int"
_K_TOKEN = "token"
# 允许"AI 提名目标"的两类
_LLM_ELIGIBLE = {_K_MULTI_VALUE, _K_NO_ROOTCAUSE}


def _read_source(code_path: str, rel_file: str) -> Optional[str]:
    """从代码包(zip 或目录)里读出某个文件的内容。只读, 不写。"""
    if not code_path:
        return None
    p = Path(code_path)
    if p.is_dir():
        try:
            base = p.resolve()
            target = (p / rel_file).resolve()
        except OSError:
            return None
        # 防路径穿越（2026-09-29 实测复现）: `rel_file` 形如 `../secret` 时不许读到
        # 代码包之外。它虽然是根因路径里拼出来的、正常情况下一定在包内，
        # 但这里是字符串拼接的结果 —— 做一道独立校验，不假定上游一定干净。
        if target != base and base not in target.parents:
            return None
        try:
            return target.read_text(encoding="utf-8-sig", errors="replace")
        except Exception:      # noqa: BLE001
            return None
    if p.suffix.lower() == ".zip" and p.exists():
        try:
            with zipfile.ZipFile(p) as zf:
                for name in zf.namelist():
                    rel = "/".join(name.split("/")[1:]) or name      # 去掉顶层目录前缀
                    if rel == rel_file or name == rel_file or name.endswith("/" + rel_file):
                        return zf.read(name).decode("utf-8-sig", errors="replace")
        except Exception:      # noqa: BLE001
            return None
    return None


def _safe_literal(value: str, normalized, key: str) -> Optional[str]:
    """把论文里的取值转成一段**可安全放进代码**的字面量；转不了就返回 None。

    论文里的数值常写成排版形式（`10−4`、`5 × 10−4`），其中减号是 Unicode U+2212、
    乘号是 U+00D7 —— **直接塞进代码就是语法错误**。因此：
      · 数值型参数：用归一化后的数值（`0.0001`）；
      · 字符串型参数（如 dataset）：要求是朴素标识符，否则不出补丁。
    """
    from .synonyms import normalize_number
    v = (value or "").strip()
    if not v:
        return None
    if key == "dataset":
        return v if re.fullmatch(r"[A-Za-z0-9_.\-]+", v) else None
    n = normalized if isinstance(normalized, (int, float)) else None
    if n is None:
        n = normalize_number(v)
    if n is None:
        return None
    if isinstance(n, float):
        # 原值本来就是整数写法（如 batch_size=64）时要输出 64 而不是 64.0 ——
        # 否则会写出 `default=64.0, type=int` 这种自相矛盾的代码。
        if n == int(n) and not re.search(r"[.eE]", v):
            return str(int(n))
        return repr(n)      # repr 给最短往返表示: 0.0001, 而不是 0.00010000000000000002
    return str(n)


def _comment_start(line: str) -> int:
    """行内注释的起点（引号感知）。返回 `len(line)` 表示整行都是代码。

    为什么要它（2026-09-29 实测复现的缺口）:
      `_replace_token` 原来在**整行**里找"唯一的待替换值"。若那一行是
          `WARMUP_EPOCHS = 20   # 1 epoch warmup`
      而根因给出的值是 `1`（从注释里抽到的），它会唯一命中**注释里**的那个 1，
      产出一条"改了注释、生效值 20 一动没动"的补丁 ——
      看上去像修好了，实际毫无作用。这类补丁最伤信任，必须从源头堵掉。
    """
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":          # 转义: 跳过下一个字符, 避免 '\"' 被当成收尾
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return i
        i += 1
    return len(line)


def _replace_token(line: str, old: str, new: str) -> Optional[str]:
    """把行里的 old 值替换成 new —— 只在**唯一命中**时才替换，拿不准一律不换。

    注意一个实测坑：证据里的 `raw_value` 可能是**归一化后的展示值**（如 `0.0001`），
    而代码原文写的是 `1e-4`。所以数值型参数要按**数值等价**去定位，而不是字面相等——
    否则会出现"明明在那一行，却报'找不到待替换值'"的假拒绝。

    另一条：**注释里的数字不参选**（见 `_comment_start`）。注释不是生效代码，
    改中它等于没改，还会让审查者以为已经改过。
    """
    if not old or not new:
        return None
    from .synonyms import normalize_number
    code_part = line[:_comment_start(line)]        # 只在代码区找待替换值
    target = normalize_number(old)
    if target is not None:
        spans = [m for m in _NUM_TOKEN.finditer(code_part)
                 if m.group(0) == old or normalize_number(m.group(0)) == target]
    else:
        pat = re.compile(r"(?<!\w)" + re.escape(old) + r"(?!\w)")
        spans = list(pat.finditer(code_part))
    if len(spans) != 1:         # 找不到, 或有多处 -> 不敢动
        return None
    m = spans[0]
    return line[:m.start()] + new + line[m.end():]


def _is_valid_snippet(line: str) -> bool:
    """生成出来的那一行是否仍是**合法 Python**。

    `_safe_literal` 已从源头挡住了 Unicode 排版字符（`10−4` 的减号、上标等），
    但"应该合法"不等于"已证明合法"。这里是最后一道机械自检 ——
    不合法就不给，而不是把一段跑不起来的代码交给人去复制。
    """
    import ast
    try:
        ast.parse(line)
        return True
    except SyntaxError:
        pass
    try:                     # 可能是跨行语句的片段, 包一层再试
        ast.parse("if True:\n    " + line)
        return True
    except SyntaxError:
        return False


def propose_patch(finding, trace: TraceResult, code_path: str, *,
                  other_values: int = 1) -> PatchProposal:
    """为一条"值不一致"的结论生成补丁草案。拿不准一律拒绝。

    `other_values`: 论文侧该参数**不同取值**的个数(已排除灵敏度/对比表)。>1 时不出补丁。
    """
    res = PatchProposal(param_key=finding.param_key, display=finding.display_name,
                        confidence=trace.confidence)

    # ---- 闸门 1: 只有"值不一致"才谈得上改成论文的值
    if finding.status not in _PATCHABLE:
        res.refuse_kind = _K_NOT_INCONSISTENT
        res.refuse_reason = (f"该结论类型是「{finding.status.value}」，"
                             "不是「值不一致」——需要人工补配置或判断，本模块不做。")
        return res

    # ---- 闸门 2: 只对"配置项"出补丁
    if finding.param_key not in _PATCHABLE_KEYS:
        res.refuse_kind = _K_NOT_CONFIG
        # 分三种说清楚 —— 原来一律说成"实现选择"，对着 `Result: accuracy` 读起来是错的:
        # 结果指标不是"实现选择"，它是"论文声明 vs 实测"的核对结论，压根不在代码里。
        if finding.param_key.startswith("result_"):
            res.refuse_reason = (
                f"「{finding.display_name}」是**实验结果指标**（论文声明 vs 你实测），"
                "不是代码里的配置项 —— 没有「把哪一行改成什么」可言。"
                "指标对不上要回训练/数据去找原因（本模块只做配置值的改值补丁）。")
        elif finding.param_key in ("optimizer", "scheduler", "model"):
            res.refuse_reason = (
                f"「{finding.display_name}」属于**实现选择**类参数（优化器 / 调度器 / 模型结构等）。"
                "把它改成论文里的写法并不等于修好问题（甚至可能改坏）——"
                "本模块只对**配置项**出改值补丁，这一项请人工判断。")
        else:
            res.refuse_reason = (
                f"「{finding.display_name}」不在可改值白名单里（本模块只对"
                "学习率 / 批大小 / 轮数 / 迭代次数 / 权重衰减 / dropout / warmup / "
                "输入尺寸 / 动量 / 种子 / 阈值 / 数据集这些**配置项**出补丁）。")
        return res

    # ---- 闸门 2b: 论文侧该参数必须只有**唯一**取值
    # 实测(2026-09-28, 新样本集)这是最主要的一类错补丁来源: 论文给了多个配置
    # (ImageNet-22k 预训练 vs 1k 微调、附表里多列对比), 抽到的"论文值"只是其中一列,
    # 于是补丁把**正确的代码值**改成了**别的配置的值**。
    # 例如 DeiT 附表把 ViT-B 与 DeiT-B 并排: 抽到 lr=0.003 / batch=4096 都是 ViT-B 那列,
    # 而代码里的 5e-4 才是 DeiT-B 本身的正确值。
    # 这类情况**无法确定该改成哪个**, 一律不给补丁。
    if other_values > 1:
        res.refuse_kind = _K_MULTI_VALUE
        res.refuse_reason = (
            f"论文里「{finding.display_name}」出现了 **{other_values} 个不同的取值**"
            "（通常对应多个实验配置，如不同规模 / 不同数据集的对比表）。"
            "无法确定该改成哪一个，按铁律**不给补丁** —— 请先人工确认目标配置。")
        return res

    # ---- 闸门 3: 必须有根因, 且能定位到唯一生效点
    if trace.confidence == "none" or not trace.verdict or not trace.verdict_loc:
        res.refuse_kind = _K_NO_ROOTCAUSE
        res.refuse_reason = ("无法确定代码里最终生效的赋值点（可能有多处且难以判断哪处生效），"
                             "按第三期铁律**不给补丁** —— 宁可不给，也不给一个可能改错地方的方案。")
        return res

    raw_val = getattr(finding.paper, "raw_value", "") if finding.paper else ""
    if not raw_val:
        res.refuse_kind = _K_NO_PAPER_VALUE
        res.refuse_reason = "论文侧没有可用取值，没有「改成什么」的目标值。"
        return res

    # ---- 闸门 3a: 取值形态必须干净
    if _MALFORMED_VALUE.search(raw_val):
        res.refuse_kind = _K_MALFORMED
        res.refuse_reason = (
            f"论文侧取值 `{raw_val}` **形态不干净**（首尾带标点，疑为句末句点或截断残留）。"
            "拿这种值去改代码会得到明显错的结果（例如 `224 → 2242.0`），按铁律不给补丁。")
        return res
    # 注: 曾试过"出处必须在实验设置章节"这道闸门, 但它**弊大于利** ——
    # 章节标签来自 `_find_section` 的启发式(取上方最近的短行), 并不可靠:
    # 实测(2026-09-28) 05_ViT 的 dataset 出处被标成「INTRODUCTION」, 于是把一条
    # 取值正确的补丁 (`config.dataset = 'cifar10' → 'ImageNet'`) 误拒了。
    # 而"跨章节取错值"这个真实问题, 已在**抽取侧**修好(dataset 全篇择优), 不需要在这里兜。
    # 论文里的值常是排版形式（`10−4` 的减号是 Unicode U+2212），直接塞进代码会变语法错误，
    # 必须先转成安全字面量；转不了就不出补丁 —— 宁可不给，也不给一段跑不起来的代码。
    paper_val = _safe_literal(raw_val,
                              getattr(finding.paper, "normalized", None),
                              finding.param_key)
    if paper_val is None:
        res.refuse_kind = _K_LITERAL
        res.refuse_reason = (
            f"论文里的取值 `{raw_val}` 无法转成代码可用的字面量"
            "（常见于排版形式，如 `10−4` 用的是 Unicode 减号）——"
            "为避免生成**语法错误**的代码，本模块不出这个补丁。")
        return res

    # ---- 闸门 3: 目标行必须真实存在
    m = re.match(r"^(?P<file>[^:]+):(?P<line>\d+)", trace.verdict_loc or "")
    if not m:
        res.refuse_kind = _K_BAD_TARGET
        res.refuse_reason = f"根因路径格式异常（{trace.verdict_loc}），无法定位到具体行。"
        return res
    rel, lineno = m.group("file"), int(m.group("line"))
    src = _read_source(code_path, rel)
    if src is None:
        res.refuse_kind = _K_BAD_TARGET
        res.refuse_reason = f"在代码包里找不到 `{rel}`，无法核对原行，故不给补丁。"
        return res
    lines = src.splitlines()
    if lineno < 1 or lineno > len(lines):
        res.refuse_kind = _K_BAD_TARGET
        res.refuse_reason = f"`{rel}:{lineno}` 超出文件行数（共 {len(lines)} 行），不给补丁。"
        return res
    before = lines[lineno - 1]

    # ---- 闸门 3b: 单位必须对得上（轮 vs 次）
    _ev_txt = f"{getattr(finding.paper, 'snippet', '') or ''} {raw_val}"
    _conflict = _unit_conflict(before, _ev_txt)
    if _conflict:
        res.refuse_kind = _K_UNIT
        res.refuse_reason = (
            f"{_conflict}（论文侧 `{raw_val}`，目标行 `{rel}:{lineno}`）"
            "按铁律**不给补丁** —— 需要人工换算到同一单位后再定。")
        res.target = f"{rel}:{lineno}"
        res.before = before.strip()
        return res

    # ---- 闸门 4: 该行里的旧值必须唯一可替换
    old_val = trace.verdict
    # ---- 闸门 4a: 整数参数不能被写成浮点（否则写出 `default=2242.0, type=int` 这种自相矛盾的代码）
    if re.search(r"type\s*=\s*int\b", before) and re.search(r"[.eE]", paper_val):
        res.refuse_kind = _K_TYPE_INT
        res.refuse_reason = (
            f"目标行声明了 `type=int`，而论文侧取值 `{paper_val}` 是浮点写法 —— "
            "直接替换会得到类型自相矛盾的代码，本模块不给这个补丁。")
        res.target = f"{rel}:{lineno}"
        res.before = before.strip()
        return res
    after = _replace_token(before, old_val, paper_val)
    if after is None or after == before:
        res.refuse_kind = _K_TOKEN
        res.refuse_reason = (f"在 `{rel}:{lineno}` 这一行里找不到唯一的待替换值 `{old_val}`"
                             "（可能已被改动或出现多次），无法安全生成补丁。")
        res.target = f"{rel}:{lineno}"
        res.before = before.strip()
        return res

    # ---- 闸门 5: 生成出来的那一行必须仍是**合法 Python**
    # 从源头 `_safe_literal` 到目标行核对都已过, 但"应该合法"不等于"已证明合法"。
    # 这是最后一道机械自检: 不合法就不给, 而不是把一段跑不起来的代码交给人去抄。
    if not _is_valid_snippet(after.strip()):
        res.refuse_kind = _K_LITERAL
        res.refuse_reason = (
            "替换后生成的那一行**通不过 Python 语法自检** —— "
            "为避免交出一段跑不起来的代码，本模块不给这个补丁。")
        res.target = f"{rel}:{lineno}"
        res.before = before.strip()
        res.after = after
        return res

    # ---- 通过全部闸门 -> 出草案
    res.status = "proposed"
    res.target = f"{rel}:{lineno}"
    res.before = before
    res.after = after
    res.diff = "".join(difflib.unified_diff(
        [before + "\n"], [after + "\n"],
        fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="", n=0))
    res.rationale = (
        f"论文声明 **{paper_val}**"
        + (f"（{finding.paper.location}）" if finding.paper else "")
        + f"，而代码最终生效值是 **{old_val}**"
        + (f"（{trace.verdict_loc}）" if trace.verdict_loc else "")
        + f"。根因追查置信度：{trace.confidence}。"
        + (f" 追查路径：{' → '.join(trace.path[:3])}" if trace.path else ""))
    res.evidence = {
        "paper": {"value": paper_val,
                  "location": finding.paper.location if finding.paper else ""},
        "code": {"value": old_val, "location": trace.verdict_loc},
        "trace_confidence": trace.confidence,
        "trace_reason": trace.reason,
    }
    return res


def _llm_target_prompt(finding, trace, refinements) -> str:
    import json
    paper_cands = [{"value": v, "location": loc, "snippet": sn[:160]}
                   for (v, loc, sn) in refinements["paper"]]
    code_cands = [{"loc": f"{c.file}:{c.line}", "value": c.value,
                   "snippet": c.snippet[:120], "kind": c.kind}
                  for c in (trace.candidates or [])]
    return (
        "你在给一条「论文↔代码不一致」的结论**挑补丁目标**。只做选择，不写代码。\n"
        f"参数: {finding.display_name}（{finding.param_key}）\n"
        f"论文侧候选（可能来自多列对比表）: {json.dumps(paper_cands, ensure_ascii=False)}\n"
        f"代码侧候选赋值点: {json.dumps(code_cands, ensure_ascii=False)}\n"
        f"代码实际配置线索: model={getattr(finding.code, 'raw_value', '') if finding.code else ''}\n\n"
        "请判断：**论文的哪一个值**对应代码实际在跑的那套配置，以及它该改在**哪一个赋值点**上。\n"
        "必须从上面的候选里选，不许新造值或新造位置。拿不准就返回 {\"ok\": false}。\n"
        "只输出 JSON: {\"ok\":true,\"paper_value\":\"...\",\"code_loc\":\"file:line\","
        "\"why\":\"一句话依据\"}"
    )


def propose_via_llm(finding, trace: TraceResult, code_path: str, *,
                    refinements: dict, proposal: Optional[dict] = None,
                    api_key: str = "", force_mock: bool = False) -> PatchProposal:
    """**AI 提名目标 + 程序盖章** —— 仅用于"值可信、缺的只是『选哪个』"的两类拒绝。

    允许 AI 参与的只有"选目标"这一件事：它不生成新代码、不改语义、不决定改不改。
    提名必须落在**已抽到的候选**里，然后走**与确定性通道完全相同**的机械闸门
    （值形态 / 单位 / type=int / token 唯一 / 字面量可转）。

    产出标 `status="proposed-llm"` 且 `needs_human=True`：
    **程序只验证了「这个值确实写在论文那句里、那一行确实是代码的赋值点、语法合法」，
     没有验证「它确实属于你要复现的那个配置」** —— 所以采纳前必须人工确认。
    这句话必须原样出现在报告与界面里，不允许简化成"AI 已确认"。
    """
    import copy

    res = PatchProposal(param_key=finding.param_key, display=finding.display_name,
                        confidence=trace.confidence, source="llm", needs_human=True)
    note = "已注入提案（测试模式）"
    if proposal is None:
        from .llm import ask_json
        proposal, note = ask_json(_llm_target_prompt(finding, trace, refinements),
                                  api_key, mode="patch", max_tokens=400,
                                  force_mock=force_mock)
    if not isinstance(proposal, dict) or not proposal.get("ok"):
        res.refuse_kind = _K_NO_ROOTCAUSE
        res.refuse_reason = (f"AI 提名未生效（{note}）—— 保持原判定：不给补丁，"
                             "请人工确认目标配置后再改。")
        return res

    # ---- 盖章 ①: 提名的论文值必须**取自已抽到的候选**
    cand_val = str(proposal.get("paper_value") or "").strip()
    from .synonyms import normalize_number
    hit = None
    for (v, loc, sn) in refinements["paper"]:
        if v == cand_val or (normalize_number(v) is not None
                             and normalize_number(v) == normalize_number(cand_val)):
            hit = (v, loc, sn)
            break
    if hit is None:
        res.refuse_kind = _K_NO_PAPER_VALUE
        res.refuse_reason = (f"AI 提名的论文值 `{cand_val}` **不在已抽到的候选里** —— "
                             "不许凭空造值，盖章不过，不给补丁。")
        return res

    # ---- 盖章 ②: 提名的代码位置必须**取自根因候选点**
    cand_loc = str(proposal.get("code_loc") or "").strip()
    c = next((x for x in (trace.candidates or [])
              if f"{x.file}:{x.line}" == cand_loc), None)
    if c is None:
        res.refuse_kind = _K_NO_ROOTCAUSE
        res.refuse_reason = (f"AI 提名的代码位置 `{cand_loc}` **不是根因追查的候选赋值点** —— "
                             "不许指一个不存在的位置，盖章不过，不给补丁。")
        return res

    # ---- 盖章 ③④⑤…: 交给**同一套机械闸门**（把 AI 的选择装成一次"影子判定"）
    shadow_f = copy.copy(finding)
    shadow_f.paper = _ShadowEvidence(hit[0], hit[1], hit[2])
    shadow_t = copy.copy(trace)
    shadow_t.verdict, shadow_t.verdict_loc = c.value, cand_loc
    shadow_t.confidence = "llm-selected"
    base = propose_patch(shadow_f, shadow_t, code_path, other_values=1)
    # 影子判定的拒绝理由要转述清楚：拒绝发生在"AI 选了目标之后"，不是原判定
    if not base.is_proposed:
        res.refuse_kind = base.refuse_kind
        res.refuse_reason = f"AI 提名的目标没通过机械闸门：{base.refuse_reason}"
        res.target, res.before = base.target, base.before
        return res

    res.status = "proposed-llm"
    res.target, res.before, res.after, res.diff = \
        base.target, base.before, base.after, base.diff
    res.evidence = base.evidence
    res.stamps = [
        f"论文值 `{hit[0]}` 取自已抽候选（{hit[1]}）",
        f"代码位置 `{cand_loc}` 取自根因追查的候选赋值点（{c.kind}）",
        f"该行待替换值 `{c.value}` 唯一命中",
        "值形态 / 单位 / 类型 / 语文字面量：均通过",
    ]
    res.rationale = (
        f"⚠️ **AI 选的目标**（{note}）：AI 认为论文的 **{hit[0]}**（{hit[1]}）"
        f"对应代码实际在跑的配置，应改在 `{cand_loc}`。AI 自述："
        f"{str(proposal.get('why') or '').strip() or '（未给理由）'}\n"
                "程序**只**验证了：这个值确实写在论文那一句里、那一行确实是代码的赋值点、"
                "待替换值唯一、语法与类型合法。**没有**验证「它确实属于你要复现的那个配置」——"
                "采纳前请人工确认目标配置。")
    return res


class _ShadowEvidence:
    """给"AI 选中的候选"套一个最小 Evidence 形状，好复用既有的机械闸门。"""

    def __init__(self, raw_value: str, location: str, snippet: str):
        self.raw_value = raw_value
        self.location = location
        self.snippet = snippet
        self.normalized = None
        self.source = "paper"


def propose_patches(audit, traces: list, code_path: str, *, max_items: int = 8,
                    llm: bool = False, api_key: str = "", force_mock: bool = False,
                    proposals: Optional[dict] = None) -> list:
    """对一批根因追查结果生成补丁草案（只为"值不一致"的结论出）。

    `llm=True` 时，对"值可信、缺的只是『选哪个』"的两类拒绝，再走一次
    **AI 提名 + 程序盖章**（见 `propose_via_llm`）；结果标 `proposed-llm` 且需人工确认。
    `proposals` 可按 param_key 注入提案，用于不调 API 的确定性测试。
    """
    from .synonyms import normalize_number

    by_key = {f.param_key: f for f in audit.findings
              if f.status == Status.INCONSISTENT}

    def _distinct_values(key: str) -> int:
        """论文侧该参数有几种**不同取值**（排除灵敏度/对比表里标了不计入的那些）。"""
        vals = set()
        for ev in (getattr(audit.paper, "params_all", {}) or {}).get(key, []) or []:
            if getattr(ev, "context_excluded", False):
                continue
            n = normalize_number(getattr(ev, "raw_value", ""))
            vals.add(n if n is not None else str(getattr(ev, "raw_value", "")).strip().lower())
        return len(vals) or 1

    def _paper_cands(key: str) -> list:
        out = []
        for ev in (getattr(audit.paper, "params_all", {}) or {}).get(key, []) or []:
            if getattr(ev, "context_excluded", False):
                continue
            out.append((str(getattr(ev, "raw_value", "")),
                        str(getattr(ev, "location", "")),
                        str(getattr(ev, "snippet", "") or "")))
        return out

    out: list = []
    _use_llm = bool(llm or proposals)      # 注入提案即视为开启该通道（测试用）
    for t in traces:
        f = by_key.get(t.param_key)
        if f is None:
            continue                       # 该参数没有"值不一致"结论 -> 不出补丁
        p = propose_patch(f, t, code_path, other_values=_distinct_values(t.param_key))
        if _use_llm and not p.is_proposed and p.refuse_kind in _LLM_ELIGIBLE:
            p = propose_via_llm(
                f, t, code_path,
                refinements={"paper": _paper_cands(t.param_key)},
                proposal=(proposals or {}).get(t.param_key),
                api_key=api_key, force_mock=force_mock)
        out.append(p)
        if len(out) >= max_items:
            break
    return out
