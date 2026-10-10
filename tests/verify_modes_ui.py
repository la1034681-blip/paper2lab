"""真机验证: 经典模式 与 计划模式 在界面上是否**看得出差别**。

四种组合各跑一遍, 抓「执行记录」面板的实际文字:
  A 经典 + 演示数据(材料齐备)      → 应显示"强制全跑（兜底模式）", 无跳过
  B 计划 + 演示数据(材料齐备)      → 应显示"调度员排计划"/"AI 排计划", 并如实呈现执行集合
  C 经典 + 只传论文(无代码)        → 代码扫描仍执行(经典模式不看材料)
  D 计划 + 只传论文(无代码)        → 代码扫描被跳过, 且给出理由  ← 两模式的真正差别

⚠️ 断言口径（2026-09-29 调整）：**不写死跳过数**。
网页端**恒开** AI 参与决策（不设开关），AI 会按成本判断额外跳过环节（实测 B 从 0 跳过变 1、D 从 3 变 4）
—— 那正是 agent 在起作用，不是回归。所以这里守的是**契约**：
  · 执行 + 跳过 = 全部工具（执行集合如实呈现）
  · 每个跳过都有理由可查（决策表在）
  · 流程面板的「未执行」次数不少于被跳过的工具数（面板跟着实际执行走）
  · AI 要么说明"判定了几个不值得跑"，要么如实说"未生效"，不许含糊
"""
from __future__ import annotations

import re
import subprocess
import time
import urllib.request
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from paper2lab.toolbox import TOOLS       # noqa: E402  （断言"执行+跳过=全部工具"要用）
PORT = 8513
PAPER = ROOT / "demo" / "paper.pdf"
OUT = ROOT / "_modes_ui.txt"
SHOTS = ROOT / "_shot_classic.png", ROOT / "_shot_plan.png"
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

    results: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)

        def run_case(tag: str, planner: bool, upload_paper: bool) -> str:
            page = browser.new_page(viewport={"width": 1500, "height": 1200})
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(f"http://127.0.0.1:{PORT}", timeout=60000)
            page.wait_for_timeout(9000)

            # 现在**默认就是计划模式**（调度员排计划）；只有打开「兜底开关」才切到经典模式。
            if not planner:
                lab = page.locator("label").filter(has_text="兜底开关")
                if lab.count():
                    lab.first.click()
                    page.wait_for_timeout(2500)
            if upload_paper:
                inputs = page.locator("input[type=file]")
                inputs.nth(0).set_input_files(str(PAPER))
                page.wait_for_timeout(2500)

            page.get_by_text("开 始 科 研 审 计", exact=False).click()
            body = ""
            for _ in range(45):
                page.wait_for_timeout(2000)
                body = page.inner_text("body")
                if "执行记录" in body:
                    break
            page.wait_for_timeout(3000)
            body = page.inner_text("body")

            shot = SHOTS[1] if planner else SHOTS[0]
            page.screenshot(path=str(shot))
            if errs:
                say(f"  ⚠ {tag} 控制台异常 {len(errs)}: {errs[:2]}")
            page.close()
            return body

        say("")
        say("=== A. 经典模式 + 演示数据（材料齐备）===")
        a = run_case("A", planner=False, upload_paper=False)
        results["A"] = a
        for k in ["经典模式", "强制全跑", "不看材料齐不齐", "调度员的决策", "计划跳过"]:
            say(f"  含「{k}」: {k in a}")

        say("")
        say("=== B. 计划模式 + 演示数据（材料齐备）===")
        b = run_case("B", planner=True, upload_paper=False)
        results["B"] = b
        for k in ["计划模式", "调度员排计划", "调度员的决策", "执行集合与经典模式相同"]:
            say(f"  含「{k}」: {k in b}")

        say("")
        say("=== C. 经典模式 + 只传论文（无代码）===")
        c = run_case("C", planner=False, upload_paper=True)
        results["C"] = c
        for k in ["经典模式", "强制全跑", "计划跳过", "未执行"]:
            say(f"  含「{k}」: {k in c}")

        say("")
        say("=== D. 计划模式 + 只传论文（无代码）===")
        d = run_case("D", planner=True, upload_paper=True)
        results["D"] = d
        for k in ["计划模式", "调度员排计划", "调度员的决策", "计划跳过", "未提供代码包", "未执行"]:
            say(f"  含「{k}」: {k in d}")

        browser.close()

    # ---------------- 断言 ----------------
    # 注: 执行明细表用 st.dataframe, 是 canvas 渲染的, inner_text 读不到单元格文本;
    #     因此改从**展开栏标题**（DOM 可见）读"执行 N 个 / 跳过 M 个"来判定。
    def counts(body: str) -> tuple:
        m = re.search(r"执行\s*(\d+)\s*个工具\s*/\s*跳过\s*(\d+)\s*个", body)
        return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)

    say("")
    say("=== 从展开栏标题读到的执行计数 ===")
    cs = {k: counts(v) for k, v in results.items()}
    for k in "ABCD":
        say(f"  {k}: 执行 {cs[k][0]} 个 / 跳过 {cs[k][1]} 个")

    say("")
    say("=== 断言 ===")
    checks = [
        ("A 是经典模式", "经典模式" in results["A"]),
        ("A 标明是兜底强制全跑", "强制全跑" in results["A"]),
        ("A 没有「调度员的决策」", "调度员的决策" not in results["A"]),
        ("A 无跳过", cs["A"][1] == 0),
        # ---- 计划模式有两条标签都算数：规则版「计划模式」/ AI 版「AI 排计划」。
        # 2026-09-29 起网页端恒开 AI 参与（无开关），标签会变成后者 —— 断言不能只认前者。
        ("B 是计划模式且有调度决策",
         ("计划模式" in results["B"] or "AI 排计划" in results["B"])
         and "调度员的决策" in results["B"]),
        # ---- 跳过数**不再写死**：AI 会按成本判断额外跳过（这正是 agent 在起作用，
        # 实测 B 从 0 跳过变成 1 跳过、D 从 3 变成 4）。要守住的是"契约"而不是某个数字。
        ("B 执行集合如实呈现（执行 + 跳过 = 全部工具）",
         cs["B"][0] + cs["B"][1] == len(TOOLS)),
        ("B 的跳过都有理由可查（决策表在）", "调度员的决策" in results["B"]),
        ("C（经典·无代码）代码扫描仍执行、无跳过", cs["C"][1] == 0),
        # 2026-09-28: 「根因追查 / 补丁草案」登记成工具后, 无代码时**至少**这三个被跳过
        # （代码扫描 + 根因追查 + 补丁草案 —— 后两者都要读代码）。
        # 2026-09-29: 由「== 3」放宽为「>= 3」—— AI 参与排计划时还可能额外跳过别的环节。
        ("D（计划·无代码）至少跳过 3 个（代码扫描 / 根因 / 补丁）", cs["D"][1] >= 3),
        ("D 执行集合如实呈现（执行 + 跳过 = 全部工具）",
         cs["D"][0] + cs["D"][1] == len(TOOLS)),
        ("D 给出了跳过理由", "未提供代码包" in results["D"]),
        ("同输入下 C 与 D 的执行集合确实不同", cs["C"][1] != cs["D"][1]),
        # ---- 流程面板（十二环节进度条）必须跟着**实际执行**走
        ("经典模式（A / C）不出现「未执行」",
         "未执行" not in results["A"] and "未执行" not in results["C"]),
        ("D 流程面板标出了「未执行」", "未执行" in results["D"]),
        # 每个被跳过的工具至少标出一处「未执行」（不写死次数：跳过数随 AI 判断波动）
        ("B / D 的「未执行」次数不少于被跳过的工具数",
         results["B"].count("未执行") >= cs["B"][1]
         and results["D"].count("未执行") >= cs["D"][1]),
        # ---- agent 的决策必须留痕：生效要写"AI 判定 N 个不值得跑"，不可用要如实说"未生效"
        ("AI 决策留痕（生效说明 或 未生效说明，二者必居其一）",
         "AI 排计划" in results["B"] or "AI 排计划未生效" in results["B"]),
    ]
    bad = 0
    for label, okk in checks:
        say(f"  [{'OK ' if okk else 'FAIL'}] {label}")
        if not okk:
            bad += 1

    say("")
    say("说明: 执行明细表用 canvas 渲染, DOM 读不到单元格 —— 其内容（含「环节」列与"
        "「这次实际做出了什么」列）由 verify_execview.py 以数据层断言覆盖。")
    say(f"截图: {SHOTS[0].name} / {SHOTS[1].name}")
    say("")
    say(f"未通过 {bad} 项" if bad else "全部通过（说明两模式在界面上确实可区分）")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

OUT.write_text("\n".join(log), encoding="utf-8")
print("done")
