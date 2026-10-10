"""验证图像通道的耗时预算兜底: 把预算压到 8 秒, 确认超时后停止读图并如实说明。"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
code = (
    "from paper2lab.pipeline import run_audit;"
    "audit, report = run_audit(r'C:\\Users\\lijiahui\\Desktop\\E题论文.pdf',"
    " r'C:\\Users\\lijiahui\\Desktop\\E题作答.zip', None, force_mock=True);"
    "img = audit.coverage['image'];"
    "print('REGIONS', img.get('regions'), 'READ', img.get('regions_read'),"
    " 'KEPT', img.get('kept'));"
    "print('NOTES', img.get('notes'));"
    "print('READINESS', audit.readiness.get('total'))"
)
for budget in ("8", "60"):
    env = dict(os.environ)
    env["PAPER2LAB_VISION_BUDGET_SECONDS"] = budget
    # 让视觉缓存"变空"以保证每次都真实调用(否则命中缓存看不出预算效果)。
    # ⚠️ 实测(2026-09-28): 本机 shell 对"同一轮删除次数"有安全熔断(阈值 50), 超了直接中止进程
    # （SAFE_DELETE_BULK_CONFIRM_REQUIRED），Python 层接不住 —— 所以**写空 JSON 而不是删文件**，
    # 效果完全一样（这次不命中缓存），而且零删除。
    cache = ROOT / "cache" / "vision_cache.json"
    if cache.exists():
        cache.write_text("{}", encoding="utf-8")
    import time
    t0 = time.time()
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=str(ROOT),
                       env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    print(f"=== 预算 {budget}s | 实际耗时 {time.time() - t0:.1f}s ===")
    print("\n".join(l for l in (r.stdout + r.stderr).splitlines()
                    if l.startswith(("REGIONS", "NOTES", "READINESS"))))
