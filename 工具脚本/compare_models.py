# -*- coding: utf-8 -*-
"""
两个模型的正确率 / 花费实测
============================
背景：config.ini 里写的 model = deepseek-chat，但 API 的 /models 只提供
      ['deepseek-flash', 'deepseek-v4-pro'] —— 配的名字根本不合法，
      请求时会被回退到最弱的 flash，这正是 AI 正确率偏低的根因。

标尺：cache.json 里的 888 条答案都是**题库命中过的**（题库在实考中 100%），
      拿它当标准答案来量模型的正确率是可靠的。
      但 cache 只存了题干没存选项，所以只能用【判断题】测 —— 它恰好只需要题干。

用法：python 工具脚本\compare_models.py [题量]
"""
import json
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config.ini")
CACHE = os.path.join(ROOT, "cache.json")


def load_cfg():
    import configparser
    c = configparser.ConfigParser()
    c.read(CFG, encoding="utf-8-sig")
    t = c["tiku"]
    return {
        "endpoint": (t.get("endpoint") or "https://api.deepseek.com/v1").rstrip("/"),
        "key": t.get("key") or "",
        "configured_model": t.get("model") or "",
    }


def ask(cfg, model, title, timeout=40):
    """只回 正确 / 错误 的判断题问法"""
    prompt = (
        "下面是一道判断题，请判断正误。\n"
        "只输出两个字：正确 或 错误。不要解释。\n\n"
        "题目：{}\n".format(title)
    )
    t0 = time.time()
    r = requests.post(
        cfg["endpoint"] + "/chat/completions",
        headers={"Authorization": "Bearer " + cfg["key"], "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            # 别把 max_tokens 设太小：这两个模型会先输出推理内容，
            # 8 个 token 直接截断，content 就是空的（第一版自测就栽在这）。
            "max_tokens": 1024,
        },
        timeout=timeout,
    )
    dt = time.time() - t0
    if r.status_code != 200:
        return None, dt, 0, 0, "HTTP {} {}".format(r.status_code, r.text[:80])
    d = r.json()
    msg = (d.get("choices") or [{}])[0].get("message", {}) or {}
    txt = (msg.get("content") or "").strip()
    if not txt:
        # 推理模型可能把内容放在 reasoning_content 里
        txt = (msg.get("reasoning_content") or "").strip()
    u = d.get("usage", {}) or {}
    return txt, dt, u.get("prompt_tokens", 0), u.get("completion_tokens", 0), ""


def norm(s):
    """
    从模型输出里取结论。

    **取最后一次出现的判断词** —— 推理模型会先说一堆「这句话说……因此……」，
    中间可能出现「正确/错误」的字样，只有最后那句才是它的结论。
    """
    s = (s or "").strip()
    if not s:
        return "?"
    last_pos, last_val = -1, "?"
    for word, val in (("正确", "正确"), ("错误", "错误"), ("不对", "错误"),
                      ("对", "正确"), ("错", "错误"), ("√", "正确"), ("×", "错误")):
        p = s.rfind(word)
        if p > last_pos:
            last_pos, last_val = p, val
    return last_val


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    cfg = load_cfg()
    print("=" * 92)
    print(" 两个模型对比（标尺 = 题库命中过的答案；题目类型：判断题）")
    print("=" * 92)
    print("  配置里写的 model : {!r}".format(cfg["configured_model"]))

    # 先问 API 支持哪些模型
    try:
        r = requests.get(cfg["endpoint"] + "/models",
                         headers={"Authorization": "Bearer " + cfg["key"]}, timeout=20)
        models = [m.get("id") for m in r.json().get("data", [])] if r.ok else []
        print("  API 实际提供     : {}".format(models))
    except Exception as e:  # noqa: BLE001
        print("  查询模型列表失败 : {}".format(e))
        models = ["deepseek-flash", "deepseek-v4-pro"]

    data = json.load(open(CACHE, encoding="utf8"))
    items = [(k, v) for k, v in data.items() if "判断题" in k and v in ("正确", "错误")]
    # 均匀取样，别只取开头（开头都是同一门课的题）
    step = max(1, len(items) // n)
    sample = items[::step][:n]
    print("  题库里可用判断题   : {} 条，本次抽 {} 条".format(len(items), len(sample)))
    print()

    summary = []
    for model in models:
        ok = bad = err = 0
        tin = tout = 0
        tsum = 0.0
        wrong = []
        for title, gold in sample:
            got, dt, pi, po, e = ask(cfg, model, title)
            tsum += dt
            if e:
                err += 1
                continue
            tin += pi
            tout += po
            if norm(got) == gold:
                ok += 1
            else:
                bad += 1
                if len(wrong) < 3:
                    wrong.append((title[:46], gold, (got or "")[:12]))
        total = ok + bad
        acc = (ok / total * 100) if total else 0
        summary.append((model, ok, bad, err, acc, tin, tout, tsum))
        print("  --- {} ---".format(model))
        print("      正确 {}/{} = {:.1f}%   错 {}   异常 {}   平均 {:.2f}s/题".format(
            ok, total, acc, bad, err, tsum / max(1, len(sample))))
        print("      token: 输入 {}  输出 {}（共 {} 题）".format(tin, tout, len(sample)))
        for w in wrong:
            print("      错例: {} | 标准={} 模型={}".format(*w))
        print()

    print("-" * 92)
    print(" 结论")
    for m, ok, bad, err, acc, tin, tout, tsum in summary:
        print("    {:<20} 正确率 {:.1f}%   平均 {:.2f}s/题".format(m, acc, tsum / max(1, len(sample))))
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
