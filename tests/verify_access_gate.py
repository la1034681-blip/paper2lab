"""访问口令门 与 **部署目录自洽性** 的真机验证。

两件事一起验（它们本来就是一回事）：
  ① 部署目录 `deploy/` 能不能独立跑起来 —— 云平台上就是"仓库根目录 + 一份依赖清单",
     所以必须证明：**脱离工程根目录、只靠 deploy/ 自己也能启动并渲染首屏**;
  ② 访问口令门的三种行为 —— 不设口令=无门 · 设了口令=有门 · 口令错=不放行。

用法: .venv\\Scripts\\python.exe verify_access_gate.py
不调任何外部 API（不花额度），只用本地浏览器与本地服务。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent.parent
DEPLOY = HERE / "deploy"
PORT = 8514
URL = f"http://127.0.0.1:{PORT}"
CODE = "QA-TEST-9527"

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def health_ok() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def start(code: str | None):
    env = dict(os.environ)
    env.pop("PAPER2LAB_ACCESS_CODE", None)
    env.pop("ACCESS_CODE", None)
    if code:
        env["PAPER2LAB_ACCESS_CODE"] = code
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.headless", "true", "--server.port", str(PORT),
         "--server.address", "127.0.0.1", "--browser.gatherUsageStats", "false"],
        cwd=str(DEPLOY), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if health_ok():
            return proc
        time.sleep(1)
    return proc


def stop(proc) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def body(page, tries: int = 20) -> str:
    """等页面渲染出内容再取全文（Streamlit 是前端渲染，必须等）。"""
    for _ in range(tries):
        try:
            t = page.inner_text("body")
            if t and len(t) > 30:
                return t
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return ""


def wait_text(page, marker: str, timeout_ms: int = 60000) -> bool:
    """等某个文本真的出现在页面上。

    ⚠️ 为什么不能用"body 长度 > 30"当判据（2026-09-30 实测）:
      Streamlit 首屏是**分帧渲染**的 —— 先到 CSS 与骨架，正文稍后才到。
      用长度判据会拿到一个"非空但还没正文"的中间态，于是断言随机失败。
      这类"检查器自己的等待策略"造成的假失败，前面已经踩过一次（ui_test 的 1.5s 假通过），
      所以这里统一改成"等目标文本"，不用任何长度/时间启发式。
    """
    t0 = time.time()
    while (time.time() - t0) * 1000 < timeout_ms:
        try:
            if marker in page.inner_text("body"):
                return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


print("① 部署目录自洽性：只靠 deploy/ 能否独立启动并渲染")
check(DEPLOY.is_dir(), "deploy/ 存在（先跑 make_deploy.py 生成）")
check((DEPLOY / "app.py").exists() and (DEPLOY / "paper2lab").is_dir()
      and (DEPLOY / "demo" / "paper.pdf").exists() and (DEPLOY / "requirements.txt").exists(),
      "deploy/ 含 app.py + paper2lab/ + demo/ + requirements.txt")

proc = start(None)
try:
    check(health_ok(), "服务在 deploy/ 里以只读方式启动成功（不依赖工程根目录）")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.goto(URL, wait_until="domcontentloaded")
        ok = wait_text(page, "使用内置演示数据")
        check(ok, "首屏渲染出材料输入区（演示数据开关可见）")
        check("访问口令" not in page.inner_text("body"),
              "未设 PAPER2LAB_ACCESS_CODE 时**不出现**口令门（本地零打扰）")
        browser.close()
finally:
    stop(proc)

print("\n② 访问口令门：设了口令之后")
proc = start(CODE)
try:
    check(health_ok(), "带口令启动成功")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.goto(URL, wait_until="domcontentloaded")
        check(wait_text(page, "访问口令"), "出现口令门（拿到链接 ≠ 能跑审计）")
        check("使用内置演示数据" not in page.inner_text("body"),
              "未通过口令时**看不到**应用主体")

        # 错误口令
        page.get_by_role("textbox").first.fill("wrong-code")
        page.get_by_text("进 入", exact=False).click()
        check(wait_text(page, "口令不正确", 20000), "口令错误被拒绝并提示")

        # 正确口令
        page.get_by_role("textbox").first.fill(CODE)
        page.get_by_text("进 入", exact=False).click()
        check(wait_text(page, "使用内置演示数据", 45000), "口令正确后进入应用主体")
        browser.close()
finally:
    stop(proc)

print("\n③ 口令逻辑单测（不依赖 Streamlit）")
sys.path.insert(0, str(HERE))
from paper2lab.access import configured_code, gate_enabled, verify_code   # noqa: E402

os.environ.pop("PAPER2LAB_ACCESS_CODE", None)
os.environ.pop("ACCESS_CODE", None)
check(configured_code() == "" and not gate_enabled(), "未配置时：无口令、门关闭")
check(verify_code("任意") is True, "未配置时：任何输入都放行（等于没有门）")
os.environ["PAPER2LAB_ACCESS_CODE"] = CODE
check(gate_enabled() and configured_code() == CODE, "配置后：门开启且读取正确（PAPER2LAB_ACCESS_CODE）")
check(verify_code(CODE) and not verify_code("x") and not verify_code(""), "配置后：对/错/空 三种输入判定正确")
check(verify_code("  " + CODE + "  "), "两侧空白被容忍（评委复制粘贴不背锅）")

print()
if fails:
    print(f"未通过 {len(fails)} 项：")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("全部通过：部署目录可独立运行；口令门在该开时开、该关时关。")
