# -*- coding: utf-8 -*-
"""
入口：组装 FluentWindow 和三个页面，充当 Backend 事件的 Dispatcher。

运行方式（仓库根目录）：
    python start_gui.py
    或：python -m gui.app
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (FluentWindow, FluentIcon as FIF, NavigationItemPosition,
                            Theme, setTheme)

from gui.backend import QtBackend
from gui.pages.bank_page import BankPage
from gui.pages.courses_page import CoursesPage
from gui.pages.exams_page import ExamsPage
from gui.pages.login_page import LoginPage
from gui.pages.settings_page import SettingsPage
from gui.pages.tasks_page import TasksPage


class AppContext:
    """页面间共享的轻量状态。谁写谁读都在注释里标清楚，避免隐式耦合。"""

    def __init__(self):
        self.qt = QtBackend()
        # ---- 登录页写，任务页读 ----
        self.logged_in = False
        self.username = ""
        self.password = ""
        # ---- 课程页写，任务页读 ----
        self.courses = []        # 最近一次 list_courses 的结果
        self.selected_ids = []   # 勾选的 courseId；空 = 用户还没挑


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.ctx = AppContext()
        self.setWindowTitle("超星刷课 · Chaoxing Fixed")
        self.resize(1100, 730)

        self.login_page = LoginPage(self.ctx, self)
        self.courses_page = CoursesPage(self.ctx, self)
        self.tasks_page = TasksPage(self.ctx, self)
        self.exams_page = ExamsPage(self.ctx, self)
        self.bank_page = BankPage(self.ctx, self)
        self.settings_page = SettingsPage(self.ctx, self)

        self.addSubInterface(self.login_page, FIF.HOME, "首页")
        # 需要登录才能用的页面：导航项先禁用，登录成功后放开
        self._gated_nav = [
            self.addSubInterface(self.courses_page, FIF.BOOK_SHELF, "课程"),
            self.addSubInterface(self.tasks_page, FIF.PLAY, "任务"),
            self.addSubInterface(self.exams_page, FIF.EDIT, "考试"),
            self.addSubInterface(self.bank_page, FIF.DICTIONARY, "题库"),
        ]
        self.addSubInterface(self.settings_page, FIF.SETTING, "配置",
                             position=NavigationItemPosition.BOTTOM)
        self.set_authenticated(False)

        # 事件总线：一条 Backend 事件广播给所有页面，各取所需
        self.pages = (self.login_page, self.courses_page, self.tasks_page,
                      self.exams_page, self.bank_page, self.settings_page)
        self.ctx.qt.event.connect(self._dispatch)

    def set_authenticated(self, ok: bool) -> None:
        """登录状态门禁：未登录时禁用 课程/任务/考试/题库 四个页面的入口。"""
        for item in self._gated_nav:
            item.setEnabled(ok)
        if not ok:
            self.switchTo(self.login_page)

    def _dispatch(self, payload: str) -> None:
        try:
            ev = json.loads(payload)
        except ValueError:
            return
        for page in self.pages:
            page.handle_event(ev)


def main() -> None:
    # 高 DPI 下取整策略交给系统，避免 125%/150% 缩放时界面发虚
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    # 显式指定中文字体：离屏/精简环境里 Qt 字体回退会把中文渲染成方框
    app.setFont(QFont("Microsoft YaHei UI", 10))
    setTheme(Theme.AUTO)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
