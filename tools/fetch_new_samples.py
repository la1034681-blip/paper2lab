"""下载新一批测试样本 -> 桌面\\Paper2Lab测试集_v2\\<编号_名称>\\

每个样本一个子目录, 三个文件分开放:
    paper.pdf     论文 (arXiv)
    code.zip      官方代码 (GitHub codeload)
    results.json  "实测结果"(见各目录的 README.md, 会如实说明来源)

校验后才采用:
  · paper.pdf 必须以 %PDF 开头且 > 100KB
  · code.zip 必须能打开, 且 .py 文件数 >= 3
按候选顺序尝试, 取前 NEED 个成功者。

用法: .venv\\Scripts\\python.exe fetch_new_samples.py
"""
from __future__ import annotations

import io
import urllib.request
import zipfile
from pathlib import Path

OUT_ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")
NEED = 6

# (编号名, arXiv pdf, GitHub repo, 分支候选)
CANDIDATES = [
    ("01_Swin", "https://arxiv.org/pdf/2103.14030", "microsoft/Swin-Transformer",
     ["main", "master"]),
    ("02_MAE", "https://arxiv.org/pdf/2111.06377", "facebookresearch/mae",
     ["main", "master"]),
    ("03_ConvNeXt", "https://arxiv.org/pdf/2201.03545",
     "facebookresearch/ConvNeXt", ["main", "master"]),
    ("04_DeiT", "https://arxiv.org/pdf/2012.12877", "facebookresearch/deit",
     ["main", "master"]),
    ("05_LoRA", "https://arxiv.org/pdf/2106.09685", "microsoft/LoRA",
     ["main", "master"]),
    ("06_ImprovedDDPM", "https://arxiv.org/pdf/2102.09672",
     "openai/improved-diffusion", ["main", "master"]),
    ("07_SimSiam", "https://arxiv.org/pdf/2011.10566", "facebookresearch/simsiam",
     ["main", "master"]),
    ("08_PerceiverIO", "https://arxiv.org/pdf/2107.14795",
     "deepmind/deepmind-research", ["master", "main"]),
    ("09_DPR", "https://arxiv.org/pdf/2004.04906", "facebookresearch/DPR",
     ["main", "master"]),
    ("10_Reformer", "https://arxiv.org/pdf/2001.04451",
     "google/trax", ["master", "main"]),
]


def fetch(url: str, timeout: int = 240) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "paper2lab/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check_pdf(data: bytes) -> tuple[bool, str]:
    if not data[:4] == b"%PDF":
        return False, f"文件头不是 %PDF（可能是 HTML 错误页）: {data[:20]!r}"
    if len(data) < 100_000:
        return False, f"太小 {len(data)/1024:.0f}KB"
    return True, f"{len(data)/1024/1024:.1f}MB"


def check_zip(data: bytes) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
    except Exception as e:                       # noqa: BLE001
        return False, f"BadZip: {type(e).__name__}"
    py = sum(1 for n in names if n.endswith(".py"))
    if py < 3:
        return False, f"{len(names)} files / {py} py（仓库可能已清空）"
    return True, f"{len(names)} files / {py} py"


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ok_count = 0
    report: list[str] = []
    for name, pdf_url, repo, branches in CANDIDATES:
        if ok_count >= NEED:
            break
        d = OUT_ROOT / name
        if (d / "paper.pdf").exists() and (d / "code.zip").exists():
            print(f"⏭  {name} 已存在，跳过下载")
            report.append(f"- {name}: 已存在（跳过下载）")
            ok_count += 1
            continue

        # ---- 代码包
        zip_data = None
        for br in branches:
            url = f"https://codeload.github.com/{repo}/zip/refs/heads/{br}"
            try:
                data = fetch(url)
            except Exception as e:               # noqa: BLE001
                print(f"    {name} [{br}] 下载异常: {type(e).__name__}")
                continue
            good, info = check_zip(data)
            print(f"    {name} [{br}] {len(data)/1024:.0f}KB -> {info}")
            if good:
                zip_data = data
                break
        if zip_data is None:
            print(f"❌ {name}: 代码包不可用，换下一个候选")
            report.append(f"- {name}: ✗ 代码包不可用（{repo}）")
            continue

        # ---- 论文
        try:
            pdf_data = fetch(pdf_url)
        except Exception as e:                   # noqa: BLE001
            print(f"❌ {name}: 论文下载异常 {type(e).__name__}")
            report.append(f"- {name}: ✗ 论文下载失败")
            continue
        good, info = check_pdf(pdf_data)
        print(f"    {name} PDF {info}")
        if not good:
            print(f"❌ {name}: 论文不可用，换下一个候选")
            report.append(f"- {name}: ✗ 论文不可用（{info}）")
            continue

        d.mkdir(parents=True, exist_ok=True)
        (d / "paper.pdf").write_bytes(pdf_data)
        (d / "code.zip").write_bytes(zip_data)
        ok_count += 1
        print(f"✅ {name}: 论文 + 代码已就位 -> {d}")
        report.append(f"- {name}: ✅ {repo}（{len(pdf_data)/1024/1024:.1f}MB PDF / "
                      f"{len(zip_data)/1024:.0f}KB ZIP）")

    report.append("")
    report.append(f"共 {ok_count} 套就位")
    (OUT_ROOT / "_download_report.md").write_text(
        "# 新样本下载报告\n\n" + "\n".join(report), encoding="utf-8")
    print("\n" + "\n".join(report))


if __name__ == "__main__":
    main()
