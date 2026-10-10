"""生成"可上线"的最小部署目录 `deploy/` —— 只装线上真正需要的东西。

为什么要单独生成一份, 而不是把整个工程推上去:
  工程根目录里有 519MB 的 .venv、6.4MB 的文档流水线、1MB 归档、以及 40 多个
  只在本地跑回归的脚本（它们硬编码了本机测试集路径）。**推上去只会拖慢构建、
  甚至因为体积被平台拒绝**，而线上应用一个都不需要它们。

上线只需四样: app.py + paper2lab/ + demo/(3 个文件) + requirements.txt
（外加 .streamlit/config.toml 与一份带平台元信息的 README）。

用法: .venv\\Scripts\\python.exe make_deploy.py
产物: deploy/（内容即"要推送到 GitHub / Hugging Face 的仓库根目录"）
"""
from __future__ import annotations

import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "deploy"

# 线上必须有的文件（相对路径 -> 是否保留目录结构）
COPY_FILES = [
    "app.py",
    "requirements.txt",
    ".streamlit/config.toml",
]
# 演示数据只带"内置演示数据"用到的三个文件（D题/E题/扫描件那几份大文件是本地回归用的）
COPY_DEMO = ["demo/paper.pdf", "demo/project.zip", "demo/results.json"]
# 引擎代码整目录带走
COPY_DIRS = ["paper2lab"]

README = """---
title: Paper2Lab 复现一致性审计
emoji: 🔬
colorFrom: blue
colorTo: indigo
sdk: streamlit
sdk_version: 1.36.0
app_file: app.py
pinned: false
---

# Paper2Lab · 论文复现一致性审计智能体

把「论文说了什么 / 代码在跑什么 / 实测得到什么」三方交叉核验，给出**每条都能回溯出处**
的结论：每个值都能追到 `文件:行号` 或 `Page N`，拿不准的一律如实说"未取到 / 未核验"。

**一句话设计原则：确定性的判定交给程序，需要取舍的提议交给 AI，否决权留在程序手里。**

- 审计流水线 **12 环节 / 10 件工具**，每一站可调度、可跳过、可留痕
- 一致性判定由规则引擎完成（可复算）；AI 只负责"哪些环节不值得跑"与"多候选里选哪个"，
  且必须通过**与确定性通道完全相同**的机械闸门
- **拒绝是一门正式能力**：补丁设六道闸门，任一不过就写明理由拒绝（只展示、绝不落盘）

## 本仓库说明

本仓库是**可上线的裁剪版**：只含应用本体（`app.py` + `paper2lab/`）、内置演示数据与依赖清单。

## 配置（在平台 Secrets 里设置，勿写进代码）

| 键 | 用途 | 必须 |
| --- | --- | --- |
| `PAPER2LAB_ACCESS_CODE` | 访问口令（评审凭口令进入；**不设则无门**，公开链接相当于对所有人开放） | 建议 |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | **模型 API**：任意 OpenAI 兼容模型，负责归因解释 / 排计划 / 补丁提议 | 建议 |
| `VISION_API_KEY` / `VISION_BASE_URL` / `VISION_MODEL` | 视觉读图（**仅在模型本身不能读图时才需要**） | 可选 |

关于模型 API 的两条硬规则：

- **Key 与 Base URL 必须成对填写**：程序**不按 key 前缀猜端点**（猜错会连到错误地址，
  且每个读图区域都要重试等待，表现为"极慢"甚至像卡死，很难看出根因）。
- 模型**自带读图（多模态）** → 无需配视觉通道，读图直接复用模型 API；
  模型是**单模态**的 → 不配视觉通道就**读不了图**，界面会如实提示，
  图片/表格/扫描页不参与审计（未读区域会列在「审计可信度」页）。

`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` 是**向后兼容的老名字**，仍可识别
（新名字优先）。

不配 AI 相关键也能跑：系统会**如实回退规则版**并在界面标注"AI 未生效"，不会假装排过。

## 免责与边界

只审"配置是否一致"，不判断方法本身好不好；论文没给的一律不猜；不从曲线图反推数值；
不替使用者跑训练。工具输出为审计结论与复现清单，**不构成对论文有效性的评价**。
"""


def main() -> int:
    made: list[str] = []
    OUT.mkdir(parents=True, exist_ok=True)

    # ① 单文件
    for rel in COPY_FILES:
        src = HERE / rel
        if not src.exists():
            print(f"  ! 缺文件: {rel}")
            continue
        dst = OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        made.append(rel)

    # ② 演示数据（只带用到的三个）
    for rel in COPY_DEMO:
        src = HERE / rel
        if src.exists():
            dst = OUT / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            made.append(f"{rel}（{src.stat().st_size / 1024:.0f} KB）")
        else:
            print(f"  ! 缺演示文件: {rel}")

    # ③ 引擎目录
    for d in COPY_DIRS:
        src = HERE / d
        if not src.is_dir():
            print(f"  ! 缺目录: {d}/")
            continue
        dst = OUT / d
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in sorted(src.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            rel = f.relative_to(src)
            t = dst / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, t)
            n += 1
        made.append(f"{d}/（{n} 个 .py）")

    # ④ README 与部署专用 .gitignore
    (OUT / "README.md").write_text(README, encoding="utf-8")
    made.append("README.md")
    (OUT / ".gitignore").write_text(
        "# 平台密钥模板之外的一切本地文件都不该进仓库\n"
        ".streamlit/secrets.toml\n"
        "__pycache__/\n*.pyc\ncache/\n.env\n", encoding="utf-8")
    made.append(".gitignore")
    (OUT / ".streamlit" / "secrets.toml.example").write_text(
        '# 本地调试用：复制成 .streamlit/secrets.toml（该文件已被 .gitignore 排除）\n'
        'PAPER2LAB_ACCESS_CODE = "给评委的邀请码"\n'
        '# —— 模型 API（任意 OpenAI 兼容模型）：Key 与 Base URL 成对填写 ——\n'
        'LLM_API_KEY = "sk-..."\n'
        'LLM_BASE_URL = "https://api.deepseek.com"\n'
        'LLM_MODEL = "deepseek-chat"\n'
        '# —— 视觉读图：仅在"模型本身不能读图"时才需要，同样成对填写 ——\n'
        '# VISION_API_KEY = "..."\n'
        '# VISION_BASE_URL = "https://..."\n'
        '# VISION_MODEL = "..."\n'
        '# 兼容老名字（仍可识别，新名字优先）：DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL\n',
        encoding="utf-8")
    made.append(".streamlit/secrets.toml.example")

    # ⑤ 清掉不该留在 deploy/ 里的东西（多为上次生成后残留）
    keep = {"app.py", "requirements.txt", "README.md", ".gitignore"}
    removed = 0
    for p in sorted(OUT.rglob("*"), reverse=True):
        if p.is_dir() or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(OUT).as_posix()
        if rel in keep or rel.startswith("paper2lab/") or rel == "demo/paper.pdf" \
                or rel == "demo/project.zip" or rel == "demo/results.json" \
                or rel.startswith(".streamlit/"):
            continue
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass

    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print("=== deploy/ 已生成 ===")
    for m in made:
        print("  +", m)
    if removed:
        print(f"  - 清掉 {removed} 个残留文件")
    print(f"  合计 {total / 1024 / 1024:.2f} MB @ {OUT}")
    print("\n下一步：把 deploy/ 里的内容作为仓库根目录推送到 GitHub / Hugging Face。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
