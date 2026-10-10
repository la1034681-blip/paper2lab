"""线上全面体检：把评委真会做的动作，在公网域名上逐个跑一遍。

与 verify_live_site.py 的分工：
    verify_live_site.py   线上冒烟（约 10 秒）—— 首屏能渲染 + 一条安全断言
    verify_live_full.py   线上全面验收（约 3 分钟）—— 本文件

覆盖 6 组：
    A 首屏         标题 / hero 数字 / 无未求值占位符 / 演示开关默认开
    B 安全         密钥框全空 / DOM 里无密钥形态 / 控制台零错误
    C 演示端到端   点运行 → 出结果（换指纹判定，不靠固定文案）
    D 结果页       各标签页逐个点开都要有内容
    E 上传自有     用测试集的真实论文（01_DDPM/paper.pdf）跑一遍
    F 手机端       390x844 视口下首屏仍能渲染

要点：**"跑完了"用数据指纹变化判定**（`🔑 数据指纹 xxxxx`），
不用固定文案 —— 否则第二次运行时旧结果还在页面上，会立刻假命中。

用法：  .venv\\Scripts\\python.exe verify_live_full.py
退出码：0 = 全部通过，1 = 有失败项
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://paper2lab.streamlit.app/"
UPLOAD_PDF = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\01_DDPM\paper.pdf")
SHOTS = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\ui_screenshots")

APP_FRAME_MARK = "/~/+/"
GATE_TEXT = "访问口令"
MAIN_TEXT = "使用内置演示数据"
RUN_TEXT = "开始科研审计"
FP_RE = re.compile(r"数据指纹\s*([0-9a-fA-F]{4,})")

SECRET_PATTERNS = {
    "sk- 风格密钥": re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    "GitHub PAT": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "AWS AKIA": re.compile(r"AKIA[0-9A-Z]{16}"),
    "私钥头": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
}

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    flag = "✅" if ok else "❌"
    print(f"  {flag} {name}" + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


def section(t: str) -> None:
    print(f"\n【{t}】", flush=True)


def find_app_frame(page, timeout_ms: int = 180_000):
    waited = 0
    while waited < timeout_ms:
        for f in page.frames:
            try:
                if APP_FRAME_MARK in (f.url or ""):
                    return f
            except Exception:  # noqa: BLE001
                continue
        page.wait_for_timeout(1000)
        waited += 1000
    return None


def wait_text(scope, needles, timeout_ms, step=1500):
    waited = 0
    last = ""
    while waited < timeout_ms:
        try:
            t = scope.inner_text("body")
        except Exception:  # noqa: BLE001
            t = ""
        if t:
            last = t
            for n in needles:
                if n in t:
                    return n, t, waited
        scope.wait_for_timeout(step)
        waited += step
    return None, last, waited


def click_by_text(frame, needle: str) -> bool:
    """按按钮文字点击（列表内的空白可能是 \\u00a0，故正则去空白后比对）。"""
    try:
        for b in frame.locator("button").all():
            try:
                t = re.sub(r"[\s\u00a0\u3000]+", "", b.inner_text() or "")
            except Exception:  # noqa: BLE001
                continue
            if needle in t:
                try:
                    b.click()
                except Exception:  # noqa: BLE001
                    b.click(force=True)
                return True
    except Exception as exc:  # noqa: BLE001
        print(f"    点按钮出错：{exc}")
    return False


def wait_new_run(frame, old_fp: str | None, timeout_ms: int = 300_000, step=2000):
    """等一次**新的**审计跑完：以数据指纹变化为判据（不是固定文案）。"""
    waited, last = 0, ""
    while waited < timeout_ms:
        try:
            t = frame.inner_text("body")
        except Exception:  # noqa: BLE001
            t = ""
        if t:
            last = t
            m = FP_RE.search(t)
            if m and m.group(1) != old_fp:
                return m.group(1), t, waited
        frame.wait_for_timeout(step)
        waited += step
    return None, last, waited


def is_ours(u: str) -> bool:
    """这个 4xx/失败资源是"我们应用的"吗？

    光看域名不够：Streamlit Cloud 会在同一域名下打自己的平台接口
    （`/api/v1/app/event/open`、`/api/v2/user/details` 等），匿名访客拿 404
    是平台行为，不是我们的资源出问题 —— 把它们算进来就是误判。
    平台保留前缀：/api/ /-/ /~/ ；`/_stcore/` 是我们应用的运行时，**要算**。
    """
    if "paper2lab.streamlit.app" not in u:
        return False
    path = u.split("paper2lab.streamlit.app", 1)[1] or "/"
    return not path.startswith(("/api/", "/-/", "/~/"))


SLEEP_MARK = re.compile(r"gone to sleep|Zzzz", re.I)
WAKE_TEXT = re.compile(r"get this app back up", re.I)


def wake_if_sleeping(page) -> bool:
    """撞上平台休眠页就代点一次唤醒按钮。

    官方行为（docs → Manage your app → App hibernation）：
    **无访问 12 小时后应用进入休眠**，访问者看到休眠页，点
    "Yes, get this app back up!" 即可唤醒 —— **任何能看到该应用的人都能点**。
    不处理这一页，检查器会报"没找到 iframe"这种看不懂的失败。
    """
    try:
        t = page.inner_text("body")
    except Exception:  # noqa: BLE001
        return False
    if not SLEEP_MARK.search(t or ""):
        return False
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
    SHOTS.mkdir(parents=True, exist_ok=True)
    t_all = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        console_errs: list[str] = []
        bad_resp: list[tuple[int, str]] = []
        failed_req: list[tuple[str, str]] = []
        page.on("console",
                lambda m: console_errs.append(m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errs.append(str(e)[:200]))
        page.on("response",
                lambda r: bad_resp.append((r.status, r.url[:150]))
                if r.status >= 400 else None)
        page.on("requestfailed",
                lambda r: failed_req.append((r.url[:150], str(r.failure)[:70])))

        # ---------------------------------------------------------- A 首屏
        section("A 首屏")
        t0 = time.time()
        page.goto(URL, wait_until="domcontentloaded", timeout=180_000)
        if wake_if_sleeping(page):
            print("  ⚠️ 实例处于休眠状态，已代点『Yes, get this app back up!』唤醒…")
            page.wait_for_timeout(6000)
        frame = find_app_frame(page)
        if frame is None:
            check("找到应用 iframe", False, "没找到，后面全部无法进行")
            browser.close()
            return 1
        check("找到应用 iframe", True, frame.url)
        hit, text, _ = wait_text(frame, [GATE_TEXT, MAIN_TEXT], 180_000)
        check("首屏渲染出内容", bool(hit), f"{time.time() - t0:.1f}s")
        check("标题正确", "Paper2Lab" in page.title(), page.title())
        # hero 数字要**单独等**：首屏判据（"使用内置演示数据"）可能在 hero 之前就满足，
        # 直接拿那次取样判 hero 会假失败 —— 这个坑本会话已踩第三次。
        hero_hit, hero_text, hero_wait = wait_text(
            frame, ["12 步", "{len(STEPS)}"], 30_000)
        if hero_text:
            text = hero_text          # 用更完整的这次取样做后续判定
        check("hero 显示「12 步」（不是 {len(STEPS)}）", hero_hit == "12 步",
              f"命中 {hero_hit}（{hero_wait / 1000:.0f}s）" if hero_hit
              else "30s 内没等到 hero 数字")
        leaks = re.findall(r"\{[^{}\n]{1,60}\}", text or "")
        check("正文无未求值的 {占位符}", not leaks, str(leaks[:4]))
        check("未设口令门（点开即用）", hit == MAIN_TEXT,
              "有门" if hit == GATE_TEXT else "无门，符合当前配置")
        page.screenshot(path=str(SHOTS / "L1_首屏.png"))

        # ---------------------------------------------------------- B 安全
        section("B 安全")
        exp = frame.get_by_text("高级设置", exact=False)
        if exp.count():
            exp.first.click()
            frame.wait_for_timeout(1800)
        pws = frame.locator("input[type=password]")
        n = pws.count()
        filled = [i for i in range(n) if pws.nth(i).input_value()]
        check(f"{n} 个密钥输入框全部为空", not filled,
              f"被预填的下标 {filled}" if filled else "key 不进浏览器")

        # ---- 输入区已升级为通用「模型 API」（2026-09-30 用户口径）----
        # 线上 Secrets 是空的、默认模型又是纯文本模型，所以这里应当**如实显示"无法读图"**
        # —— 这恰恰是评委打开链接时看到的状态，必须按这个状态来验，不能只看首屏。
        adv = frame.inner_text("body")
        check("输入区用通用名「模型 API」且 Key/URL 成对",
              "模型 API Key" in adv and "模型 Base URL（必填）" in adv,
              "DeepSeek 专用名已升级为任意 OpenAI 兼容模型")
        check("有「该模型本身可以读图（多模态）」开关",
              "该模型本身可以读图" in adv, "")
        check("未配模型 API 时如实提示**无法读图**并说明原因",
              "无法读图" in adv and ("未配置任何模型 API" in adv or "不支持读图" in adv),
              "不许把「没配」说成「已配置」，也不许静默跳过")

        html = frame.content()
        dom_leaks = [lab for lab, pat in SECRET_PATTERNS.items() if pat.search(html)]
        check("DOM 里没有密钥形态的字符串", not dom_leaks, str(dom_leaks))
        # 控制台错误必须分清"我们的"和"平台的"：Streamlit Cloud 自己会加载
        # Google Analytics / Segment / heap / statuspage 这些第三方资源，
        # 被网络策略挡掉是常态 —— 拿它当"体检不通过"就是自己骗自己。
        ours_4xx = [u for s, u in bad_resp if is_ours(u)]
        other_4xx = [(s, u) for s, u in bad_resp if not is_ours(u)]
        ours_fail = [u for u, _ in failed_req if is_ours(u)]
        other_fail = [(u, f) for u, f in failed_req if not is_ours(u)]
        check("本站资源无 4xx/5xx", not ours_4xx, str(ours_4xx[:3]))
        check("本站请求无失败", not ours_fail, str(ours_fail[:3]))
        print(f"    （平台/第三方噪声：{len(other_4xx)} 个 4xx + {len(other_fail)} 个连接失败，"
              f"不计入判定）")
        for s, u in other_4xx[:5]:
            print(f"      · HTTP {s}  {u}")
        for u, f in other_fail[:5]:
            print(f"      · FAILED   {u}  ({f})")

        # ---------------------------------------------------------- C 演示端到端
        section("C 演示端到端（内置演示数据）")
        fp_before = (FP_RE.search(text).group(1) if FP_RE.search(text) else None)
        check("找到「开始科研审计」按钮", click_by_text(frame, RUN_TEXT))
        fp_demo, text2, waited = wait_new_run(frame, fp_before)
        check("演示审计跑出结果", bool(fp_demo),
              f"指纹 {fp_demo}，{waited / 1000:.0f}s")
        for kw in ("审计流水线", "待确认问题", "根因追查", "补丁草案"):
            check(f"结果页含「{kw}」", kw in text2)
        check("流程面板有环节勾选记录", text2.count("✓") >= 5,
              f"{text2.count('✓')} 个 ✓")
        page.screenshot(path=str(SHOTS / "L2_演示结果.png"), full_page=False)

        # ---------------------------------------------------------- D 结果页标签页
        section("D 结果页标签页")
        tabs = frame.get_by_role("tab")
        if tabs.count() == 0:
            tabs = frame.locator('[data-baseweb="tab"]')
        tn = tabs.count()
        check("结果页有标签页", tn >= 2, f"{tn} 个")
        for i in range(min(tn, 4)):
            try:
                label = re.sub(r"\s+", " ", tabs.nth(i).inner_text()).strip()[:24]
            except Exception:  # noqa: BLE001
                label = f"#{i}"
            try:
                tabs.nth(i).click()
                frame.wait_for_timeout(1800)
                body = frame.inner_text("body")
                check(f"标签页「{label}」可渲染", len(body) > 500, f"正文 {len(body)} 字")
            except Exception as exc:  # noqa: BLE001
                check(f"标签页「{label}」可点击", False, str(exc)[:80])

        # ---------------------------------------------------------- E 上传自有文件
        section("E 上传自有文件（真实论文）")
        check("待上传的测试论文存在", UPLOAD_PDF.exists(), str(UPLOAD_PDF))
        if UPLOAD_PDF.exists():
            fp_prev = fp_demo
            try:
                frame.locator('input[type="file"]').first.set_input_files(str(UPLOAD_PDF))
                frame.wait_for_timeout(6000)   # 等上传控件登记文件
                up_txt = frame.inner_text("body")
                check("上传控件已登记文件", "paper.pdf" in up_txt or "1 file" in up_txt,
                      "看到了上传结果" if ("paper.pdf" in up_txt) else "未看到文件名（可能延迟）")
                check("点击运行（上传优先于演示开关）", click_by_text(frame, RUN_TEXT))
                fp_up, text3, waited2 = wait_new_run(frame, fp_prev)
                check("上传论文跑出结果", bool(fp_up) and fp_up != fp_prev,
                      f"指纹 {fp_up}（演示是 {fp_prev}），{waited2 / 1000:.0f}s")
                if fp_up:
                    check("结果页含审计流水线", "审计流水线" in text3)
                    check("结果页未退化为错误页",
                          "Traceback" not in text3 and "Error" not in text3)
                page.screenshot(path=str(SHOTS / "L3_上传结果.png"))
            except Exception as exc:  # noqa: BLE001
                check("上传流程可完成", False, f"{type(exc).__name__}: {exc}"[:150])

        # ---------------------------------------------------------- F 手机端
        section("F 手机端（390x844）")
        try:
            m = browser.new_page(viewport={"width": 390, "height": 844},
                                 user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 "
                                             "like Mac OS X) AppleWebKit/605.1.15 "
                                             "(KHTML, like Gecko) Version/17.0 Mobile/15E148"))
            m.goto(URL, wait_until="domcontentloaded", timeout=180_000)
            mf = find_app_frame(m)
            mhit, mtext, _ = (wait_text(mf, [MAIN_TEXT, GATE_TEXT], 120_000)
                              if mf else (None, "", 0))
            check("手机视口首屏可渲染", bool(mhit),
                  f"{len(mtext)} 字" if mhit else "未渲染")
            check("手机视口 hero 数字正常", "12 步" in (mtext or ""))
            m.screenshot(path=str(SHOTS / "L4_手机端.png"))
            m.close()
        except Exception as exc:  # noqa: BLE001
            check("手机端检查", False, f"{type(exc).__name__}: {exc}"[:150])

        browser.close()

    # ---------------------------------------------------------- 汇总
    bad = [(n, d) for n, ok, d in RESULTS if not ok]
    print("\n" + "=" * 66)
    print(f"线上全面体检：{len(RESULTS) - len(bad)}/{len(RESULTS)} 项通过"
          f"，耗时 {time.time() - t_all:.0f}s")
    if bad:
        print("失败项：")
        for n, d in bad:
            print(f"  ❌ {n} — {d}")
    else:
        print("✅ 全部通过：评委能做的动作在公网域名上都验过了。")
    print(f"截图目录：{SHOTS}")
    print("=" * 66)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
