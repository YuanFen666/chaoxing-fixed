# -*- coding: utf-8 -*-
"""
按 provider 顺序分段，统计题库的命中 / 未命中
==============================================
日志里每题都记了来源：
    从ANEVOL题库获取答案        -> 题库命中 ✓
    ANEVOL题库未命中，继续问下一个题库 -> ★ 题库答不上来
    从ANEVOL题库获取答案失败     -> 调用异常（超时/网络）
    从AI大模型答题获取答案        -> 落到 AI 兜底
    从缓存中获取答案             -> 本地缓存命中（0 成本）
每次运行开头会有「查询顺序: X -> Y」，据此把统计分段。
"""
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "chaoxing.log")

RE_ORDER = re.compile(r"查询顺序[:：]\s*(.+?)(?:（|$)")
RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
RE_SRC = re.compile(r"从\s*([^\s：]+?)\s*(?:题库|大模型)?\s*获取(?:答案|解答)[：:]")
RE_MISS = re.compile(r"([A-Za-z\u4e00-\u9fa5]+?)(?:题库)?未命中")


def main():
    if not os.path.exists(LOG):
        print("没有日志:", LOG)
        return 1
    seg = defaultdict(Counter)
    order = "(未知)"
    first_ts = last_ts = ""
    with open(LOG, encoding="utf8", errors="replace") as fp:
        for line in fp:
            line = line.replace("\x1b", "")
            line = re.sub(r"\[\d+(?:;\d+)*m", "", line)
            if "查询顺序" in line:
                m = RE_ORDER.search(line)
                if m:
                    order = m.group(1).strip()
                continue
            ts = RE_TS.match(line)
            if ts:
                if not first_ts:
                    first_ts = ts.group(1)
                last_ts = ts.group(1)
            m = RE_SRC.search(line)
            if m:
                seg[order]["命中:" + m.group(1)] += 1
                continue
            m = RE_MISS.search(line)
            if m:
                seg[order]["未命中:" + m.group(1)] += 1
                continue
            if "获取答案失败" in line:
                m = re.search(r"从\s*(\S+?)\s*获取答案失败", line)
                seg[order]["调用失败:" + (m.group(1) if m else "?")] += 1

    print("=" * 92)
    print(" 按 provider 顺序分段：题库命中 / 未命中统计")
    print("  日志时间范围: {} ~ {}".format(first_ts, last_ts))
    print("=" * 92)
    for order, c in sorted(seg.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(c.values())
        if total < 20:
            continue
        print()
        print("  【顺序: {}】  共 {} 条来源记录".format(order, total))
        for k, v in c.most_common(12):
            print("      {:<28} {}".format(k, v))
        # 只看 ANEVOL 的命中率
        hit = sum(v for k, v in c.items() if k == "命中:ANEVOL")
        miss = sum(v for k, v in c.items() if k == "未命中:ANEVOL")
        fail = sum(v for k, v in c.items() if k == "调用失败:ANEVOL")
        if hit + miss + fail:
            print("      --> ANEVOL：命中 {}，未命中 {}，调用失败 {}；"
                  "命中率 {:.1f}%".format(hit, miss, fail, hit / max(1, hit + miss) * 100))
        ai = sum(v for k, v in c.items() if "AI" in k and k.startswith("命中"))
        print("      --> 落到 AI 兜底 {} 次".format(ai))
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
