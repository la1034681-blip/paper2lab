# Paper2Lab 科研实验一致性审计报告

- 论文: **Lightweight Residual Networks for Small-Scale Image Classification**
- 审计时间: 2026-09-24 23:05
- 论文页数: 3　代码文件: 4 个 .py

---

## 复现就绪度: 88 / 100

| 维度 | 得分 |
| --- | --- |
| 环境一致性 | 100 |
| 数据一致性 | 92 |
| 参数一致性 | 77 |
| 实验记录完整度 | 100 |
| 结果一致性 | 70 |

**当前阻碍复现的主要因素**: Learning Rate、Result: accuracy、Result: loss

---

## 审计概览: 发现 5 项复现风险, 6 项一致

| 参数 | 论文 | 代码/实际 | 状态 | 风险 |
| --- | --- | --- | --- | --- |
| Learning Rate | `1e-4` | `0.001` | 🔴 不一致 | 高 |
| Result: accuracy | `94.3` | `91.7` | 🔴 不一致 | 高 |
| Result: loss | `0.21` | `0.38` | 🔴 不一致 | 高 |
| Dataset | `CIFAR-10 v2.1` | `v2.0` | 🔴 不一致 | 中 |
| Random Seed | `42` | `—` | 🟠 未固定 | 中 |
| Batch Size | `32` | `32` | 🟢 一致 | — |
| Dropout | `0.1` | `0.1` | 🟢 一致 | — |
| Epochs | `100` | `100` | 🟢 一致 | — |
| Optimizer | `Adam` | `Adam` | 🟢 一致 | — |
| LR Scheduler | `cosine annealing` | `cosine annealing` | 🟢 一致 | — |
| Weight Decay | `5e-4` | `0.0005` | 🟢 一致 | — |

---

## 逐项审计详情(含证据链)

### 🔴 Learning Rate — 不一致

- **论文证据**: Page 3 · 4. Training Setup
  > izer. The learning rate is set to 1e-4 with weight decay 5e-4. We use a batch size of 32 and train for 100 epochs. The
  - 声明值: `1e-4`
- **代码证据**: train.py:11
  > parser.add_argument("--lr", type=float, default=0.001)
  - 实现值: `0.001`
- **归一化对比**: `0.0001` ≠ `0.001`
- **风险等级**: 高　**置信**: 🟢 Confirmed(规则验证)

**AI 归因分析**: 学习率存在约 10 倍数量级差异, 会直接改变梯度下降步长与收敛轨迹, 通常导致最终精度与论文结果出现可观测偏差, 是最常见的复现失败诱因。成因多为代码默认值未按论文更新或沿用了其他实验配置。建议将训练脚本中的学习率修正为论文声明值后重新实验。

### 🔴 Result: accuracy — 不一致

- **论文证据**: Page 1 · Abstract
  > ur method achieves 94.3% accuracy on CIFAR-10 v2.1 with only 2.7M parameters. We describe the training setup in d
  - 声明值: `94.3`
- **代码证据**: 用户上传实验结果
  > accuracy = 91.7
  - 实现值: `91.7`
- **归一化对比**: `94.3` ≠ `91.7`
- **风险等级**: 高　**置信**: 🟢 Confirmed(规则验证)

**AI 归因分析**: 实际实验结果与论文声明值存在明显差距, 结合上方参数审计发现, 差异很可能源于训练配置不一致而非方法本身失效。建议先消除所有高风险参数差异, 再重新执行实验对比。

### 🔴 Result: loss — 不一致

- **论文证据**: Page 3 · 5. Experiments
  > The final test loss is 0.21. All results are averaged over 3 runs with the fixed seed.
  - 声明值: `0.21`
- **代码证据**: 用户上传实验结果
  > loss = 0.38
  - 实现值: `0.38`
- **归一化对比**: `0.21` ≠ `0.38`
- **风险等级**: 高　**置信**: 🟢 Confirmed(规则验证)

**AI 归因分析**: 实际实验结果与论文声明值存在明显差距, 结合上方参数审计发现, 差异很可能源于训练配置不一致而非方法本身失效。建议先消除所有高风险参数差异, 再重新执行实验对比。

### 🔴 Dataset — 不一致

- **论文证据**: Page 1 · Abstract
  > curacy on CIFAR-10 v2.1 with only 2.7M parameters. We describe the training setup in detail to support
  - 声明值: `CIFAR-10 v2.1`
- **代码证据**: dataset.py:3
  > DATASET_VERSION = "v2.0"
  - 实现值: `v2.0`
- **归一化对比**: `cifar-10v2.1` ≠ `v2.0`
- **风险等级**: 中　**置信**: 🟢 Confirmed(规则验证)

**AI 归因分析**: 数据集版本不一致意味着训练/评测样本分布可能不同, 指标不具备可比性, 会直接削弱复现结论的可信度。成因多为沿用了旧版数据或未记录版本。建议统一下载论文声明的数据集版本并核对校验信息。

### 🟠 Random Seed — 未固定

- **论文证据**: Page 3 · 4. Training Setup
  > he random seed is fixed to 42 for all experiments. We apply a cosine annealing learning rate scheduler. 5. Ex
  - 声明值: `42`
- **代码证据**: 未找到
- **风险等级**: 中　**置信**: 🟢 Confirmed(规则验证)

**AI 归因分析**: 论文要求固定随机种子而代码未固定, 数据打乱顺序与参数初始化每次运行都不同, 实验结果将无法稳定复现。成因多为开发阶段图省事省略了 seed 设置。建议在训练入口显式调用 torch.manual_seed 等固定种子。

### 🟢 Batch Size — 一致

- **论文证据**: Page 3 · 4. Training Setup
  > We use a batch size of 32 and train for 100 epochs. The random seed is fixed to 42 for all experiments. W
  - 声明值: `32`
- **代码证据**: train.py:12
  > parser.add_argument("--batch-size", type=int, default=32)
  - 实现值: `32`
- **归一化对比**: `32.0` = `32.0` ✓ 规则验证通过
- **风险等级**: —　**置信**: 🟢 Confirmed(规则验证)

### 🟢 Dropout — 一致

- **论文证据**: Page 2 · 3. Method
  > 32x32 and dropout 0.1 in the classifier head.
  - 声明值: `0.1`
- **代码证据**: train.py:23
  > dropout = 0.1
  - 实现值: `0.1`
- **归一化对比**: `0.1` = `0.1` ✓ 规则验证通过
- **风险等级**: —　**置信**: 🟢 Confirmed(规则验证)

### 🟢 Epochs — 一致

- **论文证据**: Page 3 · 4. Training Setup
  > of 32 and train for 100 epochs. The random seed is fixed to 42 for all experiments. We apply a cosine annealin
  - 声明值: `100`
- **代码证据**: train.py:13
  > parser.add_argument("--epochs", type=int, default=100)
  - 实现值: `100`
- **归一化对比**: `100.0` = `100.0` ✓ 规则验证通过
- **风险等级**: —　**置信**: 🟢 Confirmed(规则验证)

### 🟢 Optimizer — 一致

- **论文证据**: Page 3 · 4. Training Setup
  > using the Adam optimizer. The learning rate is set to 1e-4 with weight decay 5e-4. We use a batch size o
  - 声明值: `Adam`
- **代码证据**: train.py:30
  > optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
  - 实现值: `Adam`
- **归一化对比**: `adam` = `adam` ✓ 规则验证通过
- **风险等级**: —　**置信**: 🟢 Confirmed(规则验证)

### 🟢 LR Scheduler — 一致

- **论文证据**: Page 3 · 4. Training Setup
  > e apply a cosine annealing learning rate scheduler. 5. Experiments Our method achieves 94.3% top-1 accuracy on the CIFAR-10 test s
  - 声明值: `cosine annealing`
- **代码证据**: train.py:31
  > scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
  - 实现值: `cosine annealing`
- **归一化对比**: `cosine annealing` = `cosine annealing` ✓ 规则验证通过
- **风险等级**: —　**置信**: 🟢 Confirmed(规则验证)

### 🟢 Weight Decay — 一致

- **论文证据**: Page 3 · 4. Training Setup
  > 1e-4 with weight decay 5e-4. We use a batch size of 32 and train for 100 epochs. The random seed is fixed t
  - 声明值: `5e-4`
- **代码证据**: train.py:22
  > weight_decay = 5e-4
  - 实现值: `0.0005`
- **归一化对比**: `0.0005` = `0.0005` ✓ 规则验证通过
- **风险等级**: —　**置信**: 🟢 Confirmed(规则验证)

---

## 审计说明

本报告由 Paper2Lab 自动生成。一致性判断由程序化规则验证完成(AST 静态分析 + 数值归一化比对), AI 仅负责风险解释与归因。本期审计范围为可自动验证的数值/配置一致性, 语义级方法审计属于产品路线图。