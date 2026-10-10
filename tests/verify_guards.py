"""五道守卫的快速回归（合计 < 60s，无需真实 API）。

覆盖:
  ① 分布参数守卫  —— `rng.normal(0.0, ...)` 里的 0.0 不得被当作取值;
                     但 `np.random.seed(42)` / `default_rng(2026)` 这类设置型调用必须放过。
  ② 读图语境守卫  —— 默认跳过"文本完整且未提参数"页的内嵌插图;
                     NeRF 应从 103 个区域降到 0, 且 PAPER2LAB_VISION_READ_ALL=1 能恢复;
                     并校验报告里"另有 N 页未读图"的 N **没有虚报**(报的每页都真有候选图)。
  ③ D题端到端     —— seed 不得再被误补回(该论文正文只有伪代码里的变量名 rng, 没有种子值)。
  ④ 记忆边界      —— 记忆文件里**绝不能出现参数取值**(只记线索、不记结论)。
  ⑤ 就绪度口径    —— 没做核验的维度必须显式标「未核验」且不计入总分,
                     不得因为"用户没提供材料"而给固定扣分。
  ⑥ 精度守卫(2026-09-28 新样本集逼出来的三道)
                  —— 压平表格(多列取值)里的数字、方括号里的参考文献编号,
                     都不得进结论; 论文说"迭代次数"而代码是 EPOCHS 时不得出补丁。
                     这三道是"论文侧取值抽错 -> 补丁跟着错"的直接防线。
"""
from __future__ import annotations
# --- 目录整理（2026-09-30）后补的引导：脚本已下沉一层，需把项目根加回 sys.path ---
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import os
import re
import sys
from pathlib import Path

from paper2lab import memory
from paper2lab.paper_parser import _extract_pages
from paper2lab.patch import _unit_conflict
from paper2lab.pipeline import run_audit
from paper2lab.tools import Candidate, _inside_dist_call, gate, tool_text_scan
from paper2lab.vision import extract_image_regions

ROOT = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集")
V2 = Path(r"C:\Users\lijiahui\Desktop\Paper2Lab测试集_v2")
HERE = Path(__file__).resolve().parent.parent
NEFR = ROOT / "03_NeRF/paper.pdf"

fails: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}")
    if not ok:
        fails.append(label)


print("① 分布参数守卫")
for text, expect, why in [
    ("Y = rng.normal(", True, "分布均值 -> 拦"),
    ("x = rng.uniform(0, ", True, "分布区间端点 -> 拦"),
    ("np.random.seed(", False, "设置种子 -> 放过"),
    ("rng = np.random.default_rng(", False, "设置种子 -> 放过"),
    ("torch.manual_seed(", False, "设置种子 -> 放过"),
    ("The learning rate is ", False, "普通叙述 -> 放过"),
]:
    check(_inside_dist_call(text) is expect, f"{why}: {text!r}")

print("② 读图语境守卫")
os.environ.pop("PAPER2LAB_VISION_READ_ALL", None)
s1: dict = {}
extract_image_regions(str(NEFR), 0, s1)
os.environ["PAPER2LAB_VISION_READ_ALL"] = "1"
s2: dict = {}
extract_image_regions(str(NEFR), 0, s2)
os.environ.pop("PAPER2LAB_VISION_READ_ALL", None)
print(f"     NeRF 候选区域: 默认={s1['candidates']}, READ_ALL=1 时={s2['candidates']}")
check(s1["candidates"] == 0, "默认不读『文本完整且未提参数』页的插图 (NeRF 应为 0)")
check(s2["candidates"] > 50, "PAPER2LAB_VISION_READ_ALL=1 可恢复全读")
check(bool(s1.get("skipped_no_context")), "如实记录被跳过的页码")

# ---- 报告里那句"另有 N 页插图未读图"必须**不多不少** ----
# 基准用产品代码自己算: 在"全读模式"下, 这些页里到底有没有产生候选区域。
# 只有真正会产生候选的区域才算"被跳过"——否则就是给用户虚报工作量。
print("   「未读图页数」口径核对（报告说的 N 是否等于真正被跳过的页数）:")
for name, pdf in [("01_DDPM", ROOT / "01_DDPM/paper.pdf"),
                  ("03_NeRF", NEFR),
                  ("D题", HERE / "demo/D题论文.pdf"),
                  ("E题", Path(r"C:\Users\lijiahui\Desktop\E题论文.pdf"))]:
    if not pdf.exists():
        print(f"     - {name}: 材料缺失，跳过")
        continue
    os.environ.pop("PAPER2LAB_VISION_READ_ALL", None)
    d1: dict = {}
    extract_image_regions(str(pdf), 0, d1)
    os.environ["PAPER2LAB_VISION_READ_ALL"] = "1"
    d2: dict = {}
    r2 = extract_image_regions(str(pdf), 0, d2)
    os.environ.pop("PAPER2LAB_VISION_READ_ALL", None)

    claimed = set(d1.get("skipped_no_context") or [])
    would_have = {x["page"] for x in r2}          # 全读模式下真正有候选的页
    bogus = sorted(claimed - would_have)
    print(f"     - {name}: 报告称未读 {len(claimed)} 页, 其中真有候选图的 "
          f"{len(claimed & would_have)} 页" + (f"；虚报页码 {bogus}" if bogus else ""))
    check(not bogus, f"{name} 无虚报页码（报的每一页都真有候选图）")

print("③ D题: 种子不得被误补回")
a, _ = run_audit(str(HERE / "demo/D题论文.pdf"), str(HERE / "demo/D题代码.zip"),
                 None, force_mock=True, plan_mode=True)
filled = (a.paper.agent_meta or {}).get("filled") or {}
seeds = [f for f in a.findings if f.param_key in ("seed", "random_seed")]
paper_vals = [f.paper.raw_value for f in seeds if f.paper]
print(f"     Agent 补回={filled or '（无）'} | 种子论文侧取值={paper_vals or '（无）'}")
check("seed" not in filled, "seed 未被 Agent 误补回")
check(not paper_vals, "种子没有论文侧取值(正文只有伪代码变量名 rng)")

print("④ 记忆边界: **只记线索, 绝不记取值**")
# 这是"跨任务记忆"最核心的承诺 —— 一旦记忆里出现参数取值, 下次审别的论文
# 就可能张冠李戴。因此用断言守住, 而不是靠打印出来给人看。
#
# 判定方式: **结构化解析 JSON 后按字段类型判断**, 不要用正则扫原文 ——
# 实测(2026-09-28)正则扫原文会误报: 指纹是 sha1 十六进制串(如 `268d347e8a`),
# 其中的 `347e8` 会被科学计数正则误抓成"疑似取值"。
_mem = HERE / "cache" / "audit_memory.json"
# 用 memory.entries() 而不是直接读文件: 文件里可能残留**旧口径**的键
# (实证 2026-09-28: 指纹口径改为"只取论文内容"后残留 1 条同标题旧键,
#  直接读文件会把"同标题多指纹"误判成 bug —— 那些键系统其实永远取不到)。
_effective = memory.entries()
if not _effective:
    print("     （记忆库暂无有效条目，跳过）")
else:
    _bad: list[str] = []

    def _walk(o, path: str = "") -> None:
        if isinstance(o, bool):
            return
        if isinstance(o, float):                     # 浮点数 = 参数取值的典型形态
            _bad.append(f"{path} 是浮点数 {o!r}")
        elif isinstance(o, int):                     # 页码 / 计数: 合法
            return
        elif isinstance(o, str):
            if re.search(r"\d+\.\d+", o):            # 取值被塞进字符串
                _bad.append(f"{path} 字符串里含小数 {o!r}")
        elif isinstance(o, dict):
            for k, v in o.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                _walk(v, f"{path}[{i}]")

    _walk(_effective, "root")
    print(f"     记忆库有效条目 {len(_effective)} 篇 / "
          f"{len(_mem.read_text(encoding='utf-8')) if _mem.exists() else 0} 字符；"
          f"疑似取值的字段：{_bad[:5] or '（无）'}")
    check(not _bad, "记忆里没有任何浮点数或含小数的字符串（参数取值不可能出现）")

    _titles: dict = {}
    for _k, _v in _effective.items():
        _titles.setdefault((_v or {}).get("title") or "(无标题)", []).append(_k)
    _dup = {t: k for t, k in _titles.items() if len(k) > 1}
    print(f"     同一篇论文被拆成多条记录的：{len(_dup)} 篇")
    check(not _dup, "记忆索引按论文收敛（同标题不得多指纹）")

print("⑤ 就绪度: 「未核验」必须显式, 且不得因'没提供材料'扣分")
# 实证来源(2026-09-28): 从前不提供实测结果时,「结果一致性」走默认值显示 **100 分(绿色)**
# —— 一次核验都没做却像"核验过且通过", 比"没有这个维度"更容易误导;
# 「实验记录完整度」固定给 **60 分** —— 这 40 分差与论文质量无关, 只反映"审计有没有拿到
# 实测结果", 等于把"用户没上传"算成"论文的问题"。且方向是反的: 做了核验反而该维度更低分。
_demo_pdf = HERE / "demo/paper.pdf"
_demo_zip = HERE / "demo/project.zip"
_demo_res = json.loads((HERE / "demo/results.json").read_text(encoding="utf-8"))
_with, _ = run_audit(str(_demo_pdf), str(_demo_zip), _demo_res,
                     force_mock=True, plan_mode=True)
_without, _ = run_audit(str(_demo_pdf), str(_demo_zip), None,
                        force_mock=True, plan_mode=True)
_c_no, _ = run_audit(str(_demo_pdf), "", None, force_mock=True, plan_mode=True)
c1 = (_with.readiness or {}).get("categories") or {}
u1 = (_with.readiness or {}).get("unverified") or {}
c2 = (_without.readiness or {}).get("categories") or {}
u2 = (_without.readiness or {}).get("unverified") or {}
c3 = (_c_no.readiness or {}).get("categories") or {}
print(f"     传结果:   记录完整度={c1.get('实验记录完整度')} "
      f"结果一致性={c1.get('结果一致性')} 未核验={u1 or '（无）'}")
print(f"     不传:     记录完整度={c2.get('实验记录完整度')} "
      f"结果一致性={c2.get('结果一致性')} 未核验={list(u2)}")
print(f"     无代码包: 环境一致性={c3.get('环境一致性')}")
check(c1.get("实验记录完整度") == 100, "有实测结果时, 实验记录完整度=100")
check(not u1, "有实测结果时不该出现未核验维度")
check(c2.get("实验记录完整度") is None, "无实测结果时, 实验记录完整度标未核验(不再是固定 60)")
check(c2.get("结果一致性") is None, "无实测结果时, 结果一致性标未核验(不再是默认 100)")
check({"实验记录完整度", "结果一致性"} <= set(u2), "未核验维度必须在 unverified 里逐条给出原因")
check(c3.get("环境一致性") is None, "无代码包时, 环境一致性标未核验(不再是固定 60)")

print("⑥ 精度守卫: 压平表格 / 方括号编号 / 单位不一致")
# 背景(全部来自 2026-09-28 新样本集 v2 的实测): 论文侧取值一旦抽错, 补丁就跟着错,
# 而且错得很"合理"(形态合法、能定位、语法合法)。这三道守卫专治这一类。
#   · DeiT 附录两列对比表压平 -> text-l1 取到 "Batch size" **前面**的 300(Epochs 行的值)
#   · 同一张表 -> llm 取到 ViT-B 那列的 0.003, 并生成 `--lr 5e-4 → 0.003`
#   · MAE Table 8 -> 取到 `[38]`(参考文献编号), 而真值 40 就写在下一行
#   · Swin -> "warmup of 1,500 iterations" 对 `WARMUP_EPOCHS`(轮数)出补丁 20 → 1500

_p1 = [(1, "Methods ViT-B [15] DeiT-B\nEpochs\n300\n300\nBatch size\n4096\n1024\n"
           "Optimizer\nAdamW")]
ok, why, _ = gate(Candidate(key="batch_size", value="300",
                            evidence_text="Epochs\n300\n300", page=1,
                            source="text-l1"), _p1)
print(f"     压平表格: {'拦' if not ok else '放过'} —— {why[:44]}")
check(not ok and "被压平" in why, "(a) 取值与相邻数值只隔空白(压平表格) -> 丢弃")

# 片段**刚好截在表格中间**时也要拦: LLM 常只返回 "learning rate 0.003" 这两行,
# 它确实是原文连续两行, 于是"片段内"看不出异常 —— 必须看页面里紧接着是什么。
_p2 = [(1, "Weight decay\n0.3\n0.05\nlearning rate\n0.003\n0.0005 × batchsize\n512")]
ok, why, _ = gate(Candidate(key="learning_rate", value="0.003",
                            evidence_text="learning rate\n0.003", page=1,
                            source="llm"), _p2)
print(f"     片段截在表中间: {'拦' if not ok else '放过'} —— {why[:44]}")
check(not ok and "被压平" in why, "(b) 证据片段截在表格中间 -> 靠页面紧接处仍能拦下")

_p3 = [(1, "cosine decay [38]\nwarmup epochs [20]\n40\naugmentation\nRandomResizedCrop")]
ok, why, _ = gate(Candidate(key="warmup", value="38",
                            evidence_text="cosine decay [38]", page=1,
                            source="text-l2"), _p3)
print(f"     方括号编号: {'拦' if not ok else '放过'} —— {why[:44]}")
check(not ok and "方括号" in why, "(c) `[38]` 是参考文献编号 -> 丢弃")

# 防误杀: 正常写法必须照过
_p4 = [(1, "We train with a batch size of 4096 for 300 epochs on 8 GPUs "
           "with 2 images per GPU")]
ok, _, _ = gate(Candidate(key="batch_size", value="4096",
                          evidence_text="We train with a batch size of 4096",
                          page=1, source="text-l1"), _p4)
check(ok, "(d) 普通写法「batch size of 4096」仍通过(防误杀)")

# level 2 从"同句里有个数"收成"数是为这个参数写的"(须由连接词挂钩)
_sent = ("For each model we take the largest possible batch size for the usual-"
         "resolution of the model and calculate the average time over 30 runs "
         "to process that batch")
r = tool_text_scan("batch_size", [(1, _sent)], level=2)
print(f"     level 2 采信: {r.candidate.value if r.ok else '（无）'}")
check(not r.ok, "(e) level 2 不再把「over 30 runs」的 30 当批大小")

check(bool(_unit_conflict("_C.TRAIN.WARMUP_EPOCHS = 20",
                          "a linear warmup of 1,500 iterations")),
      "(f) 论文说迭代次数 / 代码是 EPOCHS -> 判为单位冲突")
check(not _unit_conflict("parser.add_argument('--epochs', default=300",
                         "we train for 300 epochs"),
      "(f) 同为轮数 -> 不冲突(防误杀)")
check(not _unit_conflict("parser.add_argument('--lr', default=5e-4",
                         "learning rate 0.003"),
      "(f) 与单位无关的参数 -> 不冲突")

# 真材料复核: DeiT 附录那张两列对比表, 取到的 300 必须被拦
_deit = V2 / "04_DeiT/paper.pdf"
if _deit.exists():
    _p16 = next((t for n, t in _extract_pages(str(_deit))[0] if n == 16), "")
    ok, why, _ = gate(Candidate(key="batch_size", value="300",
                                evidence_text="Epochs\n300\n300", page=16,
                                source="agent"), [(16, _p16)])
    check(not ok and "被压平" in why, "(g) 真材料(DeiT 附录表 p16)复核: 300 被拦下")
else:
    print("     （v2 样本缺失，跳过真材料复核）")

print()
if fails:
    print(f"未通过 {len(fails)} 项:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("全部通过")
