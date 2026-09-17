# -*- coding: utf-8 -*-
"""
考试页：考试看板 + 就绪体检 + 跳转作答。

数据来源：Backend.watch_exams()（阻塞，走后台线程），结果以 kind=exams 事件到达：
    exams: [{course_title, course_id, name, status, exam_id, remain_human, todo, done}]
    ready: {exam_id: {can_start, reason, need_face, need_captcha, need_code, monitor, duration}}

「作答选中考试」不在这里跑任务，而是构造参数跳转到任务页执行 —
刷课/考试共用同一条运行管线（进度、日志、两级停止都在任务页）。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CheckBox, DoubleSpinBox, FluentIcon as FIF,
                            InfoBar, InfoBarPosition, MessageBox, PrimaryPushButton,
                            PushButton, SimpleCardWidget, StrongBodyLabel, TableWidget,
                            TitleLabel)

_FLAG_TEXT = (("need_face", "需人脸"), ("need_captcha", "需验证码"),
              ("need_code", "需考试码"), ("monitor", "有监考"))


class ExamsPage(QWidget):
    def __init__(self, ctx, main_window):
        super().__init__(main_window)
        self.ctx = ctx
        self._win = main_window
        self.setObjectName("examsPage")
        self._exams = []   # 最近一次 exams 事件的内容
        self._ready = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        root.addWidget(TitleLabel("考试"))

        # ---- 工具条 ----
        bar = SimpleCardWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 10, 16, 10)
        bar_layout.setSpacing(10)

        self.refresh_btn = PrimaryPushButton(FIF.SYNC, "读取考试情况")
        self.refresh_btn.clicked.connect(self.refresh)
        bar_layout.addWidget(self.refresh_btn)
        bar_layout.addWidget(StrongBodyLabel("提前提醒"))
        self.hours_spin = DoubleSpinBox()
        self.hours_spin.setRange(1, 720)
        self.hours_spin.setValue(48)
        self.hours_spin.setSuffix(" 小时")
        bar_layout.addWidget(self.hours_spin)
        bar_layout.addStretch(1)
        self.submit_check = CheckBox("答完自动提交")
        bar_layout.addWidget(self.submit_check)
        self.take_btn = PushButton(FIF.PLAY, "作答选中考试")
        self.take_btn.clicked.connect(self._on_take_clicked)
        bar_layout.addWidget(self.take_btn)
        root.addWidget(bar)

        # ---- 考试表 ----
        self.table = TableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["课程", "考试", "剩余时间", "状态", "就绪体检"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        self.hint = BodyLabel("点「读取考试情况」拉取未交/临近的考试；选中一行后可跳转作答")
        self.hint.setTextColor("#6b6b6b", "#9a9a9a")
        root.addWidget(self.hint)

        self.ctx.qt.result.connect(self._on_result)

    # ------------------------------------------------------------------ 交互
    def refresh(self):
        if not self.ctx.logged_in:
            InfoBar.warning("尚未登录", "请先在「首页」登录", parent=self,
                            position=InfoBarPosition.TOP, duration=2500)
            return
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("读取中…")
        self.ctx.qt.watch_exams(self.hours_spin.value())

    def _on_take_clicked(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._exams):
            InfoBar.warning("还没选考试", "先在列表里选中一场考试", parent=self,
                            position=InfoBarPosition.TOP, duration=2500)
            return
        exam = self._exams[row]
        ready = self._ready.get(str(exam.get("exam_id", ""))) or {}
        if ready and not ready.get("can_start"):
            InfoBar.warning("暂不能作答", ready.get("reason") or "就绪检查未通过",
                            parent=self, position=InfoBarPosition.TOP, duration=4000)
            return
        auto = self.submit_check.isChecked()
        if auto:
            box = MessageBox("确认自动提交？",
                             f"将自动作答并提交《{exam.get('course_title', '')}》的"
                             f"「{exam.get('name', '')}」。\n提交后不可撤回，确认继续？",
                             self._win)
            if not box.exec():
                return
        self._win.switchTo(self._win.tasks_page)
        self._win.tasks_page.start_run(overrides={
            "courseIds": [str(exam.get("course_id", ""))],
            "study": False, "exam": True, "examWatch": False,
            "autoSubmit": auto, "maxExams": 1,
        })

    # ------------------------------------------------------------------ 结果与事件
    def _on_result(self, tag: str, payload: str):
        if tag != "exams":
            return
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("读取考试情况")
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if not data.get("ok"):
            InfoBar.error("读取失败", str(data.get("msg", "")), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)

    def handle_event(self, ev: dict):
        if ev.get("kind") != "exams":
            return
        self._exams = ev.get("exams") or []
        self._ready = ev.get("ready") or {}
        self.table.setRowCount(len(self._exams))
        for row, e in enumerate(self._exams):
            self.table.setItem(row, 0, _item(e.get("course_title", "")))
            self.table.setItem(row, 1, _item(e.get("name", "")))
            self.table.setItem(row, 2, _item(e.get("remain_human", "")))
            self.table.setItem(row, 3, _item(self._status_text(e)))
            self.table.setItem(row, 4, _item(self._ready_text(e)))
        todo = sum(1 for e in self._exams if e.get("todo"))
        self.hint.setText(f"共 {len(self._exams)} 场考试（待做 {todo} 场）")

    def _status_text(self, e: dict) -> str:
        if e.get("done"):
            return "已完成"
        if e.get("todo"):
            return "待做"
        return str(e.get("status", "")) or "-"

    def _ready_text(self, e: dict) -> str:
        r = self._ready.get(str(e.get("exam_id", "")))
        if not r:
            return "-"
        flags = [text for key, text in _FLAG_TEXT if r.get(key)]
        if r.get("can_start"):
            return "可作答" + ("（" + "、".join(flags) + "）" if flags else "")
        reason = r.get("reason") or "不可作答"
        return reason + ("（" + "、".join(flags) + "）" if flags else "")


def _item(text):
    from PySide6.QtWidgets import QTableWidgetItem
    return QTableWidgetItem(str(text))
