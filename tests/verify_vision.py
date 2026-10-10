"""图像通道验证——用离线伪造的模型返回跑通链路(无 key 环境)。

验证点:
1. 扫描页被识别为"需读图的区域";
2. 未配置 key 时如实提示"图像通道未启用", 页面内容不计入审计;
3. 配置(mock)后读图结果进入 findings: parser=vlm、confidence=inferred、附人工核对提示;
4. 读图结论不计入就绪度评分(与未启用时总分一致);
5. 文本层已抽到的参数不被读图结果覆盖。
"""
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
DEMO = ROOT / "demo"


def run_once(mock_file: str | None):
    env = dict(os.environ)
    if mock_file:
        env["PAPER2LAB_VISION_MOCK_FILE"] = mock_file
    else:
        env.pop("PAPER2LAB_VISION_MOCK_FILE", None)
    code = (
        "from paper2lab.pipeline import run_audit;"
        "audit, report = run_audit('demo/scan_paper.pdf', 'demo/scan_code.zip', None, force_mock=True);"
        "img = audit.coverage.get('image', {});"
        "print('IMAGE_META', img.get('regions'), img.get('enabled'), img.get('mode'),"
        " img.get('kept'), img.get('dropped'));"
        "print('READINESS', audit.readiness.get('total'));"
        "vlm = [f for f in audit.findings if f.paper and f.paper.parser == 'vlm'];"
        "print('VLM_FINDINGS', [(f.display_name, f.status.value, f.confidence.value,"
        " f.paper.raw_value, (f.code.raw_value if f.code else None)) for f in vlm]);"
        "print('SELFCHECK', audit.selfcheck.get('passed'), audit.selfcheck.get('checked'));"
        "open('demo/scan_audit_report.md','w',encoding='utf-8').write(report)"
    )
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=str(ROOT),
                       env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.stdout + r.stderr


def main():
    print("子进程:", sys.executable, "(mock)", DEMO / "vision_mock.json")
    print("=== 1) 未启用图像通道(无 key 也无 mock) ===")
    out1 = run_once(None)
    print("\n".join(l for l in out1.splitlines() if l.startswith(("IMAGE_META", "READINESS",
                                                                 "VLM_FINDINGS", "SELFCHECK"))))
    print("=== 2) 启用图像通道(离线 mock 返回) ===")
    out2 = run_once(str(DEMO / "vision_mock.json"))
    print("\n".join(l for l in out2.splitlines() if l.startswith(("IMAGE_META", "READINESS",
                                                                 "VLM_FINDINGS", "SELFCHECK"))))
    print("报告已写入 demo/scan_audit_report.md")


if __name__ == "__main__":
    main()
