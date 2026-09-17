# -*- coding: utf-8 -*-
"""
课程页：列出账号下的课程，勾选后跳到任务页开刷。

「含进度」开关会逐门课多打 3 个请求换取完成度/分数（较慢），默认关闭。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CheckBox, FluentIcon as FIF, InfoBar,
                            InfoBarPosition, PrimaryPushButton, PushButton,
                            SimpleCardWidget, TableWidget, TitleLabel)


class CoursesPage(QWidget):
    def __init__(self, ctx, main_window):
        super().__init__(main_window)
        self.ctx = ctx
        self._win = main_window
        self.setObjectName("coursesPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        root.addWidget(TitleLabel("课程"))

        # ---- 工具条 ----
        bar = SimpleCardWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 10, 16, 10)
        bar_layout.setSpacing(10)

        self.refresh_btn = PrimaryPushButton(FIF.SYNC, "读取课程列表")
        self.refresh_btn.clicked.connect(self.refresh)
        self.progress_check = CheckBox("同时读取进度（较慢）")
        self.select_all_btn = PushButton("全选")
        self.select_none_btn = PushButton("全不选")
        self.select_all_btn.clicked.connect(lambda: self._set_all(Qt.Checked))
        self.select_none_btn.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        self.start_btn = PrimaryPushButton(FIF.PLAY, "开始刷所选课程")
        self.start_btn.clicked.connect(self._on_start_selected)

        bar_layout.addWidget(self.refresh_btn)
        bar_layout.addWidget(self.progress_check)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self.select_all_btn)
        bar_layout.addWidget(self.select_none_btn)
        bar_layout.addWidget(self.start_btn)
        root.addWidget(bar)

        # ---- 课程表 ----
        self.table = TableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["", "课程", "教师", "进度"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        self.hint = BodyLabel("点「读取课程列表」拉取账号下的课程；勾选后点「开始刷所选课程」")
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
        self.ctx.qt.refresh_courses(self.progress_check.isChecked())

    def selected_ids(self):
        ids = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _set_all(self, state):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)

    def _on_start_selected(self):
        ids = self.selected_ids()
        if not ids:
            InfoBar.warning("还没选课程", "先在列表里勾选要刷的课程",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        self.ctx.selected_ids = ids
        self._win.switchTo(self._win.tasks_page)
        self._win.tasks_page.start_run()

    # ------------------------------------------------------------------ 结果与事件
    def _on_result(self, tag: str, payload: str):
        if tag != "courses":
            return
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("读取课程列表")
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if not data.get("ok"):
            msg = str(data.get("msg", ""))
            if "未登录" in msg:
                InfoBar.warning("尚未登录", "请先在「首页」登录",
                                parent=self, position=InfoBarPosition.TOP, duration=2500)
            else:
                InfoBar.error("读取失败", msg, parent=self,
                              position=InfoBarPosition.TOP, duration=4000)

    def handle_event(self, ev: dict):
        if ev.get("kind") != "courses":
            return
        courses = ev.get("courses") or []
        self.ctx.courses = courses
        self.table.setRowCount(len(courses))
        for row, c in enumerate(courses):
            self.table.setItem(row, 0, _check_item(c.get("courseId", "")))
            self.table.setItem(row, 1, _item(c.get("title", "")))
            self.table.setItem(row, 2, _item(c.get("teacher", "")))
            percent = c.get("percent")
            progress = c.get("progress") or ""
            if percent is not None:
                progress = f"{progress}（{percent}%）" if progress else f"{percent}%"
            self.table.setItem(row, 3, _item(progress))
        self.hint.setText(f"共 {len(courses)} 门课程，默认全选；勾选后点右上角「开始刷所选课程」")


def _item(text):
    """普通只读单元格。"""
    from PySide6.QtWidgets import QTableWidgetItem
    return QTableWidgetItem(str(text))


def _check_item(course_id):
    """第一列的勾选项：UserRole 里存 courseId；默认勾选（「全都要刷」是主流场景）。"""
    from PySide6.QtWidgets import QTableWidgetItem
    item = QTableWidgetItem()
    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
    item.setCheckState(Qt.Checked)
    item.setData(Qt.UserRole, str(course_id))
    return item
