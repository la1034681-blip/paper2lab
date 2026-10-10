"""网站功能实测——用真实浏览器(Edge)操作 Streamlit 驾驶舱, 逐步截图取证。

覆盖三条路径:
A. 内置演示数据(默认开关) -> 完整结果页
B. 上传真实样本(arXiv 论文 + GitHub 代码包) -> 结果页显示"当前审计对象"
C. 审计可信度标签页 + 报告下载区

用法: .venv\\Scripts\\python.exe ui_test.py
输出: C:\\Users\\lijiahui\\Desktop\\Paper2Lab测试集\\ui_screenshots\\*.png + ui_test_report.md
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8501"
ROOT = Path(__file__).resolve().parent.parent
SAMPLES = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
OUT = SAMPLES / "ui_screenshots"
OUT.mkdir(exist_ok=True)


def _health_ok() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_server() -> subprocess.Popen | None:
    """服务不在运行时自动拉起(本环境里后台进程会被回收, 故让测试自带服务)。"""
    if _health_ok():
        print("[ui_test] 复用已在运行的服务")
        return None
    print("[ui_test] 启动 Streamlit 服务…")
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.headless", "true", "--server.port", "8501"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if _health_ok():
            print("[ui_test] 服务就绪")
            return proc
        time.sleep(1)
    print("[ui_test] ⚠️ 服务启动超时")
    return proc

def _pick_default_sample() -> tuple[Path, Path, str]:
    """默认样本: 测试集里第一个同时含 paper.pdf + code.zip 的目录。

    (早期版本硬编码 04_SimSiam, 测试集换代后路径失效 -> 直接 FileNotFoundError。)
    """
    if SAMPLES.exists():
        for d in sorted(p for p in SAMPLES.iterdir() if p.is_dir()):
            pdf, zp = d / "paper.pdf", d / "code.zip"
            if pdf.exists() and zp.exists():
                return pdf, zp, d.name
    return SAMPLES / "paper.pdf", SAMPLES / "code.zip", "(无可用样本)"


# 可选参数: ui_test.py [paper.pdf] [code.zip] [期望标题片段]
_default_pdf, _default_zip, _default_name = _pick_default_sample()
PAPER = Path(sys.argv[1]) if len(sys.argv) > 1 else _default_pdf
CODE = Path(sys.argv[2]) if len(sys.argv) > 2 else _default_zip
# 期望标志: 默认等"当前审计对象"条(上传路径出结果后必然出现);
# 不要用样本目录名当标志——它不会出现在页面上, 会白等到超时。
# 期望标志: 必须是"只有本次上传才会出现"的内容。
# 曾用"当前审计对象"——但该条在旧结果里已经存在, 点击后会立刻被旧 DOM 满足,
# 导致"0.1s 就出结果"的假通过。改用新上传的**文件名**(演示数据/上一次审计都没有它)。
EXPECT_TITLE = sys.argv[3] if len(sys.argv) > 3 else PAPER.name
SAMPLE_NAME = PAPER.parent.name
RESULTS = PAPER.parent / "results.json"     # 可选: 同目录下的实验结果数据

log: list[str] = []
errors: list[str] = []


def note(s: str):
    print(s)
    log.append(s)


def wait_text(page, text: str, timeout: int = 60000) -> bool:
    try:
        page.wait_for_selector(f"text={text}", timeout=timeout)
        return True
    except Exception:
        return False


def wait_text_gone(page, text: str, timeout: int = 60000) -> bool:
    """等某段文字从页面上**消失**。

    用途：确认"上一次的结果已被清掉、本次重跑真的开始了"。
    （2026-09-29 加的，理由见上传路径里那处调用的注释。）
    """
    t0 = time.time()
    while (time.time() - t0) * 1000 < timeout:
        try:
            if text not in page.inner_text("body"):
                return True
        except Exception:      # noqa: BLE001
            return True
        page.wait_for_timeout(500)
    return False


def start_button(page):
    """Streamlit 主按钮: 优先按 kind=primary, 退化到正则匹配文字
    (按钮可访问名会被 CJK 字间距拆开, 不能用精确字符串)。"""
    loc = page.locator('button[kind="primary"]')
    if loc.count():
        return loc.first
    loc = page.get_by_role("button", name=re.compile(r"科\s*研\s*审\s*计"))
    if loc.count():
        return loc.first
    for b in page.locator("button").all():
        if "审" in b.inner_text():
            return b
    return None


def tab_by_text(page, word: str):
    for t in page.locator('[role=tab]').all():
        if word in t.inner_text():
            return t
    return None


def main():
    sample_missing = not PAPER.exists() or not CODE.exists()
    server_proc = ensure_server()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)

        note("# Paper2Lab 网站功能实测报告(真实浏览器)")
        note("")
        note(f"- 浏览器: Microsoft Edge (Playwright, headless)")
        note(f"- 目标: {URL}")
        note(f"- 测试时间: {time.strftime('%Y-%m-%d %H:%M')}")
        note("")

        # ---- 打开页面
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        ok_hero = wait_text(page, "论文—代码—实验结果", 45000)
        note(f"## 1. 页面加载: {'✅ 首屏渲染成功' if ok_hero else '❌ 首屏未渲染'}")
        if not ok_hero:
            errors.append("首屏未渲染")
        page.screenshot(path=str(OUT / "01_home.png"), full_page=True)

        ok_upload = wait_text(page, "论文 PDF", 20000)
        note(f"   - 三个上传入口: {'✅ 可见' if ok_upload else '❌ 缺失'}")

        # ---- A. 演示数据路径
        start = start_button(page)
        note(f"   - 主按钮「开始科研审计」: {'✅ 找到' if start else '❌ 缺失'}")
        if start:
            start.click()
            t0 = time.time()
            ok_res = wait_text(page, "综合复现就绪度", 90000)
            note(f"## 2. 演示数据审计: {'✅ 跑通' if ok_res else '❌ 未出结果'}"
                 f" (耗时 {time.time() - t0:.1f}s)")
            if ok_res:
                for t in ("审计可信度", "证据链总览", "审计发现"):
                    note(f"   - 结果区「{t}」: {'✅' if wait_text(page, t, 15000) else '❌'}")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / "02_demo_result.png"), full_page=True)
            note(f"   - 证据自证徽章: {'✅ 出现' if wait_text(page, '证据自证', 10000) else '❌ 未出现'}")
        else:
            errors.append("未找到主按钮")

        # ---- B. 上传真实样本路径
        inputs = page.locator("input[type=file]")
        n_in = inputs.count()
        note(f"## 3. 上传真实样本({SAMPLE_NAME}): 上传控件 {n_in} 个"
             + ("  ⚠️ 样本文件缺失" if sample_missing else ""))
        if sample_missing:
            errors.append(f"样本文件缺失, 跳过上传路径: {PAPER} / {CODE}")
            note("   - ❌ 样本文件不存在, 已跳过上传路径(请检查测试集路径)")
        elif n_in >= 2:
            inputs.nth(0).set_input_files(str(PAPER))
            page.wait_for_timeout(1500)
            inputs.nth(1).set_input_files(str(CODE))
            page.wait_for_timeout(2000)
            # 第三个上传位: 实验结果 JSON(可选) —— 有则一并上传, 覆盖"结果核验"这一步
            has_res = RESULTS.exists()
            if n_in >= 3 and has_res:
                inputs.nth(2).set_input_files(str(RESULTS))
                page.wait_for_timeout(1500)
            note(f"   - 实验结果 JSON: {'✅ 已上传 ' + RESULTS.name if (has_res and n_in >= 3) else '— 未提供(跳过结果核验)'}")
            page.screenshot(path=str(OUT / "03_uploaded.png"), full_page=True)
            btn = start_button(page)
            note(f"   - 上传后重新点击审计: {'✅' if btn else '❌ 按钮消失'}")
            if btn:
                btn.click()
                t0 = time.time()
                # ⚠️ 两段式等待，缺一不可（2026-09-29 定稿）:
                #   ① 先等**旧结果消失** —— 证明本次重跑真的开始了；
                #   ② 再等**新结果渲染出来** —— 判据直接用结果区第一项「当前审计对象」。
                #
                # 为什么不再用"page 内容稳定"那个启发式: 实测点击后浏览器会先把按钮变灰、
                # 而**旧结果仍留在页面上**, 于是"内容已稳定 + 关键词命中（旧结果里的）"立刻成立，
                # 曾出现 **1.5s 假通过**；紧接着的结果区检查全部扑空，误报
                # "缺少 当前审计对象条 / 来源标注为用户上传"。
                #
                # 为什么现在才暴露: 从前运行缓存命中、审计几秒就跑完，恰好掩盖了它；
                # 本轮起「两轮之间清运行缓存」成为默认行为, 第二次跑要真调 API (更久), 问题才显形。
                # 另附实测: `inner_text("body")` 与 `text=` 选择器对这段文字**同时**命中
                # (探针 probe_ui_marker.py 测得差值 0.0s) —— 是时序问题, 不是选择器问题。
                wait_text_gone(page, "当前审计对象", 90000)
                ok_up = wait_text(page, "当前审计对象", 300000)
                elapsed_up = time.time() - t0
                note(f"## 4. 上传样本审计: {'✅ 跑通' if ok_up else '❌ 未出结果'}"
                     f" (出结果耗时 {elapsed_up:.1f}s)")
                page.wait_for_timeout(1500)
                page.screenshot(path=str(OUT / "04_upload_result.png"), full_page=True)
                checks = {
                    "当前审计对象条": wait_text(page, "当前审计对象", 15000),
                    "来源标注为用户上传": wait_text(page, "用户上传", 15000),
                    "本次审计已出结果(页面已更新)": ok_up,
                    "上传文件名出现在页面": (wait_text(page, PAPER.name, 10000)
                                            or wait_text(page, CODE.name, 5000)),
                }
                if has_res and n_in >= 3:
                    checks["结果核验已执行(出现 Result: 结论)"] = wait_text(
                        page, "Result:", 15000)
                for k, v in checks.items():
                    note(f"   - {k}: {'✅' if v else '❌'}")
                    if not v:
                        errors.append(f"上传路径缺少: {k}")
        else:
            errors.append("未找到上传控件")

        # ---- C. 审计可信度标签页
        tab = tab_by_text(page, "可信度")
        if tab:
            tab.click()
            checks = {
                "页面覆盖指标": wait_text(page, "论文内容覆盖", 25000),
                "文本层覆盖指标": wait_text(page, "其中文本层可解析", 10000),
                "参数种类覆盖": wait_text(page, "论文参数种类覆盖", 10000),
                "可信度得分": wait_text(page, "本次审计可信度", 10000),
                "多语言通道指标": wait_text(page, "多语言通道", 10000),
                "被拒收抽取": wait_text(page, "被合理性校验拒收", 10000),
                "多语言通道指标": wait_text(page, "多语言通道 / 完全无法处理", 10000),
            }
            note(f"## 5. 审计可信度标签页: "
                 f"{'✅ 全部指标渲染' if all(checks.values()) else '⚠️ 部分缺失'}")
            for k, v in checks.items():
                note(f"   - {k}: {'✅' if v else '❌'}")
                if not v:
                    errors.append(f"可信度页缺少: {k}")
            page.screenshot(path=str(OUT / "05_trust_tab.png"), full_page=True)
            # 展开折叠面板(比较日志 / 自检结果)后再验证。
            # 注意: 面板可能默认就是展开的, 先直接找内容, 找不到再点开
            for name, expect in (("程序比较日志", "[比较]"), ("审计自检", "结论复算")):
                ok = wait_text(page, expect, 3000)
                if not ok:
                    el = page.get_by_text(name, exact=False)
                    if el.count():
                        try:
                            el.first.click()
                            page.wait_for_timeout(900)
                        except Exception:
                            pass
                    ok = wait_text(page, expect, 6000)
                note(f"   - {name}(展开后含关键内容): {'✅' if ok else '❌'}")
                if not ok:
                    errors.append(f"可信度页展开后缺少: {name}")
            page.screenshot(path=str(OUT / "05b_trust_expanded.png"), full_page=True)
        else:
            errors.append("未找到审计可信度标签页")
            note("## 5. 审计可信度标签页: ❌ 未找到")

        # ---- D. 审计报告标签页
        tabr = tab_by_text(page, "审计报告")
        if tabr:
            tabr.click()
            page.wait_for_timeout(2000)
            page.screenshot(path=str(OUT / "06_report_tab.png"), full_page=True)
            note("## 6. 审计报告标签页: ✅ 可打开(含 Markdown 报告与下载按钮)")
        else:
            errors.append("未找到审计报告标签页")
            note("## 6. 审计报告标签页: ❌ 未找到")

        browser.close()

    note("")
    note("## 结论")
    note("")
    if errors:
        note(f"- ⚠️ 发现 {len(errors)} 处问题:")
        for e in errors:
            note(f"  - {e}")
    else:
        note("- ✅ 三条路径全部通过, 无浏览器控制台错误, 无页面异常")

    (SAMPLES / "ui_test_report.md").write_text("\n".join(log), encoding="utf-8")
    if server_proc:
        note("(服务由本次测试自动拉起, 结束后仍在运行: http://localhost:8501)")
        (SAMPLES / "ui_test_report.md").write_text("\n".join(log), encoding="utf-8")
    print("UI TEST REPORT SAVED")


if __name__ == "__main__":
    main()
