# Paper2Lab 科研实验一致性审计报告

- 论文: **Lightweight Residual Networks for Small-Scale Image Classification**
- 审计时间: 2026-09-26 00:01
- 论文页数: 3　代码文件: 4 个(含 notebook cell)
- 本次审计可信度: **高**(得分 100/100)

---

## 复现就绪度: 80 / 100

> 就绪度评价**被审对象**的可复现程度; 审计可信度评价**本次审计过程**的覆盖与可靠程度, 两者独立。

| 维度 | 得分 |
| --- | --- |
| 环境一致性 | 100 |
| 数据一致性 | 92 |
| 参数一致性 | 69 |
| 实验记录完整度 | 60 |
| 结果一致性 | 100 |

**当前阻碍复现的主要因素**: Learning Rate、Dataset、Model Architecture

---

## 解析覆盖与审计可信度

| 项目 | 数值 |
| --- | --- |
| 论文文本可解析页 | 3 / 3 |
| 其中薄页(图表/公式/扫描区) | 0 |
| 论文参数种类覆盖 | 6 / 9 类(67%) |
| 文中疑似声明句式(参考) | 3 处, 结构化 7 处 |
| 代码文件成功解析 | 4 / 4 |
| 代码文件解析失败 | 0 |
| 多语言通用通道(非 Python) | 0 个文件 |
| 图像/扫描区域 | 0 个(图像通道未启用) |
| 文件格式无法处理 | 0 个 |

**论文提到但未取到数值的参数种类**: Model Architecture、Optimizer、LR Scheduler

---

## 审计概览: 发现 4 项复现风险, 6 项一致

| 参数 | 论文 | 代码/实际 | 状态 | 风险 | 自证 |
| --- | --- | --- | --- | --- | --- |
| Learning Rate | `1e-4` | `0.001` | 🔴 不一致 | 高 | ✅ |
| Dataset | `CIFAR-10` | `v2.0` | 🔴 不一致 | 中 | ✅ |
| Model Architecture | `ResNet-18` | `—` | 🟡 代码未找到 | 中 | ✅ |
| Random Seed | `42` | `—` | 🟠 未固定 | 中 | ✅ |
| Batch Size | `32` | `32` | 🟢 一致 | — | ✅ |
| Dropout | `0.1` | `0.1` | 🟢 一致 | — | ✅ |
| Epochs | `100` | `100` | 🟢 一致 | — | ✅ |
| Optimizer | `Adam` | `Adam` | 🟢 一致 | — | ✅ |
| LR Scheduler | `cosine annealing` | `CosineAnnealingLR` | 🟢 一致 | — | ✅ |
| Weight Decay | `5e-4` | `0.0005` | 🟢 一致 | — | ✅ |

---

## 逐项审计详情(含证据链)

本节对全部 10 项审计发现逐条给出: 结论释义 · 双侧证据(论文页码·章节 / 代码文件:行号 · 原文片段) · 比对过程 · 证据自证 · 人工核查建议。

### 🔴 Learning Rate — 不一致

**结论释义**: 论文声明值与代码实现值经归一化后不相等——这是本次审计的核心风险, 通常会导致实验无法复现出论文指标。

**风险等级**: 高　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 3 · 4. Training Setup`
  > izer. The learning rate is set to 1e-4 with weight decay 5e-4. We use a batch size of 32 and train for 100 epochs. The
  - 声明值: `1e-4`　归一化后: `0.0001`
- **代码侧证据**: `train.py:11`
  > parser.add_argument("--lr", type=float, default=0.001)
  - 实现值: `0.001`　归一化后: `0.001`

#### 比对过程

- 归一化对比: `0.0001` ≠ `0.001` → 判定 **不一致**(差异见上表原文, 可直接复算)

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 建议人工确认以哪一侧为准: 先看代码是否为论文对应的实验配置, 再决定修改代码还是修正论文描述。

**AI 归因分析**: 学习率存在约 10 倍数量级差异, 会直接改变梯度下降步长与收敛轨迹, 通常导致最终精度与论文结果出现可观测偏差, 是最常见的复现失败诱因。成因多为代码默认值未按论文更新或沿用了其他实验配置。建议将训练脚本中的学习率修正为论文声明值后重新实验。

---

### 🔴 Dataset — 不一致

**结论释义**: 论文声明值与代码实现值经归一化后不相等——这是本次审计的核心风险, 通常会导致实验无法复现出论文指标。

**风险等级**: 中　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 3 · 5. Experiments`
  > cy on the CIFAR-10 test set. The final test loss is 0.21. All results are averaged over 3 runs wit
  - 声明值: `CIFAR-10`　归一化后: `cifar-10`
- **代码侧证据**: `dataset.py:3`
  > DATASET_VERSION = "v2.0"
  - 实现值: `v2.0`　归一化后: `v2.0`

#### 比对过程

- 归一化对比: `cifar-10` ≠ `v2.0` → 判定 **不一致**(差异见上表原文, 可直接复算)

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 建议人工确认以哪一侧为准: 先看代码是否为论文对应的实验配置, 再决定修改代码还是修正论文描述。

**AI 归因分析**: 数据集版本不一致意味着训练/评测样本分布可能不同, 指标不具备可比性, 会直接削弱复现结论的可信度。成因多为沿用了旧版数据或未记录版本。建议统一下载论文声明的数据集版本并核对校验信息。

---

### 🟡 Model Architecture — 代码未找到

**结论释义**: 论文明确声明了该参数, 但静态扫描未在代码中找到对应实现(既非命名赋值也非内联判定)。可能由框架默认值/外部配置注入, 或确实被遗漏。

**风险等级**: 中　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 2 · 3. Method`
  > llows the ResNet-18 architecture with width multiplier 0.5. We use input size 32x32 and dropout 0.1
  - 声明值: `ResNet-18`　归一化后: `resnet-18`
- **代码侧证据**: 未找到(静态扫描未命中)

#### 比对过程

- 论文侧有值、代码侧无证据 → 标记为 **代码未找到**(中风险, 需人工确认)

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 建议在训练入口显式声明该参数并与论文对齐; 若确认由框架默认值提供, 请在论文/README 中注明。

**AI 归因分析**: 论文明确声明了该参数, 但静态扫描未在代码中找到对应实现(既非命名赋值也非内联判定)。可能原因: 代码使用了框架默认值、参数由外部配置注入, 或该设置确实被遗漏。建议在代码中显式声明并与论文对齐, 以保证复现时取值可追溯。

---

### 🟠 Random Seed — 未固定

**结论释义**: 论文要求固定该随机性来源, 但代码中未找到固定动作, 实验结果不可稳定复现。

**风险等级**: 中　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 3 · 4. Training Setup`
  > he random seed is fixed to 42 for all experiments. We apply a cosine annealing learning rate scheduler. 5. Ex
  - 声明值: `42`　归一化后: `42.0`
- **代码侧证据**: 未找到(静态扫描未命中)

#### 比对过程

- 论文要求固定随机性、代码无固定动作 → 标记为 **未固定**

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 建议在训练入口显式固定随机种子(如 torch.manual_seed / random_state)。

**AI 归因分析**: 论文要求固定随机种子而代码未固定, 数据打乱顺序与参数初始化每次运行都不同, 实验结果将无法稳定复现。成因多为开发阶段图省事省略了 seed 设置。建议在训练入口显式调用 torch.manual_seed 等固定种子。

---

### 🟢 Batch Size — 一致

**结论释义**: 论文声明值与代码实现值经归一化后相等, 规则验证通过。

**风险等级**: —　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 3 · 4. Training Setup`
  > We use a batch size of 32 and train for 100 epochs. The random seed is fixed to 42 for all experiments. W
  - 声明值: `32`　归一化后: `32.0`
- **代码侧证据**: `train.py:12`
  > parser.add_argument("--batch-size", type=int, default=32)
  - 实现值: `32`　归一化后: `32.0`

#### 比对过程

- 归一化对比: `32.0` = `32.0` → 判定 **一致**(规则验证通过)

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 无需人工干预; 如需引用可将本项作为「已核对」证据。

---

### 🟢 Dropout — 一致

**结论释义**: 论文声明值与代码实现值经归一化后相等, 规则验证通过。

**风险等级**: —　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 2 · 3. Method`
  > 32x32 and dropout 0.1 in the classifier head.
  - 声明值: `0.1`　归一化后: `0.1`
- **代码侧证据**: `train.py:23`
  > dropout = 0.1
  - 实现值: `0.1`　归一化后: `0.1`

#### 比对过程

- 归一化对比: `0.1` = `0.1` → 判定 **一致**(规则验证通过)

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 无需人工干预; 如需引用可将本项作为「已核对」证据。

---

### 🟢 Epochs — 一致

**结论释义**: 论文声明值与代码实现值经归一化后相等, 规则验证通过。

**风险等级**: —　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 3 · 4. Training Setup`
  > of 32 and train for 100 epochs. The random seed is fixed to 42 for all experiments. We apply a cosine annealin
  - 声明值: `100`　归一化后: `100.0`
- **代码侧证据**: `train.py:13`
  > parser.add_argument("--epochs", type=int, default=100)
  - 实现值: `100`　归一化后: `100.0`

#### 比对过程

- 归一化对比: `100.0` = `100.0` → 判定 **一致**(规则验证通过)

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 无需人工干预; 如需引用可将本项作为「已核对」证据。

---

### 🟢 Optimizer — 一致

**结论释义**: 论文声明值与代码实现值经归一化后相等, 规则验证通过。

**风险等级**: —　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 3 · 4. Training Setup`
  > using the Adam optimizer. The learning rate is set to 1e-4 with weight decay 5e-4. We use a batch size o
  - 声明值: `Adam`　归一化后: `adam`
- **代码侧证据**: `train.py:30`
  > optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
  - 实现值: `Adam`　归一化后: `adam`

#### 比对过程

- 归一化对比: `adam` = `adam` → 判定 **一致**(规则验证通过)

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 无需人工干预; 如需引用可将本项作为「已核对」证据。

---

### 🟢 LR Scheduler — 一致

**结论释义**: 论文声明值与代码实现值经归一化后相等, 规则验证通过。

**风险等级**: —　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 3 · 4. Training Setup`
  > e apply a cosine annealing learning rate scheduler. 5. Experiments Our method achieves 94.3% top-1 accuracy on the CIFAR-10 test s
  - 声明值: `cosine annealing`　归一化后: `cosine annealing`
- **代码侧证据**: `train.py:31`
  > scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
  - 实现值: `CosineAnnealingLR`　归一化后: `cosine annealing`

#### 比对过程

- 归一化对比: `cosine annealing` = `cosine annealing` → 判定 **一致**(规则验证通过)

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 无需人工干预; 如需引用可将本项作为「已核对」证据。

---

### 🟢 Weight Decay — 一致

**结论释义**: 论文声明值与代码实现值经归一化后相等, 规则验证通过。

**风险等级**: —　**置信**: 🟢 Confirmed(规则验证)　**证据自证**: ✅ 通过

#### 证据链

- **论文侧证据**: `Page 3 · 4. Training Setup`
  > 1e-4 with weight decay 5e-4. We use a batch size of 32 and train for 100 epochs. The random seed is fixed t
  - 声明值: `5e-4`　归一化后: `0.0005`
- **代码侧证据**: `train.py:22`
  > weight_decay = 5e-4
  - 实现值: `0.0005`　归一化后: `0.0005`

#### 比对过程

- 归一化对比: `0.0005` = `0.0005` → 判定 **一致**(规则验证通过)

#### 证据自证与人工核查

- 证据自证: ✅ 通过——原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现
- **人工核查建议**: 无需人工干预; 如需引用可将本项作为「已核对」证据。

---

---

## 需人工核查清单(2 项)

以下条目无法由程序单方面给出确定结论, 或存在未参与审计的内容 —— 系统**不假装都已审过**, 请按下表逐项人工确认:

| 级别 | 类别 | 对象 | 原因 | 建议动作 |
| --- | --- | --- | --- | --- |
| 中 | 论文提到但未取到数值 | model、optimizer、scheduler | 论文正文出现过这些参数词, 但未匹配到数值(可能以表格/公式/图片给出) | 翻原文对应表格或公式, 人工补录后再比对代码 |
| 中 | 论文声明但代码未找到 | Model Architecture | 论文声明 `ResNet-18`, 静态扫描未在代码中找到对应实现 | 确认该设置是否由框架默认值/外部配置注入, 或确实被遗漏 |

---

## 未参与本次审计的部分(1 项)

审计结论只覆盖**已成功解析**的内容; 以下部分未参与比对, 不应被视为「已核对」:

- **论文提到但未取到数值的参数种类**: Model Architecture、Optimizer、LR Scheduler

---

## 审计自检(证据自证与结论回放)

- 校验发现数: 10
- 自证通过: 10
- 自证未通过: 0

全部结论均通过证据自证与结论复算: 每条证据的原文片段中确实包含所声明的值, 且一致性结论可由归一化比较复现。

---

## 附录: 程序比较日志

所有一致性判定均由程序完成, 以下为完整比较记录(可逐条复核):

```text
[比较] batch_size: 归一化后 32.0 == 32.0 (Page 3 · 4. Training Setup vs train.py:12) -> CONSISTENT
[比较] dataset: 归一化后 cifar-10 != v2.0 (Page 3 · 5. Experiments vs dataset.py:3) -> INCONSISTENT
[比较] dropout: 归一化后 0.1 == 0.1 (Page 2 · 3. Method vs train.py:23) -> CONSISTENT
[比较] epochs: 归一化后 100.0 == 100.0 (Page 3 · 4. Training Setup vs train.py:13) -> CONSISTENT
[比较] learning_rate: 归一化后 0.0001 != 0.001 (Page 3 · 4. Training Setup vs train.py:11) -> INCONSISTENT
[比较] model: 论文声明 ResNet-18 @ Page 2 · 3. Method, 代码未找到 -> MISSING_IN_CODE
[比较] optimizer: 归一化后 adam == adam (Page 3 · 4. Training Setup vs train.py:30) -> CONSISTENT
[比较] scheduler: 归一化后 cosine annealing == cosine annealing (Page 3 · 4. Training Setup vs train.py:31) -> CONSISTENT
[比较] seed: 论文声明 42 @ Page 3 · 4. Training Setup, 代码无固定证据 -> NOT_FIXED
[比较] weight_decay: 归一化后 0.0005 == 0.0005 (Page 3 · 4. Training Setup vs train.py:22) -> CONSISTENT
```

---

## 审计说明

本报告由 Paper2Lab 自动生成。一致性判断由程序化规则验证完成(AST 静态分析 + 数值归一化比对), AI 仅负责风险解释与归因。报告中的每一条结论都经过: ① 合理性先验校验(拒收错位抽取) ② 证据自证(原文片段必须包含所声明的值) ③ 结论复算(归一化比较可重现)。本期审计范围为可自动验证的数值/配置一致性, 语义级方法审计属于产品路线图。