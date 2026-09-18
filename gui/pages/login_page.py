# -*- coding: utf-8 -*-
"""
首页：登录状态管理。

两个状态（QStackedWidget 切换）：
  · 未登录 → 登录表单（账号 / 密码 / 登录）
  · 已登录 → 账号卡片（当前账号 + 切换账号 / 取消登录）

「切换账号」= 先取消登录再退回表单（避免编辑一半时旧会话还在生效的歧义）。
账号密码只保存在本机 config.ini（Backend.login 成功后自动写回）。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon as FIF,
                            IndeterminateProgressBar, InfoBar, InfoBarPosition,
                            LineEdit, PasswordLineEdit, PrimaryPushButton,
                            PushButton, SimpleCardWidget, TitleLabel)


class LoginPage(QWidget):
    def __init__(self, ctx, main_window):
        super().__init__(main_window)
        self.ctx = ctx
        self._win = main_window
        self.setObjectName("loginPage")  # FluentWindow 要求唯一 objectName
        self._prefilled = False

        card = SimpleCardWidget()
        card.setFixedWidth(400)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 30, 36, 30)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_form())     # index 0：未登录
        self.stack.addWidget(self._build_profile())  # index 1：已登录
        card_layout.addWidget(self.stack)

        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(2)

        self.ctx.qt.result.connect(self._on_result)

    # ------------------------------------------------------------------ 两个状态的界面
    def _build_form(self) -> QWidget:
        page = QWidget()
        form = QVBoxLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        title = TitleLabel("超星刷课")
        subtitle = CaptionLabel("使用超星账号登录；账号仅保存在本机 config.ini")
        subtitle.setTextColor("#6b6b6b", "#9a9a9a")

        self.account_edit = LineEdit()
        self.account_edit.setPlaceholderText("手机号 / 邮箱")
        self.account_edit.setClearButtonEnabled(True)

        self.password_edit = PasswordLineEdit()
        self.password_edit.setPlaceholderText("密码")

        self.progress = IndeterminateProgressBar()
        self.progress.setVisible(False)

        self.login_btn = PrimaryPushButton("登 录")
        self.login_btn.setFixedHeight(36)
        self.login_btn.clicked.connect(self._on_login_clicked)

        self.status_label = BodyLabel("")
        self.status_label.setWordWrap(True)

        form.addWidget(title)
        form.addWidget(subtitle)
        form.addSpacing(14)
        form.addWidget(self.account_edit)
        form.addWidget(self.password_edit)
        form.addSpacing(6)
        form.addWidget(self.progress)
        form.addWidget(self.login_btn)
        form.addWidget(self.status_label)

        self.account_edit.returnPressed.connect(self._on_login_clicked)
        self.password_edit.returnPressed.connect(self._on_login_clicked)
        return page

    def _build_profile(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = TitleLabel("已登录")
        self.account_label = BodyLabel("")
        self.account_label.setWordWrap(True)

        self.switch_btn = PrimaryPushButton(FIF.PEOPLE, "切换账号")
        self.switch_btn.setFixedHeight(36)
        self.switch_btn.clicked.connect(self._on_switch_clicked)

        self.logout_btn = PushButton(FIF.CANCEL, "取消登录")
        self.logout_btn.setFixedHeight(36)
        self.logout_btn.clicked.connect(self._on_logout_clicked)

        hint = CaptionLabel("「取消登录」只丢弃当前会话；config.ini 里的账号保留，下次仍可一键登录")
        hint.setTextColor("#6b6b6b", "#9a9a9a")
        hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.account_label)
        layout.addSpacing(14)
        layout.addWidget(self.switch_btn)
        layout.addWidget(self.logout_btn)
        layout.addSpacing(4)
        layout.addWidget(hint)
        return page

    # ------------------------------------------------------------------ 交互
    def showEvent(self, event):
        super().showEvent(event)
        if not self._prefilled:
            self._prefilled = True
            self.ctx.qt.config_values()  # 回填上次保存的账号

    def _on_login_clicked(self):
        username = self.account_edit.text().strip()
        password = self.password_edit.text().strip()
        if not username or not password:
            InfoBar.warning("信息不全", "请输入账号和密码", parent=self,
                            position=InfoBarPosition.TOP, duration=2500)
            return
        self._set_busy(True, "正在登录…")
        self.ctx.qt.login(username, password)

    def _on_switch_clicked(self):
        """切换账号 = 取消登录 + 退回表单（保留账号、清空密码方便换号）。"""
        self._do_logout()
        self.password_edit.clear()
        self.stack.setCurrentIndex(0)
        self.password_edit.setFocus()

    def _on_logout_clicked(self):
        self._do_logout()
        self.stack.setCurrentIndex(0)  # 退回账号密码表单
        InfoBar.success("已取消登录", "会话已丢弃，账号仍保存在本机",
                        parent=self._win, position=InfoBarPosition.TOP, duration=2500)

    def _do_logout(self):
        self.ctx.qt.backend.logout()  # 纯本地操作（清会话/缓存），同步调用即可
        self.ctx.logged_in = False
        self.ctx.courses = []
        self.ctx.selected_ids = []
        self.status_label.setText("")  # 清掉「已登录」之类的旧状态文字
        self._win.set_authenticated(False)  # 禁用四个功能页面并退回首页

    # ------------------------------------------------------------------ 结果与事件
    def _on_result(self, tag: str, payload: str):
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if tag == "config_values":
            values = data.get("values") or {}
            if not self.account_edit.text():
                self.account_edit.setText(values.get("common:username", ""))
            if not self.password_edit.text():
                self.password_edit.setText(values.get("common:password", ""))
        elif tag == "login":
            self._set_busy(False)
            if data.get("ok"):
                self.ctx.logged_in = True
                self.ctx.username = self.account_edit.text().strip()
                self.ctx.password = self.password_edit.text().strip()
                self.account_label.setText(f"当前账号：{self.ctx.username}")
                self.stack.setCurrentIndex(1)
                self._win.set_authenticated(True)  # 放开四个功能页面的入口
                InfoBar.success("登录成功", "账号已保存，下次启动自动回填",
                                parent=self._win, position=InfoBarPosition.TOP,
                                duration=2500)
                # 主链路：登录成功 → 课程页 → 自动拉列表
                self._win.switchTo(self._win.courses_page)
                self._win.courses_page.refresh()
            else:
                self.status_label.setText("登录失败：" + str(data.get("msg", "")))
                InfoBar.error("登录失败", str(data.get("msg", "")),
                              parent=self, position=InfoBarPosition.TOP,
                              duration=4000)

    def handle_event(self, ev: dict):
        if ev.get("kind") == "state" and ev.get("state") in ("login", "error"):
            text = ev.get("text", "")
            if text and self.stack.currentIndex() == 0:
                self.status_label.setText(text)

    def _set_busy(self, busy: bool, text: str = ""):
        self.login_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
        if text:
            self.status_label.setText(text)
