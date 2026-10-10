"""定点调试: DeiT 的 learning_rate / batch_size 每一处命中，各道守卫是否触发。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.paper_parser import (          # noqa: E402
    PARAM_SYNONYMS, _extract_pages, _in_bibliography, _in_table_run,
    _num_ctx_veto, _param_patterns,
)

PDF = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2\04_DeiT\paper.pdf")
pages, _ = _extract_pages(str(PDF))

out = []
for key in ("learning_rate", "batch_size"):
    _disp, aliases = PARAM_SYNONYMS[key]
    pats = _param_patterns(aliases)
    out.append(f"## {key}")
    for i, (page_no, text) in enumerate(pages):
        nxt = pages[i + 1][1] if i + 1 < len(pages) else ""
        guard = text + "\n" + nxt
        for pat in pats:
            for m in pat.finditer(text):
                raw = m.group(1)
                st, en = m.start(), m.end()
                out.append(
                    f"- p{page_no} `{raw}` | 页内表串列={_in_table_run(text, st, en)} "
                    f"| 跨页表串列={_in_table_run(guard, st, en)} "
                    f"| 参考文献={_in_bibliography(guard, st, en)} "
                    f"| 语境否决={_num_ctx_veto(key, text[max(0, st - 90): en + 90]) or '—'}")
                out.append(f"    左20={text[max(0, st - 20): st]!r}")
                out.append(f"    右30={text[en: en + 30]!r}")
    out.append("")

(HERE / "demo/_deit_dbg.md").write_text("\n".join(out), encoding="utf-8")
print("done")
