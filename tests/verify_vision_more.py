"""验证「调大读图上限」能否覆盖全部稀薄页并补出缺失参数（真实调用 MiMo）。"""
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from paper2lab.pipeline import run_audit

PDF = r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\01_DDPM\paper.pdf"
ZIP = r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\01_DDPM\code.zip"

import time
t0 = time.time()
audit, report = run_audit(PDF, ZIP, None, force_mock=True,
                          vision_max_regions=int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 9,
                          vision_budget_seconds=900)
img = audit.coverage["image"]
cov = audit.coverage
print(f"=== 上限 {img.get('max_regions')} | 耗时 {time.time()-t0:.1f}s ===")
print(f"候选 {img.get('candidates')} 个 → 送去读图 {img.get('regions')} 个 → 实际读图 {img.get('regions_read')} 个")
print(f"采信 {img.get('kept')} 条, 丢弃 {img.get('dropped')} 条")
print("读图页面:", [r["page"] for r in img.get("region_list", [])])
print("\n稀薄页覆盖:")
print(f"  已读图 : {cov.get('thin_pages_read')}")
print(f"  未读图 : {cov.get('thin_pages_unread')}  ({cov.get('thin_unread_reason') or '—'})")
print("\n种类覆盖:")
print(f"  {cov.get('kinds_valued')}/{cov.get('kinds_seen')} = {cov.get('kinds_ratio')}")
print(f"  仍未取到: {cov.get('kinds_unmatched')}")
print(f"  来源分布: {cov.get('kinds_by_channel')}")
print("\n图像通道读到的全部参数:")
for k, evs in (audit.paper.image_params or {}).items():
    for e in evs:
        print(f"  {k:14} = {e.raw_value!r} @ {e.location}")
print("\n图像通道提示:")
for n in img.get("notes", []):
    print("  -", n[:200])
print(f"\n就绪度 {audit.readiness.get('total')} | 自检 {audit.selfcheck['passed']}/{audit.selfcheck['checked']}")
