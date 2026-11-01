#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务管理器 (PyQt6 单文件版)

运行方式:
    pip install PyQt6
    python task_manager.py

数据保存位置: ~/.task_manager/tasks.json
"""
import json
import os
import sys
import uuid
from datetime import date

from PyQt6.QtCore import QDate, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

DATA_DIR = os.path.join(os.path.expanduser("~"), ".task_manager")
DATA_FILE = os.path.join(DATA_DIR, "tasks.json")

PRIORITIES = ["高", "中", "低"]
PRIORITY_COLORS = {0: "#d93025", 1: "#e8a200", 2: "#188038"}


# ---------------------------------------------------------------- 数据层
def load_tasks():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def save_tasks(tasks):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- 编辑对话框
class TaskDialog(QDialog):
    def __init__(self, parent=None, task=None):
        super().__init__(parent)
        self.setWindowTitle("编辑任务" if task else "新建任务")
        self.setMinimumWidth(420)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("请输入任务标题")
        self.priority_box = QComboBox()
        self.priority_box.addItems(PRIORITIES)
        self.priority_box.setCurrentIndex(1)

        self.due_check = QCheckBox("设置截止日期")
        self.due_edit = QDateEdit(QDate.currentDate())
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDisplayFormat("yyyy-MM-dd")
        self.due_edit.setEnabled(False)
        self.due_check.toggled.connect(self.due_edit.setEnabled)

        due_row = QHBoxLayout()
        due_row.addWidget(self.due_check)
        due_row.addWidget(self.due_edit, 1)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("备注（可选）")
        self.notes_edit.setFixedHeight(100)

        form = QFormLayout()
        form.addRow("标题：", self.title_edit)
        form.addRow("优先级：", self.priority_box)
        form.addRow("截止：", due_row)
        form.addRow("备注：", self.notes_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if task:
            self.title_edit.setText(task["title"])
            self.priority_box.setCurrentIndex(task.get("priority", 1))
            self.notes_edit.setPlainText(task.get("notes", ""))
            if task.get("due"):
                d = QDate.fromString(task["due"], "yyyy-MM-dd")
                if d.isValid():
                    self.due_check.setChecked(True)
                    self.due_edit.setDate(d)

    def _accept(self):
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "提示", "任务标题不能为空")
            return
        self.accept()

    def values(self):
        return {
            "title": self.title_edit.text().strip(),
            "priority": self.priority_box.currentIndex(),
            "due": self.due_edit.date().toString("yyyy-MM-dd") if self.due_check.isChecked() else "",
            "notes": self.notes_edit.toPlainText().strip(),
        }


# ---------------------------------------------------------------- 主窗口
class MainWindow(QMainWindow):
    COLS = ["完成", "任务", "优先级", "截止日期", "备注"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("任务管理器")
        self.resize(900, 580)
        self.tasks = load_tasks()

        # 顶部：搜索 + 过滤
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 搜索标题或备注…")
        self.search.setClearButtonEnabled(True)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部", "未完成", "已完成", "已逾期"])
        self.prio_filter = QComboBox()
        self.prio_filter.addItems(["所有优先级"] + [f"{p}优先级" for p in PRIORITIES])

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.status_filter)
        top.addWidget(self.prio_filter)

        # 表格
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        # 按钮
        self.btn_add = QPushButton("＋ 新建任务")
        self.btn_edit = QPushButton("编辑")
        self.btn_del = QPushButton("删除")
        self.btn_clear = QPushButton("清除已完成")
        self.stats = QLabel()
        btns = QHBoxLayout()
        for b in (self.btn_add, self.btn_edit, self.btn_del, self.btn_clear):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(self.stats)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addLayout(btns)
        self.setCentralWidget(central)

        # 信号
        self.btn_add.clicked.connect(self.add_task)
        self.btn_edit.clicked.connect(self.edit_task)
        self.btn_del.clicked.connect(self.delete_tasks)
        self.btn_clear.clicked.connect(self.clear_done)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.itemDoubleClicked.connect(lambda it: it.column() != 0 and self.edit_task())
        self.search.textChanged.connect(self.refresh)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.prio_filter.currentIndexChanged.connect(self.refresh)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.add_task)
        QShortcut(QKeySequence("Delete"), self.table, activated=self.delete_tasks)
        QShortcut(QKeySequence("Return"), self.table, activated=self.edit_task)

        self.setStyleSheet("""
            QPushButton { padding: 6px 14px; }
            QTableWidget { alternate-background-color: rgba(128,128,128,0.08); }
            QTableWidget::item { padding: 4px; }
        """)
        self.refresh()

    # ---- 工具
    @staticmethod
    def is_overdue(t):
        return bool(t.get("due")) and not t["done"] and t["due"] < date.today().isoformat()

    def find(self, tid):
        return next((t for t in self.tasks if t["id"] == tid), None)

    def selected_ids(self):
        rows = {i.row() for i in self.table.selectedItems()}
        return [self.table.item(r, 1).data(Qt.ItemDataRole.UserRole) for r in sorted(rows)]

    def persist(self):
        if not save_tasks(self.tasks):
            QMessageBox.critical(self, "错误", f"无法保存数据到\n{DATA_FILE}")

    # ---- 刷新表格
    def refresh(self):
        kw = self.search.text().strip().lower()
        sf = self.status_filter.currentIndex()
        pf = self.prio_filter.currentIndex() - 1

        def ok(t):
            if kw and kw not in t["title"].lower() and kw not in t.get("notes", "").lower():
                return False
            if sf == 1 and t["done"]:
                return False
            if sf == 2 and not t["done"]:
                return False
            if sf == 3 and not self.is_overdue(t):
                return False
            if pf >= 0 and t.get("priority", 1) != pf:
                return False
            return True

        shown = sorted(
            (t for t in self.tasks if ok(t)),
            key=lambda t: (t["done"], t.get("due") or "9999-99-99", t.get("priority", 1)),
        )

        self.table.blockSignals(True)
        self.table.setRowCount(len(shown))
        for r, t in enumerate(shown):
            overdue = self.is_overdue(t)
            prio = t.get("priority", 1)
            cells = [
                QTableWidgetItem(),
                QTableWidgetItem(t["title"]),
                QTableWidgetItem(PRIORITIES[prio]),
                QTableWidgetItem(t.get("due", "") or "—"),
                QTableWidgetItem(t.get("notes", "").replace("\n", " ")),
            ]
            cells[0].setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            cells[0].setCheckState(Qt.CheckState.Checked if t["done"] else Qt.CheckState.Unchecked)
            cells[1].setData(Qt.ItemDataRole.UserRole, t["id"])
            cells[2].setForeground(QBrush(QColor(PRIORITY_COLORS[prio])))
            cells[2].setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cells[3].setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            for c, item in enumerate(cells):
                f = QFont(item.font())
                if t["done"]:
                    f.setStrikeOut(True)
                    if c != 0:
                        item.setForeground(QBrush(QColor("#888888")))
                if c == 2 and not t["done"]:
                    f.setBold(True)
                if overdue and c in (1, 3):
                    item.setForeground(QBrush(QColor("#d93025")))
                item.setFont(f)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

        total = len(self.tasks)
        done = sum(t["done"] for t in self.tasks)
        overdue_n = sum(self.is_overdue(t) for t in self.tasks)
        self.stats.setText(f"共 {total} 项 | 已完成 {done} | 未完成 {total - done} | 逾期 {overdue_n}")

    # ---- 操作
    def on_item_changed(self, item):
        if item.column() != 0:
            return
        tid = self.table.item(item.row(), 1).data(Qt.ItemDataRole.UserRole)
        t = self.find(tid)
        if t:
            t["done"] = item.checkState() == Qt.CheckState.Checked
            self.persist()
            QTimer.singleShot(0, self.refresh)

    def add_task(self):
        dlg = TaskDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            t = dlg.values()
            t.update(id=uuid.uuid4().hex, done=False, created=date.today().isoformat())
            self.tasks.append(t)
            self.persist()
            self.refresh()

    def edit_task(self):
        ids = self.selected_ids()
        if len(ids) != 1:
            if not ids:
                QMessageBox.information(self, "提示", "请先选择一个任务")
            else:
                QMessageBox.information(self, "提示", "一次只能编辑一个任务")
            return
        t = self.find(ids[0])
        dlg = TaskDialog(self, t)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            t.update(dlg.values())
            self.persist()
            self.refresh()

    def delete_tasks(self):
        ids = self.selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, "确认删除", f"确定删除选中的 {len(ids)} 个任务吗？") \
                == QMessageBox.StandardButton.Yes:
            self.tasks = [t for t in self.tasks if t["id"] not in ids]
            self.persist()
            self.refresh()

    def clear_done(self):
        n = sum(t["done"] for t in self.tasks)
        if not n:
            QMessageBox.information(self, "提示", "没有已完成的任务")
            return
        if QMessageBox.question(self, "确认", f"确定清除全部 {n} 个已完成任务吗？") \
                == QMessageBox.StandardButton.Yes:
            self.tasks = [t for t in self.tasks if not t["done"]]
            self.persist()
            self.refresh()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
