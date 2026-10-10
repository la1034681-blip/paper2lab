"""边缘情况测试集生成——专门验证交叉审查防线是否真的生效。

构造一个"问题代码包", 内含:
- 语法错误的 .py (验证: 失败示众, 不再静默跳过)
- MATLAB .m 文件 (验证: 识别到但明确告知不支持)
- 带 BOM 的 .py (验证: 编码兼容)
- notebook .ipynb (验证: code cell 被解析)
- 错位抽取诱饵 lr = 2024 (验证: 合理性校验拒收)
- 内部矛盾: train.py lr=0.001 vs config 里 lr=0.0001 (验证: 代码内部不一致)

论文侧使用 demo/paper.pdf 即可(其中声明 lr=1e-4)。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo" / "edge_code.zip"

TRAIN_PY = '''\
# -*- coding: utf-8 -*-
LEARNING_RATE = 0.001
BATCH_SIZE = 32
EPOCHS = 100
optimizer = "Adam"
import torch
torch.manual_seed(0)
'''

BROKEN_PY = '''\
def train(
    lr=1e-4
    print("this file has a syntax error")
'''

MATLAB_M = '''\
% MATLAB 实现(本期不支持分析)
lr = 0.0001;
batch_size = 32;
'''

BOM_PY = '\ufeff# -*- coding: utf-8 -*-\nweight_decay = 0.0005\n'

NOTEBOOK = {
    "cells": [
        {"cell_type": "markdown", "source": ["# 训练配置"]},
        {"cell_type": "code", "source": [
            "# 与论文声明保持一致\n",
            "dropout = 0.1\n",
            "warmup_epochs = 5\n",
            "lr = 2024  # 诱饵: 超出学习率先验范围, 应被合理性校验拒收\n",
        ]},
    ],
    "metadata": {},
    "nbformat": 4,
    "nbformat_minor": 5,
}

CONFIG_JSON = {"train": {"learning_rate": 0.0001, "batch_size": 32}}


def main():
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("edge/train.py", TRAIN_PY)
        zf.writestr("edge/broken.py", BROKEN_PY)
        zf.writestr("edge/matlab_solver.m", MATLAB_M)
        zf.writestr("edge/bom_file.py", BOM_PY)
        zf.writestr("edge/notebook.ipynb", json.dumps(NOTEBOOK, ensure_ascii=False))
        zf.writestr("edge/config.json", json.dumps(CONFIG_JSON))
        zf.writestr("edge/requirements.txt", "torch==2.1\nnumpy>=1.24\n")
    print("edge_code.zip written ->", OUT)


if __name__ == "__main__":
    main()
