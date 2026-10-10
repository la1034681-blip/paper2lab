"""真机验证: 点「开始科研审计」时, 页面上能不能看到「上一轮清掉了什么」。

为什么必须真机跑: 清理发生在**服务端**（读文件、删文件），界面上的那句回执是它唯一
对用户可见的证据 —— 数据层的 `verify_housekeeping.py` 证明不了"这句提示真的渲染出来了"。
用户明确要求这件事要"看得见"，所以这里断言的是页面文本。

做法: 先人为放一个"上一轮留下的运行缓存"（假 `llm_cache.json`），再点运行。
  若清理真的发生，回执里必须**点名这个文件**；同时必须说明**跨任务记忆被保留**。
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8514
CACHE = ROOT / "cache"
FAKE = CACHE / "llm_cache.json"
MEM = CACHE / "audit_memory.json"

fails: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}", flush=True)
    if not ok:
        fails.append(label)


# 0) 人为造一份"上一轮留下的运行缓存"
CACHE.mkdir(parents=True, exist_ok=True)
FAKE.write_text('{"__ui_probe__": "上一轮留下的运行缓存"}', encoding="utf-8")
mem_before = MEM.read_bytes() if MEM.exists() else None
print(f"已放置假缓存 {FAKE.name}（{FAKE.stat().st_size} 字节）；"
      f"记忆文件{'存在' if mem_before is not None else '不存在'}", flush=True)

proc = subprocess.Popen(
    [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-X", "utf8", "-m", "streamlit", "run",
     "app.py", "--server.headless", "true", "--server.address", "127.0.0.1",
     "--server.port", str(PORT)],
    cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    from playwright.sync_api import sync_playwright
    import urllib.request

    ok = False
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/_stcore/health",
                                        timeout=3) as r:
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
        page.goto(f"http://127.0.0.1:{PORT}", timeout=60000)
        page.wait_for_timeout(9000)

        body0 = page.inner_text("body")
        check("🧹 清理：" not in body0,
              "运行前页面上不该提前出现清理回执（它是运行后的回执）")

        # 点开始（演示数据开关默认开，直接点即可）
        page.get_by_text("开 始 科 研 审 计", exact=False).click()
        for _ in range(90):
            page.wait_for_timeout(2000)
            if "🧹 清理：" in page.inner_text("body"):
                break
        page.wait_for_timeout(3000)
        body = page.inner_text("body")

        check("🧹 清理：" in body, "页面上出现了清理回执")
        check("llm_cache.json" in body,
              "回执点名了上一轮留下的那个缓存文件（说明确实清了它）")
        check("audit_memory.json" in body, "回执写明了保留的记忆文件")
        # 2026-09-29 用户要求精简（"看着很乱，简洁保留功能名就好"）——
        # 这条断言把要求固化：回执必须是一行短句，不许夹带说理。
        _pl = next((ln for ln in body.splitlines() if "🧹 清理：" in ln), "")
        check(bool(_pl) and len(_pl) < 90,
              f"清理回执足够简短（实测 {len(_pl)} 字，上限 90）")

        # 界面整体没坏（顺带做一轮基本结构检查）
        for key in ("执行记录", "审计流水线", "当前审计对象"):
            check(key in body, f"界面主体仍在：「{key}」")
        check("<div" not in body and "</div>" not in body,
              "页面无 HTML 泄漏（标签没被当文本渲染出来）")
        check(not errors, f"控制台无 JS 报错（{len(errors)} 条）")

        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:      # noqa: BLE001
        proc.kill()
    print("服务已停", flush=True)

# ---- 磁盘侧复核
# ⚠️ 断言口径说明（第一版写错过，这里记下来）:
#   跑完审计后 `llm_cache.json` **本来就该重新存在**（本轮真调 API 后又缓存了结果），
#   `audit_memory.json` 也**本来就该变化**（本轮审计会往记忆里写入这篇论文的线索）。
#   所以不能断言"文件不存在/逐字节不变" —— 那是把**正常行为**当成失败。
#   该断言的是两件**清理动作**负责的事：
#     ① 上一轮那份缓存的内容（`__ui_probe__`）不能再留在文件里；
#     ② 清理前已有的记忆条目**一条都不能少**（增长可以，被清理删掉不行）。
try:
    _cache_txt = FAKE.read_text(encoding="utf-8") if FAKE.exists() else ""
except OSError:
    _cache_txt = ""
check("__ui_probe__" not in _cache_txt,
      "上一轮那份缓存的内容已不在文件里（本轮新写的缓存不算，旧条目必须清掉）")

if mem_before is not None:
    def _keys(blob: bytes | None) -> set | None:
        if not blob:
            return None
        try:
            obj = json.loads(blob.decode("utf-8"))
            return set(obj.keys()) if isinstance(obj, dict) else None
        except Exception:      # noqa: BLE001
            return None

    before_keys = _keys(mem_before)
    after_keys = _keys(MEM.read_bytes()) if MEM.exists() else None
    if before_keys is None:
        check(MEM.exists(), "记忆文件仍在（清理前格式无法解析，只断言存在）")
    elif after_keys is None:
        check(False, "记忆文件被损坏或清掉了（无法解析）")
    else:
        check(before_keys <= after_keys,
              f"清理前已有的 {len(before_keys)} 条记忆条目一条没少"
              f"（本轮记忆共 {len(after_keys)} 条 —— 增长是正常的，被清理删掉才不正常）")

print("")
if fails:
    print(f"未通过 {len(fails)} 项：")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("全部通过（清理在界面上看得见、在磁盘上做得到、记忆没被动）")
