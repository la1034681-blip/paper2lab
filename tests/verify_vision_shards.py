"""验证读图通道分片并发（第二期第四批续）。

验证设计同归因那次:
  ① 主验证: 用**离线 mock**（确定性）——串行与并发的读图结果必须**逐字一致**;
  ② 提速: 真实 API 下串行 vs 并发的耗时对比（读图结果本身有随机性, 不作一致性判据）;
  ③ 保序与元信息: regions_read / kept / dropped 必须一致。
"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import json
import os
import time
from pathlib import Path

MOCK = Path("_mock_vision.json")
MOCK.write_text(json.dumps({
    "params": [
        {"name": "dropout", "value": "0.1", "evidence_text": "dropout = 0.1"},
        {"name": "learning_rate", "value": "0.001", "evidence_text": "lr = 0.001"},
        {"name": "batch_size", "value": "32", "evidence_text": "batch size = 32"},
    ]
}, ensure_ascii=False), encoding="utf-8")
os.environ["PAPER2LAB_VISION_MOCK_FILE"] = str(MOCK)

from paper2lab import vision                      # noqa: E402
from paper2lab.envfile import load_env            # noqa: E402

load_env()
ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
VC = vision._cache_path()
backup = VC.read_text(encoding="utf-8") if VC.exists() else None

out: list[str] = []


def clear_cache():
    """让视觉缓存"变空"以便冷跑 —— **清空内容**而不是删文件。

    ⚠️ 实测（2026-09-28）: 本机 shell 对"同一轮删除次数"有安全熔断（阈值 50），超了会直接中止
    进程（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`），Python 层 try/except 接不住。
    写空 JSON 与删文件对本脚本**完全等效**（都让这次不命中缓存），且零删除。
    """
    if not VC.exists():
        return
    VC.write_text("{}", encoding="utf-8")


def sig(found):
    return {k: sorted((e.location, e.raw_value) for e in v) for k, v in found.items()}


def run(pdf, budget, api_key="", tag=""):
    clear_cache()
    t0 = time.time()
    found, meta = vision.analyze_images(pdf, api_key=api_key, budget_seconds=budget,
                                        max_regions=0)
    return found, meta, time.time() - t0


try:
    # ================= ① 主验证：mock（确定性） =================
    PDF = str(ROOT / "01_DDPM" / "paper.pdf")
    out.append("=" * 62)
    out.append("① 主验证 · 离线 mock（确定性，这验证的是分片本身）")
    out.append("=" * 62)
    f1, m1, t1 = run(PDF, 999999)      # budget>0 → workers=1（串行）
    f2, m2, t2 = run(PDF, 0)           # budget=0 → 并发
    out.append(f"  候选区域：{m1.get('candidates')} 个 ｜ 实际读取：{m1.get('regions_read')} 个")
    out.append(f"  串行分片记录：{m1.get('shard')}")
    out.append(f"  并发分片记录：{m2.get('shard')}")
    same = (sig(f1) == sig(f2)) and (m1["regions_read"] == m2["regions_read"]) \
        and (m1["kept"] == m2["kept"]) and (m1["dropped"] == m2["dropped"])
    out.append(f"  【判定】读图结果 + 计数完全一致：{same}")
    out.append(f"    regions_read {m1['regions_read']} vs {m2['regions_read']} ｜ "
               f"kept {m1['kept']} vs {m2['kept']} ｜ dropped {m1['dropped']} vs {m2['dropped']}")
    if not same:
        for k in set(f1) | set(f2):
            if sig(f1).get(k) != sig(f2).get(k):
                out.append(f"    差异 {k}：{sig(f1).get(k)} vs {sig(f2).get(k)}")
    out.append("")

    # ================= ② 提速：真实 API =================
    out.append("=" * 62)
    out.append("② 真实 API 提速实测（结果本身有随机性，只看耗时）")
    out.append("=" * 62)
    os.environ.pop("PAPER2LAB_VISION_MOCK_FILE", None)

    from paper2lab.envfile import get
    key = (get("VISION_API_KEY") or get("DASHSCOPE_API_KEY")
           or get("ZHIPUAI_API_KEY") or "")
    if not key:
        out.append("  未配置视觉 key，跳过")
    else:
        _, m_s, ts = run(PDF, 999999)        # 串行
        _, m_c, tc = run(PDF, 0)             # 并发
        out.append(f"  区域数：{m_s.get('regions_read')} 个（每个区域读两次）")
        out.append(f"  串行：{ts:.1f}s ｜ 分片：{m_s.get('shard')}")
        out.append(f"  并发：{tc:.1f}s ｜ 分片：{m_c.get('shard')}")
        out.append(f"  提速：{ts / tc:.2f}x" if tc else "  提速：—")
finally:
    if backup is not None:
        VC.write_text(backup, encoding="utf-8")
        out.append("")
        out.append("已还原视觉缓存")
    # 这个 mock 文件是本脚本自己的临时中转。**不要删它** —— 本机 shell 对"同一轮删除次数"有
    # 安全熔断（阈值 50），超了会直接中止进程（Python 层接不住），而这个 finally 在脚本末尾，
    # 实测（2026-09-28）会让跑了 9 分钟的验证白跑、还丢掉结果文件。清空内容即可（零删除）。
    try:
        MOCK.write_text("{}", encoding="utf-8")
    except OSError:
        pass

Path("_vshard.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
