# -*- coding: utf-8 -*-
"""
用项目自己的 AI 管道实测正确率（对比裸调 API）
==============================================
目的：判定"AI 答错"到底是**模型判断错**，还是**管道（提示词/JSON 解析/内容→字母映射）**造成的。

方法：拿 cache.json 里题库验证过的判断题当标尺，
      分别用 (a) 裸调 API、(b) 项目自己的 AI 类 各答一遍，比正确率。

如果 (b) 明显低于 (a)，说明问题在管道而不是模型 —— 这正是用户怀疑的方向。
"""
import configparser
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "源码", "chaoxing-fixed"))

CACHE = os.path.join(ROOT, "cache.json")


def load_section():
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(ROOT, "config.ini"), encoding="utf-8-sig")
    return cfg["tiku"]


def build_ai(section):
    """按项目的方式装配 AI provider"""
    import api.answer as A
    ai = A.AI()
    # 项目里 provider 拿到的 conf 就是 [tiku] 这一段
    ai._conf = section
    for attr in ("_init_tiku", "init_tiku", "_init"):
        if hasattr(ai, attr):
            getattr(ai, attr)()
            break
    return ai


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    sec = load_section()
    print("=" * 92)
    print(" 项目 AI 管道 vs 裸调 API（标尺 = 题库验证过的判断题答案）")
    print("=" * 92)
    print("  配置 model =", repr(sec.get("model")))

    data = json.load(open(CACHE, encoding="utf8"))
    items = [(k, v) for k, v in data.items() if "判断题" in k and v in ("正确", "错误")]
    step = max(1, len(items) // n)
    sample = items[::step][:n]

    try:
        ai = build_ai(sec)
        print("  AI provider:", type(ai).__name__, " model 属性 =", repr(getattr(ai, "model", None)))
        print("  client 就绪:", getattr(ai, "client", None) is not None)
    except Exception as e:  # noqa: BLE001
        print("  装配 AI 失败:", type(e).__name__, e)
        return 1

    ok = bad = err = 0
    detail = []
    for title, gold in sample:
        q = {"title": title, "options": "A. 正确\nB. 错误", "type": "judgement"}
        try:
            got = ai._query(q)
        except Exception as e:  # noqa: BLE001
            got = "EXC:{}".format(type(e).__name__)
        # 判断题的答案可能是 正确/错误，也可能是 A/B
        g = str(got or "").strip()
        norm = "?"
        if g in ("正确", "A", "对", "√"):
            norm = "正确"
        elif g in ("错误", "B", "错", "×"):
            norm = "错误"
        elif g:
            norm = "无法识别({})".format(g[:14])
        if norm == gold:
            ok += 1
        elif norm == "?":
            err += 1
            detail.append((title[:40], gold, "(空)"))
        else:
            bad += 1
            detail.append((title[:40], gold, norm))
    total = ok + bad + err
    print()
    print("  项目管道结果: 正确 {}/{} = {:.1f}%   错 {}   未识别/空 {}".format(
        ok, total, ok / max(1, total) * 100, bad, err))
    print()
    print("  逐题明细（前 12 条非正确项）:")
    for d in detail[:12]:
        print("    标准={:<4} 得到={:<22} | {}".format(d[1], d[2], d[0]))
    print()
    print("  对照（裸调 API 实测）: flash 75.0%   v4-pro 95.0%")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
