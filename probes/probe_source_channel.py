"""看清 info.params / params_all 里每个取值的来源通道与位置（定性用）。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.paper_parser import parse_paper      # noqa: E402

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")
CASES = [
    ("03_ConvNeXt", ["momentum", "iterations"]),
    ("04_DeiT", ["weight_decay", "batch_size", "learning_rate"]),
    ("05_LoRA", ["batch_size", "epochs"]),
]

out = ["# 取值来源通道与位置", ""]
for name, keys in CASES:
    p = parse_paper(str(ROOT / name / "paper.pdf"))
    out.append(f"## {name}")
    for k in keys:
        primary = p.params.get(k)
        out.append(f"- **{k}** 主值: `{primary.raw_value if primary else '—'}` "
                   f"({primary.location if primary else '—'}; parser="
                   f"{primary.parser if primary else '—'})")
        for ev in (p.params_all.get(k) or [])[:6]:
            out.append(f"    - `{ev.raw_value}` @ {ev.location} [{ev.parser}] "
                       f"snippet={ev.snippet[:90]!r}")
    out.append("")

(ROOT / "_source_channel.md").write_text("\n".join(out), encoding="utf-8")
print("done")
