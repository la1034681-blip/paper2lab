"""验证：key 的状态显示是否正确，且**密钥绝不进浏览器**（不打印明文密钥）。

流程：杀掉旧服务 → 起新服务 → 打开页面 → 检查状态文案 → 断言两个 key 输入框**为空**
      → 保留服务运行。

为什么断言"必须为空"(2026-09-30 加固)：原先 `value=<服务端key>` 会把真 key
随页面发到浏览器，链接公开后任何人打开开发者工具就能读走。现在恒为空，
服务端 key 照用（`api_key or None` 回落到环境变量），状态改由文案告知。
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
URL = "http://localhost:8501"
OUT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集\ui_screenshots")
OUT.mkdir(parents=True, exist_ok=True)

log: list[str] = []
errors: list[str] = []


def note(s: str):
    print(s)
    log.append(s)


def kill_8501():
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        for line in out.splitlines():
            if ":8501" in line and "LISTENING" in line:
                pid = line.split()[-1]
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                note(f"  已结束旧服务进程 {pid}")
    except Exception as e:
        note(f"  结束旧进程失败(忽略): {e}")


def start_server():
    """后台起服务(独立进程组, 不随本脚本退出而结束)。"""
    py = HERE / ".venv" / "Scripts" / "python.exe"
    logf = open(HERE / "_svc_keys_log.txt", "w", encoding="utf-8")
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(py), "-m", "streamlit", "run", "app.py",
         "--server.headless", "true", "--server.address", "127.0.0.1",
         "--server.port", "8501"],
        cwd=str(HERE), stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)


def wait_health(timeout=90) -> bool:
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(URL + "/_stcore/health", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(2)
    return False


def main():
    kill_8501()
    time.sleep(2)
    start_server()
    if not wait_health():
        note("## 服务启动: ❌ 健康检查未通过")
        sys.exit(1)
    note("## 服务启动: ✅ 健康检查 200")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 1100})
        console_errs: list[str] = []
        page.on("console", lambda m: console_errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errs.append(str(e)))

        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        body = page.inner_text("body")
        # 1) 主页面状态行
        note("## 1. 主页面通道状态提示")
        for label, key in (("读图通道", "读图通道"), ("归因引擎", "归因引擎"),
                           ("视觉模型名出现(mimo)", "mimo"),
                           ("输入区用的是通用名「模型 API」", "模型 API")):
            ok = key in body
            note(f"   - {label}: {'✅' if ok else '❌'}")
            if not ok:
                errors.append(f"主页面缺少: {label}")
        # 2026-09-30：归因引擎改为**如实显示实际模型名**（用户可换任意模型 API），
        # 不该再写死 "DeepSeek" 品牌 —— 这里把"写死"本身当成失败条件来防回归。
        if "归因引擎：DeepSeek" in body:
            note("   - 归因引擎仍写死 DeepSeek 品牌名: ❌")
            errors.append("归因引擎未按实际模型名显示，仍写死 DeepSeek")

        # 2) 展开高级设置
        note("## 2. 高级设置内的密钥状态")
        exp = page.get_by_text("高级设置", exact=False)
        if exp.count():
            exp.first.click()
            page.wait_for_timeout(1500)
        body2 = page.inner_text("body")
        for label, key in (("视觉读图通道: 已配置", "视觉读图通道：已配置"),
                           ("提示来源为 .env", ".env"),
                           ("归因引擎状态说明", "归因引擎"),
                           ("明确不影响结论", "不影响结论")):
            ok = key in body2
            note(f"   - {label}: {'✅' if ok else '❌'}")
            if not ok:
                errors.append(f"高级设置缺少: {label}")

        # 3) 密钥输入框**必须为空**——这是安全要求，不是可用性偏好
        #    2026-09-30 加固：原先 value=<服务端key> 会把真 key 随页面发到浏览器，
        #    链接一旦公开，任何人打开开发者工具（或点"眼睛"图标）就能读走。
        #    现在恒为空，服务端 key 仍照用（api_key or None 回落到环境变量）。
        pws = page.locator("input[type=password]")
        n = pws.count()
        note(f"## 3. 密钥输入框（共 {n} 个密码框）—— 期望**全部为空**")
        vals = [pws.nth(i).input_value() for i in range(n)]
        for i, v in enumerate(vals):
            label = ("模型 API" if i == 0 else
                     "视觉模型" if i == 1 else f"第{i + 1}个")
            if v:
                note(f"   - 第 {i + 1} 个({label}): ❌ 被预填了（长度 {len(v)}）"
                     f"—— key 会随页面发到浏览器，存在泄漏风险")
                errors.append(f"{label} key 输入框被预填，key 会被发到浏览器")
            else:
                note(f"   - 第 {i + 1} 个({label}): ✅ 空（正确，key 不进浏览器）")
        if n < 2:
            errors.append("未找到两个 key 输入框")
        # 服务端 key 的状态仍必须让用户看得见（靠文案，而不是靠预填）
        has_srv_note = "服务端" in body2
        note(f"   - 服务端 key 状态文案可见: {'✅' if has_srv_note else '❌'}")
        if not has_srv_note:
            errors.append("缺少『服务端 key 状态』说明文案（用户无法判断是否已配置）")

        # 4) HTML 泄漏 + 控制台错误
        leaks = [m for m in ("</div>", "class='", "unsafe_allow_html") if m in body2]
        note(f"## 4. HTML 标记泄漏: {'✅ 0 处' if not leaks else '❌ ' + str(leaks)}")
        if leaks:
            errors.append(f"HTML 泄漏: {leaks}")
        note(f"## 5. 浏览器控制台错误: {'✅ 0 条' if not console_errs else '❌ ' + str(console_errs[:3])}")

        page.screenshot(path=str(OUT / "09_keys_status.png"), full_page=True)
        b.close()

    note("")
    note(f"## 结论: {'✅ 全部通过' if not errors else '❌ ' + str(len(errors)) + ' 项异常'}")
    for e in errors:
        note(f"   - {e}")
    (OUT.parent / "ui_keys_report.md").write_text("\n".join(log), encoding="utf-8")
    print("REPORT SAVED")


if __name__ == "__main__":
    main()
