# -*- coding: utf-8 -*-
"""
题库页：答案库（answer_key.json）+ 刷题缓存（cache.json）的查看与维护。

后端方法（全部本地操作，不需要登录）：
    bank_stats()            → 两个库的条数/大小
    bank_search(kw, limit)  → 跨库模糊搜索
    bank_add(q, a)          → 写入已核验答案库（归一化题干）
    bank_export(which,path) → 导出为 TSV
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, FluentIcon as FIF, InfoBar, InfoBarPosition,
                            LineEdit, PrimaryPushButton, PushButton, SearchLineEdit,
                            SimpleCardWidget, TableWidget, TitleLabel)


class BankPage(QWidget):
    def __init__(self, ctx, main_window):
        super().__init__(main_window)
        self.ctx = ctx
        self._win = main_window
        self.setObjectName("bankPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        root.addWidget(TitleLabel("题库"))

        # ---- 统计 + 搜索 ----
        top = SimpleCardWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 10, 16, 10)
        top_layout.setSpacing(10)
        self.stats_label = BodyLabel("答案库 - 条 · 缓存 - 条")
        self.refresh_btn = PushButton(FIF.SYNC, "刷新")
        self.refresh_btn.clicked.connect(self.ctx.qt.bank_stats)
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索题干或答案…")
        self.search_edit.searchSignal.connect(self._on_search)
        self.search_edit.returnPressed.connect(
            lambda: self._on_search(self.search_edit.text()))
        top_layout.addWidget(self.stats_label)
        top_layout.addWidget(self.refresh_btn)
        top_layout.addStretch(1)
        top_layout.addWidget(self.search_edit, 2)
        root.addWidget(top)

        # ---- 结果表 ----
        self.table = TableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["来源", "题干", "答案"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setWordWrap(False)
        root.addWidget(self.table, 1)

        # ---- 添加 + 导出 ----
        bottom = SimpleCardWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 10, 16, 10)
        bottom_layout.setSpacing(10)
        self.q_edit = LineEdit()
        self.q_edit.setPlaceholderText("题干")
        self.a_edit = LineEdit()
        self.a_edit.setPlaceholderText("答案")
        self.add_btn = PrimaryPushButton(FIF.ADD, "添加")
        self.add_btn.clicked.connect(self._on_add)
        self.export_key_btn = PushButton(FIF.SAVE, "导出答案库")
        self.export_cache_btn = PushButton(FIF.SAVE, "导出缓存")
        self.export_key_btn.clicked.connect(lambda: self._on_export("answer_key"))
        self.export_cache_btn.clicked.connect(lambda: self._on_export("cache"))
        bottom_layout.addWidget(self.q_edit, 3)
        bottom_layout.addWidget(self.a_edit, 2)
        bottom_layout.addWidget(self.add_btn)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.export_key_btn)
        bottom_layout.addWidget(self.export_cache_btn)
        root.addWidget(bottom)

        self.ctx.qt.result.connect(self._on_result)
        self.ctx.qt.bank_stats()

    # ------------------------------------------------------------------ 交互
    def _on_search(self, keyword: str):
        self.ctx.qt.bank_search(keyword.strip())

    def _on_add(self):
        q, a = self.q_edit.text().strip(), self.a_edit.text().strip()
        if not q or not a:
            InfoBar.warning("信息不全", "题干和答案都要填", parent=self,
                            position=InfoBarPosition.TOP, duration=2500)
            return
        self.ctx.qt.bank_add(q, a)

    def _on_export(self, which: str):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出", f"{which}.tsv", "TSV 文件 (*.tsv);;所有文件 (*)")
        if path:
            self.ctx.qt.bank_export(which, path)

    # ------------------------------------------------------------------ 结果
    def _on_result(self, tag: str, payload: str):
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if tag == "bank_stats" and data.get("ok"):
            stats = data.get("stats") or {}
            key_info = stats.get("answer_key") or {}
            cache_info = stats.get("cache") or {}
            self.stats_label.setText(
                f"答案库 {key_info.get('count', 0)} 条 · 缓存 {cache_info.get('count', 0)} 条")
        elif tag == "bank_search" and data.get("ok"):
            self._fill(data.get("rows") or [])
        elif tag == "bank_add":
            if data.get("ok"):
                self.q_edit.clear()
                self.a_edit.clear()
                InfoBar.success("已添加", "答案已写入答案库", parent=self,
                                position=InfoBarPosition.TOP, duration=2000)
                self.ctx.qt.bank_stats()  # 刷新统计
            else:
                InfoBar.error("添加失败", str(data.get("msg", "")), parent=self,
                              position=InfoBarPosition.TOP, duration=4000)
        elif tag == "bank_export":
            if data.get("ok"):
                InfoBar.success("导出成功", str(data.get("msg", "")), parent=self,
                                position=InfoBarPosition.TOP, duration=3000)
            else:
                InfoBar.error("导出失败", str(data.get("msg", "")), parent=self,
                              position=InfoBarPosition.TOP, duration=4000)

    def _fill(self, rows):
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for col, key in enumerate(("source", "question", "answer")):
                self.table.setItem(i, col, _item(r.get(key, "")))

    def handle_event(self, ev: dict):
        pass  # 本页只靠 result 通道，不消费事件流


def _item(text):
    from PySide6.QtWidgets import QTableWidgetItem
    return QTableWidgetItem(str(text))
