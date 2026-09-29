"""分片审查（第二期第四批）——把"一次要处理很多条"的活拆成若干片, 各自独立处理再汇总。

**先说清现状**(避免做一个解决不存在的问题的东西):

本系统的 LLM **从来不是一次性读全部** ——
  · 归因: `llm._build_prompt` 每条结论**单独调用一次**, prompt 里只有这一条的证据片段,
    不含论文全文、不含代码全文;
  · 论文解析 / 代码扫描: 走确定性内核(逐页、逐 AST 文件), **完全不经过大模型**;
  · Agent 补漏: 喂给模型的摘录有 4000 字符硬上限。
因此"一次性读取撑爆上下文"在本架构下**不会发生**。

**那为什么还要分片?** 因为真正的痛点是**串行太慢**:
  · ViT 21 条归因串行约 31s;
  · 一份 25 页扫描件全量读图(多个薄页区域)实测超过 600s, 会直接撞上执行超时。

分片并发正好解决它, 而且它**天生满足"拆分-独立处理-汇总"的诉求**:
  · 每片独立调用, 上下文互不干扰(一片的输入绝不会流到另一片);
  · 一片失败只影响那一片, 如实记录, **绝不假装看过**;
  · 汇总阶段只收结构化结论, 不把原文堆回去, 因此不会二次膨胀。

三条约束:
1. **分片只改变"怎么调度", 不改变"结论是什么"** —— 同一批输入, 串行与分片必须产出
   完全相同的结论(**保序**), 这是本模块最重要的不变式;
2. **单片失败不拖垮全局** —— 失败片记为"未覆盖", 并在报告里如实标出;
3. **并发有上限** —— 防止打爆 API 限流, 默认 4 路。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

DEFAULT_MAX_WORKERS = 4        # 并发上限
SPEEDUP_MIN_ITEMS = 2          # 少于 2 条没必要开线程池


@dataclass
class ShardReport:
    """分片执行的记录 —— 每一片的下场都要说清楚。"""
    total: int = 0
    done: int = 0
    failed: int = 0
    seconds: float = 0.0
    workers: int = 1
    mode: str = "serial"                       # serial | sharded
    label: str = ""
    failures: list = field(default_factory=list)   # [(index, error)]

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "mode": self.mode,
            "total": self.total,
            "done": self.done,
            "failed": self.failed,
            "workers": self.workers,
            "seconds": round(self.seconds, 2),
            "failures": [{"index": i, "error": e} for i, e in self.failures],
        }

    def summary(self) -> str:
        if self.mode == "serial":
            return (f"{self.label}：串行处理 {self.total} 条，"
                    f"{self.seconds:.1f}s")
        return (f"{self.label}：分片并发 {self.workers} 路处理 {self.total} 条"
                f"（失败 {self.failed} 条），{self.seconds:.1f}s")


def run_sharded(items, worker: Callable, *,
                max_workers: int = DEFAULT_MAX_WORKERS,
                enabled: bool = True,
                label: str = "") -> tuple:
    """把 items 分片并发交给 worker, **保序**返回 (results, report)。

    - `worker(index, item)` 处理单条, 返回值按原顺序放进 results;
    - `enabled=False` / `max_workers<=1` / 条目不足时**退化为串行**,
      行为与改造前逐字一致(便于做等价性验证);
    - worker 抛异常时该片记为失败(结果为 None), 其余片照常执行 —— 不静默吞掉。
    """
    items = list(items)
    t0 = time.time()
    results: list = [None] * len(items)
    failures: list = []

    use_pool = enabled and max_workers > 1 and len(items) >= SPEEDUP_MIN_ITEMS

    if not use_pool:
        for i, it in enumerate(items):
            try:
                results[i] = worker(i, it)
            except Exception as ex:      # noqa: BLE001
                failures.append((i, f"{type(ex).__name__}: {ex}"))
        return results, ShardReport(
            total=len(items), done=len(items) - len(failures), failed=len(failures),
            seconds=time.time() - t0, workers=1, mode="serial",
            label=label, failures=failures)

    def _one(pair):
        i, it = pair
        try:
            return i, worker(i, it), None
        except Exception as ex:      # noqa: BLE001
            return i, None, f"{type(ex).__name__}: {ex}"

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for i, res, err in pool.map(_one, list(enumerate(items))):
            if err:
                failures.append((i, err))
            else:
                results[i] = res

    return results, ShardReport(
        total=len(items), done=len(items) - len(failures), failed=len(failures),
        seconds=time.time() - t0, workers=max_workers, mode="sharded",
        label=label, failures=failures)
