"""实测: 上传 results.json 与否, 各维度差异有多大。

目的: 判断"实验结果 JSON 是否可去掉"时, 需要知道它实际参与了哪些判断。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.envfile import load_env          # noqa: E402
from paper2lab.pipeline import run_audit         # noqa: E402

load_env()
DEMO = HERE / "demo"
RES = json.loads((DEMO / "results.json").read_text(encoding="utf-8"))


def _show(v):
    """None 表示未核验(不是 0 分、也不是满分)。"""
    return "未核验" if v is None else v


def brief(a):
    """把一次审计的关键量抽出来。"""
    res_findings = [f for f in a.findings
                    if f.param_key.startswith("result_")]
    cats = (a.readiness or {}).get("categories") or {}
    return {
        "结论数": len(a.findings),
        "结果类结论": [(f.display_name, f.status.value, f.risk.value)
                       for f in res_findings],
        "就绪度": (a.readiness or {}).get("total"),
        "实验记录完整度": _show(cats.get("实验记录完整度")),
        "结果一致性": _show(cats.get("结果一致性")),
        "未核验维度": list(((a.readiness or {}).get("unverified") or {}).keys()),
        "日志含结果核对": any("结果核对" in x for x in (a.compare_log or [])),
    }


out = []
out.append("# 实验结果 JSON 的作用实测")
out.append("")
out.append(f"- 样本: demo（受控样例）")
out.append(f"- results.json 内容: {RES}")
out.append("")

with_res, _ = run_audit(str(DEMO / "paper.pdf"), str(DEMO / "project.zip"),
                        RES, force_mock=True, plan_mode=True)
without_res, _ = run_audit(str(DEMO / "paper.pdf"), str(DEMO / "project.zip"),
                           None, force_mock=True, plan_mode=True)

b1, b2 = brief(with_res), brief(without_res)

out.append("| 指标 | 传了 results.json | 不传 |")
out.append("|---|---|---|")
for k in b1:
    out.append(f"| {k} | {b1[k]} | {b2[k]} |")
out.append("")

out.append("## 结果类结论明细")
out.append("")
out.append(f"- 传了: {b1['结果类结论'] or '（无）'}")
out.append(f"- 不传: {b2['结果类结论'] or '（无）'}")
out.append("")

# 论文侧声明了什么结果
out.append("## 论文侧声明的结果（与 JSON 无关, 恒在）")
out.append("")
for metric, ev in (with_res.paper.results or {}).items():
    out.append(f"- {metric} = {ev.raw_value}  ← {ev.location}")
out.append("")
out.append("## 代码包侧抓到的结果")
out.append("")
code_res = [f for f in with_res.findings if f.category.value == "result"
            and f.code and f.code.source == "code"]
out.append(f"- 代码侧产出的『结果类』结论数: {len(code_res)}")
out.append("  （代码分析器只做 AST 配置扫描, 不解析 accuracy/loss 等实验指标）")
out.append("")

out.append("## 结论")
out.append("")
out.append("1. results.json 是**唯一**能触发『结果一致性』核验的通道——"
           "论文侧只会解析出『声明值』，把它和『实际值』比对必须有实际值。")
out.append("2. 不传时『结果一致性』显示**未核验**（不是扣分、也不是满分）；"
           "『实验记录完整度』同样标未核验，两者都不计入总分。")
out.append("3. 代码包里的结果数字**系统读不到**（代码分析器不做指标解析），"
           "所以『数据都在代码包里』对本系统不成立。")
out.append("4. 注：代码包 README 里的成绩表是**作者声明**，与论文声明同源，"
           "拿它做对照不构成复现核验。")

(HERE / "_res_probe.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
