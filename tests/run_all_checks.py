"""全套监控 —— 依次跑全部检查项, 记录耗时/退出码/报错关键词, 输出汇总报告。

用法: .venv\\Scripts\\python.exe run_all_checks.py
输出: Desktop\\Paper2Lab测试集\\monitor_suite_report.md

设计要点:
- 每项作为子进程运行, 单独设置超时(默认 900s), 超时如实标记 TIMEOUT;
- 记录 stdout+stderr, 并按关键词扫描异常(Traceback/❌/⚠️/异常/未通过/ERR);
- 先跑离线与流水线检查, 最后跑会重启服务的 UI 检查(避免互相干扰)。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
OUT_DIR = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHECKS: list[tuple[str, list[str], int]] = [
    ("五套真实论文样本审计",        ["tests/monitor_samples.py"], 900),
    ("demo / D题 / E题 回归",       ["tests/verify_sets.py"], 600),
    ("边缘集(诱饵值拒收)",          ["tests/verify_edge.py"], 600),
    ("图像通道 开关对比(mock)",     ["tests/verify_vision.py"], 600),
    ("图像通道 真实读图",           ["tests/verify_vision_real.py"], 900),
    # 覆盖策略: 默认读「文本稀薄页」+「正文提及参数/配置页的内嵌插图」。
    # 2026-09-27 实测: 八套样本共 128 个候选区域中 112 个(88%)是"文本已完整解析、
    # 且正文完全没提参数"页面上的插图(几乎必然是结果曲线/示意图) —— NeRF 的 103 个
    # 此类区域**全部零产出**却耗时 583s。设 PAPER2LAB_VISION_READ_ALL=1 可恢复全读。
    ("图像通道 默认覆盖策略",       ["tests/verify_vision_more.py", "0"], 900),
    ("DeepSeek 真实归因",           ["tests/verify_deepseek.py"], 600),
    ("界面 密钥状态与不预填",       ["tests/verify_keys_ui.py"], 600),
    # 模型 API 改造（2026-09-30 用户口径）: 页面输入区是通用的「模型 API」
    # （任意 OpenAI 兼容模型，Key 与 Base URL 成对）；多模态模型可复用模型 API 读图，
    # 单模态则必须单独配视觉 API，否则**如实提示无法读图**。
    # 为什么必须单列一项: 本机 .env 配了视觉 key，"完全没配读图通道"那几条分支
    # 在页面/真机上永远走不到 —— 靠页面点一遍是验证不到的，必须在函数层锁死。
    ("模型 API 与读图通道判定",     ["tests/verify_model_api.py"], 600),
    ("界面 结构与泄漏检查",         ["tests/verify_ui_live.py"], 600),
    ("界面 三路径真机实测",         ["tests/ui_test.py"], 900),
    # 端到端总验收: 像用户一样调用(不预传 key, 走 .env 兜底), 跑真实样本的完整流程。
    # 为什么必须固定跑这一项: 单元级验证脚本都是"作者自己写的", 会顺手传对参数、
    # 从而绕开真实调用路径 —— 2026-09-27 实测, 3 个缺陷(调度员误判跳过读图、Agent 拿不到
    # LLM key、读图问题清单类型错误)在单元级全绿的情况下依然存在, 端到端一跑才暴露。
    ("全流程端到端(真实样本·计划模式)", ["tests/demo_full_flow.py"], 900),
    # 新增守卫的快速回归: 分布参数守卫(分布均值不是取值; 设置型调用要放过)、
    # 读图语境守卫(默认不读"文本完整且未提参数"页的插图; READ_ALL=1 可恢复)、
    # D题种子不得被误补回。2026-09-27 由"全量跑真实样本"发现并修复, 固化为检查防回退。
    # 2026-09-28 并入第⑥节: 精度守卫(压平表格里的数字 / 方括号参考文献编号 / 论文说"迭代次数"
    # 而代码是 EPOCHS 时不得出补丁) —— 这三道由新样本集 v2 的"错补丁"逼出来。
    ("新增守卫 分布/读图/取值精度",  ["tests/verify_guards.py"], 300),
    # 「执行记录」表的两列（环节 / 这次实际做出了什么）由 paper2lab/execview.py 派生；
    # 界面里这张表是 canvas 渲染, DOM 读不到单元格, 所以必须在数据层断言。
    # 另: 界面级验证见 verify_modes_ui.py（四种组合, 约 75s, 按需跑, 未纳入本套）。
    ("执行记录 环节与产出派生",    ["tests/verify_execview.py"], 300),
    # 消融对照: 八套样本「经典模式(固定全跑) vs 计划模式(调度员排计划)」逐项比对。
    # 这是"经典模式为什么不能删"的直接证据 —— 没有对照组就无法证明调度员没改结论。
    ("消融对照 经典vs计划 8套",    ["tests/verify_ablation_modes.py"], 600),
    # 无代码路径: 代码 ZIP 已是**可选**的常规用法, 必须验证"跳过代码扫描"后
    # repro / rootcause / patch / inquiry 四个下游模块都扛得住, 且不凭空给出补丁。
    ("无代码路径 下游模块健壮性",  ["tests/verify_nocode_flow.py"], 600),
    # 就绪度「未核验」语义: 没做核验的维度必须显式标未核验、且不进总分。
    # 2026-09-28 修正 —— 从前"没提供实测结果"会让「结果一致性」显示 100 分(绿色)、
    # 「实验记录完整度」固定给 60 分, 等于把"用户没上传"算成论文的问题。
    # 这条口径影响所有展示的分数, 因此逐样本(8 套)断言, 防回退。
    ("就绪度 未核验语义 8套",      ["tests/verify_readiness_semantics.py"], 600),
    # 第三期三件（复现清单 / 根因追查 / 补丁草案）此前**只在报告之外的脚本里跑**,
    # 没进全套, 也就没有防回退保护。2026-09-28 用户点出"这不是执行 agent 的责任吗"后,
    # 三件已作为流水线环节接入（见 toolbox 的 rootcause / patch 两站）, 与之一并纳入回归。
    # 其中 verify_patch.py 还带一道硬自检: **跑完代码包哈希必须一字不变**（补丁绝不落盘）。
    ("复现清单 出处与建议",        ["tests/verify_repro.py"], 600),
    ("根因追查 只读且可回溯源",     ["tests/verify_rootcause.py"], 600),
    ("补丁草案 闸门与绝不落盘",     ["tests/verify_patch.py"], 600),
    # AI 参与决策的两条通道（2026-09-28）: 排计划 / 给补丁提名目标。
    # **不调 API** —— 用注入的提案测"程序盖章"是否真的挡得住乱来的 AI
    # （核心步骤、有代码包就必须扫、依赖级联、提名越界）。确定性的东西不能靠模型当天心情。
    ("AI 提议+程序盖章 两条通道",   ["tests/verify_llm_planner.py"], 600),
    # 两轮之间的清理口径（2026-09-29 用户要求）: 点下一次"开始审计"时,
    # 必须清掉上一轮的**运行缓存**与**上传临时文件**, 但跨任务记忆
    # （cache/audit_memory.json）必须一字不动 —— 它是记忆不是缓存。
    ("两轮清理 清运行态保记忆",     ["tests/verify_housekeeping.py"], 300),
    # 网页端默认即 agent 模式（2026-09-29 用户口径）: 输入材料启动，默认由 LLM
    # 参与决定跑哪些环节，不跑的环节在流程面板标「未执行」。
    # 真机断言两件事: ① 开关打开页面时就是开的；② 执行记录里确实走了 AI 排计划
    # （若 AI 不可用，必须**如实说明已回退规则版**，不许悄悄退回还说自己是 AI 排的）。
    ("网页端默认 agent 模式",       ["tests/verify_agent_default.py"], 600),
]

ERR_PAT = ("Traceback", "❌", "异常", "未通过", "Error", "error", "ERR:",
           "FAIL", "超时", "TIMEOUT")

# 正常输出里会"看起来像异常"的行, 过滤掉以免误报(如"未通过 0"、空列表、故意造的诱饵文件)
_BENIGN = ("fitz", "pymupdf", "未通过 0", "监控方式", "监控脚本",
           "broken.py",   # 边缘集里故意放的语法错误文件, 被拒收才是正确行为
           "强制 Mock", "对照:", "模板样例",
           # 否定式表述("无异常/无错误")是正常结论, 不是异常
           "无页面异常", "无控制台错误", "无浏览器控制台错误", "无异常", "无错误")


def _benign(line: str) -> bool:
    if any(b in line for b in _BENIGN):
        return True
    s = line.rstrip()
    return s.endswith("[]") or s.endswith(": []")     # 空列表/空结果


def run_one(name: str, args: list[str], timeout: int):
    t0 = time.time()
    try:
        p = subprocess.run([PY, "-X", "utf8", *args], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        code, timed_out = p.returncode, False
    except subprocess.TimeoutExpired as e:
        # text=True 时 stdout/stderr 已是 str; 未设置时为 bytes —— 两种都要能处理
        def _s(v):
            if v is None:
                return ""
            return v if isinstance(v, str) else v.decode("utf-8", "replace")
        out = _s(e.stdout) + _s(e.stderr)
        code, timed_out = -1, True
    el = time.time() - t0
    hits = sorted({ln.strip() for ln in out.splitlines()
                   if any(k in ln for k in ERR_PAT)})
    hits = [h for h in hits if not _benign(h)]
    return {"name": name, "cmd": " ".join(args), "elapsed": el,
            "code": code, "timeout": timed_out, "hits": hits[:12],
            "tail": "\n".join(out.splitlines()[-12:])}


def main():
    results = []
    for i, (name, args, to) in enumerate(CHECKS, 1):
        print(f"[{i}/{len(CHECKS)}] {name} …", flush=True)
        r = run_one(name, args, to)
        results.append(r)
        status = "TIMEOUT" if r["timeout"] else ("OK" if r["code"] == 0 else f"exit={r['code']}")
        print(f"    -> {status}  {r['elapsed']:.1f}s", flush=True)

    bad = [r for r in results if r["timeout"] or r["code"] != 0]
    warn = [r for r in results if r not in bad and r["hits"]]

    md = ["# Paper2Lab 全套监控报告", "",
          f"- 运行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
          f"- 检查项: {len(results)}　异常: {len(bad)}　含警示关键词: {len(warn)}", "",
          "| # | 检查项 | 命令 | 状态 | 耗时 |", "| --- | --- | --- | --- | --- |"]
    for i, r in enumerate(results, 1):
        st = "⏱️ 超时" if r["timeout"] else ("✅ 通过" if r["code"] == 0 else f"❌ exit={r['code']}")
        md.append(f"| {i} | {r['name']} | `{r['cmd']}` | {st} | {r['elapsed']:.1f}s |")

    md += ["", "## 异常与警示明细", ""]
    if not bad and not warn:
        md.append("- 无：全部检查通过，未发现报错、异常或超时。")
    for r in bad:
        st = "超时" if r["timeout"] else ("退出码 " + str(r["code"]))
        md += [f"### ❌ {r['name']}", "",
               f"- 状态: {st}",
               f"- 耗时: {r['elapsed']:.1f}s", "- 输出尾部:", "```text", r["tail"], "```", ""]
    for r in warn:
        md += [f"### ⚠️ {r['name']}（通过但有关键词）", ""]
        for h in r["hits"]:
            md.append(f"- `{h[:160]}`")
        md.append("")

    (OUT_DIR / "monitor_suite_report.md").write_text("\n".join(md), encoding="utf-8")
    print("\n=================== 汇总 ===================")
    for r in results:
        st = "TIMEOUT" if r["timeout"] else ("OK" if r["code"] == 0 else f"exit={r['code']}")
        print(f"{r['name']:28} {st:10} {r['elapsed']:7.1f}s")
    print(f"\n异常 {len(bad)} 项 / 含警示 {len(warn)} 项")
    print(f"报告: {OUT_DIR / 'monitor_suite_report.md'}")

    # ---- 跑完自觉清理（2026-09-28）: 关掉残留进程 + 清运行缓存与临时草稿。
    # 必须放在**最后**: 界面类检查自己会抢占 8501 端口（跑完留着常驻服务白占内存）。
    # 缓存只是提速用的, 删了不影响任何结论; 想跑得快就用 --keep-cache 单独跑那个脚本。
    print("\n--- 跑完清理 ---", flush=True)
    sys.stdout.flush()          # 子进程直接写同一个 fd, 不 flush 会让日志顺序看起来错乱
    subprocess.run([PY, "-X", "utf8", "tools/cleanup_after_run.py"], cwd=str(ROOT))


if __name__ == "__main__":
    sys.exit(main())
