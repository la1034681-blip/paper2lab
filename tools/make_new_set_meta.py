"""给新样本建 results.json + 逐目录 README（如实交代每个文件的来源与性质）。

results.json 刻意覆盖「结果一致性」的四种分支：

| 样本 | results.json | 预期判定 |
| --- | --- | --- |
| 01_Swin | accuracy 87.3（= 论文报告值）| 一致（完全相同）|
| 02_MAE | accuracy 86.1（受控扰动 −1.7）| 不一致·中风险（相对 1.9%）|
| 03_ConvNeXt | accuracy 78.0（受控扰动 −3.5）| 不一致·高风险（绝对差 ≥ 2）|
| 04_DeiT | accuracy 83.4（偏离 0.36%）| 一致（验证 ≤1% 容差）|
| 05_LoRA | accuracy 85.0（论文未声明该指标）| **未核验** |
| 06_ImprovedDDPM | loss 0.05（论文未声明该指标）| **未核验** |

**诚实声明**：真实场景里 results.json 应填「你自己跑出来的数字」。
本测试集里 02/03 刻意做了扰动、01/04 取了论文报告值 —— 这是**受控测试夹具**，
目的是覆盖判定分支；每个目录的 README.md 里都写明了这一点，不得当作真实复现结果。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")

# 名称 -> (arxiv 编号, github repo, 分支, results.json 内容, 性质说明)
SPEC = {
    "01_Swin": (
        "2103.14030", "microsoft/Swin-Transformer", "main",
        {"accuracy": 87.3},
        "**与论文报告值完全相同** —— 用于验证「一致」判定（值相等分支）"),
    "02_MAE": (
        "2111.06377", "facebookresearch/mae", "main",
        {"accuracy": 86.1},
        "**受控扰动**：论文报告 87.8%，此处填 86.1%（差 1.7 点 / 相对 1.9%）"
        "—— 用于验证「不一致 · 中风险」判定"),
    "03_ConvNeXt": (
        "2201.03545", "facebookresearch/ConvNeXt", "main",
        {"accuracy": 78.0},
        "**受控扰动**：论文报告 81.5%，此处填 78.0%（差 3.5 点 ≥ 2）"
        "—— 用于验证「不一致 · 高风险」判定"),
    "04_DeiT": (
        "2012.12877", "facebookresearch/deit", "main",
        {"accuracy": 83.4},
        "**受控邻近值**：论文报告 83.1%，此处填 83.4%（相对差异 0.36%）"
        "—— 用于验证「≤1% 视为一致」的容差规则"),
    "05_LoRA": (
        "2106.09685", "microsoft/LoRA", "main",
        {"accuracy": 85.0},
        "**论文未声明 accuracy** —— 用于验证「有实测结果但论文无可对照指标」"
        "时该维度应标「未核验」"),
    "06_ImprovedDDPM": (
        "2102.09672", "openai/improved-diffusion", "main",
        {"loss": 0.05},
        "**论文未声明 loss** —— 同上，验证「未核验」路径"),
}

README_TMPL = """# {name} —— 测试样本

## 文件

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `paper.pdf` | arXiv:{arxiv} | 官方论文 PDF（直接下载，未改动）|
| `code.zip` | GitHub `{repo}` @ `{branch}` | 官方代码仓库打包（直接下载，未改动）|
| `results.json` | **测试夹具** | 见下 |

## results.json 的性质（重要）

内容：`{json_body}`

{note}

> ⚠️ **真实场景里这个文件应填「你自己跑出来的数字」。** 本目录里的取值是
> **受控测试夹具**，仅为覆盖审计系统的判定分支而构造，**不是真实复现结果**，
> 不得用于任何论文或代码的评价。

## 已知的抽取观察

- 论文声明的结果指标：{declared}
"""

out_report = ["# Paper2Lab 测试集 v2 —— 说明", "",
              "每个样本一个子目录，统一三个文件分开存放：",
              "`paper.pdf`（论文）/ `code.zip`（代码）/ `results.json`（实测结果，测试夹具）。", "",
              "## 样本清单", "",
              "| 目录 | 论文 | 代码仓库 | results.json 的性质 |",
              "| --- | --- | --- | --- |"]

for name, (arx, repo, branch, body, note) in SPEC.items():
    d = ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    declared = ("accuracy（论文报告值见 `_result_evidence.md`）"
                if name not in ("05_LoRA", "06_ImprovedDDPM")
                else "（无）")
    (d / "README.md").write_text(
        README_TMPL.format(name=name, arxiv=arx, repo=repo, branch=branch,
                           json_body=json.dumps(body, ensure_ascii=False), note=note,
                           declared=declared),
        encoding="utf-8")
    print(f"✅ {name}: results.json + README.md")
    out_report.append(
        f"| `{name}` | arXiv:{arx} | `{repo}` | {note.split('——')[0].strip()} |")

out_report += ["", "## 诚实声明", "",
               "`results.json` 是**受控测试夹具**：其中 02/03 刻意做了扰动、01/04 取了论文报告值，",
               "目的是覆盖「结果一致性」的四种判定分支（一致 / 不一致·中 / 不一致·高 / 未核验）。",
               "**真实场景应填你自己跑出的数字**；本测试集的取值不得用于评价论文或代码。",
               "", "另见 `_download_report.md`（下载来源与校验）、"
               "`_survey.md`（抽到的参数与指标）、`_result_evidence.md`（结果指标出处回原文核实）。"]
(ROOT / "README.md").write_text("\n".join(out_report), encoding="utf-8")
print("\n" + "\n".join(out_report))
