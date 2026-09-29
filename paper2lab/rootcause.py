"""根因追查（第三期 3.2）——从"多个赋值点"里找出**真正生效**的那一个。

**问题场景**：论文说 learning rate = `1e-4`，代码里却在三个地方出现 `0.001` / `0.001` / `3e-4`。
到底哪个是实际生效的？光看审计报告看不出来——得顺着代码追。

**只读代码，绝不修改任何文件**（补丁草案是另一个模块，有独立的闸门）。

**三条约束**：
1. **结论必须可回溯**：每个判断都要落到 `文件:行号`，不许出现"应该是……"这种没有依据的话；
2. **追不出就明说**：无法确定时输出「无法定位最终生效值」，**绝不猜**——
   与第一期"宁可不报一个值"同源；
3. **只读**：全程不写任何文件、不执行任何代码。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .models import CodeInfo

# 入口类文件名: 这些文件通常"命令"配置, 而不是"被命令"
_ENTRY_HINTS = ("train", "main", "run", "launch", "finetune", "experiment", "eval")
# 配置类路径: 这些容易被上层覆盖
_CONFIG_HINTS = ("config", "configs", "setting", "param", "option", "default")
# 这些名字的文件常是被继承的基类, 更容易被覆盖
_BASE_HINTS = ("__init__", "base", "abstract", "template", "common")

_LOC_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+)")


@dataclass
class Candidate:
    """一个候选赋值点。"""
    file: str
    line: int
    value: str
    snippet: str
    kind: str          # entry | config | base | other
    score: int
    why: str

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "value": self.value,
                "snippet": self.snippet, "kind": self.kind,
                "score": self.score, "why": self.why,
                "loc": f"{self.file}:{self.line}"}


@dataclass
class TraceResult:
    """一次根因追查的结果。"""
    param_key: str = ""
    display: str = ""
    paper_value: str = ""
    code_value: str = ""
    candidates: list = field(default_factory=list)   # [Candidate]
    verdict: str = ""                 # 最终生效值; 空串 = 无法确定
    verdict_loc: str = ""
    confidence: str = "none"          # high | medium | low | none
    reason: str = ""
    path: list = field(default_factory=list)         # 人类可读的追查路径

    def to_dict(self) -> dict:
        return {
            "param_key": self.param_key, "display": self.display,
            "paper_value": self.paper_value, "code_value": self.code_value,
            "candidates": [c.to_dict() for c in self.candidates],
            "verdict": self.verdict, "verdict_loc": self.verdict_loc,
            "confidence": self.confidence, "reason": self.reason,
            "path": list(self.path),
        }


def _classify(file_path: str) -> tuple:
    low = (file_path or "").lower().replace("\\", "/")
    name = low.rsplit("/", 1)[-1]
    stem = name[:-3] if name.endswith(".py") else name
    if any(h in stem for h in _BASE_HINTS):
        return "base", -1, "常见基类/共享文件，容易被上层覆盖"
    if any(h in stem for h in _ENTRY_HINTS):
        return "entry", 4, "入口/训练脚本，通常命令其他模块而非被命令"
    if any(h in low for h in _CONFIG_HINTS):
        return "config", 0, "配置文件，通常被入口脚本覆盖"
    return "other", 1, "普通模块"


def _collect(key: str, code: CodeInfo) -> list:
    """收集某参数在代码里的全部赋值点并打分。"""
    cands: list = []
    for ev in (code.params or {}).get(key, []) or []:
        m = _LOC_RE.match(ev.location or "")
        if not m:
            continue
        f, ln = m.group("file"), int(m.group("line"))
        kind, base, why = _classify(f)
        score = base
        # 同一文件内, 行号越靠后越可能覆盖前面的赋值
        score += 1 if ln > 200 else 0
        cands.append(Candidate(file=f, line=ln, value=ev.raw_value,
                               snippet=(ev.snippet or "")[:120], kind=kind,
                               score=score, why=why))
    # 去重(同文件同行同值)
    seen = set()
    uniq: list = []
    for c in cands:
        k = (c.file, c.line, c.value)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    uniq.sort(key=lambda c: (-c.score, c.file, c.line))
    return uniq


def trace_param(key: str, code: CodeInfo,
                paper_value: str = "", display: str = "") -> TraceResult:
    """追查某参数在代码里**最终生效**的赋值点。追不出就如实说。"""
    cands = _collect(key, code)
    res = TraceResult(param_key=key, display=display or key, paper_value=paper_value)

    if not cands:
        res.confidence = "none"
        res.reason = "代码里没有任何该参数的赋值点，无从追查。"
        return res

    res.code_value = cands[0].value
    res.candidates = cands      # 挂上候选列表(否则界面/报告里看不到追查依据)

    if len(cands) == 1:
        c = cands[0]
        res.verdict, res.verdict_loc = c.value, f"{c.file}:{c.line}"
        res.confidence = "high"
        res.reason = f"代码里只有一处赋值（{c.why}），即为最终生效值。"
        res.path = [f"{c.file}:{c.line} = {c.value}（唯一赋值点）"]
        return res

    top, second = cands[0], cands[1]
    gap = top.score - second.score
    res.path = [f"{c.file}:{c.line} = {c.value}　[{c.kind}，{c.why}]" for c in cands[:6]]

    if gap >= 3:
        res.verdict, res.verdict_loc = top.value, f"{top.file}:{top.line}"
        res.confidence = "medium"
        res.reason = (f"共 {len(cands)} 处赋值；`{top.file}:{top.line}` 最可能是最终生效值"
                      f"（{top.why}），但**这是启发式判断**，建议实际跑一次打印核对。")
    else:
        # 分值接近 -> 不猜
        res.verdict = ""
        res.confidence = "none"
        res.reason = (f"共 {len(cands)} 处赋值，且无从判断哪一处最终生效"
                      f"（{top.file}:{top.line} 与 {second.file}:{second.line} 的可能性接近）。"
                      "**无法定位最终生效值**，建议实际运行并打印该参数，或查阅配置继承关系。")
    return res


def trace_findings(audit, *, keys: Optional[set] = None, max_items: int = 8) -> list:
    """对"论文与代码不一致"的发现做批量追查（默认只追不一致项，省时且最相关）。"""
    from .models import Status
    out: list = []
    done: set = set()
    for f in audit.findings:
        if f.status not in (Status.INCONSISTENT, Status.INTERNAL_INCONSISTENT):
            continue
        if keys is not None and f.param_key not in keys:
            continue
        if f.param_key in done:
            continue
        done.add(f.param_key)
        out.append(trace_param(
            f.param_key, audit.code,
            paper_value=(f.paper.raw_value if f.paper else ""),
            display=f.display_name))
        if len(out) >= max_items:
            break
    return out
