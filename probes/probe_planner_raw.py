"""诊断：AI 排计划的 LLM 到底返回了什么，为什么不是合法 JSON。

背景（2026-09-29 实测）：`make_plan(use_llm=True)` 每次都回退规则版，
note 写的是「AI（plan）· 返回不是合法 JSON」。也就是说**这个功能其实一直没跑通** ——
光看代码看不出来，必须把原始返回打出来。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.envfile import get, load_env      # noqa: E402

load_env()
key = get("DEEPSEEK_API_KEY") or ""

from paper2lab.llm import _call_deepseek, _extract_json   # noqa: E402
from paper2lab.planner import _llm_prompt, _rule_plan     # noqa: E402
from paper2lab.toolbox import Job                         # noqa: E402

job = Job(pdf_path=str(HERE / "demo" / "paper.pdf"),
          code_path=str(HERE / "demo" / "project.zip"),
          api_key=key)
base = _rule_plan(job, plan_mode=True)
prompt = _llm_prompt(job, base)
print(f"prompt 长度 : {len(prompt)} 字符")
print(f"prompt 尾部 : …{prompt[-160:]}")
print()

for mt in (900, 2000):
    print("=" * 62)
    print(f"max_tokens = {mt}")
    print("=" * 62)
    try:
        raw = _call_deepseek(prompt, key, max_tokens=mt)
    except Exception as ex:      # noqa: BLE001
        print(f"调用异常: {type(ex).__name__}: {ex}")
        continue
    print(f"返回长度 : {len(raw)} 字符")
    print("--- 前 600 字符 ---")
    print(raw[:600])
    print("--- 后 300 字符 ---")
    print(raw[-300:])
    obj = _extract_json(raw)
    print(f"--- _extract_json 结果: {type(obj).__name__} / {obj if obj is None else '解析成功'} ---")
    print()

# ---- 走真实路径（ask_json，含缓存与异常兜底）连跑 3 次：判断是偶发还是稳定失败
# 用递增的 mode 前缀，避免缓存把结果顶掉（否则测的是缓存不是调用）。
print("=" * 62)
print("走真实路径 ask_json（mode 各不相同以绕开缓存）× 3")
print("=" * 62)

from paper2lab.llm import ask_json                        # noqa: E402

for i in range(3):
    obj2, note2 = ask_json(prompt, key, mode=f"planprobe{i}", max_tokens=900)
    good = isinstance(obj2, dict) and isinstance(obj2.get("decisions"), list)
    n_dec = len(obj2.get("decisions", [])) if isinstance(obj2, dict) else 0
    print(f"  第 {i + 1} 次: {'✅ 解析成功' if good else '❌ 失败'}"
          f"（decisions={n_dec}）— {note2}")

