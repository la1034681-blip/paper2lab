"""线上验收：打开 https://paper2lab.streamlit.app/，确认部署成功、首屏正确，
可用 --e2e 让它在线上真跑一遍内置演示，验到"出结果"为止。

复用项目已装的 Playwright（与 verify_access_gate.py 同一套，channel=msedge）。

用法：
    .venv\\Scripts\\python.exe verify_live_site.py           # 只验首屏（约 10 秒）
    .venv\\Scripts\\python.exe verify_live_site.py --e2e     # 连跑一遍演示（约 1-3 分钟）

三个踩过的坑，写在这里免得下次再犯：
1. **Streamlit Community Cloud 把应用放在 iframe 里**（src 形如
   https://<app>.streamlit.app/~/+/）。在顶层文档里找 stAppViewContainer 永远找不到，
   div#root 是空的 —— 必须进入该 frame 取正文。
2. 判定"渲染好了"要用**等目标文本**，不能用"等 body 变长"：后者会撞上
   Streamlit 分帧渲染的中间态，制造假失败（ui_test / verify_access_gate 都踩过）。
3. 按钮的可访问名里有空格（"🚀 开 始 科 研 审 计"），精确匹配会找不到 ——
   取 innerText 去掉空格后再比。
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://paper2lab.streamlit.app/"
SHOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab_线上首屏.png")
SHOT_E2E = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab_线上审计结果.png")
DUMP = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\ui_screenshots") / "live_dom_dump.html"

GATE_TEXT = "访问口令"            # 口令门存在时的标志
MAIN_TEXT = "使用内置演示数据"     # 进入主界面后的标志
RUN_TEXT = "开始科研审计"          # 运行按钮（比对时会去掉空格）
DONE_TEXT = "一致性证据"           # 结果页标签页（app.py:1122）
# 注意：**不能**拿"风险项"当完成标志 —— 顶部导航栏里就有这四个字，
# 会立刻假命中（第一次跑就是 0.1s 假成功）。
APP_FRAME_MARK = "/~/+/"           # Streamlit Cloud 应用 iframe 的 URL 特征


def find_app_frame(page, timeout_ms: int = 180_000):
    """找到承载应用的 iframe（Frame 对象）。"""
    waited = 0
    while waited < timeout_ms:
        for f in page.frames:
            try:
                if APP_FRAME_MARK in (f.url or ""):
                    return f
            except Exception:
                continue
        page.wait_for_timeout(1000)
        waited += 1000
    return None


def wait_text(scope, needles: list[str], timeout_ms: int, step: int = 1500):
    """在给定作用域（page 或 frame）里等任一句目标文本出现。"""
    waited = 0
    last = ""
    while waited < timeout_ms:
        try:
            t = scope.inner_text("body")
        except Exception:
            t = ""
        if t:
            last = t
            for n in needles:
                if n in t:
                    return n, t, waited
        scope.wait_for_timeout(step)
        waited += step
    return None, last, waited


def click_run(frame) -> bool:
    """点「开始科研审计」按钮。

    注意：标签里的"空格"可能是不换行空格(\\u00a0)或全角空格(\\u3000)，
    所以用正则把所有空白一并去掉再比对 —— 只 replace(" ") 会漏。
    找不到时把页面上所有按钮的标签打出来，便于定位而不是瞎猜。
    """
    els = []
    try:
        els = frame.locator("button").all()
    except Exception as exc:  # noqa: BLE001
        print(f"枚举 button 失败：{exc}")
    print(f"页面上的 button 共 {len(els)} 个：")
    target = None
    for i, b in enumerate(els):
        try:
            raw = b.inner_text()
        except Exception as exc:  # noqa: BLE001
            raw = f"<inner_text 失败: {exc}>"
        norm = re.sub(r"[\s\u00a0\u3000]+", "", raw or "")
        print(f"  [{i}] {norm[:40]!r}")
        if target is None and RUN_TEXT in norm:
            target = b
    if target is None:
        return False
    try:
        target.click()
    except Exception as exc:  # noqa: BLE001
        print(f"常规定位点击失败({exc})，改用 force 点击…")
        target.click(force=True)
    return True


SLEEP_MARK = re.compile(r"gone to sleep|Zzzz", re.I)
WAKE_TEXT = re.compile(r"get this app back up", re.I)


def wake_if_sleeping(page, wait_ms: int = 30_000) -> bool:
    """撞上平台休眠页就代点一次唤醒按钮。

    官方行为（docs → Manage your app → App hibernation）：
    **无访问 12 小时后应用进入休眠**，访问者会看到休眠页，
    点 "Yes, get this app back up!" 即可唤醒 —— **任何能看到该应用的人都能点**，
    不限于开发者。不处理这一页的话，检查器会报"找不到 iframe"这种看不懂的失败。

    ⚠️ 2026-10-02 实测修正：休眠页是**动态渲染**的，`domcontentloaded` 当场读 body
    可能是空的 —— 原写法"只读一次"会静默漏判，然后白等 180s 才报"找不到 iframe"
    （连跑两次都这样，极易误判成构建失败）。现改为**轮询等待**（默认 30s）。
    """
    waited = 0
    while True:
        try:
            t = page.inner_text("body")
        except Exception:  # noqa: BLE001
            t = ""
        if SLEEP_MARK.search(t or ""):
            break
        if waited >= wait_ms:
            return False
        page.wait_for_timeout(1000)
        waited += 1000
    for loc in (page.get_by_role("button", name=WAKE_TEXT),
                page.get_by_text(WAKE_TEXT)):
        try:
            if loc.count():
                loc.first.click()
                return True
        except Exception:  # noqa: BLE001
            continue
    print("    （识别到休眠页，但没找到唤醒按钮，请人工点一下）")
    return False


def main() -> int:
    do_e2e = "--e2e" in sys.argv
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))

        t0 = time.time()
        page.goto(URL, wait_until="domcontentloaded", timeout=180_000)

        if wake_if_sleeping(page):
            print("⚠️ 实例处于休眠状态，已代点『Yes, get this app back up!』唤醒…")
            page.wait_for_timeout(6000)

        frame = find_app_frame(page, timeout_ms=60_000)
        if frame is None and wake_if_sleeping(page, wait_ms=10_000):
            # 第二次机会：慢网络下休眠页可能比第一轮轮询更晚才出现。
            # 不给第二次机会的话，一次漏判就要白等满超时才失败。
            print("⚠️ 二次识别到休眠页，再次代点『Yes, get this app back up!』唤醒…")
            page.wait_for_timeout(6000)
            frame = find_app_frame(page, timeout_ms=180_000)
        if frame is None:
            print("❌ 没找到应用 iframe（页面可能还在构建/唤醒）")
            print("页面标题 :", page.title())
            try:
                # 把顶层正文打出来：休眠页会直接显示 Zzzz，一眼可辨，
                # 省得下次又在"构建失败 / 网络抖动 / 休眠"之间瞎猜。
                print("顶层正文片段 :", (page.inner_text("body") or "")[:200])
            except Exception:  # noqa: BLE001
                pass
            browser.close()
            return 1
        print(f"应用 iframe: {frame.url}")

        hit, text, waited = wait_text(frame, [GATE_TEXT, MAIN_TEXT], 180_000)
        if not hit:
            print("首屏未出现，再等 60s 复查…")
            hit, text, _ = wait_text(frame, [GATE_TEXT, MAIN_TEXT], 60_000)
        print(f"首屏耗时 : {time.time() - t0:.1f}s（其中等待 {waited / 1000:.1f}s）")
        print(f"页面标题 : {page.title()}")
        print("=" * 64)
        print("应用正文：")
        print(text[:1000] if text else "<空>")
        print("=" * 64)

        # 经验性检查：正文里不该出现未求值的 {占位符}。
        # 线上实测抓到过 `{len(STEPS)} 步` 直接显示给用户（漏 f 前缀），
        # 用"渲染后扫正文"来兜这类 bug 比任何静态推断都可靠。
        leaks = re.findall(r"\{[^{}\n]{1,60}\}", text or "")
        if leaks:
            print(f"⚠️ 正文发现未求值的占位符 {len(leaks)} 处：{leaks[:6]}")
        else:
            print("✅ 正文没有未求值的占位符（{...}）")

        # 安全断言：所有密码框必须是空的 —— key 绝不能被发到浏览器。
        # 2026-09-30 加固前 `value=<服务端key>` 会把真 key 随页面发下来，
        # 链接公开后任何人打开开发者工具就能读走。
        try:
            # 密钥框在「高级设置」折叠区里，先展开
            exp = frame.get_by_text("高级设置", exact=False)
            if exp.count():
                exp.first.click()
                frame.wait_for_timeout(1500)
            pws = frame.locator("input[type=password]")
            n = pws.count()
            filled = [i for i in range(n) if pws.nth(i).input_value()]
            if filled:
                print(f"❌ 有 {len(filled)}/{n} 个密钥输入框被预填 —— key 会被发到浏览器！")
            else:
                print(f"✅ {n} 个密钥输入框全部为空（key 不进浏览器）")
        except Exception as exc:  # noqa: BLE001
            print(f"密钥框检查失败：{exc}")

        if hit == GATE_TEXT:
            print("首屏判定：✅ 部署成功，口令门生效")
        elif hit == MAIN_TEXT:
            print("首屏判定：✅ 部署成功，但**没有口令门**（拿到链接即可使用）")
        else:
            print("首屏判定：❌ 未识别到预期首屏")
            browser.close()
            return 1

        ok_e2e = True
        if hit == MAIN_TEXT and do_e2e:
            print("=" * 64)
            print("▶ 端到端：在线上跑一遍内置演示…")
            t1 = time.time()
            if not click_run(frame):
                print("❌ 没找到「开始科研审计」按钮")
                ok_e2e = False
            else:
                d_hit, d_text, d_wait = wait_text(frame, [DONE_TEXT], 300_000)
                print(f"审计耗时 : {time.time() - t1:.1f}s")
                if d_hit:
                    print(f"✅ 出结果了（命中「{d_hit}」）")
                    print("-" * 64)
                    print("结果页正文（前 1500 字）：")
                    print(d_text[:1500])
                else:
                    print("❌ 没等到结果页；页面当前正文：")
                    print(d_text[:1500] if d_text else "<空>")
                    ok_e2e = False
                try:
                    page.screenshot(path=str(SHOT_E2E))
                    print(f"结果截图：{SHOT_E2E}")
                except Exception as exc:  # noqa: BLE001
                    print(f"截图失败：{exc}")

        # 需求单第 2 项：hero 必须**真的**渲染出「12 步」。
        # 上面的"无未求值占位符"只是**代理断言**：万一 hero 压根没渲染出来
        # （首屏正文没取全 / 组件被删），它会空跑通过、给出假绿。
        # 所以这里补一条正向命中断言；只在主界面分支生效（口令门分支没有 hero）。
        hero_ok = True
        if hit == MAIN_TEXT:
            hero_ok = "12 步" in (text or "")
            if hero_ok:
                print("✅ hero 渲染出「12 步」（不是 {len(STEPS)} 占位符）")
            else:
                print("❌ hero 未出现「12 步」—— 疑似漏 f 前缀回归，或首屏正文没取全")

        if errors:
            print("页面异常：")
            for e in errors[-5:]:
                print("  " + e)

        try:
            page.screenshot(path=str(SHOT))
            print(f"首屏截图：{SHOT}")
        except Exception as exc:  # noqa: BLE001
            print(f"截图失败：{exc}")
        try:
            DUMP.parent.mkdir(parents=True, exist_ok=True)
            DUMP.write_text(frame.content(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        browser.close()
    return 0 if (ok_e2e and hero_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
