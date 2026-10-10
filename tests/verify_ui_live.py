"""一体化: 重启服务(确保加载最新代码) -> 界面结构与渲染检查(含 HTML 泄漏检测)。

用法: .venv\\Scripts\\python.exe verify_ui_live.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
URL = "http://localhost:8501"
OUT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\ui_screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def health_ok() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def kill_port(port: int = 8501) -> None:
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
    except Exception:
        return
    pids = set()
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            pids.add(line.split()[-1])
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)


def start_server() -> subprocess.Popen:
    print("[live] 启动 Streamlit…")
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.headless", "true", "--server.address", "127.0.0.1",
         "--server.port", "8501"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if health_ok():
            print("[live] 服务就绪")
            return proc
        time.sleep(1)
    print("[live] ⚠️ 启动超时")
    return proc


def main() -> None:
    kill_port()
    proc = start_server()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        page = b.new_page(viewport={"width": 1600, "height": 1100})
        errs: list[str] = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("text=审计输入", timeout=60000)
        page.locator('button[kind="primary"]').first.click()
        page.wait_for_selector("text=综合复现就绪度", timeout=120000)
        page.wait_for_timeout(3000)
        body = page.inner_text("body")

        leaks = [m for m in ("</div>", "<span", "class='", 'class="', "evi-loc",
                             "risk-bar", "ai-box", "chip-ghost", "mc-item")
                 if m in body]
        res = {
            "发现卡片": page.locator("div.finding").count(),
            "卡片结论行": page.locator("div.f-head").count(),
            "三列证据块": page.locator("div.f-evi > div.evi").count(),
            "比对结论列": body.count("比对结论"),
            "人工核查清单(主页面)": "需人工核查清单" in body,
            "未参与审计(主页面)": "未参与本次审计的部分" in body,
            "HTML 泄漏": leaks,
            "浏览器异常": errs[:3],
        }
        page.screenshot(path=str(OUT / "07_new_layout.png"), full_page=True)

        for t in page.locator("[role=tab]").all():
            if "可信度" in t.inner_text():
                t.click()
                break
        page.wait_for_timeout(2500)
        tb = page.inner_text("body")
        res["可信度页·核查清单块"] = page.locator("div.mc-item").count()
        res["可信度页·日志条数"] = bool(re.search(r"全部\s*\d+\s*条", tb))
        res["可信度页·未参与部分"] = "未参与本次审计的部分" in tb
        res["可信度页·参数覆盖清单"] = "参数覆盖清单" in tb
        res["可信度页·取值来源分布"] = "取值来源分布" in tb
        res["可信度页·Agent轨迹面板"] = "抽取 Agent 轨迹" in tb
        res["可信度页·泄漏"] = [m for m in ("</div>", "class='", "mc-item") if m in tb]
        page.screenshot(path=str(OUT / "08_trust_new.png"), full_page=True)

        # 回风险项页, 检查"风险判定依据"是否渲染
        for t in page.locator("[role=tab]").all():
            if "风险项" in t.inner_text():
                t.click()
                break
        page.wait_for_timeout(1500)
        rb = page.inner_text("body")
        res["风险判定依据(卡片)"] = rb.count("风险判定依据")
        res["覆盖清单可见(风险页)"] = "参数覆盖清单" in rb or "参数覆盖清单" in tb
        b.close()

    print("=== 界面渲染检查 ===")
    for k, v in res.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
