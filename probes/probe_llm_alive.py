"""快速探针：当前 LLM 通道是否可用。

为什么需要它：网页端的 agent 模式（AI 排计划 / AI 提名补丁目标）依赖 LLM。
若 key 余额不足、网络不通或未配置，系统会**如实回退**规则版并写明原因 ——
那是正确行为（不会假装 AI 排过），但演示时会看不出 agent 的效果。
这个探针一眼看清：可用，还是回退了、为什么。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from paper2lab.envfile import get, load_env      # noqa: E402

load_env()
key = get("DEEPSEEK_API_KEY") or ""
print(f"key      : {'已配置（' + key[:6] + '…，长度 ' + str(len(key)) + '）' if key else '未配置'}")
print(f"base_url : {get('DEEPSEEK_BASE_URL') or '默认 https://api.deepseek.com'}")
print(f"model    : {get('DEEPSEEK_MODEL') or '默认 deepseek-chat'}")

from paper2lab.llm import ask_json               # noqa: E402

obj, note = ask_json('只输出 JSON，不要任何别的文字: {"ok": true}', key,
                     mode="probe-alive", max_tokens=50)
print(f"\n调用结果 : {note}")
print(f"返回     : {obj}")
print("\n判定:", "✅ LLM 通道可用 —— agent 模式能真正生效" if obj
      else "⚠️ LLM 通道**不可用** —— 网页端会如实回退规则版（不是 bug，但演示效果会打折）")

# ---------------------------------------------------------------- 真排一次计划
# 光测"能不能调用"不够：AI 排计划要返回**合法 JSON**，prompt 长、输出长，
# 被截断或格式跑偏都会导致回退。这里真跑一次，把 note 打出来看到底是哪种情况。
print("\n" + "=" * 60)
print("真排一次计划（材料齐备的演示数据）")
print("=" * 60)

from paper2lab.planner import make_plan          # noqa: E402
from paper2lab.toolbox import Job                # noqa: E402

job = Job(pdf_path=str(HERE / "demo" / "paper.pdf"),
          code_path=str(HERE / "demo" / "project.zip"),
          api_key=key)
plan = make_plan(job, plan_mode=True, use_llm=True)
print(f"planner = {plan.planner}    （llm = AI 真的参与了；rule = 回退）")
print(f"执行 {plan.to_dict()['ran']} 个 / 跳过 {plan.to_dict()['skipped']} 个")
print("notes:")
for n in plan.notes[:4]:
    print(f"  · {n[:160]}")

