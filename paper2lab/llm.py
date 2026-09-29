"""LLM 归因层——DeepSeek API + 缓存兜底 + Mock 模式。

架构原则(评审定稿): "确定性问题交给程序验证, 复杂归因交给 AI"。
LLM 只负责对已确认的 Finding 生成风险解释与归因, 不参与判断。

可靠性三保险:
1. temperature=0 + 超时 + 重试
2. 结果按 prompt 哈希缓存到 cache/llm_cache.json, API 故障直接用缓存
3. 无 API key 或调用失败 -> Mock 模板生成, 演示永不中断
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

from .models import Finding, Status
from .shards import DEFAULT_MAX_WORKERS, run_sharded

CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "llm_cache.json"

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEEPSEEK_MODEL = "deepseek-chat"

_STATUS_ZH = {
    Status.INCONSISTENT: "不一致",
    Status.MISSING_IN_CODE: "代码中未找到",
    Status.MISSING_IN_PAPER: "论文中未声明",
    Status.NOT_FIXED: "未固定",
    Status.UNVERIFIABLE: "代码中以变量动态确定, 静态分析无法验证",
    Status.INTERNAL_INCONSISTENT: "同一载体内部多处声明互不一致",
    Status.CONSISTENT: "一致",
}


# ---------------------------------------------------------------- 缓存

def _load_cache() -> dict:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except Exception:
        pass


def _cache_key(prompt: str, mode: str) -> str:
    """缓存键带模式前缀: Mock 与真实 API 的结果不互相污染。

    (早期版本用同一个键, 导致先跑 Mock 后配 key 时命中 Mock 文本,
     看起来像"DeepSeek 没生效"。)
    """
    return hashlib.sha256(f"{mode}\x00{prompt}".encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------- Prompt

def _build_prompt(f: Finding) -> str:
    paper_side = "论文中未找到该参数声明" if f.paper is None else (
        f"论文声明: {f.paper.raw_value}(出处: {f.paper.location}, 原文: \"{f.paper.snippet}\")")
    code_side = "代码中未找到该参数" if f.code is None else (
        f"代码实现: {f.code.raw_value}(位置: {f.code.location}, 代码: \"{f.code.snippet}\")")
    return (
        "你是科研实验复现审计助手。以下审计发现已由程序化规则验证确认, "
        "不需要你判断真伪, 请只做风险解释与归因。\n\n"
        f"参数: {f.display_name}\n"
        f"审计状态: {_STATUS_ZH.get(f.status, f.status.value)}\n"
        f"风险等级: {f.risk.value}\n"
        f"{paper_side}\n"
        f"{code_side}\n\n"
        "请用 2-3 句中文回答:\n"
        "1) 该差异对实验复现的具体影响;\n"
        "2) 最可能的成因;\n"
        "3) 一句可执行的修复建议。\n"
        "只输出纯文本, 不要标题、不要 markdown、不要客套话。"
    )


# ---------------------------------------------------------------- Mock 模板

_MOCK_TEMPLATES = {
    "learning_rate": (
        "学习率存在{magnitude}差异, 会直接改变梯度下降步长与收敛轨迹, "
        "通常导致最终精度与论文结果出现可观测偏差, 是最常见的复现失败诱因。"
        "成因多为代码默认值未按论文更新或沿用了其他实验配置。"
        "建议将训练脚本中的学习率修正为论文声明值后重新实验。"
    ),
    "seed": (
        "论文要求固定随机种子而代码未固定, 数据打乱顺序与参数初始化每次运行都不同, "
        "实验结果将无法稳定复现。成因多为开发阶段图省事省略了 seed 设置。"
        "建议在训练入口显式调用 torch.manual_seed 等固定种子。"
    ),
    "dataset": (
        "数据集版本不一致意味着训练/评测样本分布可能不同, 指标不具备可比性, "
        "会直接削弱复现结论的可信度。成因多为沿用了旧版数据或未记录版本。"
        "建议统一下载论文声明的数据集版本并核对校验信息。"
    ),
    "_default": (
        "该参数与论文声明不一致, 可能使实际训练配置偏离论文设定, "
        "从而影响复现结果的可比性。成因多为代码默认值未同步论文更新。"
        "建议按论文声明值修正后重新运行实验验证。"
    ),
}

# 结果类 finding 的模板
_MOCK_RESULT = (
    "实际实验结果与论文声明值存在明显差距, 结合上方参数审计发现, "
    "差异很可能源于训练配置不一致而非方法本身失效。"
    "建议先消除所有高风险参数差异, 再重新执行实验对比。"
)

# 动态确定(变量引用)类 finding 的模板
_MOCK_UNVERIFIABLE = (
    "该参数在代码中以变量形式动态确定(非硬编码字面量), 静态分析无法验证其运行时取值。"
    "这本身不是错误, 但意味着论文声明值与代码实际值的一致性需要运行时核对。"
    "建议在代码中打印该参数的运行日志, 或将其值写入配置文件以便追溯。"
)


# 内部不一致类 finding 的模板
_MOCK_INTERNAL = (
    "同一载体内部对该参数的表述/实现存在多个不同值, 这是一条由交叉审查(多处声明互查)"
    "自动发现的问题。若两处差异并非出自灵敏度分析或分组实验的刻意设置, "
    "则说明该载体的参数表述不自洽, 会直接影响复现时的取值判断。"
    "建议先明确唯一口径, 再统一正文、附录与代码中的取值。"
)


# 代码未声明/找不到时的模板
_MOCK_MISSING_IN_CODE = (
    "论文明确声明了该参数, 但静态扫描未在代码中找到对应实现(既非命名赋值也非内联判定)。"
    "可能原因: 代码使用了框架默认值、参数由外部配置注入, 或该设置确实被遗漏。"
    "建议在代码中显式声明并与论文对齐, 以保证复现时取值可追溯。"
)

# 论文未声明时的模板
_MOCK_MISSING_IN_PAPER = (
    "代码中给出了该参数的实现值, 但论文未作声明(或仅在正文中泛泛提及而未给出取值)。"
    "这属于实验记录完整度问题: 读者仅凭论文无法还原该设置, 必须翻阅代码。"
    "建议在实验设置章节补齐声明, 提升论文自身的可复现性。"
)


def _mock_analysis(f: Finding) -> str:
    if f.param_key.startswith("result_"):
        return _MOCK_RESULT
    if f.status == Status.UNVERIFIABLE:
        return _MOCK_UNVERIFIABLE
    if f.status == Status.INTERNAL_INCONSISTENT:
        return _MOCK_INTERNAL
    if f.status == Status.MISSING_IN_CODE:
        return _MOCK_MISSING_IN_CODE
    if f.status == Status.MISSING_IN_PAPER:
        return _MOCK_MISSING_IN_PAPER
    tpl = _MOCK_TEMPLATES.get(f.param_key, _MOCK_TEMPLATES["_default"])
    magnitude = ""
    try:
        pv, cv = float(f.paper.normalized), float(f.code.normalized)
        if pv and cv and pv != cv:
            ratio = max(pv, cv) / min(pv, cv)
            magnitude = f"约 {ratio:g} 倍数量级" if ratio >= 5 else ""
    except (TypeError, ValueError, AttributeError):
        pass
    return tpl.format(magnitude=magnitude)


# ---------------------------------------------------------------- DeepSeek 调用

def _deepseek_model() -> str:
    """模型名优先取 .env 的 DEEPSEEK_MODEL(调用时读取, 不受导入顺序影响)。"""
    from .envfile import get
    return get("DEEPSEEK_MODEL") or _DEEPSEEK_MODEL


def _call_deepseek(prompt: str, api_key: str, max_tokens: int = 300) -> str:
    from openai import OpenAI

    from .envfile import get
    client = OpenAI(api_key=api_key,
                    base_url=get("DEEPSEEK_BASE_URL") or _DEEPSEEK_BASE_URL,
                    timeout=30)
    resp = client.chat.completions.create(
        model=_deepseek_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


# ---------------------------------------------------------------- 一次性 JSON 问答
# 给"不是归因"的两处用（2026-09-28）:
#   · 规划器 `planner`（让 AI 排计划）—— mode="plan"
#   · 补丁的「LLM 提议 + 程序盖章」通道 —— mode="patch"
# 与归因共用**同一份缓存**（省调用、可复现），但**不共用**降级模板：
# 这里拿不到 JSON 就返回 None，由调用方**回退确定性路径**（规则版计划 / 拒绝），
# 绝不编一个假计划出来。
_aux_lock = threading.Lock()


def _extract_json(text: str) -> Optional[dict]:
    """从模型回复里抠出 JSON（容忍 ```json 围栏与前后废话）。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1] if "```" in t[3:] else t[3:]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(t[i:j + 1])
    except Exception:      # noqa: BLE001
        return None
    return obj if isinstance(obj, dict) else None


def ask_json(prompt: str, api_key: str, *, mode: str = "aux",
             max_tokens: int = 800, force_mock: bool = False) -> tuple:
    """一次性的 JSON 问答，返回 `(dict 或 None, 说明)`。**绝不抛异常。**

    调用方口径：拿不到（None）就回退确定性路径，并把说明如实写进日志/报告 ——
    "AI 这次没参与"本身是要告诉用户的信息，不是静默失败。
    """
    # ⚠️ force_mock 必须**优先于缓存**（2026-09-29 修）:
    # 它的语义是"完全确定性、绝不调外部"。原来把缓存检查放在它前面,
    # 于是"离线测试会不会回退"取决于**之前有没有真跑过一次**（缓存里有 = AI 参与过）
    # —— 测试因此时好时坏，是典型的 flaky。强制离线就该直接回退，不看缓存。
    if force_mock:
        return None, f"AI（{mode}）· 强制离线（force_mock），回退确定性路径"
    key = _cache_key(prompt, mode)
    with _aux_lock:
        cache = _load_cache()
    if key in cache:
        obj = _extract_json(cache[key]) if isinstance(cache[key], str) else None
        if obj is not None:
            return obj, f"AI（{mode}）· 缓存命中"
    if not api_key:
        return None, f"AI（{mode}）· 未配置 LLM，回退确定性路径"

    # 为什么允许**一次**重试（2026-09-29 实测）:
    #   真实调用会偶发返回非 JSON —— 那多半不是"模型不会写 JSON"，而是服务端回了
    #   限流/异常文案（实测：同一个 prompt 连跑 3 次全成功，但此前有一次就是这种失败）。
    #   这类抖动重试一次就能过去。**API 层异常（鉴权/网络）不重试** —— 那种重试也是白费。
    #   重试必须**如实说出来**（"第 2 次尝试才成功"），不能假装一次就成。
    text, last_note = "", "未调用"
    for attempt in (1, 2):
        try:
            text = _call_deepseek(prompt, api_key, max_tokens=max_tokens)
        except Exception as ex:      # noqa: BLE001
            return None, (f"AI（{mode}）· 调用失败（{type(ex).__name__}）"
                          "，回退确定性路径")
        obj = _extract_json(text)
        if obj is not None:
            with _aux_lock:
                cache = _load_cache()
                cache[key] = text
                _save_cache(cache)
            return obj, (f"AI（{mode}）· 真实调用"
                         + ("" if attempt == 1 else "（第 2 次尝试才成功）"))
        last_note = "返回不是合法 JSON"

    # 失败必须带上**返回片段**：只报"不是合法 JSON"会把排查方向带偏
    # —— 真实原因可能是限流 / 余额 / 服务异常，那些文案本来就不是 JSON，看片段一眼能分清。
    head = re.sub(r"\s+", " ", text or "").strip()[:140]
    detail = f"（返回片段：{head}）" if head else "（返回为空）"
    return None, f"AI（{mode}）· {last_note}{detail}，回退确定性路径"



# ---------------------------------------------------------------- 对外接口

class LLMAnalyzer:
    """归因分析器: 自动选择 真实API -> 缓存 -> Mock 三级降级。"""

    def __init__(self, api_key: Optional[str] = None, force_mock: bool = False):
        from .envfile import get
        # 走 envfile: 兼容 .env 与系统环境变量(CLI 入口不必自己 load_env)
        self.api_key = api_key or get("DEEPSEEK_API_KEY")
        self.force_mock = force_mock
        self.cache = _load_cache()
        self.mode = "mock"
        self.last_error = ""      # 真实 API 失败原因(界面如实提示)
        self.failed_calls = 0
        self.real_calls = 0       # 成功调用真实 API 的次数
        self.cache_hits = 0       # 命中缓存的条数(不产生 API 费用)
        # 分片并发(第二期第四批)下的共享资源保护: cache / 计数 / mode 都会被多线程碰
        self._lock = threading.Lock()
        self.shard_report: dict = {}
        if not force_mock and self.api_key:
            self.mode = "deepseek"

    def analyze(self, f: Finding) -> str:
        """为单条 Finding 生成归因文字(只处理非一致项)。"""
        if f.status == Status.CONSISTENT:
            f.ai_analysis = ""
            f.confidence = f.confidence  # 保持 Confirmed
            return ""

        prompt = _build_prompt(f)
        with self._lock:
            mode = self.mode
        key = _cache_key(prompt, mode)

        # 1) 缓存命中(加锁: 分片并发下 cache 会被多个线程同时读写)
        with self._lock:
            if key in self.cache:
                f.ai_analysis = self.cache[key]
                self.cache_hits += 1
                return f.ai_analysis

        # 2) 真实 API
        if self.mode == "deepseek":
            last_err: Optional[Exception] = None
            for _ in range(3):  # 重试 3 次
                try:
                    text = _call_deepseek(prompt, self.api_key)
                    if text:
                        with self._lock:      # 写缓存+落盘必须互斥, 否则并发下会互相覆盖
                            self.cache[key] = text
                            _save_cache(self.cache)
                            self.real_calls += 1
                        f.ai_analysis = text
                        return text
                except Exception as e:  # noqa: BLE001
                    last_err = e
            # API 彻底失败, 落 Mock 保底(演示不中断)。失败原因记在实例上供界面提示。
            with self._lock:
                self.last_error = (f"{type(last_err).__name__}: {last_err}"
                                   if last_err else "未知错误")
                self.failed_calls += 1
                if self.failed_calls == 1:
                    self.mode = "fallback"    # 真实 API 不可用, 后续走模板

        # 3) Mock 保底(模板确定性输出, 不写缓存以免污染真实 API 的缓存)
        text = _mock_analysis(f)
        f.ai_analysis = text
        return text

    def analyze_all(self, findings: list[Finding], *,
                    max_workers: int = DEFAULT_MAX_WORKERS) -> int:
        """批量归因, 返回生成条数。

        第二期第四批: 由**串行**改为**分片并发**。每片仍是一条独立调用
        (prompt 里只有这一条的证据, 上下文互不干扰), 因此"拆分 - 各自处理 - 汇总"
        只改变调度方式, **不改变任何结论**; 结果**保序**, 与串行逐字一致。
        """
        todo = [f for f in findings if f.status != Status.CONSISTENT]
        if not todo:
            self.shard_report = {"label": "AI 归因", "mode": "serial", "total": 0,
                                 "done": 0, "failed": 0, "workers": 1,
                                 "seconds": 0.0, "failures": []}
            return 0
        _, report = run_sharded(todo, lambda i, f: self.analyze(f),
                                max_workers=max_workers, label="AI 归因")
        self.shard_report = report.to_dict()
        return len(todo)
