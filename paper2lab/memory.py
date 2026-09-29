"""跨任务记忆（第二期第三批）——记住"去哪儿找", 绝不记"等于多少"。

**一条硬边界**（与第一期"宁可不报, 也不报可能错的值"同源）:

    记忆里**只允许**存"线索" —— 某参数在论文里出现在哪几页、哪条通道取值、
    哪些参数已确认"论文确实没给值"。
    记忆里**绝不允许**存"结论" —— 参数等于多少。

为什么: 一旦记住"这篇论文的 dropout 是 0.1", 下次审另一篇时就可能把 0.1 安到
新论文上(张冠李戴)。**线索错了最多浪费一次尝试, 结论错了就是伪造证据。**

**第二条边界**: 记忆不自动改变执行。
同一份材料跑两次, 结论必须完全一致(可复现性优先于省成本), 因此"跳过已确认无解
的参数"这类优化默认**关闭**, 需要显式开启 `memory_skip`。默认只把线索**显示**出来。

存储: `cache/audit_memory.json`, 按论文指纹索引(指纹相同 == 内容相同, 复用才安全)。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

MEM_DIR = Path(__file__).resolve().parent.parent / "cache"
MEM_PATH = MEM_DIR / "audit_memory.json"

# ---- 容量上限(可用环境变量覆盖): 到极限不是"丢弃", 而是**压缩成摘要**
#   闸门一: 明细条目数上限   PAPER2LAB_MEM_MAX_ENTRIES
#   闸门二: 文件字符数上限   PAPER2LAB_MEM_MAX_CHARS
# 摘要里**同样只保留线索**(哪些参数常"论文未给值"、常出现在哪几页), 不含任何参数取值。
MAX_ENTRIES = int(os.environ.get("PAPER2LAB_MEM_MAX_ENTRIES") or 40)
MAX_CHARS = int(os.environ.get("PAPER2LAB_MEM_MAX_CHARS") or 24000)
DIGEST_MAX_PAGES = 12      # 摘要里每个参数最多记多少个"常见页"

# ---- 指纹口径版本: 口径一变, 文件里的旧键就**永远取不到**了 —— 它们既占容量,
# 又会被"同一篇论文不得多指纹"的守卫当成重复条目误报。
# 因此给记忆文件打版本号: 读到不匹配的版本即视为空库, 旧键随下一次写入被清除。
# 实证(2026-09-28): 把指纹改成"只取论文内容"后, 文件里残留 1 条旧键
# (与有效记录同标题、内容完全相同, 但键不同), 使守卫误报。
# 版本 1: 指纹 = sha1(论文 + 代码)   版本 2: 指纹 = sha1(论文)
_SCHEME = 2


def _load() -> dict:
    try:
        data = json.loads(MEM_PATH.read_text(encoding="utf-8"))
    except Exception:      # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    if int(data.get("_scheme") or 0) != _SCHEME:
        return {}          # 旧口径的键已不可达 -> 视为空库
    return data


def _save(data: dict) -> None:
    try:
        MEM_DIR.mkdir(parents=True, exist_ok=True)
        data = _compact(data)        # 超限则压缩成摘要(不丢弃线索)
        data["_scheme"] = _SCHEME    # 打版本号: 口径变更后旧键自动失效
        MEM_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    except Exception:      # noqa: BLE001
        pass               # 记忆是增强项, 失败不能影响审计本身


def _split(data: dict) -> tuple:
    """拆成 (摘要, 明细条目)。`_digest` 是压缩后的统计性线索。"""
    digest = dict(data.get("_digest") or {})
    entries = {k: v for k, v in (data or {}).items() if not k.startswith("_")}
    return digest, entries


def _merge_digest(digest: dict, overflow: list) -> dict:
    """把被挤出的明细合并进摘要 —— 只累积统计性线索, 不保留任何取值。"""
    d = dict(digest)
    d["papers_seen"] = int(d.get("papers_seen") or 0) + len(overflow)
    freq = dict(d.get("unresolved_freq") or {})
    pages = {k: list(v) for k, v in (d.get("page_hints_summary") or {}).items()}
    for rec in overflow:
        rec = rec or {}
        for k in rec.get("unresolved") or []:
            freq[k] = freq.get(k, 0) + 1
        for k, ps in (rec.get("page_hints") or {}).items():
            bucket = pages.setdefault(k, [])
            for p in ps:
                if p not in bucket and len(bucket) < DIGEST_MAX_PAGES:
                    bucket.append(p)
    d["unresolved_freq"] = dict(sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])))
    d["page_hints_summary"] = pages
    d["compressed_at"] = f"{datetime.now():%Y-%m-%d %H:%M}"
    d["note"] = ("摘要只保留统计性线索(哪些参数常『论文未给值』、常出现在哪几页), "
                 "不含任何参数取值; 明细已按容量上限自动压缩。")
    return d


def _compact(data: dict) -> dict:
    """容量控制: 超出上限时把最旧的一批明细**压缩成摘要**, 而不是直接丢弃。"""
    digest, entries = _split(data)
    overflow: list = []

    # 闸门一: 明细条目数
    if len(entries) > MAX_ENTRIES:
        keep = sorted(entries.items(),
                      key=lambda kv: (kv[1] or {}).get("last_seen", ""),
                      reverse=True)[:MAX_ENTRIES]
        keep_keys = {k for k, _ in keep}
        overflow += [v for k, v in entries.items() if k not in keep_keys]
        entries = dict(keep)

    # 闸门二: 文件体积(摘要自身也占空间, 因此要迭代挤出最旧的一条)
    while entries and len(json.dumps({"_d": digest, **entries},
                                     ensure_ascii=False)) > MAX_CHARS:
        oldest = min(entries, key=lambda k: (entries[k] or {}).get("last_seen", ""))
        overflow.append(entries.pop(oldest))

    if overflow:
        digest = _merge_digest(digest, overflow)

    out: dict = {}
    if digest:
        out["_digest"] = digest
    out.update(entries)
    return out


def fingerprint(pdf_path: str, code_path: str = "") -> str:
    """跨任务记忆的索引键 —— **只取论文内容**（与页面显示的数据指纹口径不同）。

    为什么**刻意不含代码包**：记忆里存的线索全是**论文侧**的
    ——「参数出现在哪几页」「哪些参数论文没给确定值」——这些与代码无关。
    实测（2026-09-28，八套样本）：把代码也算进指纹，会让**同一篇论文**因为
    「这次有没有传代码」被拆成两条记录 —— 八套样本**全部**出现重复条目
    （demo 甚至 3 条），"本机已审计 N 次"的连续性被切断（传代码 94 次 / 不传 2 次），
    历史线索也接不上。代码 ZIP 已是可选项，这条路径必须修。

    `code_path` 仅为兼容调用方既有写法而保留，**不参与摘要**。
    """
    h = hashlib.sha1()
    try:
        h.update(Path(pdf_path).read_bytes())
    except Exception:      # noqa: BLE001
        h.update(str(pdf_path).encode("utf-8", "replace"))
    return h.hexdigest()[:10]


def _pages_of(evs) -> list:
    """从证据的 location（如 "Page 9 · Training"）里取页码 —— 只取页码, 不取值。"""
    pages = set()
    for ev in evs or []:
        m = re.search(r"Page\s+(\d+)", getattr(ev, "location", "") or "")
        if m:
            pages.add(int(m.group(1)))
    return sorted(pages)


def recall(fp: str) -> dict:
    """读取某篇论文的历史线索(没有则返回空 dict)。"""
    if not fp:
        return {}
    return dict(_load().get(fp) or {})


def remember(audit, fp: str) -> dict:
    """把本次审计的**线索**写进记忆(只写线索, 不写任何参数值)。"""
    if not fp or audit is None:
        return {}
    paper = audit.paper
    seen = set(paper.alias_kinds or [])
    got = set(paper.params_all or {}) | set(paper.image_params or {})
    channel_of = {
        "text": set((audit.coverage or {}).get("kinds_by_channel", {}).get("text") or []),
        "table": set((audit.coverage or {}).get("kinds_by_channel", {}).get("table") or []),
        "vision": set((audit.coverage or {}).get("kinds_by_channel", {}).get("vision") or []),
        "agent": set((audit.coverage or {}).get("kinds_by_channel", {}).get("agent") or []),
    }

    page_hints: dict = {}
    for k, evs in (paper.params_all or {}).items():
        pages = _pages_of(evs)
        if pages:
            page_hints[k] = pages
    for k, ev in (paper.image_params or {}).items():
        pages = _pages_of([ev])
        if pages:
            page_hints.setdefault(k, pages)

    where: dict = {}
    for name, keys in channel_of.items():
        for k in keys:
            where.setdefault(k, name)

    data = _load()
    old = data.get(fp) or {}
    entry = {
        "title": paper.title or old.get("title", ""),
        "runs": int(old.get("runs") or 0) + 1,
        "last_seen": f"{datetime.now():%Y-%m-%d %H:%M}",
        "unresolved": sorted(seen - got),         # 线索: 已确认"论文没给确定值"
        "page_hints": page_hints,                 # 线索: 参数出现在哪些页
        "where": where,                           # 线索: 取值来自哪条通道
    }
    data[fp] = entry
    _save(data)
    return entry


def hint_lines(fp: str) -> list:
    """把记忆整理成"人话"提示行, 供计划面板与报告展示。"""
    rec = recall(fp)
    if not rec:
        return []
    # 用「本机累计」而不是「第 N 次」——`runs` 会把自动化回归与演示也算进去,
    # 说是"第 95 次审计"容易被误读成假数据; 如实说明计数口径即可, 数字本身不改。
    runs = int(rec.get("runs", 1) or 1)
    lines = [f"本篇论文在本机已审计 {runs} 次（含自动化回归与演示）· 上次 "
             f"{rec.get('last_seen', '—')}"]
    un = rec.get("unresolved") or []
    if un:
        lines.append("上次审计确认『论文未给出确定值』的参数："
                     + "、".join(un) + "（本次仍会重新尝试，不沿用旧结论）")
    ph = rec.get("page_hints") or {}
    if ph:
        sample = "；".join(f"{k} → 第 {','.join(map(str, v[:4]))} 页"
                          for k, v in list(ph.items())[:4])
        lines.append(f"历史候选页（线索，非结论）：{sample}")
    # 记忆库容量状况: 让用户知道"记忆是否被压缩过、摘要里留下了什么"
    lines.extend(digest_lines())
    return lines


def cross_task_stats() -> list:
    """跨论文统计: 哪些参数最常"论文没给出确定值"。只作参考, 不自动应用。

    统计口径**包含已压缩的摘要**, 因此不会因为压缩而"忘记"历史。
    """
    data = _load()
    if not data:
        return []
    digest, entries = _split(data)
    total = int(digest.get("papers_seen") or 0) + len(entries)
    freq: dict = dict(digest.get("unresolved_freq") or {})
    for rec in entries.values():
        for k in (rec or {}).get("unresolved") or []:
            freq[k] = freq.get(k, 0) + 1
    if not freq:
        return [f"记忆库共 {total} 篇论文，暂无「论文未给出确定值」的记录"]
    top = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
    return [f"跨任务线索（{total} 篇论文的统计，仅供参考、不自动套用）："
            + "、".join(f"{k} {v}/{total} 篇" for k, v in top)]


def capacity_info() -> dict:
    """记忆库容量与压缩状态(供界面/报告展示)。"""
    data = _load()
    digest, entries = _split(data)
    raw = json.dumps(data, ensure_ascii=False)
    return {
        "entries": len(entries),                                  # 明细篇数
        "digest_papers": int(digest.get("papers_seen") or 0),     # 摘要覆盖篇数
        "total_papers": int(digest.get("papers_seen") or 0) + len(entries),
        "chars": len(raw),
        "max_entries": MAX_ENTRIES,
        "max_chars": MAX_CHARS,
        "usage": round(len(raw) / MAX_CHARS, 3) if MAX_CHARS else 0.0,
        "compressed_at": digest.get("compressed_at", ""),
    }


def digest_lines() -> list:
    """摘要的人话描述(供界面/报告展示)。"""
    info = capacity_info()
    if not info["digest_papers"]:
        return []
    d = _load().get("_digest") or {}
    lines = [f"记忆库已自动压缩：{info['digest_papers']} 篇早期论文折叠为摘要"
             f"（{d.get('compressed_at', '—')}），明细保留最近 {info['entries']} 篇"
             f"（容量 {info['chars']}/{info['max_chars']} 字符）"]
    freq = d.get("unresolved_freq") or {}
    if freq:
        lines.append("摘要中的高频线索：" + "、".join(
            f"{k} {v} 篇" for k, v in list(freq.items())[:5]))
    return lines


def size() -> int:
    """明细条目数(不含摘要)。"""
    return len(_split(_load())[1])


def entries() -> dict:
    """当前**有效**的记忆明细 —— 已按口径版本过滤掉过期键。

    供校验脚本使用: 直接读文件会把旧口径的残留键也算进来,
    从而把"同标题多指纹"误判成 bug(这些键系统其实永远取不到)。
    """
    return _split(_load())[1]


def clear() -> None:
    _save({})
