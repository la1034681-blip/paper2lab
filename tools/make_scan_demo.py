"""扫描件样例生成——专门验证"图像通道"(视觉模型读图)链路。

构造:
- 论文 PDF: 把含超参数的"扫描页"做成图片再嵌入 PDF(文本层为空), 模拟扫描件/图片表格;
  页面上写的声明值: learning rate = 3e-5, batch size = 64, num epochs = 50, dropout = 0.3
- 代码 zip: 与论文不一致的实现值(lr 1e-4 / batch 32 / epochs 100), 用于验证读图后能否比对
- 伪造的"模型返回" JSON: 供无 key 环境做离线链路验证(PAPER2LAB_VISION_MOCK_FILE)
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
DEMO.mkdir(exist_ok=True)

PAPER_LINES = [
    "Supplementary Material (scanned)",
    "",
    "Training configuration",
    "learning rate = 3e-5",
    "batch size = 64",
    "num epochs = 50",
    "dropout = 0.3",
    "",
    "All models trained with a fixed seed.",
]

TRAIN_PY = """\
# -*- coding: utf-8 -*-
LEARNING_RATE = 1e-4
BATCH_SIZE = 32
EPOCHS = 100
DROPOUT = 0.3
import torch
torch.manual_seed(7)
"""

MOCK_VISION = {
    "params": [
        {"name": "learning rate", "value": "3e-5", "evidence_text": "learning rate = 3e-5"},
        {"name": "batch size", "value": "64", "evidence_text": "batch size = 64"},
        {"name": "num epochs", "value": "50", "evidence_text": "num epochs = 50"},
        {"name": "dropout", "value": "0.3", "evidence_text": "dropout = 0.3"},
    ]
}


def make_scan_pdf(path: Path) -> None:
    """先生成一张"扫描页"图片, 再作为整页图片放进 PDF(文本层为空)。"""
    tmp = fitz.open()
    page = tmp.new_page(width=595, height=842)
    y = 90
    for line in PAPER_LINES:
        if line:
            page.insert_text((70, y), line, fontsize=14)
        y += 34
    png = page.get_pixmap(dpi=150).tobytes("png")
    tmp.close()

    out = fitz.open()
    p2 = out.new_page(width=595, height=842)
    p2.insert_image(fitz.Rect(0, 0, 595, 842), stream=png)
    out.save(str(path))
    out.close()


def main() -> None:
    make_scan_pdf(DEMO / "scan_paper.pdf")
    with zipfile.ZipFile(DEMO / "scan_code.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("proj/train.py", TRAIN_PY)
    (DEMO / "vision_mock.json").write_text(
        json.dumps(MOCK_VISION, ensure_ascii=False, indent=2), encoding="utf-8")
    print("scan_paper.pdf / scan_code.zip / vision_mock.json written ->", DEMO)


if __name__ == "__main__":
    main()
