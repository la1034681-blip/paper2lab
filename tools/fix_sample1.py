"""补齐第 1 个样本: 按候选顺序下载, 校验 zip 有效(py 文件数 > 3) 才采用。

MoCo 仓库已被作者清空(codeload 只返回根目录), 故改用候选列表逐个尝试。
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
TARGET_DIR = ROOT / "01_DDPM"

CANDIDATES = [
    ("DDPM(diffusion)", "hojonathanho/diffusion", ["master", "main"],
     "https://arxiv.org/pdf/2006.11239"),
    ("pix2pixHD", "NVIDIA/pix2pixHD", ["master", "main"],
     "https://arxiv.org/pdf/1712.01208"),
    ("DeepSORT", "nwojke/deep_sort", ["master", "main"],
     "https://arxiv.org/pdf/1703.07402"),
    ("YOLOv3(darknet)", "pjreddie/darknet", ["master", "main"],
     "https://arxiv.org/pdf/1804.02767"),
]


def fetch(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "paper2lab/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def valid_zip(data: bytes) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            py = sum(1 for n in names if n.endswith(".py"))
            return (py >= 3, f"{len(names)} files / {py} py")
    except Exception as e:
        return False, f"BadZip: {type(e).__name__}"


def main() -> None:
    for name, repo, branches, pdf_url in CANDIDATES:
        for br in branches:
            url = f"https://codeload.github.com/{repo}/zip/refs/heads/{br}"
            try:
                data = fetch(url)
            except Exception as e:
                print(f"{name} [{br}] 下载失败: {type(e).__name__}")
                continue
            ok, info = valid_zip(data)
            print(f"{name} [{br}] {len(data) / 1024:.0f}KB -> {info} {'✅' if ok else '❌'}")
            if not ok:
                continue
            TARGET_DIR.mkdir(parents=True, exist_ok=True)
            (TARGET_DIR / "code.zip").write_bytes(data)
            try:
                (TARGET_DIR / "paper.pdf").write_bytes(fetch(pdf_url))
            except Exception as e:
                print("  论文下载失败:", type(e).__name__)
            print(f"✅ 采用 {name} ({repo}@{br}) -> {TARGET_DIR}")
            return
    print("❌ 所有候选都不可用")


if __name__ == "__main__":
    sys.exit(main())
