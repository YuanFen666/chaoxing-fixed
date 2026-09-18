# -*- coding: utf-8 -*-
"""
任务页：运行参数 → preflight → 刷课进度 / 任务状态 / 日志 → 两级停止。

数据流（全部由 Backend 事件驱动，本页不做任何轮询）：
    kind=log      → 日志区（按级别着色）
    kind=state    → 状态行；done/cancelled/error 时复位按钮
    kind=progress → 顶部总进度条（全局：课程数 + 考试阶段）
    kind=task     → 任务表 upsert（按课程名定位行）
    kind=result   → 收尾提示
"""
from __future__ import annotations

import html
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CheckBox, DoubleSpinBox, FluentIcon as FIF,
                            InfoBar, InfoBarPosition, PrimaryPushButton, ProgressBar,
                            PushButton, SimpleCardWidget, SpinBox, StrongBodyLabel,
                            TableWidget, TextEdit, TitleLabel)

_TASK_STATE_TEXT = {"running": "进行中", "done": "已完成", "error": "失败",
                    "pending": "等待中", "cancelled": "已停止"}
_LOG_COLOR = {"ERROR": "#d13438", "WARNING": "#ca5010", "DEBUG": "#8a8a8a"}


class TasksPage(QWidget):
    def __init__(self, ctx, main_window):
        super().__init__(main_window)
        self.ctx = ctx
        self._win = main_window
        self.setObjectName("tasksPage")
        self._stop_armed = False     # False=下一次点击优雅停止；True=强制
        self._task_rows = {}         # 课程名 → 表格行号

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        root.addWidget(TitleLabel("任务"))

        # ---- 运行参数 + 开始/停止 ----
        opt_card = SimpleCardWidget()
        opt = QHBoxLayout(opt_card)
        opt.setContentsMargins(16, 10, 16, 10)
        opt.setSpacing(14)

        opt.addWidget(StrongBodyLabel("倍速"))
        self.speed_spin = DoubleSpinBox()
        self.speed_spin.setRange(1.0, 2.0)      # 与 Backend 的钳制范围一致
        self.speed_spin.setSingleStep(0.5)
        self.speed_spin.setValue(1.0)
        opt.addWidget(self.speed_spin)

        opt.addWidget(StrongBodyLabel("并发"))
        self.jobs_spin = SpinBox()
        self.jobs_spin.setRange(1, 8)
        self.jobs_spin.setValue(4)
        opt.addWidget(self.jobs_spin)

        self.study_check = CheckBox("刷课")
        self.study_check.setChecked(True)
        self.exam_check = CheckBox("考试")
        self.submit_check = CheckBox("自动提交")
        self.watch_check = CheckBox("考试检测")
        self.watch_check.setChecked(True)
        for w in (self.study_check, self.exam_check, self.submit_check, self.watch_check):
            opt.addWidget(w)

        opt.addStretch(1)
        self.start_btn = PrimaryPushButton(FIF.PLAY, "开始刷课")
        self.start_btn.clicked.connect(self.start_run)
        self.stop_btn = PushButton(FIF.CANCEL, "停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        opt.addWidget(self.start_btn)
        opt.addWidget(self.stop_btn)
        root.addWidget(opt_card)

        # ---- 总进度 ----
        prog_card = SimpleCardWidget()
        prog = QHBoxLayout(prog_card)
        prog.setContentsMargins(16, 10, 16, 10)
        prog.setSpacing(12)
        self.progress_bar = ProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.state_label = BodyLabel("就绪")
        self.state_label.setFixedWidth(260)
        prog.addWidget(self.progress_bar, 1)
        prog.addWidget(self.state_label)
        root.addWidget(prog_card)

        # ---- 任务表 ----
        self.table = TableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["课程", "状态", "进度", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 3)

        # ---- 日志 ----
        self.log_view = TextEdit()
        self.log_view.setReadOnly(True)
        root.addWidget(self.log_view, 2)

    # ------------------------------------------------------------------ 开始 / 停止
    def start_run(self, overrides: dict | None = None):
        """启动刷课。overrides 可覆盖界面参数（考试页「作答」就是这么进来的）。"""
        if not self.ctx.logged_in:
            InfoBar.warning("尚未登录", "请先在「首页」登录", parent=self,
                            position=InfoBarPosition.TOP, duration=2500)
            return
        options = {
            "username": self.ctx.username,
            "password": self.ctx.password,
            "speed": self.speed_spin.value(),
            "jobs": self.jobs_spin.value(),
            "courseIds": list(self.ctx.selected_ids),  # 空列表 = 全部课程
            "study": self.study_check.isChecked(),
            "exam": self.exam_check.isChecked(),
            "autoSubmit": self.submit_check.isChecked(),
            "examWatch": self.watch_check.isChecked(),
        }
        if overrides:
            options.update(overrides)
        res = self.ctx.qt.start(options)  # start_run 内部先做 preflight 并逐条打日志
        if not res.get("ok"):
            InfoBar.error("无法启动", str(res.get("msg", "")), parent=self,
                          position=InfoBarPosition.TOP, duration=5000)
            return
        self._enter_running_ui()
        self._log("INFO", "已启动，等待后端事件…")

    def _on_stop_clicked(self):
        # 两级停止：第一下优雅（任务点边界退出），第二下强制（1 秒内中断）
        self.ctx.qt.cancel(force=self._stop_armed)
        if not self._stop_armed:
            self._stop_armed = True
            self.stop_btn.setText("再点一次立即中断")

    # ------------------------------------------------------------------ 事件
    def handle_event(self, ev: dict):
        kind = ev.get("kind")
        if kind == "log":
            self._log(ev.get("level", "INFO"), ev.get("text", ""), ev.get("time", ""))
        elif kind == "state":
            state = ev.get("state", "")
            text = ev.get("text", "")
            if text:
                self.state_label.setText(text)
            if state in ("done", "cancelled", "error"):
                self._exit_running_ui()
        elif kind == "progress":
            total = max(1, int(ev.get("total") or 1))
            done = int(ev.get("done") or 0)
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(done)
            if ev.get("text"):
                self.state_label.setText(ev["text"])
        elif kind == "task":
            self._upsert_task(ev)
        elif kind == "result":
            ok = bool(ev.get("ok"))
            summary = str(ev.get("summary", ""))
            (InfoBar.success if ok else InfoBar.warning)(
                "运行结束" if ok else "未正常结束", summary,
                parent=self._win, position=InfoBarPosition.TOP, duration=4000)
            self._exit_running_ui()

    def _upsert_task(self, ev: dict):
        course = str(ev.get("course", ""))
        state = str(ev.get("state", ""))
        if course in self._task_rows:
            row = self._task_rows[course]
        else:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, _item(course))
            self._task_rows[course] = row
        self.table.setItem(row, 1, _item(_TASK_STATE_TEXT.get(state, state)))
        done, total = ev.get("done"), ev.get("total")
        progress = f"{done}/{total}" if total else "-"
        self.table.setItem(row, 2, _item(progress))
        self.table.setItem(row, 3, _item(str(ev.get("text", ""))))

    def _log(self, level: str, text: str, time_str: str = ""):
        color = _LOG_COLOR.get(level)
        escaped = html.escape(str(text))
        prefix = f"[{time_str}] " if time_str else ""
        body = f"{prefix}[{level}] {escaped}"
        # 必须始终包一层标签：QTextEdit.append 靠「文本里有没有 HTML 标签」猜测格式，
        # 裸文本里的 &gt; 会被当成普通字符原样显示（INFO 行曾因此出现 -&gt;）。
        style = f' style="color:{color}"' if color else ""
        self.log_view.append(f"<span{style}>{body}</span>")

    # ------------------------------------------------------------------ UI 状态切换
    def _enter_running_ui(self):
        self._stop_armed = False
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("停止")
        self.progress_bar.setValue(0)
        self.table.setRowCount(0)
        self._task_rows.clear()

    def _exit_running_ui(self):
        self._stop_armed = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("停止")


def _item(text):
    from PySide6.QtWidgets import QTableWidgetItem
    return QTableWidgetItem(str(text))
