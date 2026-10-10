"""真机验证：网页端就是 **agent 模式**（AI 参与决定跑哪些环节），而且**没有开关**。

用户口径（2026-09-29）：
  "输入论文数据后启动它默认 LLM 参与决策决定使用什么工具环节，
   不用的环节工具就显示没运行" + "去除 AI 参与决策开关，因为本来就是默认参与的"。

所以这里断言三件**端到端**的事（不是读代码里的默认值）：
  ① 页面上**没有**「要不要 AI」的开关 —— AI 参与是默认行为本身，不是选项；
  ② 跑完之后执行记录里能看到 **AI 真的参与了排计划**（标签「🧠 AI 排计划」，
     或 notes 里"AI 判定 N 个工具本次不值得跑"）；
  ③ 若 AI 不可用而回退，界面必须**如实说明**（不许悄悄退回规则版还说自己是 AI 排的）。
"""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8518
URL = f"http://127.0.0.1:{PORT}"
fails: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}", flush=True)
    if not ok:
        fails.append(label)


proc = subprocess.Popen(
    [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-X", "utf8", "-m", "streamlit", "run",
     "app.py", "--server.headless", "true", "--server.address", "127.0.0.1",
     "--server.port", str(PORT), "--browser.gatherUsageStats", "false"],
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
    check(ok, "界面服务已起来")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL, timeout=60000)
        page.wait_for_timeout(9000)
        head = page.inner_text("body")

        # ---- ① 不该再有「要不要 AI」的开关
        check("AI 参与决策" not in head,
              "页面上已无「AI 参与决策」开关（AI 参与是默认行为，不是选项）")
        check("兜底开关" in head,
              "「兜底开关」（经典模式）仍在 —— 它是唯一的对照口子，不是 AI 开关")

        # ---- ② 跑一次（演示数据默认已勾选）
        page.get_by_text("开 始 科 研 审 计", exact=False).click()
        for _ in range(120):
            page.wait_for_timeout(2000)
            body = page.inner_text("body")
            if "执行记录" in body:
                break
        page.wait_for_timeout(4000)
        body = page.inner_text("body")

        ai_on = "🧠 AI 排计划" in body
        fell_back = "AI 排计划未生效" in body
        print(f"      含「AI 排计划」标签: {ai_on}；含「未生效」说明: {fell_back}", flush=True)
        check(ai_on or fell_back,
              "执行记录里能看到「AI 参与排计划」的结果（生效，或如实说明未生效）")
        check(not fell_back or "回退规则版" in body,
              "若 AI 未生效，界面如实说明已回退规则版（不假装 AI 排过）")
        check("审计流水线" in body and "执行记录" in body, "结果区正常渲染")
        check(not errors, f"控制台无 JS 报错（{len(errors)} 条）")

        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:      # noqa: BLE001
        proc.kill()
    print("服务已停", flush=True)

print("")
if fails:
    print(f"未通过 {len(fails)} 项：")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("全部通过（网页端即 agent 模式、无开关、AI 未生效时会如实说明）")
