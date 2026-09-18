# -*- coding: utf-8 -*-
"""
配置页：常用配置项的表单编辑 + config.ini 原文编辑。

表单保存走 Backend.save_config_values（块级改写，用户手写的注释不会丢）；
原文编辑走 read_config_text / write_config_text（整份读写，自负责）。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CheckBox, DoubleSpinBox, FluentIcon as FIF,
                            InfoBar, InfoBarPosition, LineEdit, PasswordLineEdit,
                            PrimaryPushButton, PushButton, ScrollArea, SimpleCardWidget,
                            SpinBox, StrongBodyLabel, TextEdit, TitleLabel)


class SettingsPage(QWidget):
    def __init__(self, ctx, main_window):
        super().__init__(main_window)
        self.ctx = ctx
        self._win = main_window
        self.setObjectName("settingsPage")

        # 整页可滚动（配置项多，小窗口放不下）
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        root.addWidget(TitleLabel("配置"))

        # ---- 题库 ----
        tiku_card, tiku_form = self._card(root, "题库链")
        self.provider_edit = LineEdit()
        self.provider_edit.setPlaceholderText("如 TikuIcodef,TikuAnevol（从左到右依次询问）")
        self.tokens_edit = PasswordLineEdit()
        self.tokens_edit.setPlaceholderText("言溪 / ANEVOL 的 token，多个用英文逗号隔开")
        self.endpoint_edit = LineEdit()
        self.endpoint_edit.setPlaceholderText("AI 接口地址，如 https://example.com/v1")
        self.key_edit = PasswordLineEdit()
        self.key_edit.setPlaceholderText("AI 接口 Key")
        self.model_edit = LineEdit()
        self.model_edit.setPlaceholderText("AI 模型名，如 deepseek-v3")
        self.submit_check = CheckBox("达到覆盖率后自动提交答题")
        self.cover_spin = DoubleSpinBox()
        self.cover_spin.setRange(0.1, 1.0)
        self.cover_spin.setSingleStep(0.1)
        self.cover_spin.setValue(0.9)
        self.delay_spin = DoubleSpinBox()
        self.delay_spin.setRange(0, 60)
        self.delay_spin.setValue(1.0)
        self.delay_spin.setSuffix(" 秒")
        tiku_form.addRow("题库链", self.provider_edit)
        tiku_form.addRow("Token", self.tokens_edit)
        tiku_form.addRow("AI Endpoint", self.endpoint_edit)
        tiku_form.addRow("AI Key", self.key_edit)
        tiku_form.addRow("AI 模型", self.model_edit)
        tiku_form.addRow("提交策略", self.submit_check)
        tiku_form.addRow("最低覆盖率", self.cover_spin)
        tiku_form.addRow("搜题间隔", self.delay_spin)

        # ---- 运行 ----
        run_card, run_form = self._card(root, "运行")
        self.speed_spin = DoubleSpinBox()
        self.speed_spin.setRange(1.0, 2.0)
        self.speed_spin.setSingleStep(0.5)
        self.jobs_spin = SpinBox()
        self.jobs_spin.setRange(1, 8)
        run_form.addRow("视频倍速", self.speed_spin)
        run_form.addRow("并发章节数", self.jobs_spin)

        # ---- 通知 ----
        notify_card, notify_form = self._card(root, "外部通知")
        self.notify_url_edit = LineEdit()
        self.notify_url_edit.setPlaceholderText("Server酱 / Qmsg / Bark 的推送 URL，留空不通知")
        notify_form.addRow("推送 URL", self.notify_url_edit)

        # ---- 保存 ----
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存以上配置")
        self.save_btn.clicked.connect(self._on_save)
        save_row.addWidget(self.save_btn)
        root.addLayout(save_row)

        # ---- 原文编辑 ----
        raw_card = SimpleCardWidget()
        raw_layout = QVBoxLayout(raw_card)
        raw_layout.setContentsMargins(16, 12, 16, 12)
        raw_layout.setSpacing(8)
        raw_layout.addWidget(StrongBodyLabel("config.ini 原文（高级）"))
        self.raw_edit = TextEdit()
        self.raw_edit.setMinimumHeight(220)
        raw_layout.addWidget(self.raw_edit)
        raw_btns = QHBoxLayout()
        raw_btns.addStretch(1)
        load_btn = PushButton(FIF.SYNC, "重新加载")
        load_btn.clicked.connect(self._load_raw)
        save_raw_btn = PushButton(FIF.SAVE, "保存原文")
        save_raw_btn.clicked.connect(self._on_save_raw)
        raw_btns.addWidget(load_btn)
        raw_btns.addWidget(save_raw_btn)
        raw_layout.addLayout(raw_btns)
        root.addWidget(raw_card)

        hint = BodyLabel("表单只覆盖上面列出的键；其余配置请用原文编辑。保存立即生效于下次启动任务。")
        hint.setTextColor("#6b6b6b", "#9a9a9a")
        root.addWidget(hint)

        self.ctx.qt.result.connect(self._on_result)
        self._reload()

    # ------------------------------------------------------------------ 构造辅助
    def _card(self, root: QVBoxLayout, title: str):
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel(title))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(16)
        layout.addLayout(form)
        root.addWidget(card)
        return card, form

    # ------------------------------------------------------------------ 加载 / 保存
    def _reload(self):
        self.ctx.qt.config_values()
        self._load_raw()

    def _load_raw(self):
        self.ctx.qt.read_config_text()

    def _on_save(self):
        pairs = {
            "tiku:provider": self.provider_edit.text().strip(),
            "tiku:tokens": self.tokens_edit.text().strip(),
            "tiku:endpoint": self.endpoint_edit.text().strip(),
            "tiku:key": self.key_edit.text().strip(),
            "tiku:model": self.model_edit.text().strip(),
            "tiku:submit": "true" if self.submit_check.isChecked() else "false",
            "tiku:cover_rate": str(self.cover_spin.value()),
            "tiku:delay": str(self.delay_spin.value()),
            "common:speed": str(self.speed_spin.value()),
            "common:jobs": str(self.jobs_spin.value()),
            "notification:url": self.notify_url_edit.text().strip(),
        }
        self.ctx.qt.save_config_values(pairs)

    def _on_save_raw(self):
        self.ctx.qt.write_config_text(self.raw_edit.toPlainText())

    # ------------------------------------------------------------------ 结果
    def _on_result(self, tag: str, payload: str):
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if tag == "config_values" and data.get("ok"):
            self._fill(data.get("values") or {})
        elif tag == "config_text" and data.get("ok"):
            self.raw_edit.setPlainText(data.get("text", ""))
        elif tag in ("config_save", "config_text_save"):
            if data.get("ok"):
                InfoBar.success("已保存", str(data.get("msg", "配置已写入 config.ini")),
                                parent=self, position=InfoBarPosition.TOP, duration=2500)
                if tag == "config_text_save":
                    self.ctx.qt.config_values()  # 原文改完同步表单
            else:
                InfoBar.error("保存失败", str(data.get("msg", "")), parent=self,
                              position=InfoBarPosition.TOP, duration=4000)

    def _fill(self, values: dict):
        self.provider_edit.setText(values.get("tiku:provider", ""))
        self.tokens_edit.setText(values.get("tiku:tokens", ""))
        self.endpoint_edit.setText(values.get("tiku:endpoint", ""))
        self.key_edit.setText(values.get("tiku:key", ""))
        self.model_edit.setText(values.get("tiku:model", ""))
        self.submit_check.setChecked(values.get("tiku:submit", "false").lower() == "true")
        self.cover_spin.setValue(_float(values.get("tiku:cover_rate"), 0.9))
        self.delay_spin.setValue(_float(values.get("tiku:delay"), 1.0))
        self.speed_spin.setValue(_float(values.get("common:speed"), 1.0))
        self.jobs_spin.setValue(_int(values.get("common:jobs"), 4))
        self.notify_url_edit.setText(values.get("notification:url", ""))

    def handle_event(self, ev: dict):
        pass  # 本页只靠 result 通道，不消费事件流


def _float(text, default):
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _int(text, default):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default
