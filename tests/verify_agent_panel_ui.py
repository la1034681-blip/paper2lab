"""真机验证: 「抽取 Agent」面板是否**随材料变化**。

用户反馈"换什么材料这个面板描述都没变"。数据层已确认会变
（demo 0 待补 / D题 3 待补 / PointNet 2 待补），所以这里验证**界面**。

三种材料各跑一遍, 读出面板的实际文字, 断言三者互不相同且含各自的待补数。
"""
from __future__ import annotations

import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8514
ROOT_SET = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
OUT = ROOT / "_agent_ui.txt"
log: list[str] = []


def say(s: str) -> None:
    log.append(s)
    print(s, flush=True)


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
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/_stcore/health", timeout=3) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception:
            time.sleep(2)
    say(f"服务就绪: {ok}")

    captured: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)

        def run_case(tag: str, pdf: Path | None, code: Path | None) -> str:
            page = browser.new_page(viewport={"width": 1500, "height": 1200})
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(f"http://127.0.0.1:{PORT}", timeout=60000)
            page.wait_for_timeout(9000)

            if pdf is not None:
                inputs = page.locator("input[type=file]")
                inputs.nth(0).set_input_files(str(pdf))
                page.wait_for_timeout(2000)
                if code is not None:
                    inputs.nth(1).set_input_files(str(code))
                    page.wait_for_timeout(2000)

            page.get_by_text("开 始 科 研 审 计", exact=False).click()
            for _ in range(45):
                page.wait_for_timeout(2000)
                if "综合复现就绪度" in page.inner_text("body"):
                    break
            page.wait_for_timeout(2500)

            # 切到「审计可信度」页（抽取 Agent 面板在那里）
            for t in page.locator("[role=tab]").all():
                if "可信度" in t.inner_text():
                    t.click()
                    break
            page.wait_for_timeout(2500)

            exp = page.locator("details").filter(has_text="抽取 Agent")
            say(f"  [{tag}] 匹配到 Agent 展开栏: {exp.count()}")
            if not exp.count():
                if errs:
                    say(f"  [{tag}] ⚠ 控制台异常: {errs[:2]}")
                body = page.inner_text("body")
                page.close()
                return body[:0]
            # 展开后再读（内容是动态生成的，折叠时读不到）
            if not exp.first.get_attribute("open"):
                exp.first.locator("summary").click()
                page.wait_for_timeout(2000)
            txt = exp.first.inner_text()
            if errs:
                say(f"  [{tag}] ⚠ 控制台异常: {errs[:2]}")
            page.close()
            return txt

        say("")
        say("=== A. 内置演示数据（预期：待补 0 类）===")
        captured["demo"] = run_case("demo", None, None)
        say("  " + captured["demo"].replace("\n", " / ")[:300])

        say("")
        say("=== B. 04_PointNet（预期：待补 2 类）===")
        captured["PointNet"] = run_case(
            "PointNet", ROOT_SET / "04_PointNet/paper.pdf", ROOT_SET / "04_PointNet/code.zip")
        say("  " + captured["PointNet"].replace("\n", " / ")[:300])

        say("")
        say("=== C. D题（预期：待补 3 类）===")
        captured["D题"] = run_case(
            "D题", ROOT / "demo/D题论文.pdf", ROOT / "demo/D题代码.zip")
        say("  " + captured["D题"].replace("\n", " / ")[:300])

        browser.close()

    # ---------------- 断言 ----------------
    say("")
    say("=== 断言 ===")
    a, b, c = captured["demo"], captured["PointNet"], captured["D题"]
    checks = [
        ("三种材料都渲染出了面板", all(x.strip() for x in (a, b, c))),
        ("demo 面板标注 待补 0 类", "待补 0 类" in a),
        ("PointNet 面板标注 待补 2 类", "待补 2 类" in b),
        ("D题 面板标注 待补 3 类", "待补 3 类" in c),
        ("demo 与 PointNet 面板不同", a.strip() != b.strip()),
        ("PointNet 与 D题 面板不同", b.strip() != c.strip()),
        ("demo 与 D题 面板不同", a.strip() != c.strip()),
        ("无待补时说明了内核覆盖情况", "本次无需补漏" in a and "已取到" in a),
    ]
    bad = 0
    for label, okk in checks:
        say(f"  [{'OK ' if okk else 'FAIL'}] {label}")
        if not okk:
            bad += 1

    say("")
    say(f"未通过 {bad} 项" if bad else "全部通过（面板确实随材料变化）")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

OUT.write_text("\n".join(log), encoding="utf-8")
print("done")
