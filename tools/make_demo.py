"""生成受控 Demo 数据(诚实声明: 为验证系统审计能力构造的受控样例)。

产出:
  demo/paper.pdf      —— 演示论文(Training Setup: lr=1e-4, bs=32, 100 epochs, Adam, seed 42, CIFAR-10 v2.1, acc 94.3%)
  demo/project.zip    —— 演示代码(埋 3 个已知问题: lr=1e-3、seed 未固定、数据集 v2.0)
  demo/results.json   —— 用户"跑完"的实验结果(acc 91.7)
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import fitz  # PyMuPDF

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"

PAPER_TEXT_PAGES = [
    # Page 1
    [
        "Lightweight Residual Networks for Small-Scale Image Classification",
        "",
        "Abstract",
        ("We propose a lightweight residual network for small-scale image "
         "classification. Our method achieves 94.3% accuracy on CIFAR-10 v2.1 "
         "with only 2.7M parameters. We describe the training setup in detail "
         "to support reproducibility."),
        "",
        "1. Introduction",
        ("Deep residual networks have achieved remarkable success in image "
         "classification. However, reproducing published results remains a "
         "challenge due to incomplete training details."),
    ],
    # Page 2
    [
        "2. Related Work",
        ("ResNet and its variants form the backbone of modern image "
         "classification systems. Wide ResNets and DenseNets further improve "
         "accuracy at the cost of additional parameters."),
        "",
        "3. Method",
        ("Our network follows the ResNet-18 architecture with width "
         "multiplier 0.5. We use input size 32x32 and dropout 0.1 in the "
         "classifier head."),
    ],
    # Page 3
    [
        "4. Training Setup",
        ("We train all models on CIFAR-10 v2.1 using the Adam optimizer. "
         "The learning rate is set to 1e-4 with weight decay 5e-4. "
         "We use a batch size of 32 and train for 100 epochs. "
         "The random seed is fixed to 42 for all experiments. "
         "We apply a cosine annealing learning rate scheduler."),
        "",
        "5. Experiments",
        ("Our method achieves 94.3% top-1 accuracy on the CIFAR-10 test set. "
         "The final test loss is 0.21. All results are averaged over 3 runs "
         "with the fixed seed."),
    ],
]

TRAIN_PY = '''"""Demo training script (受控样例, 故意埋了 3 个问题)."""
import argparse

import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=100)
    return parser.parse_args()


def main():
    args = parse_args()
    lr = 0.001  # 论文声明 1e-4, 这里是 1e-3 (问题1: 差 10 倍)
    batch_size = 32
    epochs = 100
    weight_decay = 5e-4
    dropout = 0.1

    dataset = load_dataset("CIFAR-10", version="v2.0")  # 问题3: 论文是 v2.1
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    model = build_resnet18(dropout=dropout)
    # 问题2: 论文声明 seed 固定为 42, 但代码里没有 torch.manual_seed
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    for epoch in range(epochs):
        train_one_epoch(model, loader, optimizer)
        scheduler.step()


if __name__ == "__main__":
    main()
'''

DATASET_PY = '''"""Dataset loading helpers."""

DATASET_VERSION = "v2.0"


def load_dataset(name, version=DATASET_VERSION):
    print(f"loading {name} {version}")
    return []
'''

MODEL_PY = '''"""Model definition."""
import torch.nn as nn


def build_resnet18(dropout=0.1):
    return nn.Sequential(nn.Flatten(), nn.Linear(3072, 10), nn.Dropout(dropout))
'''

UTILS_PY = '''"""Training utilities."""


def train_one_epoch(model, loader, optimizer):
    for x, y in loader:
        optimizer.zero_grad()
        loss = model(x).sum()
        loss.backward()
        optimizer.step()
'''

REQUIREMENTS = """torch>=2.1
torchvision>=0.16
numpy>=1.24
"""

RESULTS = {"accuracy": 91.7, "loss": 0.38}


def _wrap(line: str, width: int = 78) -> list[str]:
    """按页宽折行, 防止 insert_text 绘制超出页面右边界导致文本被裁剪。"""
    if len(line) <= width:
        return [line]
    words, out, cur = line.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out


def make_pdf(path: Path):
    doc = fitz.open()
    for lines in PAPER_TEXT_PAGES:
        page = doc.new_page()
        y = 72
        for line in lines:
            for seg in _wrap(line):
                page.insert_text((72, y), seg, fontsize=10)
                y += 16
    doc.save(str(path))
    doc.close()


def make_zip(path: Path):
    files = {
        "demo_project/train.py": TRAIN_PY,
        "demo_project/dataset.py": DATASET_PY,
        "demo_project/model.py": MODEL_PY,
        "demo_project/utils.py": UTILS_PY,
        "demo_project/requirements.txt": REQUIREMENTS,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def main():
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    make_pdf(DEMO_DIR / "paper.pdf")
    make_zip(DEMO_DIR / "project.zip")
    (DEMO_DIR / "results.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print("demo data generated:")
    for p in ("paper.pdf", "project.zip", "results.json"):
        print(" -", DEMO_DIR / p)


if __name__ == "__main__":
    main()
