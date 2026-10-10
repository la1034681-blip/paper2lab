"""诊断: 结果区的「当前审计对象」条, 到底能不能被 Playwright 的 `text=` 选择器命中。

背景: `ui_test.py` 的上传路径报 "缺少 当前审计对象条"，但同一时刻用
`page.inner_text("body")` 能读到这段文字（`verify_housekeeping_ui.py` 断言过）。
两种口径不一致，必须分清是哪种情况：
  A. 页面还没渲染出来（时序问题 —— 那就该等，而不是改选择器）；
  B. 渲染了，但 `text=` 选择器匹配不到（选择器问题 —— 那就该换判据）。

做法: 起服务 → 点一次运行 → 每 2 秒同时打两种判据，看谁先为真。
"""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8517
URL = f"http://127.0.0.1:{PORT}"

proc = subprocess.Popen(
    [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-X", "utf8", "-m", "streamlit", "run",
     "app.py", "--server.headless", "true", "--server.address", "127.0.0.1",
     "--server.port", str(PORT)],
    cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    from playwright.sync_api import sync_playwright

    ok = False
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=3) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception:      # noqa: BLE001
            time.sleep(2)
    print(f"服务就绪: {ok}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.goto(URL, timeout=60000)
        page.wait_for_timeout(9000)

        def probe(tag: str) -> tuple:
            try:
                body = page.inner_text("body")
            except Exception:      # noqa: BLE001
                body = ""
            in_body = "当前审计对象" in body
            try:
                page.wait_for_selector("text=当前审计对象", timeout=300)
                sel = True
            except Exception:      # noqa: BLE001
                sel = False
            print(f"  [{tag}] body含={in_body}  text选择器命中={sel}", flush=True)
            return in_body, sel

        print("① 点运行前", flush=True)
        probe("前")

        page.get_by_text("开 始 科 研 审 计", exact=False).click()
        print("② 点击后逐 2 秒观察（最多 100 秒）", flush=True)
        t0 = time.time()
        first_body = first_sel = None
        while time.time() - t0 < 100:
            page.wait_for_timeout(2000)
            b, s = probe(f"{time.time() - t0:5.1f}s")
            if b and first_body is None:
                first_body = time.time() - t0
            if s and first_sel is None:
                first_sel = time.time() - t0
            if b and s:
                break

        print("", flush=True)
        print(f"body 文本首次出现: {first_body}s", flush=True)
        print(f"text 选择器首次命中: {first_sel}s", flush=True)
        if first_body is not None and first_sel is not None:
            print("→ 两者都会命中，只是**时间点**不同（时序问题，不是选择器问题）", flush=True)
            print(f"   差值 {(first_sel - first_body):.1f}s", flush=True)
        elif first_body is not None and first_sel is None:
            print("→ **选择器问题**：文字渲染了但 `text=` 匹配不到", flush=True)
        elif first_body is None:
            print("→ 100 秒内文字都没出现（渲染问题，需查渲染路径）", flush=True)
        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:      # noqa: BLE001
        proc.kill()
    print("服务已停", flush=True)
