"""推送前密钥闸门：确认待发布的文件里**没有**任何真实密钥。

做三件事：
  1. 通用形态扫描：sk-/ghp_/AKIA/Bearer/私钥头/常见 token 字段赋值；
  2. **真值反查**：把本地 .env / secrets.toml 里的每个真实值拿去仓库文件里搜
     （只报是否命中与第几个字符，**绝不打印密钥本身**）；
  3. 栈底核对：确认 git 工作区干净、且远端 main 的 SHA == 本地 HEAD
     —— 否则"我扫的不是 GitHub 上那一份"，结论就不成立。

用法：  .venv\\Scripts\\python.exe verify_no_secrets.py
退出码：0 = 干净，1 = 发现问题
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"                 # 推到 GitHub 的就是这个目录
REMOTE = "origin"
BRANCH = "main"
MIN_SECRET_LEN = 12                      # 短于此值的"密钥"不值得反查（噪音太大）

# 值长这样的是**公开地址**，不是凭据 —— 命中不算泄露。
# 实例：.env 里的 VISION_BASE_URL 就是 vision.py:124 内置的那个公开端点
#       `https://api.xiaomimimo.com/v1`，反查必然命中，但它本来就不是秘密。
PUBLIC_VALUE = re.compile(r"^https?://[^@\s]+$")
_TOKENISH_IN_URL = ("token=", "key=", "secret=", "apikey=", "api_key=", "sig=")


def is_public_value(v: str) -> bool:
    """是公开地址（而非凭据）？带 @ 或 query 里塞了 token 的不算公开。"""
    if not PUBLIC_VALUE.match(v):
        return False
    low = v.lower()
    return not any(s in low for s in _TOKENISH_IN_URL)

# 通用密钥形态
PATTERNS = {
    "OpenAI/DeepSeek 风格 sk-": re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    "GitHub PAT": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "AWS AKIA": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Bearer token": re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"),
    "私钥文件头": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    "赋值式疑似密钥": re.compile(
        r"(?i)(api[_\-]?key|secret|token|password|passwd)\s*[:=]\s*"
        r"[\"']([A-Za-z0-9_\-]{20,})[\"']"),
}

SKIP_NAMES = {".gitignore", "secrets.toml.example", "README.md",
              ".env.example", "requirements.txt"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2",
               ".zip", ".pdf", ".pyc"}


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=str(DEPLOY), capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    return [DEPLOY / line.strip() for line in out.stdout.splitlines() if line.strip()]


def is_scannable(p: Path) -> bool:
    if p.name in SKIP_NAMES or p.suffix.lower() in SKIP_SUFFIX:
        return False
    return True


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        try:
            return p.read_bytes().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return ""


def gather_real_secrets() -> dict[str, str]:
    """从本地私有配置里取"真值"，用于反查。键名会打印，值不会。"""
    found: dict[str, str] = {}
    for cfg in (ROOT / ".env", ROOT / ".streamlit" / "secrets.toml",
                DEPLOY / ".env", DEPLOY / ".streamlit" / "secrets.toml"):
        if not cfg.exists():
            continue
        for raw in read_text(cfg).splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if len(v) >= MIN_SECRET_LEN:
                found[f"{cfg.name}:{k}"] = v
    return found


def scan_patterns(files: list[Path]) -> list[tuple[str, str, int, str]]:
    hits = []
    for p in files:
        if not is_scannable(p):
            continue
        text = read_text(p)
        for label, pat in PATTERNS.items():
            for m in pat.finditer(text):
                seg = m.group(0)
                # 模板里的占位符不算（如 "sk-..." / "给评委的邀请码"）
                if "..." in seg or "xxx" in seg.lower() or "example" in seg.lower():
                    continue
                lineno = text[:m.start()].count("\n") + 1
                hits.append((label, str(p.relative_to(DEPLOY)), lineno,
                             seg[:4] + "*" * (len(seg) - 4)))
    return hits


def scan_values(files: list[Path], secrets: dict[str, str]) -> list[tuple[str, str, int]]:
    """真值反查：只报 [配置项名, 文件, 行号]。"""
    hits = []
    for name, val in secrets.items():
        for p in files:
            if not is_scannable(p):
                continue
            text = read_text(p)
            idx = text.find(val)
            if idx >= 0:
                hits.append((name, str(p.relative_to(DEPLOY)),
                             text[:idx].count("\n") + 1))
    return hits


def git_probe() -> tuple[str, str, str, str]:
    """返回 (工作区状态, 本地HEAD, 远端SHA, 取远端的方式)。

    取远端要能容错：本机 git 全局配了 `http.proxy = http://127.0.0.1:7890`，
    而那个代理是**随用随开**的 —— 它没在跑时 git 会连不上，闸门就会误报
    "远端取不到、不要推送"（2026-09-30 实测踩到）。所以先直连试，失败再
    本次禁用代理重试（github.com 直连可达，工程已验证）。
    """
    def run(args, extra=()):
        return subprocess.run(["git", *extra, *args], cwd=str(DEPLOY),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout.strip()

    status = run(["status", "--porcelain"])
    head = run(["rev-parse", "HEAD"])
    # 网络是**间歇性**的（2026-09-30 实测：同一条命令连跑 3 次，1 次成功、2 次被重置）。
    # 单次探测失败就判"远端取不到"，会让闸门变成狼来了 —— 所以这里必须重试。
    fetched, how = "", "直连"
    for attempt in range(4):
        for extra, tag in (([], "直连"), (["-c", "http.proxy="], "绕过代理")):
            fetched = run(["ls-remote", REMOTE, BRANCH], extra=extra)
            if fetched:
                how = tag + (f"（第 {attempt + 1} 轮才通）" if attempt else "")
                break
        if fetched:
            break
        time.sleep(2)
    parts = fetched.split()
    return status, head, (parts[0] if parts else "<取不到>"), how


def main() -> int:
    problems: list[str] = []

    if not (DEPLOY / ".git").exists():
        print(f"❌ {DEPLOY} 不是 git 仓库，无法核对")
        return 1

    files = [p for p in tracked_files() if is_scannable(p)]
    print(f"仓库纳入版本控制的文件：{len(tracked_files())} 个，其中可扫描文本 {len(files)} 个")
    print("=" * 66)

    # 危险文件名必须不在仓库里
    names = {p.name for p in tracked_files()}
    for bad in (".env", "secrets.toml"):
        if bad in names:
            problems.append(f"危险文件被纳入版本控制：{bad}")
            print(f"❌ 危险文件在仓库里：{bad}")
    if not any(n in names for n in (".env", "secrets.toml")):
        print("✅ .env / secrets.toml 均未被纳入版本控制")

    # 1) 通用形态扫描
    print("\n【1】通用密钥形态扫描")
    ph = scan_patterns(files)
    if ph:
        for label, f, ln, masked in ph:
            print(f"  ❌ {label} | {f}:{ln} | {masked}")
            problems.append(f"{label} 命中于 {f}:{ln}")
    else:
        print("  ✅ 0 处")

    # 2) 真值反查
    secrets = gather_real_secrets()
    token_secs = {k: v for k, v in secrets.items() if not is_public_value(v)}
    addr_secs = {k: v for k, v in secrets.items() if is_public_value(v)}
    print(f"\n【2】真值反查（本地私有配置取了 {len(secrets)} 个值，长度≥{MIN_SECRET_LEN}）")
    if not secrets:
        print("  ⚠️ 没读到任何私有配置值，无法反查（.env 不存在？）")
    else:
        if token_secs:
            vh = scan_values(files, token_secs)
            if vh:
                for name, f, ln in vh:
                    print(f"  ❌ 命中！{name} 的真值出现在 {f}:{ln}")
                    problems.append(f"{name} 的真值出现在 {f}:{ln}")
            else:
                print(f"  ✅ 凭据类 {len(token_secs)} 个值：仓库文件里**零命中**")
        else:
            print("  ⚠️ 没有识别出凭据类配置值，反查失去意义")
        if addr_secs:
            ah = scan_values(files, addr_secs)
            print(f"  ℹ️ 地址类 {len(addr_secs)} 个值不参与判定"
                  f"（{'命中的是同一份公开端点，不算泄露' if ah else '未命中'}）")
            for name, f, ln in ah:
                print(f"      · {name} 与 {f}:{ln} 是同一个公开地址")
        print("     （反查过的配置项：" + "、".join(sorted(secrets)) + "）")

    # 3) 栈底核对
    print("\n【3】我扫的是不是 GitHub 上那一份？")
    status, head, remote_sha, how = git_probe()
    print(f"  工作区状态 : {'干净' if not status else '有未提交改动 → ' + status[:120]}")
    print(f"  本地 HEAD  : {head}")
    print(f"  远端 main  : {remote_sha}　（取法：{how}）")
    if head and head == remote_sha:
        print("  ✅ 一致 —— 上面扫的就是线上那一份")
    else:
        print("  ❌ 不一致 —— 本地扫描结论对远端不成立")
        problems.append("本地 HEAD 与远端 main 不一致")

    print("\n" + "=" * 66)
    if problems:
        print(f"❌ 发现 {len(problems)} 个问题，**不要推送**：")
        for x in problems:
            print(f"   - {x}")
    else:
        print("✅ 通过：仓库里没有你的任何密钥。")
    print("=" * 66)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
