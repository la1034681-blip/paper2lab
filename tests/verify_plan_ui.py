"""真机验证: 「执行记录」面板是否真的渲染, 以及计划模式能否在界面上跑通。

**注意(2026-09-28 起)**: 调度员已是**默认开启**; 页面上的开关变成了
「⚠️ 兜底开关：强制跑完全部环节（关闭调度员）」。因此本脚本**不再需要点开关**,
直接点开始即为计划模式。
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8511
OUT = ROOT / "_plan_ui.txt"
log: list[str] = []


def say(s: str):
    log.append(s)
    print(s, flush=True)


# 1) 起服务
proc = subprocess.Popen(
    [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-X", "utf8", "-m", "streamlit", "run",
     "app.py", "--server.headless", "true", "--server.address", "127.0.0.1",
     "--server.port", str(PORT)],
    cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    from playwright.sync_api import sync_playwright

    # 等健康检查通过
    import urllib.request
    ok = False
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/_stcore/health", timeout=3) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception:
            time.sleep(2)
    say(f"服务就绪: {ok}")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{PORT}", timeout=60000)
        page.wait_for_timeout(9000)
        say(f"页面文本长度: {len(page.inner_text('body'))}")
        say(f"含「兜底开关」: {'兜底开关' in page.inner_text('body')}")

        # 调度员已默认开启, 无需点开关 —— 直接点开始即为计划模式
        # 点开始
        page.get_by_text("开 始 科 研 审 计", exact=False).click()
        for _ in range(60):
            page.wait_for_timeout(2000)
            body = page.inner_text("body")
            if "执行记录" in body:
                break

        page.wait_for_timeout(4000)
        body = page.inner_text("body")
        say("")
        say("=== 页面关键内容检查 ===")
        for key in ["执行记录", "计划模式", "审计流水线", "调度员的决策"]:
            say(f"  含「{key}」: {key in body}")

        m = re.search(r"执行记录[^\n]{0,140}", body)
        say(f"  执行记录行: {m.group(0) if m else '未找到'}")

        page.screenshot(path=str(ROOT / "_plan_ui.png"), full_page=False)
        say("")
        say(f"控制台异常: {len(errors)} {errors[:3]}")
        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

OUT.write_text("\n".join(log), encoding="utf-8")
print("done")
