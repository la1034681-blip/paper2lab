"""抽取 Agent 的工具集（第一期）。

设计约束（与确定性内核保持一致）:
1. **工具只"提议"候选，绝不写入结论**——候选必须通过 agent.gate() 才能入库；
2. 每个工具声明自身成本（是否消耗 LLM/视觉调用），供上层做预算控制；
3. 返回结构固定为 ToolResult{ok, candidate, cost, note}，人和模型都能读；
4. 证据必须是**原文逐字片段**，供 gate 回原文核对。

工具阶梯（从便宜到贵）:
  text-l1  同句 + 紧邻（如 "100K iterations"）：零成本、高精度
  text-l2  同句 + 近距离（如 "Our 32 × 32 models ... resolutions"）：零成本、中精度
  negation 论文明确"不使用该参数"（如 "Without dropout"）→ 记为 0
  llm      LLM 提议取值 + **程序回原文核对**：1 次 LLM 调用
  vision   对提到该参数的页读图 + 双次取交集：2 次视觉调用/区域
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .paper_parser import (_NUM_B, _SENTENCE_RE, _alias_re, _in_table_run,
                           _FALLBACK_CONNECTOR_END as _CONNECTOR_END)
from .synonyms import PARAM_SYNONYMS, is_plausible

# ---------------------------------------------------------------- 数据结构


@dataclass
class Candidate:
    """一个"候选取值"——由工具提议，能否入库由 gate 决定。"""
    key: str
    value: str
    evidence_text: str = ""     # 原文逐字片段（供回原文核对）
    page: int = 0
    source: str = ""            # 工具名
    parser: str = "agent-text"  # 入库后的抽取通道标记
    note: str = ""
    note_only: bool = False     # True = 只作提示, 不作为取值入库(如否定式表述)


@dataclass
class ToolResult:
    ok: bool = False
    candidate: Optional[Candidate] = None
    cost: dict = field(default_factory=lambda: {"llm_calls": 0, "vision_calls": 0,
                                                "seconds": 0.0})
    note: str = ""


# ---------------------------------------------------------------- 公共小工具

# 数字与别名之间只允许出现这些字符（分隔符/单位），否则不算"紧邻"
_SEP_ONLY = re.compile(r"^[\s×xX*\-–—/·]*[kKmMbB]?[\s×xX*\-–—/·]*$")
# 否定义（"no dropout" / "without dropout" / "不使用 dropout"）
# 中文侧只认明确的"不使用类"表述: 不能用裸"无"——"从无误差到含误差"会被误判(实测噪音)
_NEGATION = re.compile(
    r"\b(no|not|without|never|none|free\s+of|omit\w*|disable\w*)\b"
    r"|不使用|未使用|没有使用|未采用|不采用|未引入|未添加|不添加|无需|不含",
    re.IGNORECASE)
# 否定词必须紧邻参数名(否则容易跨句误判)
_NEG_WINDOW = 18
# 特殊形状守卫: 某些参数必须出现特定形状, 否则视为误解（如 input_size 必须有 N×N）
_SHAPE_GUARD: dict[str, re.Pattern] = {
    "input_size": re.compile(r"\d+\s*[×xX*]\s*\d+"),
}
# 区间守卫: "100–300k iterations" 是收敛范围, 不是训练设置 -> 不算取值
_RANGE_TAIL = re.compile(r"^\s*[-–—~]\s*\d")
_RANGE_HEAD = re.compile(r"[-–—~]\s*$")
# 频率守卫: "divided by 2 every 20 epochs" 是调度周期, 不是总轮数 -> 不算取值
_FREQUENCY = re.compile(r"\b(every|per|each|once\s+every)\b|每", re.IGNORECASE)
# 语义反转陷阱: "dropout with keep ratio 0.7" 里的 0.7 是**保留率**,
# 等价 dropout rate = 0.3 —— 回原文核对抓不到这种错(证据里确实有 0.7), 必须显式拦下。
_SEMANTIC_TRAP: dict[str, re.Pattern] = {
    "dropout": re.compile(r"keep[\s_-]?(?:ratio|prob|probability)|保留率|keep_?prob",
                          re.IGNORECASE),
}
# 区间/范围: "100–300k iterations" 是收敛范围(实际观测), 不是训练设置
_RANGE_IN_VALUE = re.compile(r"[-–—~]")
# 中文编号守卫: "图2 模型" / "表3 参数" 里的数字是编号, 不是取值
_CN_NUMBERING = re.compile(r"[图表式第条]\s*$")
# 数字截断守卫: "8_000_000" 里抓到的 "8" 只是大数的一段(下一字符是 _ 或 ,+数字)
_NUM_CONTINUATION = re.compile(r"^[_,]\d")
# 文本型参数(模型/数据集/优化器/调度器)的值必须含字母——纯数字一定是编号误抓
_TEXT_VALUED = {"optimizer", "scheduler", "dataset", "model"}
_NEAR_CHARS = 45        # level-2 允许的"近距离"上限

# 分布采样调用守卫: "Y = rng.normal(0.0, sigma, N)" 里的 0.0 是**分布的均值**,
# 不是训练设置。实证来源(真实论文回读):
#   · D题 p27 "Y = rng.normal(0.0, sigma, N)" —— 变量名 rng 命中 seed 的别名,
#     0.0 被误当成随机种子(该论文真正的种子在代码里是 np.random.default_rng(2026))。
# 注意只否决**采样函数**的实参; `np.random.seed(42)` / `default_rng(42)` 这类
# "设置型"调用的实参**就是**取值, 必须放过, 所以 seed / default_rng 不在名单里。
_DIST_FN = re.compile(
    r"\b(normal|standard_normal|randn|rand|random|random_sample|uniform|"
    r"randint|choice|permutation|binomial|poisson|beta|gamma|exponential|"
    r"multivariate_normal|dirichlet|laplace|logistic|weibull|shuffle)\s*$",
    re.IGNORECASE)


def _inside_dist_call(before: str) -> bool:
    """数值前的这段文字, 是否正处于某个**分布采样调用**的实参列表内。

    只看末尾一小段: 从右往左找第一个未闭合的 '(' , 判断被调方是不是采样函数。
    例: "Y = rng.normal(" -> True ; "np.random.seed(" -> False 。
    """
    seg = (before or "")[-48:]
    depth = 0
    for i in range(len(seg) - 1, -1, -1):
        ch = seg[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                return bool(_DIST_FN.search(seg[:i]))
            depth -= 1
    return False


def _num_re() -> re.Pattern:
    return re.compile(_NUM_B)


def _alive(seconds: float, deadline: float) -> bool:
    return time.time() < deadline


# ---------------------------------------------------------------- 工具 1/2: 文本加宽扫描


def tool_text_scan(kind: str, page_texts: list, level: int = 1) -> ToolResult:
    """在正文里找"参数与数值相邻"的写法。level 1 严格紧邻, level 2 放宽距离。"""
    t0 = time.time()
    aliases = PARAM_SYNONYMS.get(kind, (kind, []))[1]
    num = _num_re()
    guard = _SHAPE_GUARD.get(kind)

    for page_no, text in page_texts:
        for sm in _SENTENCE_RE.finditer(text):
            sent = sm.group(0)
            for a in aliases:
                for am in _alias_re(a).finditer(sent):
                    # ---- 后向: 别名之后紧邻数值 "dropout rate ... to 0.1" 已由内核句式覆盖,
                    #      这里只补"更宽"的写法, 避免与内核重复
                    # ---- 前向: 数值在别名之前 "100K iterations" / "32 × 32 models"
                    head = sent[max(0, am.start() - _NEAR_CHARS): am.start()]
                    nums = list(num.finditer(head))
                    if not nums:
                        continue
                    nm = nums[-1]                       # 离别名最近的那个数
                    gap = head[nm.end():]
                    if level == 1 and not _SEP_ONLY.match(gap):
                        continue                        # 中间还有别的词 -> 不算紧邻
                    if level == 2 and num.search(gap):
                        continue                        # 数字与别名之间又出现数字 -> 不可信
                    # level 2 放宽了"中间不能有别的词", 于是会把**与本参数无关的数字**拉进来。
                    # 实证(2026-09-28, DeiT p12): "…calculate the average time over 30 runs to
                    # process that batch" —— 别名 `batch` 回看 45 字抓到了 `30`, 而那是**计时轮数**,
                    # 不是批大小(该句根本没有给出批大小)。
                    # 收紧为: 数字必须**由连接词挂到参数名上**(与内核 `_FALLBACK_CONNECTOR_END`
                    # 同一口径) —— gap 的结尾须是 of / with / = / : / 为 / 是 这类连接词。
                    # 这条把 level 2 从"同句里有个数就算"收成"数是为这个参数写的"。
                    if level == 2 and not _CONNECTOR_END.search(gap):
                        continue
                    if _NEGATION.search(head[max(0, nm.start() - 25): nm.start()]):
                        continue                        # 前面是否定语境 -> 不是取值
                    # 区间守卫: "100–300k iterations" 是收敛范围, 不是取值
                    if _RANGE_HEAD.search(head[:nm.start()]) or _RANGE_TAIL.match(gap):
                        continue
                    val = nm.group(0)
                    if _RANGE_IN_VALUE.search(val):
                        continue                        # 取值本身是区间 -> 不算确定取值
                    # 编号守卫: "图2 模型" / "表3" 里的数字是编号, 不是取值
                    if _CN_NUMBERING.search(head[:nm.start()]):
                        continue
                    # 数字截断守卫: "8_000_000" 里的 8 只是大数的一段
                    if _NUM_CONTINUATION.match(gap + " "):
                        continue
                    # 文本型参数不接受纯数字(段落编号 6.1 / 图号 2 都是误抓)
                    if kind in _TEXT_VALUED and not re.search(r"[A-Za-z]", val):
                        continue
                    # 分布参数守卫: "rng.normal(0.0, sigma, N)" 里的 0.0 是分布均值, 不是取值
                    if _inside_dist_call(head[:nm.start()]):
                        continue
                    # 频率守卫: "every 20 epochs" 是调度周期, 不是总轮数
                    if _FREQUENCY.search(head[max(0, nm.start() - 30): nm.start()]):
                        continue
                    if is_plausible(kind, val) is False:
                        continue
                    ev = sent
                    if guard and not guard.search(ev):
                        continue                        # 形状守卫不满足
                    return ToolResult(
                        ok=True,
                        candidate=Candidate(
                            key=kind, value=val, evidence_text=ev, page=page_no,
                            source=f"text-l{level}",
                            note=("数值紧邻参数名" if level == 1 else "数值在本句内近距离出现")),
                        cost={"llm_calls": 0, "vision_calls": 0,
                              "seconds": time.time() - t0})
    return ToolResult(ok=False, cost={"llm_calls": 0, "vision_calls": 0,
                                      "seconds": time.time() - t0},
                      note="正文里没有「参数名与数值相邻」的写法")


def tool_negation(kind: str, page_texts: list) -> ToolResult:
    """论文出现"不使用该参数"的表述（如 "No dropout is used ..."）。

    **只作提示，不作为取值入库**——实测踩过坑: PointNet 的 "No dropout is used for
    segmentation network" 只针对分割子网络, 而分类网络其实用了 dropout(keep ratio 0.7)。
    因此这里返回 note_only 候选: 进入轨迹与人工核查清单, 但不参与"一致/不一致"判定。
    """
    t0 = time.time()
    aliases = PARAM_SYNONYMS.get(kind, (kind, []))[1]
    for page_no, text in page_texts:
        for sm in _SENTENCE_RE.finditer(text):
            sent = sm.group(0)
            for a in aliases:
                am = _alias_re(a).search(sent)
                if not am:
                    continue
                before = sent[max(0, am.start() - _NEG_WINDOW): am.start()]
                if not _NEGATION.search(before):
                    continue
                if _num_re().search(sent):
                    continue        # 本句另有数字 -> 交给别的工具, 避免张冠李戴
                return ToolResult(
                    ok=True,
                    candidate=Candidate(
                        key=kind, value="(论文提及不使用)", evidence_text=sent,
                        page=page_no, source="negation", parser="agent-negation",
                        note_only=True,
                        note="论文出现「不使用该参数」的表述, 但可能只针对某个子模块/子实验 —— "
                             "需人工确认适用范围, 系统不据此判定取值"),
                    cost={"llm_calls": 0, "vision_calls": 0,
                          "seconds": time.time() - t0})
    return ToolResult(ok=False, cost={"llm_calls": 0, "vision_calls": 0,
                                      "seconds": time.time() - t0},
                      note="正文没有「明确不使用该参数」的表述")


# ---------------------------------------------------------------- 工具 3: LLM 提议

_LLM_PROMPT = """你在协助做论文复现审计。下面给出论文中包含「{disp}」的原文片段。

请只回答一个问题: 论文是否**明确给出了该参数的取值**?
严格要求:
1. 只能返回原文中**逐字出现**的片段作为证据, 不得改写、不得推断、不得补全;
2. 找不到明确取值就返回 found=false, 不要猜;
3. 证据片段必须能让人看出这个值属于该参数。

仅输出 JSON: {{"found": true/false, "value": "取值", "evidence_text": "原文逐字片段"}}

原文片段:
{excerpts}
"""


def tool_llm_propose(kind: str, page_texts: list, api_key: str,
                     model: str = "") -> ToolResult:
    """让 LLM 从正文里提议取值——**它只是提议**, 必须过 gate(回原文核对)才能入库。"""
    t0 = time.time()
    cost = {"llm_calls": 0, "vision_calls": 0, "seconds": 0.0}
    if not api_key:
        return ToolResult(ok=False, cost=cost, note="未配置 LLM key, 该工具跳过")

    aliases = PARAM_SYNONYMS.get(kind, (kind, []))[1]
    disp = PARAM_SYNONYMS.get(kind, (kind, []))[0]
    excerpts: list[str] = []
    for page_no, text in page_texts:
        for sm in _SENTENCE_RE.finditer(text):
            sent = sm.group(0)
            if any(_alias_re(a).search(sent) for a in aliases):
                excerpts.append(f"[Page {page_no}] {sent}")
        if len(excerpts) >= 6:
            break
    if not excerpts:
        return ToolResult(ok=False, cost=cost, note="正文里没有提到该参数, 无法提议")

    # ---- 走统一的 LLM 通道（ask_json）：**内容哈希缓存 + 一次重试 + 失败带返回片段**
    # ⚠️ 这里原先**自己直连 OpenAI，且完全没有缓存** —— 于是同一篇论文的补漏结果**不稳定**。
    # 实测（2026-09-29）：03_NeRF 论文里确有 `5 × 10−4`，但 5 轮里 **3 轮**没把它补回来，
    # 导致同一次审计的结论在 `consistent` 与 `missing_in_paper` 之间来回跳，
    # 进而让「经典 vs 计划」消融对照**假失败**（87 vs 85）——
    # 更要紧的是，它直接损害了本项目"同输入同输出"的承诺。
    # 改为 ask_json 后，同一 prompt 命中同一份缓存，**补漏从此可复现**。
    from .llm import ask_json
    data, _note = ask_json(
        _LLM_PROMPT.format(disp=disp, excerpts="\n".join(excerpts)[:4000]),
        api_key, mode=f"propose-{kind}", max_tokens=400)
    # 缓存命中不产生费用，就不该扣 LLM 预算（如实统计）
    cost["llm_calls"] = 0 if "缓存命中" in _note else 1
    cost["seconds"] = time.time() - t0
    if not isinstance(data, dict):
        return ToolResult(ok=False, cost=cost, note=f"LLM 未给出可用提议（{_note}）")
    if not data.get("found"):
        return ToolResult(ok=False, cost=cost, note="LLM 认为论文没有给出明确取值")
    value = str(data.get("value", "")).strip()
    ev = str(data.get("evidence_text", "")).strip()
    if not value or not ev:
        return ToolResult(ok=False, cost=cost, note="LLM 返回内容不完整, 已丢弃")
    page = next((p for p, t in page_texts if _norm(ev) and _norm(ev) in _norm(t)), 0)
    return ToolResult(ok=True, candidate=Candidate(
        key=kind, value=value, evidence_text=ev, page=page,
        source="llm", parser="agent-llm",
        note="LLM 提议, 待程序回原文核对"), cost=cost)


# ---------------------------------------------------------------- 工具 4: 读图


def vision_ready(vision_kwargs: dict) -> bool:
    """视觉通道是否可用: 页面传了 key, 或 .env/环境变量里配了(与图像通道同一口径)。"""
    if not vision_kwargs:
        return False
    if vision_kwargs.get("mock"):
        return True
    from .vision import _provider
    return _provider(vision_kwargs.get("api_key", ""),
                     vision_kwargs.get("base_url", ""),
                     vision_kwargs.get("model", "")) is not None


def tool_vision_read(kind: str, pdf_path: str, page_texts: list,
                     vision_kwargs: dict) -> ToolResult:
    """对"提到该参数的页"读图（双次独立读取取交集）。"""
    t0 = time.time()
    cost = {"llm_calls": 0, "vision_calls": 0, "seconds": 0.0}
    if not vision_ready(vision_kwargs):
        return ToolResult(ok=False, cost=cost, note="未配置视觉模型 key, 该工具跳过")

    aliases = PARAM_SYNONYMS.get(kind, (kind, []))[1]
    pages = [p for p, t in page_texts
             if any(_alias_re(a).search(t) for a in aliases)][:2]
    if not pages:
        return ToolResult(ok=False, cost=cost, note="正文没提到该参数, 不知道该读哪几页")

    from .vision import analyze_images
    kw = dict(vision_kwargs)
    found, meta = analyze_images(pdf_path, only_pages=set(pages),
                                 focus=[PARAM_SYNONYMS.get(kind, (kind, []))[0]],
                                 max_regions=2,          # 聚焦补漏: 最多读 2 个区域
                                 **kw)
    cost["vision_calls"] = 2 * int(meta.get("regions_read") or 0)
    cost["seconds"] = time.time() - t0
    evs = found.get(kind)
    if not evs:
        return ToolResult(ok=False, cost=cost,
                          note=f"读了第 {pages} 页的图, 没有读到该参数"
                               + (f"; {meta['notes'][0]}" if meta.get("notes") else ""))
    e = evs[0]
    return ToolResult(ok=True, candidate=Candidate(
        key=kind, value=e.raw_value, evidence_text=e.snippet, page=pages[0],
        source="vision", parser="vlm",
        note="读图得到(两次独立读取取交集)"), cost=cost)


# ---------------------------------------------------------------- 回原文核对闸门


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _in_flattened_table(evidence: str, value: str,
                        lo: int = 0, hi: int = -1) -> bool:
    """证据里的取值是否**处在被压平的表格串**里(与相邻数值只隔空白)。

    与 `paper_parser._in_table_run` 是同一判据, 只是这里要找的是**取值在证据中的位置**。
    `lo`/`hi` 用来把检查限制在某个区间(见 gate 里"片段刚好截在表格中间"的用法)。

    实证(2026-09-28, DeiT 附录对比表):
        "Methods ⏎ ViT-B[15] ⏎ DeiT-B ⏎ Epochs ⏎ 300 ⏎ 300 ⏎ Batch size ⏎ 4096 ⏎ 1024 ⏎ …"
    这张**两列对比表被压平**成一串裸数字后, Agent 的 text-l1 通道取到了 "Batch size" **前面**
    那个 300(其实是 Epochs 行的值), 于是把 batch_size 误报成 300, 并进一步生成了错补丁。
    该值本身形态合法(整数、在证据里确实出现), 所以只有"与相邻数值只隔空白"这条判据能识破它。
    """
    pat = re.compile(r"(?<![\w.])" + re.escape(value) + r"(?![\w.])")
    for m in pat.finditer(evidence):
        if m.start() < lo or (hi >= 0 and m.start() > hi):
            continue
        if _in_table_run(evidence, m.start(), m.end()):
            return True
    return False


# 方括号编号守卫: "cosine decay [38]" / "AdamW [39]" 里的数字是**参考文献编号**, 不是取值。
# 实证(2026-09-28, MAE): 论文 Table 8 是「config | value」两列键值表, 压平后成
#   "… cosine decay [38] ⏎ warmup epochs [20] ⏎ 40 ⏎ augmentation …"
# 真值 40 在**下一行**, 而 text-l2 在别名前 45 字窗口里抓到了 `[38]` 的 38 ——
# 于是论文侧 warmup 被报成 38(真值 40 是明确写着的), 并进了比对。
# 引用编号在论文里**永远不是参数取值**, 因此这类形态一律丢弃。
_BRACKET_NUM = re.compile(r"[\[\]（）()【】]")


def gate(candidate: Candidate, page_texts: list) -> tuple[bool, str, str]:
    """闸门: 工具提出的候选**必须**通过以下检查才能入库。

    note_only 候选（如"论文提到不使用该参数"）不走此闸门——它们只作提示，不进结论。
    返回 (是否通过, 说明, 额外提示或空串)。额外提示用于"信息有价值但不能作为取值"的情形。
    """
    ev = _norm(candidate.evidence_text)
    if not ev:
        return False, "没有证据片段", ""
    page_txt = {p: _norm(t) for p, t in page_texts}
    if not (candidate.page in page_txt and ev in page_txt[candidate.page]) \
            and not any(ev in t for t in page_txt.values()):
        return False, "证据片段在论文原文里找不到(疑似编造), 已丢弃", ""

    # 表格压平守卫: 取值与**相邻数值只隔空白** -> 来自被压平的表格(多列取值),
    # 取到的是"任选一列", 不是论文给该参数定的值。对**所有通道**生效(text-l1/l2/llm/vision),
    # 因为这张 DeiT 表的误取恰恰一个来自 text-l1(300)、一个来自 llm(0.003)。
    #
    # 两步: ① 在证据片段里找; ② 片段可能**刚好截在表格中间**(LLM 常只返回 "learning rate
    # 0.003", 它确实是原文的连续两行, 于是"片段内"看不出异常) —— 此时看它在**整页原文**里
    # **紧接着**是什么: 若下一个非空白字符又是数字, 说明它来自多列取值表。
    _hit = _in_flattened_table(ev, candidate.value)
    if not _hit:
        for t in ([page_txt[candidate.page]] if candidate.page in page_txt
                  else list(page_txt.values())):
            pos = t.find(ev)
            if pos >= 0 and _in_flattened_table(t, candidate.value,
                                                pos, pos + len(ev) + 24):
                _hit = True
                break
    if _hit:
        return (False,
                f"取值 {candidate.value} 与相邻数值之间只隔空白 —— 取自**被压平的表格**"
                "(表头后跟多列取值)。这类位置取到的只是「任选一列」, 无法确定属于哪个配置, 已丢弃",
                "该处原文是压平的对比表(多列配置并排); 若论文确实给了该配置的确定值, 需人工补充")

    # 方括号编号守卫: 取值被方括号包着(或紧邻) -> 是参考文献/图表编号, 不是取值
    _mv0 = re.search(r"(?<![\w.])" + re.escape(candidate.value) + r"(?![\w.])", ev)
    if _mv0:
        _l = ev[max(0, _mv0.start() - 1): _mv0.start()]
        _r = ev[_mv0.end(): _mv0.end() + 1]
        if _l and _r and _BRACKET_NUM.search(_l) and _BRACKET_NUM.search(_r):
            return (False,
                    f"取值 {candidate.value} 被方括号包着 —— 论文里的 `[n]` 是**参考文献编号**, "
                    "不是参数取值, 已丢弃",
                    "该参数的真正取值可能在邻近行(如键值表的下一行), 需人工确认")

    # 语义守卫: 证据里是"keep ratio"这类反向表述时, 数值语义与参数相反
    trap = _SEMANTIC_TRAP.get(candidate.key)
    if trap and trap.search(candidate.evidence_text):
        return (False, "证据以「keep ratio(保留率)」表述, 与 dropout rate 语义相反, 已丢弃",
                "论文用 keep ratio 表述 dropout, 需人工换算(keep ratio 0.7 → dropout rate 0.3)")

    # 文本型参数不接受纯数字(段落编号 6.1、图号 2 属于误抓)
    if candidate.key in _TEXT_VALUED and not re.search(r"[A-Za-z]", candidate.value):
        return False, f"取值 {candidate.value} 对文本型参数而言是纯数字(疑为编号), 已丢弃", ""

    # 分布参数守卫: 取值若出现在采样调用的实参位置, 那是分布参数(均值/标准差/区间)而非训练设置
    mv = re.search(r"(?<![\w.])" + re.escape(candidate.value) + r"(?![\w.])",
                   candidate.evidence_text)
    probe = candidate.evidence_text[:mv.start()] if mv else candidate.evidence_text
    if _inside_dist_call(probe):
        return (False, f"取值 {candidate.value} 位于分布采样调用的实参位置"
                       "(均值/标准差/区间等), 不是训练设置值, 已丢弃",
                "该处原文在描述分布或生成公式; 若论文确实设置了该参数, 需人工补充")

    # 区间守卫: 取值本身是区间(如 100–300k)时不是确定取值
    if _RANGE_IN_VALUE.search(candidate.value):
        return False, f"取值 {candidate.value} 是区间/范围而非确定值, 已丢弃", ""

    from .synonyms import normalize_number
    if candidate.key in _TEXT_VALUED:
        pass
    elif normalize_number(candidate.value) is None:
        return False, f"取值 {candidate.value} 无法解析为数值, 已丢弃", ""

    from .selfcheck import _snippet_contains
    if not _snippet_contains(candidate.evidence_text, candidate.value):
        return False, f"取值 {candidate.value} 未出现在证据片段里, 已丢弃", ""
    if is_plausible(candidate.key, candidate.value) is False:
        return False, f"取值 {candidate.value} 超出领域先验范围, 已丢弃", ""
    guard = _SHAPE_GUARD.get(candidate.key)
    if guard and not guard.search(candidate.evidence_text):
        return False, "证据中缺少该参数应有的形状(如 N×N), 已丢弃", ""
    return True, "通过", ""
