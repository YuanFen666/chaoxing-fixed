# -*- coding: utf-8 -*-
"""
多选题「逐项判断」自测（离线，不联网）
======================================
背景：实考 85 题按题型拆开 —— 单选 87.5% / 判断 86.7% / **多选只有 73.3%**。
      用项目管道在同一批判断题上实测 flash 90%、v4-pro 95%，说明模型和管道都正常，
      问题在"一次吐出所有正确项"的问法容易漏选/多选。
      所以把多选拆成 N 个独立的是非判断，再把判"对"的合起来。

本自测用假 _chat（不打网络）验证：
  · 逐项判断能把选项正确合起来
  · 判"对"的少于 2 个（多选不可能只有 1 个正确项）-> 退回一次性问法
  · 任何一次调用失败 -> 退回一次性问法（不硬编答案）
  · 模型回答认不出来 -> 退回（绝不能把"没说清"当成"错"）
  · multi_choice_mode=all -> 完全不走近项判断（保留旧行为）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api.answer as A


def report(name, ok, extra=""):
    print(" [{}] {}{}".format("PASS" if ok else "FAIL", name, extra))
    return ok


class FakeAI(A.AI):
    """只替换 _chat：按预设脚本回话，不打网络"""

    def __init__(self, script, mode="per_option"):
        self._conf = {"multi_choice_mode": mode}
        self.model = "fake-model"
        self._script = list(script)
        self.calls = []

    def _chat(self, model, messages):
        user = messages[-1]["content"]
        self.calls.append(user)
        if not self._script:
            return None
        item = self._script.pop(0)
        if isinstance(item, Exception) or item is None:
            return None

        class C:
            class choices:  # noqa: N801
                pass
        c = C()
        msg = type("M", (), {"content": item})()
        ch = type("Ch", (), {"message": msg})()
        c.choices = [ch]
        return c


Q = {"title": "下列哪些是奇数？", "options": "A. 1\nB. 2\nC. 3\nD. 4", "type": "multiple"}
OPTS = ["1", "2", "3", "4"]


def main():
    res = []
    print("=" * 92)
    print(" 多选题「逐项判断」自测")
    print("=" * 92)

    # 1) 正常路径：1/3 为对 -> 应合起来
    ai = FakeAI(['{"Answer": ["对"]}', '{"Answer": ["错"]}',
                 '{"Answer": ["对"]}', '{"Answer": ["错"]}'])
    out = ai._ask_multiple_per_option(Q, OPTS)
    res.append(report("逐项判断把 1/3 正确合起来", out == "1\n3", "  -> {!r}".format(out)))
    res.append(report("四个选项各问了一次", len(ai.calls) == 4, "  实际 {} 次".format(len(ai.calls))))

    # 2) 只有 1 个判对 -> 不可靠，必须退回
    ai = FakeAI(['{"Answer": ["对"]}', '{"Answer": ["错"]}',
                 '{"Answer": ["错"]}', '{"Answer": ["错"]}'])
    out = ai._ask_multiple_per_option(Q, OPTS)
    res.append(report("判对的少于 2 个 -> 退回（多选至少 2 个正确项）", out is None,
                      "  -> {!r}".format(out)))

    # 3) 中途调用失败 -> 退回，不能编答案
    ai = FakeAI(['{"Answer": ["对"]}', None])
    out = ai._ask_multiple_per_option(Q, OPTS)
    res.append(report("任何一次调用失败 -> 退回，不硬编答案", out is None, "  -> {!r}".format(out)))

    # 4) 回答认不出来 -> 退回（绝不能当成"错"）
    ai = FakeAI(['{"Answer": ["对"]}', '嗯…这个嘛', '{"Answer": ["对"]}', '{"Answer": ["错"]}'])
    out = ai._ask_multiple_per_option(Q, OPTS)
    res.append(report("模型回答认不出来 -> 退回（不把『没说清』当『错』）", out is None,
                      "  -> {!r}".format(out)))

    # 5) mode=all -> 不走逐项判断
    ai = FakeAI([], mode="all")
    res.append(report("multi_choice_mode=all 时 _multi_mode() 返回 all",
                      ai._multi_mode() == "all"))
    ai2 = FakeAI([], mode="")
    res.append(report("multi_choice_mode 留空/写错 -> 默认 per_option",
                      ai2._multi_mode() == "per_option"))

    # 6) 是非解析器的边界
    cases = [
        ('{"Answer": ["对"]}', "yes"), ('{"Answer": ["错"]}', "no"),
        ('{"Answer":["正确"]}', "yes"), ('{"Answer":["错误"]}', "no"),
        ("这个说法不对", "no"), ("我认为不正确", "no"),
        ("对", "yes"), ("是", "yes"), ("√", "yes"),
        ("嗯…", None), ("", None), (None, None),
    ]
    bad = [(r, A.AI._parse_yes_no(r), w) for r, w in cases if A.AI._parse_yes_no(r) != w]
    res.append(report("是非解析器 {} 个边界用例".format(len(cases)), not bad,
                      "" if not bad else "  失败: {}".format(bad)))

    # 7) 选项为空 -> 直接退回，不该发请求
    ai = FakeAI(['{"Answer": ["对"]}'])
    out = ai._ask_multiple_per_option(Q, [])
    res.append(report("没有选项时直接退回、不发请求", out is None and not ai.calls))

    print("-" * 92)
    print(" 结果: {} passed, {} failed".format(sum(res), len(res) - sum(res)))
    print("=" * 92)
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())
