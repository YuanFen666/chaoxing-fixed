# -*- coding: utf-8 -*-
"""
从「批改页」取回考试全部题目，判定 AI 答错的原因
================================================
批改页同时有：题干、选项、**正确答案**、**我提交的答案**。
所以能区分两种完全不同的失败：

  A. 我提交的是**合法字母但选错了**  -> 模型判断错（模型问题）
  B. 我提交的是**空/乱码/多字母**    -> 内容→字母的映射失败（管道问题）

后者才是用户怀疑的"题目上传后变了 / 答案没被正确解析"。
"""
import configparser
import json
import os
import re
import sys

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "源码", "chaoxing-fixed"))

from api.answer import Tiku                      # noqa: E402
from api.base import Chaoxing, Account, SessionManager   # noqa: E402
from api.exam import ExamWatch                   # noqa: E402


def main():
    which = int(sys.argv[1]) if len(sys.argv) > 1 else 2      # 账号序号（1 起）
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(ROOT, "config.ini"), encoding="utf-8-sig")
    acc = [(u.strip(), p.strip()) for u, p in cfg.items("accounts")]
    u, p = acc[which - 1]
    t = Tiku(); t.DISABLE = True
    cx = Chaoxing(account=Account(u, p), tiku=t)
    cx.login(login_with_cookies=False)
    s = SessionManager.get_session()
    courses = cx.get_course_list()
    w = ExamWatch()
    exams = w.fetch(courses)
    for e in exams:
        print("  {:<28} 状态={:<6} examId={}".format(e.name[:26], e.status, e.exam_id))
    print()

    # 找出已交卷（待批阅/已完成）的那场
    target = None
    for e in exams:
        if not e.todo and e.exam_id:
            target = e
    if target is None:
        print("没找到已交卷的考试"); return 1
    course = next((c for c in courses if c.get("courseId") == target.course_id), None)
    print("分析这场:", target.name, " examId =", target.exam_id)

    # 批改页
    uid = s.cookies.get("_uid") or ""
    urls = [
        ("markContentNew", "https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionPaperMarkContentNew"),
        ("markContent", "https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionPaperMarkContent"),
    ]
    html = ""
    for name, url in urls:
        r = s.get(url, params={
            "courseId": course["courseId"], "classId": course["clazzId"], "cpi": course["cpi"],
            "examId": target.exam_id, "examRelationId": "", "userId": uid,
            "ut": "s", "enc": getattr(target, "enc_task", ""), "openc": "", "p": 1, "vx": 0,
        }, timeout=25, allow_redirects=True)
        print("  {} -> HTTP {} {} 字节".format(name, r.status_code, len(r.text or "")))
        if r.status_code == 200 and len(r.text or "") > 3000:
            html = r.text
            break
    if not html:
        print("  批改页取不到 —— 换个思路"); return 1

    open(os.path.join(ROOT, "工具脚本", "_mark_page.html"), "w", encoding="utf8").write(html)
    soup = BeautifulSoup(html, "lxml")
    txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    print("  页面标题:", (soup.title.get_text(strip=True) if soup.title else "")[:40])
    for kw in ("正确答案", "我的答案", "得分", "解析", "共", "题"):
        n = txt.count(kw)
        if n:
            print("    含 {:>5}: {} 次".format(kw, n))
    print()
    print("  片段预览:", txt[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
