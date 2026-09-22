# -*- coding: utf-8 -*-
"""
思考模式 A/B 实测：enabled(high) vs disabled
============================================
标尺：cache.json 里**题库命中过**的判断题（题干+答案，答案来自题库）。
同一批题、同一个项目管道，只改 thinking 开关，比较：
    正确率 / 输入tokens / 输出tokens / 单题耗时

用法：python 工具脚本\ab_thinking.py [题量，默认30]
"""
import configparser
import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "源码", "chaoxing-fixed"))

import api.answer as A  # noqa: E402


def run_mode(sec, sample, mode, effort):
    cfg = dict(sec)
    cfg["thinking"] = mode
    cfg["reasoning_effort"] = effort
    ai = A.AI()
    ai._conf = cfg
    ai._init_tiku()

    stat = {"in": 0, "out": 0, "ok": 0, "bad": 0, "empty": 0, "t": 0.0}
    wrong = []
    orig = ai._chat

    def patched(model, messages, _orig=orig, _s=stat, **kw):
        r = _orig(model, messages, **kw)
        try:
            u = getattr(r, "usage", None)
            if u:
                _s["in"] += u.prompt_tokens or 0
                _s["out"] += u.completion_tokens or 0
        except Exception:  # noqa: BLE001
            pass
        return r

    ai._chat = patched
    for title, gold in sample:
        q = {"title": title, "options": "A. 正确\nB. 错误", "type": "judgement"}
        t0 = time.time()
        try:
            got = ai._query(q)
        except Exception as e:  # noqa: BLE001
            got = "EXC:{}".format(type(e).__name__)
        stat["t"] += time.time() - t0
        g = str(got or "").strip()
        norm = "正确" if g in ("正确", "A", "对", "√") else \
               ("错误" if g in ("错误", "B", "错", "×") else "")
        if not norm:
            stat["empty"] += 1
            wrong.append((title[:40], gold, "(空/{})".format(g[:10])))
        elif norm == gold:
            stat["ok"] += 1
        else:
            stat["bad"] += 1
            wrong.append((title[:40], gold, norm))
    return stat, wrong


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(ROOT, "config.ini"), encoding="utf-8-sig")
    sec = dict(cfg["tiku"])
    print("=" * 92)
    print(" 思考模式 A/B（同批题、同管道，只改 thinking）")
    print("=" * 92)
    print("  model = {!r}".format(sec.get("model")))

    data = json.load(open(os.path.join(ROOT, "cache.json"), encoding="utf8"))
    items = [(k, v) for k, v in data.items() if "判断题" in k and v in ("正确", "错误")]
    random.seed(20260921)          # 固定种子，两种模式必须用同一批题
    sample = random.sample(items, min(n, len(items)))
    print("  题库可用判断题 {} 条，本次抽 {} 条（固定随机种子）".format(len(items), len(sample)))
    print()

    out = {}
    for mode, effort in (("enabled", "high"), ("disabled", "low")):
        t0 = time.time()
        stat, wrong = run_mode(sec, sample, mode, effort)
        out[mode] = stat
        total = stat["ok"] + stat["bad"] + stat["empty"]
        print("  --- thinking = {} (effort={}) ---".format(mode, effort))
        print("      正确 {}/{} = {:.1f}%   错 {}   空/认不出 {}".format(
            stat["ok"], total, stat["ok"] / max(1, total) * 100, stat["bad"], stat["empty"]))
        print("      tokens: 输入 {}  输出 {}  →  输出/题 {:.0f}".format(
            stat["in"], stat["out"], stat["out"] / max(1, total)))
        print("      耗时: 总计 {:.0f}s，平均 {:.2f}s/题".format(stat["t"], stat["t"] / max(1, total)))
        for w in wrong[:4]:
            print("        错例: 标准={:<4} 得到={:<14} | {}".format(w[1], w[2], w[0]))
        print()

    e, d = out["enabled"], out["disabled"]
    te = e["ok"] + e["bad"] + e["empty"]
    td = d["ok"] + d["bad"] + d["empty"]
    print("-" * 92)
    print(" 对比")
    print("   正确率   enabled {:.1f}%   vs   disabled {:.1f}%".format(
        e["ok"] / max(1, te) * 100, d["ok"] / max(1, td) * 100))
    print("   输出/题  enabled {:.0f}   vs   disabled {:.0f}   （省 {:.0f} 倍）".format(
        e["out"] / max(1, te), d["out"] / max(1, td),
        (e["out"] / max(1, te)) / max(1e-9, d["out"] / max(1, td))))
    print("   速度     enabled {:.2f}s/题  vs  disabled {:.2f}s/题".format(
        e["t"] / max(1, te), d["t"] / max(1, td)))
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
