"""风险分级策略——集中一处, 每个等级都给出可解释的理由。

分级原则(答辩可讲):
    风险 = **该差异对"能否复现出论文结论"的影响**  ×  **证据的确凿程度**

一、参数重要性(按"取值变化会不会改变结论"分档, 域内已调优)
    - 高: learning rate / 模型架构 / 聚类数 / 杀伤半径 / 深弹数量 / 水平定位标准差 …
    - 中: batch size / epochs / optimizer / dataset / input size / seed / threshold …
    - 低: dropout / weight decay / momentum / warmup / scheduler / 深度下界 …

二、状态与风险的对应(关键: 不是"一律低"或"一律中")
    - **论文↔代码取值矛盾**(INCONSISTENT): 属"会直接导致复现失败", 按参数重要性定高/中/低;
      若代码存在多个候选取值(无法断定实际用的是哪个) → 降为低并说明。
    - **单边缺失**(代码有论文没写 / 论文有代码没找到): 属"记录完整性"问题, 风险按参数重要性
      降一档(重要参数→中: 他人无法照做; 次要参数→低: 代码里已有确定值可补齐)。
      例外: 论文未声明随机种子 → 低(代码固定了种子本身是加分项)。
    - **未固定随机性**(NOT_FIXED): 中 —— 结果不可稳定复现。
    - **运行时确定**(UNVERIFIABLE): 低 —— 程序不下判断, 但列入人工核查清单。
    - **内部不一致**: 论文侧多为分段叙述 → 低; 代码同一文件内自相矛盾(配置被覆盖) → 中。
    - **实验结果与论文指标不符**: 高 —— 最直接的复现失败信号。
"""

from __future__ import annotations

from .models import Risk, Status

# 参数重要性 -> 不一致时的风险等级(域内含数模参数)
MISMATCH_RISK: dict[str, Risk] = {
    "learning_rate": Risk.HIGH,
    "batch_size": Risk.MEDIUM,
    "epochs": Risk.MEDIUM,
    "iterations": Risk.MEDIUM,
    "optimizer": Risk.MEDIUM,
    "weight_decay": Risk.LOW,
    "momentum": Risk.LOW,
    "dropout": Risk.LOW,
    "warmup": Risk.LOW,
    "scheduler": Risk.LOW,
    "input_size": Risk.MEDIUM,
    "seed": Risk.MEDIUM,
    "dataset": Risk.MEDIUM,
    "model": Risk.HIGH,
    "num_clusters": Risk.HIGH,
    "threshold": Risk.MEDIUM,
    "sigma_xy": Risk.HIGH,
    "sigma_z": Risk.MEDIUM,
    "kill_radius": Risk.HIGH,
    "depth_est": Risk.MEDIUM,
    "min_depth": Risk.LOW,
    "num_bombs": Risk.HIGH,
}
_DEFAULT = Risk.MEDIUM

# 风险 -> 文字重要性
_TIER_ZH = {Risk.HIGH: "关键复现参数", Risk.MEDIUM: "重要参数", Risk.LOW: "次要参数"}


def importance(key: str) -> Risk:
    return MISMATCH_RISK.get(key, _DEFAULT)


def assess_risk(status: Status, key: str, *, side: str = "code",
                same_file: bool = False, is_result: bool = False,
                downgraded: bool = False) -> tuple[Risk, str]:
    """返回 (风险等级, 风险理由)。理由会直接显示在界面与报告里。"""
    imp = importance(key)
    tier = "实验结论指标" if is_result else _TIER_ZH[imp]

    if status == Status.INCONSISTENT:
        if is_result:
            return (Risk.HIGH, "实验结果指标与论文声明不符, 是复现失败最直接的信号")
        if downgraded:
            return (Risk.LOW,
                    "代码中存在多个候选取值, 本次只比对了默认/首选实现, "
                    "不足以断定实际使用值与论文矛盾")
        if imp == Risk.HIGH:
            return (Risk.HIGH,
                    f"{tier}({key})取值与论文矛盾 —— 会直接改变训练过程与结果, "
                    "是复现失败最常见的原因, 必须优先处理")
        if imp == Risk.MEDIUM:
            return (Risk.MEDIUM,
                    f"{tier}({key})取值与论文不一致 —— 可能影响收敛过程与指标可比性, 建议对齐")
        return (Risk.LOW, f"{tier}({key})取值与论文不一致 —— 对最终结论影响有限, 建议对齐")

    if status == Status.MISSING_IN_PAPER:
        if key == "seed":
            return (Risk.LOW, "论文未声明随机种子; 代码中已固定种子, 属加分项而非缺陷")
        if imp in (Risk.HIGH, Risk.MEDIUM):
            return (Risk.MEDIUM,
                    f"代码中实现了{tier}({key})但论文未声明取值 —— "
                    "他人无法照论文复现该设置, 属复现记录不完整(代码取值可作补齐依据)")
        return (Risk.LOW,
                f"论文未声明{tier}({key}) —— 属记录完整性问题; 代码中已有确定取值, 影响有限")

    if status == Status.MISSING_IN_CODE:
        if imp == Risk.LOW:
            return (Risk.LOW,
                    f"论文声明了{tier}({key})但代码中未见显式实现, 需确认是否由框架默认值提供")
        return (Risk.MEDIUM,
                f"论文声明的{tier}({key})在代码中未找到 —— 可能由外部配置注入, "
                "也可能确实遗漏; 建议人工确认后再判定")

    if status == Status.NOT_FIXED:
        return (Risk.MEDIUM,
                "论文要求固定随机性而代码未固定 —— 同代码多次运行结果会漂移, 无法稳定复现")

    if status == Status.UNVERIFIABLE:
        return (Risk.LOW,
                "代码中该取值由运行时变量或外部输入决定, 静态分析无法给出确定值 —— "
                "程序不下结论, 已列入人工核查清单")

    if status == Status.INTERNAL_INCONSISTENT:
        if side == "code":
            if same_file:
                return (Risk.MEDIUM,
                        "同一代码文件内该参数出现多个不同取值(配置被覆盖), 实际生效值不明确")
            return (Risk.LOW,
                    "多个文件中出现不同取值, 可能对应不同实验/模块, 未必是同一套配置")
        return (Risk.LOW,
                "论文内部多处表述不同(常见于分段叙述或灵敏度分析), 需人工确认是否同一实验")

    return (Risk.LOW, "")
