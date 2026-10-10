"""真机验证：页面输入区已升级为**通用的「模型 API」**，读图能力按模型是否多模态决定。

用户口径（2026-09-30）：
  "把页面显示的 dp 的 api 改成名称为模型 api，也就是用户换别的模型 api 都可；
   如果是多模态那就不需要视觉模型 api，如果不是，那就需要视觉的 api 才可读图；
   同时如果用没视觉的模型会提示无法读图"
  补充（同轮）："支持任意模型 key 同时还要填对应 url，无论是不是多模态；
   如果是单模态还要填对应视觉模型的 key 和 url"

分两层验证（都真跑，不是"应该没问题"）：

第 1 层 · 纯函数：`paper2lab.llm.resolve_vision` 的每个分支逐一断言。
  为什么必须单独测它：本机 `.env` 里配了视觉 key，于是"完全没有读图通道"这一类分支
  在**页面上永远走不到**（会被 .env 兜住）。线上 Secrets 是空的 —— 那才是评委看到的状态，
  所以这两条必须在函数层锁死，不能靠"页面上试了一下没事"。

第 2 层 · 真机：起本地服务、用 Edge 打开，断言
  · 输入区已是通用名（不再写死 DeepSeek），① 与 ② 都是 Key + URL 成对；
  · 两个密钥框仍**为空**（安全：key 不进浏览器）；
  · 填多模态模型（gpt-4o）→ 读图复用模型 API，无需视觉 key；
  · 清空视觉 Base URL（只留 key）→ **如实提示"无法读图"**并说明缺的是 URL。
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:                 # 脚本已不在项目根，需把根加回来
    sys.path.insert(0, str(ROOT))

PORT = 8521
URL = f"http://127.0.0.1:{PORT}"
fails: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}", flush=True)
    if not ok:
        fails.append(label)


# ================================================================ 第 1 层：纯函数分支
def layer1() -> None:
    from paper2lab.llm import resolve_vision as rv

    print("\n=== 第 1 层 · resolve_vision 分支（纯函数，不依赖 .env）===", flush=True)
    cases = [
        # 名字, 关键字参数, 期望 ok, 期望 source 片段, 期望 reason 片段
        ("① 页面成对填视觉 key+url",
         dict(page_key="vk", page_url="https://v/v1", page_model="mimo-v2.5"),
         True, "页面输入", ""),
        ("② 页面只填视觉 key、没填 url",
         dict(page_key="vk", page_url=""),
         False, "", "Base URL"),
        ("③ 服务端成对（.env 有 key+url）",
         dict(env_key="ek", env_url="https://e/v1", env_model="mimo-v2.5"),
         True, ".env", ""),
        ("④ 服务端厂商专用变量（有已知端点）",
         dict(env_key="ek", env_url="", env_key_has_known_url=True),
         True, ".env", ""),
        ("⑤ 服务端配了 key 却没 url",
         dict(env_key="ek", env_url="", env_key_has_known_url=False),
         False, "", "Base URL"),
        ("⑥ 单模态模型 + 无视觉配置 → 无法读图",
         dict(llm_key="lk", llm_url="https://l/v1", llm_model="llama-3-70b",
              llm_multimodal=False),
         False, "", "不支持读图"),
        ("⑦ 多模态模型 → 复用模型 API",
         dict(llm_key="lk", llm_url="https://l/v1", llm_model="gpt-4o",
              llm_multimodal=True),
         True, "复用模型 API", ""),
        ("⑧ 自称多模态却没填 Base URL → 不能复用",
         dict(llm_key="lk", llm_url="", llm_model="gpt-4o", llm_multimodal=True),
         False, "", "Base URL"),
        ("⑨ 什么都没配",
         dict(),
         False, "", "未配置任何模型 API"),
    ]
    for name, kw, want_ok, want_src, want_reason in cases:
        r = rv(**kw)
        good = (r["ok"] == want_ok
                and (want_src in r["source"] if want_src else r["source"] == "")
                and (want_reason in r["reason"] if want_reason else r["reason"] == ""))
        check(good, f"{name} → ok={r['ok']} source={r['source'] or '-'} "
                    f"reason={r['reason'][:34] or '-'}")

    # 多模态识别：这是"要不要额外配视觉 key"的默认判据，判错代价不对称（猜成能读图会全失败）
    from paper2lab.llm import looks_multimodal as lm
    check(lm("gpt-4o") and lm("qwen-vl-max") and lm("mimo-v2.5") and lm("glm-4v-plus"),
          "视觉模型名被识别为多模态（gpt-4o / qwen-vl-max / mimo-v2.5 / glm-4v-plus）")
    check(not lm("deepseek-chat") and not lm("llama-3-70b") and not lm(""),
          "纯文本模型名**不**被误判为多模态（含空名）")


# ================================================================ 第 2 层：真机
def layer2() -> None:
    print("\n=== 第 2 层 · 真机（Edge 打开本地页面）===", flush=True)
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-X", "utf8", "-m", "streamlit",
         "run", "app.py", "--server.headless", "true", "--server.address", "127.0.0.1",
         "--server.port", str(PORT), "--browser.gatherUsageStats", "false"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        up = False
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=3) as r:
                    if r.status == 200:
                        up = True
                        break
            except Exception:      # noqa: BLE001
                time.sleep(2)
        check(up, "界面服务已起来")
        if not up:
            return

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True)
            page = b.new_page(viewport={"width": 1500, "height": 1200})
            page.goto(URL, wait_until="domcontentloaded")
            # 等**目标文本**，不要等"body 变长"（分帧渲染会假通过）
            for _ in range(30):
                if "使用内置演示数据" in page.inner_text("body"):
                    break
                page.wait_for_timeout(1000)

            body = page.inner_text("body")
            check("模型 API" in body, "输入区已用通用名「模型 API」（不再写死 DeepSeek）")
            check("归因引擎：DeepSeek" not in body,
                  "主页面状态行不再写死 DeepSeek 品牌（改为实际模型名）")

            exp = page.get_by_text("高级设置", exact=False)
            if exp.count():
                exp.first.click()
                page.wait_for_timeout(1800)
            body2 = page.inner_text("body")
            check("模型 Base URL（必填）" in body2, "① 模型 API 有 Base URL 输入（必填）")
            check("模型名（必填）" in body2, "① 模型 API 有模型名输入（必填）")
            check("视觉 Base URL（必填）" in body2, "② 视觉通道也有 Base URL 输入（必填）")
            check("该模型本身可以读图" in body2, "有「该模型本身可以读图（多模态）」开关")

            # 安全：两个密钥框必须为空
            pws = page.locator("input[type=password]")
            vals = [pws.nth(i).input_value() for i in range(pws.count())]
            check(pws.count() == 2 and all(v == "" for v in vals),
                  f"两个密钥框共 {pws.count()} 个且**全部为空**（key 不进浏览器）")

            box = page.locator("div[data-testid='stExpander']").first
            # 先打印实际结构：定位靠 aria-label 前缀，不靠索引（勾选框夹在中间，索引易错）
            info = box.locator("input").evaluate_all(
                "els => els.map(e => e.type + ' | ' + (e.getAttribute('aria-label') || ''))")
            print(f"  （展开区 input 共 {len(info)} 个）", flush=True)
            for one in info:
                print(f"      {one}", flush=True)
            check(len(info) >= 6, f"展开区内输入项齐全（{len(info)} 个）")

            def field(prefix: str):
                loc = box.locator(f"input[aria-label^='{prefix}']")
                if loc.count() == 0:
                    raise AssertionError(f"找不到输入项：{prefix}")
                return loc.first

            f_llm_key = field("模型 API Key")
            f_llm_url = field("模型 Base URL")
            f_llm_name = field("模型名")
            f_vk = field("视觉模型 API Key")
            f_vu = field("视觉 Base URL")

            def setv(loc, val: str):
                """填值并**提交**。

                ⚠️ 坑：Streamlit 的文本框只在**回车或失焦**时才把值发回服务端，
                只调 fill() 改的是 DOM，服务端根本不知道 —— 表现就是"填了但页面没反应"，
                很容易被误判成产品 bug。这里必须补一次 Enter。
                """
                loc.fill(val)
                loc.press("Enter")
                page.wait_for_timeout(900)

            def wait_until(pred, secs: float = 20) -> tuple[bool, str]:
                """等到正文满足条件（Streamlit 分帧渲染，必须等**目标文本**，不能只 sleep）。"""
                end = time.time() + secs
                t = ""
                while time.time() < end:
                    t = page.inner_text("body")
                    if pred(t):
                        return True, t
                    page.wait_for_timeout(500)
                return False, t

            # --- 多模态模型：读图应复用模型 API（无需视觉 key）
            setv(f_llm_key, "dummy-model-key-not-used")
            setv(f_llm_url, "https://api.example.invalid/v1")
            setv(f_llm_name, "gpt-4o")
            ok_reuse, t = wait_until(lambda s: "复用①的模型 API" in s and "已就绪（gpt-4o）" in s)
            check(ok_reuse, "填多模态模型(gpt-4o) → 读图状态显示**复用模型 API**"
                            "，主页面同步显示 已就绪（gpt-4o）")

            # --- 单模态模型：本机 .env 有视觉 key，所以应回落到 .env 而不是误报"无法读图"
            setv(f_llm_name, "llama-3-70b")
            ok_single, t = wait_until(lambda s: "视觉读图通道：已配置" in s
                                      and "复用①的模型 API" not in s)
            check(ok_single, "换单模态模型(llama-3-70b) → 回落到 .env 的视觉配置"
                             "（不误报无法读图，也不再说读图来自模型 API）")

            # --- 只填视觉 key 不填 url：必须**当场提示无法读图**并点明缺 URL
            setv(f_vk, "dummy-vision-key-not-used")
            ok_miss, t = wait_until(lambda s: "无法读图" in s and "Base URL" in s)
            check(ok_miss, "只填视觉 Key 不填 Base URL → **如实提示无法读图**且点明缺 URL")

            # --- 页面成对填视觉 key+url：来源应显示"页面输入"
            setv(f_vu, "https://api.example.invalid/v1")
            ok_pair, t = wait_until(lambda s: "视觉读图通道：已配置" in s and "页面输入" in s)
            check(ok_pair, "视觉 Key+URL 成对填写 → 已配置 · 来源：页面输入")

            b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:      # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    layer1()
    layer2()
    print("\n" + "=" * 60, flush=True)
    if fails:
        print(f"结论：❌ {len(fails)} 项未通过", flush=True)
        for f in fails:
            print(f"   - {f}", flush=True)
        sys.exit(1)
    print("结论：✅ 全部通过", flush=True)
