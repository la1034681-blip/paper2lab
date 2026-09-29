"""图像通道——读图理解(扫描页 / 图片表格里的超参数)。

设计要点(与"规则验证 + AI 归因"的架构一致, 但图像无法用文本层验证, 所以换三道保险):
1. AI 只提议: 视觉模型输出必须是严格 JSON, 且必须附"图中原文";
2. 双次独立读图求交集: 两次调用结果不一致的值直接丢弃(防幻觉);
3. 结论降级: parser="vlm"、confidence=Inferred、不计入就绪度评分, 单列"待人工核对"区。

配置(任一即可, 均走 OpenAI 兼容接口):
- DASHSCOPE_API_KEY  -> 通义千问 qwen-vl-max
- ZHIPUAI_API_KEY    -> 智谱 glm-4v-plus
- VISION_API_KEY + VISION_BASE_URL + VISION_MODEL (自定义)
测试钩子: 无 key 时若设置 PAPER2LAB_VISION_MOCK_FILE, 则读取该 JSON 作为模型返回(用于离线验证链路)。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from .models import Evidence
from .shards import DEFAULT_MAX_WORKERS, run_sharded
from .synonyms import (PARAM_SYNONYMS, canonical_key, is_plausible,
                       normalize_number)

# 读图覆盖范围: 默认**全部候选区域都读、不限时**(宁可等, 也要覆盖全);
# 需要控时可在页面「高级设置」或环境变量里设上限/预算(设 0 = 不限)
_DEFAULT_MAX_REGIONS = 0            # 0 = 不限(读全部候选区域, 含所有文本稀薄页)
_DEFAULT_BUDGET_SECONDS = 0.0       # 0 = 不限时
_HARD_MAX_REGIONS = 120             # 内部安全上限(防超长扫描件失控), 命中时如实说明
_MIN_IMG_AREA_RATIO = 0.20     # 图片占页面面积比阈值
_RENDER_DPI = 110
_MAX_SIDE = 1200               # 送模型前的最长边(控制图片 token 与耗时)
_JPEG_QUALITY = 80


def _read_all_images() -> bool:
    """是否对"文本完整且未提参数"的页面也读其内嵌插图(逃生开关)。

    默认 False: 这类插图几乎必然是结果曲线/示意图, 读不出实验配置。
    需要恢复"页内插图全读"时设 PAPER2LAB_VISION_READ_ALL=1。
    """
    return (os.getenv("PAPER2LAB_VISION_READ_ALL", "") or "").strip().lower() \
        in ("1", "true", "yes", "on")


def _max_regions_default() -> int:
    """0 或负数 = 不限(读全部候选)。"""
    try:
        return int(os.getenv("PAPER2LAB_VISION_MAX_REGIONS",
                             str(_DEFAULT_MAX_REGIONS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_REGIONS


def _budget_seconds_default() -> float:
    """0 或负数 = 不限时。"""
    try:
        return float(os.getenv("PAPER2LAB_VISION_BUDGET_SECONDS",
                               str(_DEFAULT_BUDGET_SECONDS)))
    except (TypeError, ValueError):
        return _DEFAULT_BUDGET_SECONDS


_MAX_REGIONS = _DEFAULT_MAX_REGIONS       # 兼容旧引用(调用时以 _max_regions_default 为准)
# 注: 这里原先还有 `_MAX_SECONDS = _DEFAULT_BUDGET_SECONDS` 的兼容别名，
# 2026-09-28 静态检查发现**全项目零引用**（读图预算现在走 budget_seconds 参数与
# PAPER2LAB_VISION_BUDGET_SECONDS），已删除 —— 留着一个没人用的常量只会误导后来者。

# 页面文本里出现这些词 -> 该页更可能含参数, 读图优先级更高
_PRIORITY_HINT = re.compile(
    r"(hyper-?parameter|learning rate|batch|epoch|optimizer|config|setting|"
    r"implement|train|超参|参数|配置|实验设置)", re.IGNORECASE)

_PROMPT = """你是科研复现审计助手。这是论文/实验材料的图片区域。
只抽取与"实验配置"有关的参数(学习率、批次大小、迭代轮数、优化器、权重衰减、动量、dropout、
随机种子、输入尺寸、数据集、模型、阈值等), 不要抽取实验结果指标, 不要推测。
严格要求:
1. 只返回图片中确实出现的值, 不得推断或补全;
2. 每个参数必须附上"图片中出现的原文片段"(逐字照抄, 用于人工核对);
3. 无法确定的不要返回。
仅输出 JSON, 格式: {"params":[{"name":"learning rate","value":"1e-4","evidence_text":"lr = 1e-4"}]}
"""


def _default_model_for(base_url: str) -> str:
    """按接口地址猜默认模型名(可用 VISION_MODEL 覆盖)。"""
    b = (base_url or "").lower()
    if "xiaomimimo" in b or "mimo" in b:
        return "mimo-v2.5"
    if "bigmodel" in b:
        return "glm-4v-plus"
    if "dashscope" in b:
        return "qwen-vl-max"
    return "qwen-vl-max"


def _provider(api_key: str = "", base_url: str = "",
              model: str = "") -> Optional[tuple[str, str, str, str]]:
    """返回 (api_key, base_url, model, 来源说明); 未配置返回 None。

    优先级: 函数参数(页面输入) > 环境变量(.env 或系统环境变量)。
    """
    from .envfile import get
    # 1) 页面输入
    if api_key:
        if base_url:
            return (api_key, base_url, model or _default_model_for(base_url),
                    "页面输入")
        if api_key.startswith("tp-") or api_key.startswith("ttp-"):
            return (api_key, "https://token-plan-cn.xiaomimimo.com/v1",
                    model or "mimo-v2.5", "页面输入(MiMo Token Plan)")
        if api_key.count(".") >= 1 and not api_key.startswith("sk-"):
            return (api_key, "https://open.bigmodel.cn/api/paas/v4",
                    model or "glm-4v-plus", "页面输入(智谱 GLM-4V)")
        return (api_key, "https://api.xiaomimimo.com/v1",
                model or "mimo-v2.5", "页面输入(MiMo sk-)")
    # 2) 环境变量 / .env
    k = get("VISION_API_KEY")
    u = get("VISION_BASE_URL")
    m = get("VISION_MODEL")
    if k and u:
        return (k, u, m or _default_model_for(u), ".env / 环境变量")
    if get("DASHSCOPE_API_KEY"):
        return (get("DASHSCOPE_API_KEY"),
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
                get("VISION_MODEL") or "qwen-vl-max", "DASHSCOPE_API_KEY")
    if get("ZHIPUAI_API_KEY"):
        return (get("ZHIPUAI_API_KEY"), "https://open.bigmodel.cn/api/paas/v4",
                get("VISION_MODEL") or "glm-4v-plus", "ZHIPUAI_API_KEY")
    return None


def _cache_path() -> Path:
    p = Path(__file__).resolve().parent.parent / "cache" / "vision_cache.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _cache_path().write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception:
        pass


def _png_to_jpeg_payload(png: bytes) -> bytes:
    """把渲染出的 PNG 压成 JPEG 并限制最长边, 降低图片 token 与传输耗时。"""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = img.size
        scale = min(1.0, _MAX_SIDE / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        return buf.getvalue()
    except Exception:
        return png      # 无 PIL 时退回原图


def extract_image_regions(pdf_path: str, max_regions: int = _MAX_REGIONS,
                          stats: Optional[dict] = None,
                          only_pages: Optional[set] = None) -> list[dict]:
    """挑出值得读图的区域: 文本稀薄的页(疑似扫描/图片页) 与 占据大面积的内嵌图片。

    max_regions <= 0 表示**不限**(读全部候选, 排序仅用于让"更可能含参数的"先读)。
    only_pages: 只在这些页码里挑候选(抽取 Agent 会用它"只读提到该参数的那几页")。
    候选排序: 页面文本里出现参数语境词 > 位图覆盖率高 > 其他。
    stats(可选, 会被就地填充): 记录候选总数与未读原因, 供报告如实说明。
    返回 [{"page": n, "kind": "page"|"image", "png": bytes, "reason": str}]
    """
    cands: list[tuple[int, int, dict]] = []
    thin_cands: set[int] = set()      # 候选中的文本稀薄页
    plain_pages: list[int] = []       # 因"文本完整且未提参数"而跳过的插图页
    read_all_imgs = _read_all_images()
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, 1):
            if only_pages is not None and i not in only_pages:
                continue
            text = page.get_text("text")
            text_len = len(text.strip())
            page_area = abs(page.rect.width * page.rect.height) or 1.0
            hint = 1 if _PRIORITY_HINT.search(text[:1200]) else 0
            if text_len < 120:
                thin_cands.add(i)
                pix = page.get_pixmap(dpi=_RENDER_DPI)
                cands.append((hint, text_len, {
                    "page": i, "kind": "page", "png": pix.tobytes("png"),
                    "reason": f"该页文本仅 {text_len} 字符(疑似扫描/图片页)"
                              + ("，且提到参数/配置" if hint else "")}))
                continue
            # 语境守卫: 文本已**完整解析**、且该页通篇未提参数/配置 —— 页内嵌图几乎必然是
            # 结果曲线/示意图, 读不出实验配置。实测(2026-09-27, 八套样本): 128 个候选区域里
            # 112 个(88%)属于此类; 其中 NeRF 的 103 个此类区域**全部零产出**, 却耗时 583s。
            # 要恢复"页内插图全读", 设 PAPER2LAB_VISION_READ_ALL=1。
            #
            # 注意 `plain_pages` 只在**确实存在够大的候选图**时才记这一页 —— 否则报告里
            # 会写"另有 N 页插图未读图", 而那些页其实没有够大的图、什么都没被跳过(实测踩过:
            # D题 曾报"2 页未读"而实际 0 页有候选图)。
            for img in page.get_images(full=True):
                try:
                    rects = page.get_image_rects(img[0])
                except Exception:
                    continue
                big = None
                for r in rects:
                    if abs(r.width * r.height) / page_area < _MIN_IMG_AREA_RATIO:
                        continue
                    big = r
                    break
                if big is None:
                    continue              # 这张图不构成候选, 不算"被跳过"
                if not hint and not read_all_imgs:
                    if i not in plain_pages:
                        plain_pages.append(i)
                    break                 # 整页跳过, 不必再看同页其他图
                pix = page.get_pixmap(dpi=_RENDER_DPI, clip=big)
                ratio = abs(big.width * big.height) / page_area
                cands.append((hint, text_len, {
                    "page": i, "kind": "image", "png": pix.tobytes("png"),
                    "reason": f"内嵌图片占页面 {ratio:.0%}"
                              + ("，页面提到参数/配置" if hint else "")}))
                # 注意: **不 break** —— 每张合格图各出一个候选(与原实现一致);
                # 若在此 break 会变成"每页只读一张图"(实测曾把 NeRF 的 103 个候选砍到 5 个)。
    # 优先级: 有参数语境词优先, 其次文本量大的页(更可能是表格/配置页而非纯图)
    cands.sort(key=lambda c: (-c[0], -c[1]))
    unlimited = max_regions is None or max_regions <= 0
    limit = _HARD_MAX_REGIONS if unlimited else max(1, max_regions)
    picked = cands[:limit]
    if stats is not None:
        picked_pages = {c[2]["page"] for c in picked}
        stats.update({
            "candidates": len(cands),
            "max_regions": 0 if unlimited else limit,
            "unlimited": unlimited,
            "hard_capped": unlimited and len(cands) > _HARD_MAX_REGIONS,
            "skipped_by_cap": len(cands) - len(picked),
            # 候选里属于文本稀薄页、被上限挡在外面的页
            "thin_candidates": sorted(thin_cands),
            "thin_skipped": sorted(thin_cands - picked_pages),
            # 因"文本完整且未提参数"而整页跳过插图的页
            "skipped_no_context": plain_pages,
        })
    return [c[2] for c in picked]


def _call_vision(png: bytes, model: str, base_url: str, api_key: str,
                 prompt: Optional[str] = None) -> dict:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=120)
    payload = _png_to_jpeg_payload(png)
    mime = "image/jpeg" if payload[:2] == b"\xff\xd8" else "image/png"
    b64 = base64.b64encode(payload).decode()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt or _PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]}]
    kwargs = dict(model=model, messages=messages, temperature=0)
    try:
        # 新版接口用 max_completion_tokens; 预算要给足——
        # 部分模型(如 MiMo)会先消耗推理 token, 预算太小会导致返回空内容
        resp = client.chat.completions.create(max_completion_tokens=1500, **kwargs)
    except TypeError:
        resp = client.chat.completions.create(max_tokens=1500, **kwargs)
    raw = (resp.choices[0].message.content or "").strip()
    return _parse_json(raw)


def _parse_json(raw: str) -> dict:
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        return {}
    try:
        return json.loads(raw[start:end + 1])
    except Exception:
        return {}


def _mock_response() -> dict:
    """测试钩子: 读取离线伪造的模型返回, 用于无 key 环境下验证链路。"""
    f = os.getenv("PAPER2LAB_VISION_MOCK_FILE")
    if not f:
        return {}
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except Exception:
        return {}


def analyze_images(pdf_path: str, max_regions: Optional[int] = None,
                   api_key: str = "", base_url: str = "",
                   model: str = "", budget_seconds: Optional[float] = None,
                   only_pages: Optional[set] = None,
                   focus: Optional[list] = None,
                   ) -> tuple[dict[str, list[Evidence]], dict]:
    """读图抽取参数。返回 (参数证据, 元信息)。

    only_pages: 只在这些页码里挑区域(抽取 Agent 用来聚焦"提到某参数的那几页")
    focus:      额外提示模型重点关注哪些参数(会拼进提示词, 并计入缓存键)
    max_regions <= 0 / None(默认) = **不限**, 全部候选区域都读;
    budget_seconds <= 0(默认) = **不限时**。
    元信息: {enabled, model, regions, regions_read, mode, kept, dropped, notes,
             candidates, max_regions, unlimited, skipped_by_cap,
             thin_candidates, thin_skipped}
    """
    if max_regions is None:
        max_regions = _max_regions_default()
    budget = _budget_seconds_default() if budget_seconds is None else float(budget_seconds)
    stats: dict = {}
    regions = extract_image_regions(pdf_path, max_regions, stats,
                                    only_pages=only_pages)
    prompt = _PROMPT
    if focus:
        prompt += ("\n本次特别关注这些参数(其他参数照常抽取): "
                   + "、".join(str(x) for x in focus) + "\n")
    meta: dict = {
        "regions": len(regions),
        "region_list": [{"page": r["page"], "kind": r["kind"], "reason": r["reason"]}
                        for r in regions],
        "enabled": False, "mode": "off", "model": "", "source": "",
        "regions_read": 0, "kept": 0, "dropped": 0, "notes": [],
        "candidates": stats.get("candidates", len(regions)),
        "max_regions": stats.get("max_regions", max_regions),
        "unlimited": stats.get("unlimited", True),
        "hard_capped": stats.get("hard_capped", False),
        "skipped_by_cap": stats.get("skipped_by_cap", 0),
        "thin_candidates": stats.get("thin_candidates", []),
        "thin_skipped": stats.get("thin_skipped", []),
        "skipped_no_context": stats.get("skipped_no_context", []),
        "budget_seconds": budget,
        "only_pages": sorted(only_pages) if only_pages else [],
        "focus": list(focus or []),
    }
    if not regions:
        meta["notes"].append("未发现需要读图的区域")
        return {}, meta

    prov = _provider(api_key, base_url, model)
    mock = _mock_response()
    if not prov and not mock:
        meta["notes"].append(
            f"发现 {len(regions)} 个图片/扫描区域, 但未配置视觉模型 key"
            "(页面可填, 或设置 DASHSCOPE_API_KEY / ZHIPUAI_API_KEY / VISION_API_KEY), "
            "图像通道未启用——这些区域的内容未参与审计")
        return {}, meta

    if mock:
        meta.update(enabled=True, mode="mock", model="mock", source="离线测试钩子")
        call_key = call_base = ""
    else:
        k, u, m, src = prov
        # 注意: key 不写入 meta(审计结果可能被导出/展示), 只在本函数内使用
        meta.update(enabled=True, mode="api", model=m, source=src)
        call_key, call_base = k, u

    cache = _load_cache()
    found: dict[str, list[Evidence]] = {}
    t_start = time.time()

    # ---- 第二期第四批: 读图改为分片并发 ----
    # 为什么: 每个区域要读两次, 串行下来十几分钟是常态, 极端情况会撞执行超时。
    # 怎么保证不出错:
    #   · 阶段一(可并发) 只负责"把 payload 取回来" —— 除缓存读写(加锁)外不碰任何共享状态;
    #   · 阶段二(串行) 按原顺序汇总 payload —— **保序**, 结果与串行完全一致;
    #   · 设了耗时预算时**退回串行**, 保留原来"读到一半就停"的语义。
    cache_lock = threading.Lock()
    workers = 1 if budget > 0 else DEFAULT_MAX_WORKERS

    def _fetch(idx, r):
        if budget > 0 and (time.time() - t_start) >= budget:
            return {"skipped": True}
        # 缓存键含提示词: 聚焦某参数的读图结果不能与通用读图结果互相复用
        key_hash = hashlib.sha1(
            r["png"] + meta["model"].encode() + prompt.encode()).hexdigest()[:16]
        with cache_lock:
            hit = cache.get(key_hash)
        if hit is not None:
            return {"payload": hit, "dropped": 0}
        if mock:
            return {"payload": mock, "dropped": 0}
        # 双次独立读图 -> 取交集(两次都出现的值才采信, 防幻觉)
        try:
            first = _call_vision(r["png"], meta["model"], call_base, call_key, prompt)
            second = _call_vision(r["png"], meta["model"], call_base, call_key, prompt)
        except Exception as e:      # noqa: BLE001
            return {"error": f"{type(e).__name__}::{e}"}
        local = {"dropped": 0}      # 每片用自己的计数器, 不碰共享 meta
        payload = _intersect(first, second, local)
        with cache_lock:
            cache[key_hash] = payload
            _save_cache(cache)
        return {"payload": payload, "dropped": local["dropped"]}

    results, shard_rep = run_sharded(regions, _fetch, max_workers=workers,
                                     label="读图")
    meta["shard"] = shard_rep.to_dict()

    # ---- 阶段二: 按原顺序汇总(保序 → 与串行结果一致)
    _skipped = 0
    for r, res in zip(regions, results):
        if res is None:
            meta["notes"].append(
                f"第 {r['page']} 页读图失败(分片异常, 该区域内容未参与审计)")
            continue
        if res.get("skipped"):
            _skipped += 1
            continue
        if res.get("error"):
            err_type, _, detail = str(res["error"]).partition("::")
            low = detail.lower()
            hint = ""
            if "insufficient" in low or "402" in detail:
                hint = "(账户余额不足, 需在服务商控制台充值)"
            elif "401" in detail or "invalid" in low:
                hint = "(key 无效或已失效)"
            elif "429" in detail:
                hint = "(触发限流, 稍后重试)"
            meta["notes"].append(
                f"第 {r['page']} 页读图失败: {err_type} {hint} {detail[:160]}")
            continue

        meta["regions_read"] += 1
        meta["dropped"] += int(res.get("dropped") or 0)
        for item in (res.get("payload") or {}).get("params", []):
            name = str(item.get("name", "")).strip()
            value = str(item.get("value", "")).strip()
            quote = str(item.get("evidence_text", "")).strip()
            ck = canonical_key(name) or canonical_key(name.replace(" ", "_"))
            if ck is None or not value:
                meta["dropped"] += 1
                continue
            norm = normalize_number(value)
            if ck not in ("optimizer", "scheduler", "dataset", "model"):
                if norm is None or is_plausible(ck, value) is False:
                    meta["dropped"] += 1
                    continue
            found.setdefault(ck, []).append(Evidence(
                source="paper",
                location=f"Page {r['page']} · 图像区域({r['kind']})",
                snippet=quote or f"图像中读到: {name} = {value}",
                raw_value=value,
                normalized=norm if norm is not None else value.lower(),
                parser="vlm",
            ))
            meta["kept"] += 1

    if _skipped:
        meta["notes"].append(
            f"为控制耗时(预算 {int(budget)}s), {_skipped} 个区域未读图"
            "——这些区域的内容未参与审计")

    if meta["dropped"]:
        meta["notes"].append(f"{meta['dropped']} 条读图结果被丢弃(参数名不认识/值超先验范围/两次读图不一致)")
    _nc = meta.get("skipped_no_context") or []
    if _nc:
        _head = "、".join(f"第 {p} 页" for p in _nc[:10])
        meta["notes"].append(
            f"另有 {len(_nc)} 页文本已完整解析、且正文未提及参数/配置, 其内嵌插图未读图"
            f"（{_head}{' 等' if len(_nc) > 10 else ''}）——此类插图通常为结果曲线/示意图, "
            "读不出实验配置; 如需全部读取, 设 PAPER2LAB_VISION_READ_ALL=1 后重跑。")
    if meta["hard_capped"]:
        meta["notes"].append(
            f"候选区域达 {meta['candidates']} 个, 超过内部安全上限 {_HARD_MAX_REGIONS}——"
            f"本次只读了前 {meta['max_regions']} 个(按「更可能含参数」排序); "
            f"另 {meta['skipped_by_cap']} 个未读图, 其内容未参与审计。")
    elif meta["unlimited"] and not meta["skipped_by_cap"]:
        _tn = len(meta["thin_candidates"])
        meta["notes"].append(
            f"本次候选区域**全部读取**: 共 {meta['candidates']} 个(候选范围 = 文本稀薄页 "
            f"+ 正文提及参数/配置的页面上的内嵌插图"
            + (f"; 其中文本稀薄页 {_tn} 页" if _tn else "")
            + "); 每个区域两次独立读取取交集以防幻觉。")
    elif meta["skipped_by_cap"] > 0:
        _skip = meta["thin_skipped"]
        meta["notes"].append(
            f"共发现 {meta['candidates']} 个候选区域(含文本稀薄页 "
            f"{len(meta['thin_candidates'])} 页), 本次按上限读取前 {meta['max_regions']} 个; "
            f"另 {meta['skipped_by_cap']} 个区域**未读图**, 其内容未参与审计"
            + (f"(其中稀薄页: 第 {', '.join(map(str, _skip))} 页)" if _skip else "")
            + "。如需覆盖更多页面, 把「读图区域上限」设为 0(全部)后重跑"
              "(结果按图缓存, 已读过的不会重复计费)。")
    return found, meta


def _intersect(first: dict, second: dict, meta: dict) -> dict:
    """两次读图结果取交集: 参数名+值归一化后都出现才保留。"""
    def norm_map(payload: dict) -> dict:
        out = {}
        for it in payload.get("params", []) or []:
            ck = canonical_key(str(it.get("name", "")).strip())
            if ck:
                out[ck] = str(it.get("value", "")).strip()
        return out

    a, b = norm_map(first), norm_map(second)
    kept = []
    for ck, va in a.items():
        vb = b.get(ck)
        if vb is None:
            meta["dropped"] += 1
            continue
        na, nb = normalize_number(va), normalize_number(vb)
        same = (na == nb) if (na is not None and nb is not None) else (va == vb)
        if not same:
            meta["dropped"] += 1
            continue
        kept.append({"name": ck, "value": va,
                     "evidence_text": next((str(i.get("evidence_text", ""))
                                            for i in first.get("params", [])
                                            if canonical_key(str(i.get("name", ""))) == ck), "")})
    return {"params": kept}
