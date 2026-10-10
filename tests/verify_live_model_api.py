"""线上真机：验证「模型 API / 读图通道」在公网域名上**逻辑真的生效**（不只是改了文案）。

为什么要单列一支：`verify_model_api.py` 验的是**本地**页面，而评委看到的是线上那一份。
线上 Secrets 是空的、默认模型又是纯文本模型 —— 所以线上首屏应当**如实显示"无法读图"**，
这恰恰是评委打开链接时的状态；而一旦在页面上填了多模态模型，就要立刻变成"复用模型 API"。

做法：在**线上页面**填假 Key + `.invalid` 的 Base URL（永不解析）+ 模型名，全程不点
「开始审计」→ **不产生任何 API 调用**。只观察状态行怎么变。
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

URL = "https://paper2lab.streamlit.app/"
SHOTS = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\ui_screenshots")
fails: list[str] = []


def check(ok: bool, label: str) -> None:
    # 防呆：参数传反会让断言永远"通过"（本项目已因此踩过两次）
    assert isinstance(ok, bool), "check() 的第 1 个参数必须是 bool"
    assert isinstance(label, str), "check() 的第 2 个参数必须是 str"
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}", flush=True)
    if not ok:
        fails.append(label)


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location(
        "vls", ROOT / "tests" / "verify_live_site.py")
    vls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vls)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 1300})
        page.goto(URL, wait_until="domcontentloaded", timeout=180_000)
        vls.wake_if_sleeping(page)          # 撞上休眠页就代点唤醒
        frame = vls.find_app_frame(page)
        check(frame is not None, "找到应用 iframe（线上把应用放在 iframe 里）")
        if frame is None:
            b.close()
            return 1
        frame.wait_for_timeout(6000)

        exp = frame.get_by_text("高级设置", exact=False)
        if exp.count():
            exp.first.click()
            frame.wait_for_timeout(2200)

        def wait_for(sub: str, secs: float = 25) -> tuple:
            """等**目标文本**，不要只 sleep（Streamlit 分帧渲染，早取样会假失败）。"""
            end = time.time() + secs
            t = ""
            while time.time() < end:
                t = frame.inner_text("body")
                if sub in t:
                    return True, t
                frame.wait_for_timeout(500)
            return False, t

        ok0, before = wait_for("视觉读图通道")
        check(ok0 and "无法读图" in before,
              "初始状态：未配模型 API → 如实提示**无法读图**（评委打开就是这一屏）")
        page.screenshot(path=str(SHOTS / "L5_高级设置_未配.png"), full_page=True)

        box = frame.locator("div[data-testid='stExpander']").first

        def field(prefix: str):
            return box.locator(f"input[aria-label^='{prefix}']").first

        def setv(loc, val: str):
            # ⚠️ Streamlit 只在**回车/失焦**时提交，只 fill() 改的是 DOM，服务端不知道
            loc.fill(val)
            loc.press("Enter")
            frame.wait_for_timeout(1000)

        setv(field("模型 API Key"), "dummy-key-not-used-no-api-call")
        setv(field("模型 Base URL"), "https://api.example.invalid/v1")
        setv(field("模型名"), "gpt-4o")
        ok1, after = wait_for("复用①的模型 API")
        check(ok1, "填多模态模型(gpt-4o) → 读图**复用模型 API**（无需视觉 key）")
        check("已就绪（gpt-4o）" in after, "主页面通道行显示 已就绪（gpt-4o）")
        check("无法读图" not in after, "不再是「无法读图」状态")

        setv(field("模型名"), "llama-3-70b")
        ok2, t2 = wait_for("视觉读图通道")
        check(ok2 and "复用①的模型 API" not in t2,
              "换单模态模型(llama-3-70b) → 不再复用模型 API 读图")
        page.screenshot(path=str(SHOTS / "L6_高级设置_多模态复用.png"), full_page=True)
        b.close()

    print("\n" + "=" * 60)
    if fails:
        print(f"结论：❌ {len(fails)} 项未通过")
        for f in fails:
            print("   -", f)
        return 1
    print("结论：✅ 线上逻辑已生效（不是只改了文案）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
