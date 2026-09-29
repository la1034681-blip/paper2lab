"""参数同义词表与数值归一化——对齐引擎的基础设施。

设计原则(评审定稿): 正则/规则能算的绝不让 LLM 自由发挥。
"""

from __future__ import annotations

import re
from typing import Any, Optional

# ---------------------------------------------------------------- 同义词表
# canonical_key -> (展示名, [别名...])
# 别名全部小写; 匹配时对文本/变量名做归一化后比较。

PARAM_SYNONYMS: dict[str, tuple[str, list[str]]] = {
    "learning_rate": (
        "Learning Rate",
        ["lr", "learning_rate", "learning rate", "learningrate",
         "base_lr", "eta", "init_lr", "initial_lr", "lr_init", "lrate",
         "learning_rate_init", "学习率"],
    ),
    "batch_size": (
        "Batch Size",
        ["batch_size", "batch size", "batchsize", "batch",
         "bs", "train_batch_size", "per_device_train_batch_size", "n_rand",
         "mini_batch", "mini batch", "mini-batch", "minibatch",
         "批大小", "批量大小", "批量"],
    ),
    "epochs": (
        "Epochs",
        ["epochs", "epoch", "num_epochs", "n_epochs", "n_epoch", "max_epochs",
         "num_train_epochs", "training epochs", "nb_epochs", "total_epochs",
         "迭代次数", "迭代轮数", "训练轮数", "轮次", "训练次数"],
    ),
    "iterations": (
        "训练迭代次数",
        ["iterations", "iteration", "n_iter", "n_iters", "num_iter", "num_iters",
         "max_iter", "max_iters", "max_steps", "train_steps", "num_steps",
         "total_steps", "training steps", "iteration steps", "训练迭代", "迭代步数"],
    ),
    "optimizer": (
        "Optimizer",
        ["optimizer", "optim", "solver", "优化器"],
    ),
    "weight_decay": (
        "Weight Decay",
        ["weight_decay", "weight decay", "wd", "weightdecay", "l2_reg",
         "weight_decay_rate", "weight decay rate", "权重衰减"],
    ),
    "momentum": (
        "Momentum",
        ["momentum", "beta1", "beta_1", "momentum_factor", "动量"],
    ),
    "dropout": (
        "Dropout",
        ["dropout", "dropout_rate", "drop rate", "drop_prob", "drop"],
    ),
    "seed": (
        # 注意: **不含裸词 "rng"**。实测(真实论文回读) D题 p27/p29 出现伪代码
        # "Y = rng.normal(0.0, sigma, N)" / "def sample_Z(rng, N): u = rng",
        # 其中 rng 是**变量名**(随机数生成器对象), 不是种子参数 —— 裸词命中后
        # 会把分布均值 0.0、公式编号 29 误当种子。需要 "RNG seed" 这类完整写法
        # 才认定为该参数("rng_seed" 已在列表中)。
        "Random Seed",
        ["seed", "random_seed", "random seed", "manual_seed", "rng_seed",
         "random_state", "随机种子", "随机数种子"],
    ),
    "dataset": (
        "Dataset",
        ["dataset", "data_set", "dataset_name", "dataset_version", "data",
         "数据集"],
    ),
    "model": (
        "Model Architecture",
        ["model", "arch", "architecture", "backbone", "net", "模型",
         "model_name", "architecture_name", "backbone_name", "net_name",
         "model_type", "网络结构"],
    ),
    "input_size": (
        "Input Size",
        ["input_size", "image_size", "img_size", "crop_size", "resolution",
         "输入尺寸", "图像尺寸"],
    ),
    "warmup": (
        "Warmup",
        ["warmup", "warmup_epochs", "warmup_steps"],
    ),
    "scheduler": (
        "LR Scheduler",
        ["scheduler", "lr_scheduler", "lr schedule", "学习率调度"],
    ),
    "num_clusters": (
        "Cluster Count K",
        ["n_clusters", "num_clusters", "n clusters", "n_clusters_",
         "聚类数", "聚类个数", "簇数", "聚类簇数", "k值", "k 值"],
    ),
    "threshold": (
        "Threshold",
        ["threshold", "thresh", "阈值", "判决阈值", "判定阈值", "判别阈值"],
    ),
    # ---- 数值仿真/数学建模常用物理参数
    "sigma_xy": (
        "水平定位标准差 σ",
        ["sigma_xy", "水平定位标准差", "水平坐标定位标准差",
         "水平误差标准差", "水平定位误差标准差"],
    ),
    "sigma_z": (
        "深度定位标准差 σ_z",
        ["sigma_z", "深度定位标准差", "深度误差标准差", "深度定位误差标准差"],
    ),
    "kill_radius": (
        "杀伤半径 R",
        ["kill_radius", "杀伤半径"],
    ),
    "depth_est": (
        "深度定位值 h₀",
        ["depth_est", "深度定位值", "中心深度定位值", "深度估计值"],
    ),
    "min_depth": (
        "深度下界 l",
        ["min_depth", "深度下界", "实际深度下界"],
    ),
    "num_bombs": (
        "深弹数量",
        ["num_bombs", "投弹数量", "深弹数量", "深弹枚数"],
    ),
}

# canonical_key <- alias 的反向索引
ALIAS_TO_KEY: dict[str, str] = {}
for _key, (_disp, _aliases) in PARAM_SYNONYMS.items():
    ALIAS_TO_KEY[_key] = _key
    for _a in _aliases:
        ALIAS_TO_KEY[_a] = _key


def canonical_key(name: str) -> Optional[str]:
    """把任意写法归一到 canonical 参数名; 不认识返回 None。"""
    if not name:
        return None
    n = normalize_name(name)
    return ALIAS_TO_KEY.get(n)


def normalize_name(name: str) -> str:
    """参数名归一化: 小写、去前后缀、下划线/空格/连字符统一。"""
    n = name.strip().lower()
    n = re.sub(r"^args\.", "", n)
    n = re.sub(r"[\-_]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    # 下划线与空格等价: 两种形态都试
    return n


# 同时索引"空格形态"和"下划线形态"
for _key, (_disp, _aliases) in list(PARAM_SYNONYMS.items()):
    for _a in _aliases:
        ALIAS_TO_KEY.setdefault(_a.replace("_", " "), _key)
        ALIAS_TO_KEY.setdefault(_a.replace(" ", "_"), _key)


def display_name(key: str) -> str:
    entry = PARAM_SYNONYMS.get(key)
    return entry[0] if entry else key


# ---------------------------------------------------------------- 合理性先验范围
# 抽到的值超出范围 -> 大概率是错位抽取(如把年份 2024 当成学习率), 拒收并示众。
# (下界, 上界, 是否要求整数); None 表示不校验。

PLAUSIBLE_RANGES: dict[str, tuple[Optional[float], Optional[float], bool]] = {
    "learning_rate": (0.0, 1.0, False),
    "batch_size": (1, 1_000_000, True),
    "epochs": (1, 100_000, True),
    "iterations": (1, 100_000_000, True),
    "weight_decay": (0.0, 1.0, False),
    "momentum": (0.0, 1.0, False),
    "dropout": (0.0, 1.0, False),
    "warmup": (0, 100_000, True),
    "num_clusters": (2, 10_000, True),
    "threshold": (0.0, 1.0, False),
    "seed": (0, 2**63, True),
    "sigma_xy": (0.0, 100_000, False),
    "sigma_z": (0.0, 100_000, False),
    "kill_radius": (0.0, 10_000, False),
    "depth_est": (0.0, 12_000, False),
    "min_depth": (0.0, 12_000, False),
    "num_bombs": (1, 10_000, True),
    # input_size 上限收紧到 2048: 分辨率/序列长度基本不超过它。
    # 实测(2026-09-28, ConvNeXt): 原文 "resolution is 224²" 的**上标 2 被文本层压平**成
    # "2242", 于是抽到 2242 —— 靠语义守卫拦不住(上下文确实是"分辨率"), 只能靠上限兜住。
    "input_size": (8, 2048, True),
}


def is_plausible(key: str, value: Any) -> Optional[bool]:
    """值是否在该参数的领域先验范围内。无先验或无法解析返回 None(不干预)。"""
    rng = PLAUSIBLE_RANGES.get(key)
    if rng is None:
        return None
    v = normalize_number(value)
    if v is None:
        return None
    lo, hi, is_int = rng
    if lo is not None and v < lo:
        return False
    if hi is not None and v > hi:
        return False
    if is_int and abs(v - round(v)) > 1e-9:
        return False
    return True


# ---------------------------------------------------------------- 数值归一化

_NUM_RE = re.compile(
    r"""^[+-]?(
        \d+\.?\d*([eE][+-]?\d+)?      # 123 / 1.5 / 1e-4 / 1E-04
        |\.\d+([eE][+-]?\d+)?         # .5
    )$""",
    re.VERBOSE,
)


# 上标数字 + 各种"排版减号"都要还原成 ASCII。
# 论文里 10^-4 常排成 10−4, 那个减号是 U+2212（排版减号）, 既不是 ASCII 的 '-',
# 也不是上标的 '⁻'(U+207B) —— 不还原就会被判"无法解析", 进而把**相等的值报成不一致**。
# 实测（2026-09-27）: DETR 论文 10−4 与代码 0.0001 本应相等, 却因缺这个映射被报成"不一致"。
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻−–—", "0123456789----")
# 常见数量级后缀(仅大写 K/M/G/B 与 k; 不收小写 m/b —— 与"米/毫"冲突)
_SCALE_SUFFIX = {"k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "B": 1e9}


def normalize_number(raw: Any) -> Optional[float]:
    """把 '1e-4' / '0.0001' / '1E-04' / 32 / '94.3%' / '500K' / '10^-4' / '10⁻⁴' / '1,500' 统一成 float。

    归一化后比较: 1e-4 == 0.0001 == 10^-4 == 1×10⁻⁴ 为 True。无法解析返回 None。
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    is_percent = s.endswith("%")
    if is_percent:
        s = s[:-1].strip()
    # 上标写法: 10⁻⁴ -> 10^-4
    s = s.translate(_SUPERSCRIPT)
    # 千分位: "1,500" -> "1500"。
    # 只在**完整匹配千分位形态**时才去逗号, 避免把 "Smith, 2020" 这类逗号当分隔符处理。
    # 实测(2026-09-28, Swin 论文): "linear warmup of 1,500 iterations" —— 数值正则若不
    # 支持千分位, 只会匹配到 "1", warmup 被抽成 1。
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
        s = s.replace(",", "")
    # a×10^b / a x 10^-b
    m = re.match(r"^([\d.]+)\s*[×xX*]\s*10\s*\^?\s*([-−]?\d+)$", s.replace(" ", ""))
    if m:
        try:
            return float(m.group(1)) * (10.0 ** int(m.group(2)))
        except (ValueError, OverflowError):
            return None
    # 10^-b 形式(题干里的科学计数法)
    m = re.match(r"^10\s*\^?\s*([-−]?\d+)$", s.replace(" ", ""))
    if m:
        try:
            return 10.0 ** int(m.group(1))
        except (ValueError, OverflowError):
            return None
    # 数量级后缀: 500K / 1.5M / 2B
    m = re.match(r"^([\d.]+)\s*([kKMGB])$", s)
    if m:
        try:
            return float(m.group(1)) * _SCALE_SUFFIX[m.group(2)]
        except (ValueError, KeyError):
            return None
    if not _NUM_RE.match(s):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    # 百分数统一按 0-100 口径, 不缩放
    return v


def numbers_equal(a: Any, b: Any, rel_tol: float = 1e-9) -> Optional[bool]:
    """归一化比较两个数值。任一无法解析返回 None(交给上层按字符串比)。"""
    fa, fb = normalize_number(a), normalize_number(b)
    if fa is None or fb is None:
        return None
    if fa == fb:
        return True
    if fa == 0.0 or fb == 0.0:
        return False
    return abs(fa - fb) / max(abs(fa), abs(fb)) <= rel_tol


def values_equal(a: Any, b: Any) -> bool:
    """通用值比较: 先数值归一化, 退化为规范化字符串比较。"""
    ne = numbers_equal(a, b)
    if ne is not None:
        return ne
    sa = re.sub(r"[\s_\-]+", "", str(a).strip().lower())
    sb = re.sub(r"[\s_\-]+", "", str(b).strip().lower())
    return sa == sb
