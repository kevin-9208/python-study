#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轻量级本地桌面记账软件
依赖：pip install PyQt5
运行：python accounting_app.py
"""

import sys
import sqlite3
import os
from datetime import datetime, date
from collections import defaultdict
import math

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QLineEdit, QComboBox,
    QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QMenu, QAction, QFrame, QSizePolicy,
    QScrollArea, QGridLayout, QDialog, QDialogButtonBox,
    QAbstractItemView, QToolButton, QSpacerItem
)
from PyQt5.QtCore import (
    Qt, QDate, QSize, QRect, QPoint, QTimer, pyqtSignal
)
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QBrush,
    QLinearGradient, QPainterPath, QIcon, QPixmap, QPalette
)


# ─────────────────────────────────────────────
#  数据库层
# ─────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounting_app.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT    NOT NULL,
                type      TEXT    NOT NULL,   -- '收入' or '支出'
                category  TEXT    NOT NULL,
                amount    REAL    NOT NULL,
                note      TEXT    DEFAULT '',
                created   TEXT    DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()

def insert_record(date_str, rec_type, category, amount, note):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO records (date, type, category, amount, note) VALUES (?,?,?,?,?)",
            (date_str, rec_type, category, amount, note)
        )
        conn.commit()

def update_record(rid, date_str, rec_type, category, amount, note):
    with get_connection() as conn:
        conn.execute(
            "UPDATE records SET date=?, type=?, category=?, amount=?, note=? WHERE id=?",
            (date_str, rec_type, category, amount, note, rid)
        )
        conn.commit()

def delete_record(rid):
    with get_connection() as conn:
        conn.execute("DELETE FROM records WHERE id=?", (rid,))
        conn.commit()

def fetch_records(year=None, month=None):
    sql = "SELECT * FROM records"
    params = []
    if year and month:
        sql += " WHERE strftime('%Y', date)=? AND strftime('%m', date)=?"
        params = [str(year), f"{month:02d}"]
    sql += " ORDER BY date DESC, id DESC"
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()

def fetch_monthly_stats(year, month):
    """Return dict: category -> total_amount for expense of given month."""
    sql = """
        SELECT category, SUM(amount) as total
        FROM records
        WHERE type='支出'
          AND strftime('%Y', date)=?
          AND strftime('%m', date)=?
        GROUP BY category
    """
    with get_connection() as conn:
        rows = conn.execute(sql, [str(year), f"{month:02d}"]).fetchall()
    return {r["category"]: r["total"] for r in rows}

def fetch_summary(year, month):
    sql = """
        SELECT type, SUM(amount) as total
        FROM records
        WHERE strftime('%Y', date)=?
          AND strftime('%m', date)=?
        GROUP BY type
    """
    with get_connection() as conn:
        rows = conn.execute(sql, [str(year), f"{month:02d}"]).fetchall()
    result = {"收入": 0.0, "支出": 0.0}
    for r in rows:
        result[r["type"]] = r["total"]
    return result


# ─────────────────────────────────────────────
#  主题定义
# ─────────────────────────────────────────────
LIGHT_THEME = {
    "bg":          "#F5F7FA",
    "surface":     "#FFFFFF",
    "surface2":    "#EEF1F6",
    "border":      "#DDE1EA",
    "text":        "#1A1D2E",
    "text2":       "#6B7280",
    "accent":      "#4F6EF7",
    "accent2":     "#7C3AED",
    "income":      "#10B981",
    "expense":     "#EF4444",
    "hover":       "#EBF0FF",
    "header_bg":   "#4F6EF7",
    "header_text": "#FFFFFF",
    "row_alt":     "#F8F9FC",
    "shadow":      "rgba(79,110,247,0.12)",
}

DARK_THEME = {
    "bg":          "#0F1117",
    "surface":     "#1A1D2E",
    "surface2":    "#252838",
    "border":      "#2E3248",
    "text":        "#E8EAF0",
    "text2":       "#8B91A8",
    "accent":      "#6C8EFF",
    "accent2":     "#A78BFA",
    "income":      "#34D399",
    "expense":     "#F87171",
    "hover":       "#252838",
    "header_bg":   "#252838",
    "header_text": "#6C8EFF",
    "row_alt":     "#1E2132",
    "shadow":      "rgba(108,142,255,0.15)",
}

CATEGORIES_EXPENSE = ["餐饮", "交通", "购物", "娱乐", "医疗", "教育", "居家", "旅行", "其他"]
CATEGORIES_INCOME  = ["工资", "奖金", "副业", "投资", "礼金", "其他"]
PIE_COLORS = [
    "#4F6EF7", "#7C3AED", "#EC4899", "#F59E0B",
    "#10B981", "#06B6D4", "#EF4444", "#84CC16", "#F97316"
]


# ─────────────────────────────────────────────
#  QSS 样式生成
# ─────────────────────────────────────────────
def build_qss(t: dict) -> str:
    return f"""
/* ── Global ── */
QWidget {{
    font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {t['text']};
    background-color: {t['bg']};
}}
QMainWindow {{
    background-color: {t['bg']};
}}

/* ── Tab Widget ── */
QTabWidget::pane {{
    border: none;
    background: {t['bg']};
}}
QTabBar::tab {{
    background: {t['surface2']};
    color: {t['text2']};
    padding: 10px 28px;
    border: none;
    border-radius: 0px;
    font-size: 13px;
    font-weight: 500;
    min-width: 100px;
}}
QTabBar::tab:selected {{
    background: {t['accent']};
    color: #FFFFFF;
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: {t['hover']};
    color: {t['accent']};
}}

/* ── Frames / Cards ── */
QFrame#card {{
    background: {t['surface']};
    border: 1px solid {t['border']};
    border-radius: 14px;
}}
QFrame#divider {{
    background: {t['border']};
    max-height: 1px;
}}

/* ── Labels ── */
QLabel#title {{
    font-size: 22px;
    font-weight: 700;
    color: {t['text']};
}}
QLabel#subtitle {{
    font-size: 13px;
    color: {t['text2']};
}}
QLabel#stat_value {{
    font-size: 28px;
    font-weight: 700;
}}
QLabel#stat_income {{
    color: {t['income']};
}}
QLabel#stat_expense {{
    color: {t['expense']};
}}
QLabel#stat_balance {{
    color: {t['accent']};
}}
QLabel#field_label {{
    font-size: 12px;
    font-weight: 600;
    color: {t['text2']};
    letter-spacing: 0.5px;
}}

/* ── Inputs ── */
QLineEdit, QComboBox, QDateEdit {{
    background: {t['surface2']};
    border: 1.5px solid {t['border']};
    border-radius: 8px;
    padding: 8px 12px;
    color: {t['text']};
    font-size: 13px;
    selection-background-color: {t['accent']};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus {{
    border: 1.5px solid {t['accent']};
    background: {t['surface']};
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background: {t['surface']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    selection-background-color: {t['hover']};
    selection-color: {t['accent']};
    padding: 4px;
    outline: none;
}}
QDateEdit::drop-down {{
    border: none;
    width: 28px;
}}

/* ── Buttons ── */
QPushButton#primary {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {t['accent']}, stop:1 {t['accent2']});
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 10px 28px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {t['accent2']}, stop:1 {t['accent']});
}}
QPushButton#primary:pressed {{
    opacity: 0.85;
    padding: 11px 27px 9px 29px;
}}
QPushButton#secondary {{
    background: {t['surface2']};
    color: {t['text']};
    border: 1.5px solid {t['border']};
    border-radius: 10px;
    padding: 9px 20px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#secondary:hover {{
    background: {t['hover']};
    border-color: {t['accent']};
    color: {t['accent']};
}}
QPushButton#theme_btn {{
    background: {t['surface2']};
    border: 1.5px solid {t['border']};
    border-radius: 18px;
    padding: 6px 16px;
    font-size: 12px;
    color: {t['text2']};
    font-weight: 500;
}}
QPushButton#theme_btn:hover {{
    background: {t['hover']};
    color: {t['accent']};
    border-color: {t['accent']};
}}

/* ── Table ── */
QTableWidget {{
    background: {t['surface']};
    gridline-color: {t['border']};
    border: none;
    border-radius: 10px;
    selection-background-color: {t['hover']};
    selection-color: {t['accent']};
    alternate-background-color: {t['row_alt']};
    outline: none;
}}
QTableWidget::item {{
    padding: 8px 12px;
    border: none;
    color: {t['text']};
}}
QTableWidget::item:selected {{
    background: {t['hover']};
    color: {t['accent']};
}}
QHeaderView::section {{
    background: {t['header_bg']};
    color: {t['header_text']};
    padding: 10px 12px;
    border: none;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QHeaderView::section:first {{
    border-top-left-radius: 10px;
}}
QHeaderView::section:last {{
    border-top-right-radius: 10px;
}}

/* ── ScrollBar ── */
QScrollBar:vertical {{
    background: {t['surface2']};
    width: 6px;
    border-radius: 3px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t['border']};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t['accent']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{
    background: {t['surface2']};
    height: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {t['border']};
    border-radius: 3px;
}}

/* ── MessageBox / Dialog ── */
QMessageBox, QDialog {{
    background: {t['surface']};
}}
QDialogButtonBox QPushButton {{
    background: {t['accent']};
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 24px;
    font-weight: 600;
}}
QDialogButtonBox QPushButton:hover {{
    background: {t['accent2']};
}}

/* ── Menu ── */
QMenu {{
    background: {t['surface']};
    border: 1px solid {t['border']};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 8px 20px;
    border-radius: 6px;
    color: {t['text']};
}}
QMenu::item:selected {{
    background: {t['hover']};
    color: {t['accent']};
}}

/* ── Type selector buttons ── */
QPushButton#type_income {{
    background: {t['income']};
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 24px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton#type_expense {{
    background: {t['expense']};
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 24px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton#type_inactive {{
    background: {t['surface2']};
    color: {t['text2']};
    border: 1.5px solid {t['border']};
    border-radius: 8px;
    padding: 8px 24px;
    font-weight: 500;
    font-size: 13px;
}}
QPushButton#type_inactive:hover {{
    background: {t['hover']};
}}
"""


# ─────────────────────────────────────────────
#  饼图 Widget
# ─────────────────────────────────────────────
class PieChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = {}      # category -> amount
        self.theme = LIGHT_THEME
        self.setMinimumSize(340, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._anim_progress = 1.0

    def set_data(self, data: dict, theme: dict):
        self.data = data
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        t = self.theme

        # background
        painter.fillRect(0, 0, w, h, QColor(t["surface"]))

        if not self.data:
            painter.setPen(QColor(t["text2"]))
            painter.setFont(QFont("PingFang SC", 13))
            painter.drawText(QRect(0, 0, w, h), Qt.AlignCenter, "本月暂无支出数据")
            return

        total = sum(self.data.values())
        if total <= 0:
            return

        # layout
        legend_w = min(160, w // 3)
        pie_size  = min(h - 60, w - legend_w - 40)
        pie_size  = max(pie_size, 100)
        cx = (w - legend_w) // 2
        cy = h // 2
        r  = pie_size // 2

        rect = QRect(cx - r, cy - r, pie_size, pie_size)

        # draw shadow ring
        shadow_pen = QPen(QColor(0, 0, 0, 18), 12)
        painter.setPen(shadow_pen)
        painter.drawEllipse(rect.adjusted(4, 4, 4, 4))

        # draw slices
        angle_start = 90 * 16
        items = sorted(self.data.items(), key=lambda x: -x[1])
        for i, (cat, val) in enumerate(items):
            span = int(round(val / total * 360 * 16))
            color = QColor(PIE_COLORS[i % len(PIE_COLORS)])

            # slice fill
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(t["surface"]), 2))
            painter.drawPie(rect, angle_start, span)
            angle_start -= span

        # center donut hole
        hole_r = int(r * 0.52)
        painter.setBrush(QBrush(QColor(t["surface"])))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(cx - hole_r, cy - hole_r, hole_r * 2, hole_r * 2)

        # center text
        painter.setPen(QColor(t["text2"]))
        painter.setFont(QFont("PingFang SC", 9))
        painter.drawText(QRect(cx - hole_r, cy - 20, hole_r * 2, 18),
                         Qt.AlignCenter, "本月支出")
        painter.setPen(QColor(t["text"]))
        painter.setFont(QFont("PingFang SC", 11, QFont.Bold))
        painter.drawText(QRect(cx - hole_r, cy - 2, hole_r * 2, 22),
                         Qt.AlignCenter, f"¥{total:,.0f}")

        # legend
        lx = w - legend_w + 4
        ly = (h - len(items) * 26) // 2
        for i, (cat, val) in enumerate(items):
            color = QColor(PIE_COLORS[i % len(PIE_COLORS)])
            pct   = val / total * 100

            # color dot
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(lx, ly + i * 26 + 4, 10, 10)

            # text
            painter.setPen(QColor(t["text"]))
            painter.setFont(QFont("PingFang SC", 11))
            painter.drawText(lx + 16, ly + i * 26, legend_w - 16, 22,
                             Qt.AlignVCenter | Qt.AlignLeft,
                             f"{cat}  {pct:.1f}%")


# ─────────────────────────────────────────────
#  迷你柱状趋势图
# ─────────────────────────────────────────────
class BarTrendWidget(QWidget):
    """7-day or 30-day mini bar chart."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars = []   # list of (label, income, expense)
        self.theme = LIGHT_THEME
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, bars, theme):
        self.bars = bars
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        if not self.bars:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        t = self.theme
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 8, 8, 10, 24

        n = len(self.bars)
        max_val = max((max(inc, exp) for _, inc, exp in self.bars), default=1) or 1
        slot_w = (w - pad_l - pad_r) / n
        bar_w  = max(4, slot_w * 0.32)
        chart_h = h - pad_t - pad_b

        for i, (label, inc, exp) in enumerate(self.bars):
            x = pad_l + i * slot_w + slot_w / 2

            # income bar
            inc_h = (inc / max_val) * chart_h
            painter.setBrush(QBrush(QColor(t["income"])))
            painter.setPen(Qt.NoPen)
            rx = x - bar_w - 1
            painter.drawRoundedRect(
                int(rx), int(h - pad_b - inc_h),
                int(bar_w), int(max(inc_h, 2)), 2, 2
            )

            # expense bar
            exp_h = (exp / max_val) * chart_h
            painter.setBrush(QBrush(QColor(t["expense"])))
            rx2 = x + 1
            painter.drawRoundedRect(
                int(rx2), int(h - pad_b - exp_h),
                int(bar_w), int(max(exp_h, 2)), 2, 2
            )

            # label
            painter.setPen(QColor(t["text2"]))
            painter.setFont(QFont("PingFang SC", 8))
            painter.drawText(int(x - slot_w / 2), h - pad_b + 4,
                             int(slot_w), pad_b - 2,
                             Qt.AlignCenter, label)


# ─────────────────────────────────────────────
#  编辑对话框
# ─────────────────────────────────────────────
class EditDialog(QDialog):
    def __init__(self, row_data, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.row_data = row_data
        self.setWindowTitle("编辑记录")
        self.setMinimumWidth(380)
        self.setModal(True)
        self._build_ui()
        self._populate(row_data)

    def _build_ui(self):
        t = self.theme
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        def field(label_text, widget):
            lbl = QLabel(label_text)
            lbl.setObjectName("field_label")
            layout.addWidget(lbl)
            layout.addWidget(widget)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        field("日期", self.date_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["支出", "收入"])
        self.type_combo.currentTextChanged.connect(self._update_categories)
        field("类型", self.type_combo)

        self.cat_combo = QComboBox()
        field("分类", self.cat_combo)

        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("0.00")
        field("金额 (¥)", self.amount_edit)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("可选备注...")
        field("备注", self.note_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _update_categories(self, rec_type):
        self.cat_combo.clear()
        cats = CATEGORIES_INCOME if rec_type == "收入" else CATEGORIES_EXPENSE
        self.cat_combo.addItems(cats)

    def _populate(self, row):
        self.date_edit.setDate(QDate.fromString(row["date"], "yyyy-MM-dd"))
        idx = self.type_combo.findText(row["type"])
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self._update_categories(row["type"])
        cat_idx = self.cat_combo.findText(row["category"])
        if cat_idx >= 0:
            self.cat_combo.setCurrentIndex(cat_idx)
        self.amount_edit.setText(str(row["amount"]))
        self.note_edit.setText(row["note"] or "")

    def get_values(self):
        return (
            self.date_edit.date().toString("yyyy-MM-dd"),
            self.type_combo.currentText(),
            self.cat_combo.currentText(),
            float(self.amount_edit.text() or 0),
            self.note_edit.text(),
        )


# ─────────────────────────────────────────────
#  收支记录 Tab
# ─────────────────────────────────────────────
class RecordTab(QWidget):
    record_saved = pyqtSignal()

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._current_type = "支出"
        self._build_ui()

    def _build_ui(self):
        t = self.theme
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ── header ──
        hdr = QHBoxLayout()
        title = QLabel("记一笔")
        title.setObjectName("title")
        hdr.addWidget(title)
        hdr.addStretch()
        root.addLayout(hdr)

        # ── type toggle ──
        type_row = QHBoxLayout()
        type_row.setSpacing(10)
        self.btn_expense = QPushButton("支出")
        self.btn_income  = QPushButton("收入")
        self.btn_expense.setFixedHeight(36)
        self.btn_income.setFixedHeight(36)
        self.btn_expense.clicked.connect(lambda: self._set_type("支出"))
        self.btn_income.clicked.connect(lambda: self._set_type("收入"))
        type_row.addWidget(self.btn_expense)
        type_row.addWidget(self.btn_income)
        type_row.addStretch()
        root.addLayout(type_row)
        # NOTE: _set_type is called AFTER cat_combo is created below

        # ── form card ──
        card = QFrame()
        card.setObjectName("card")
        form_layout = QGridLayout(card)
        form_layout.setContentsMargins(24, 20, 24, 20)
        form_layout.setHorizontalSpacing(20)
        form_layout.setVerticalSpacing(12)

        def lbl(text):
            l = QLabel(text)
            l.setObjectName("field_label")
            return l

        # Date
        form_layout.addWidget(lbl("日期"), 0, 0)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setFixedHeight(38)
        form_layout.addWidget(self.date_edit, 1, 0)

        # Category
        form_layout.addWidget(lbl("分类"), 0, 1)
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(CATEGORIES_EXPENSE)
        self.cat_combo.setFixedHeight(38)
        form_layout.addWidget(self.cat_combo, 1, 1)

        # Amount
        form_layout.addWidget(lbl("金额 (¥)"), 2, 0)
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("0.00")
        self.amount_edit.setFixedHeight(38)
        form_layout.addWidget(self.amount_edit, 3, 0)

        # Note
        form_layout.addWidget(lbl("备注"), 2, 1)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("可选备注...")
        self.note_edit.setFixedHeight(38)
        form_layout.addWidget(self.note_edit, 3, 1)

        root.addWidget(card)

        # Now safe to call _set_type — cat_combo exists
        self._set_type("支出")

        # ── save button ──
        save_btn = QPushButton("  保存记录  ✓")
        save_btn.setObjectName("primary")
        save_btn.setFixedHeight(44)
        save_btn.clicked.connect(self._save)
        root.addWidget(save_btn)

        root.addStretch()

    def _set_type(self, rec_type):
        self._current_type = rec_type
        cats = CATEGORIES_INCOME if rec_type == "收入" else CATEGORIES_EXPENSE
        if not hasattr(self, "cat_combo"):
            return
        self.cat_combo.clear()
        self.cat_combo.addItems(cats)
        if rec_type == "支出":
            self.btn_expense.setObjectName("type_expense")
            self.btn_income.setObjectName("type_inactive")
        else:
            self.btn_expense.setObjectName("type_inactive")
            self.btn_income.setObjectName("type_income")
        self.btn_expense.setStyle(self.btn_expense.style())
        self.btn_income.setStyle(self.btn_income.style())

    def _save(self):
        amount_text = self.amount_edit.text().strip()
        if not amount_text:
            QMessageBox.warning(self, "提示", "请输入金额")
            return
        try:
            amount = float(amount_text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "提示", "请输入有效的正数金额")
            return

        insert_record(
            self.date_edit.date().toString("yyyy-MM-dd"),
            self._current_type,
            self.cat_combo.currentText(),
            amount,
            self.note_edit.text().strip(),
        )
        self.amount_edit.clear()
        self.note_edit.clear()
        self.record_saved.emit()
        QMessageBox.information(self, "成功", "记录已保存！")

    def update_theme(self, theme):
        self.theme = theme


# ─────────────────────────────────────────────
#  账单列表 Tab
# ─────────────────────────────────────────────
class ListTab(QWidget):
    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # header
        hdr = QHBoxLayout()
        title = QLabel("账单明细")
        title.setObjectName("title")
        hdr.addWidget(title)
        hdr.addStretch()

        # month filter
        hdr.addWidget(QLabel("筛选月份:"))
        self.year_combo = QComboBox()
        cy = datetime.now().year
        for y in range(cy - 3, cy + 2):
            self.year_combo.addItem(str(y))
        self.year_combo.setCurrentText(str(cy))
        self.year_combo.setFixedWidth(80)
        hdr.addWidget(self.year_combo)

        self.month_combo = QComboBox()
        self.month_combo.addItem("全部", 0)
        for m in range(1, 13):
            self.month_combo.addItem(f"{m}月", m)
        self.month_combo.setCurrentIndex(datetime.now().month)
        self.month_combo.setFixedWidth(72)
        hdr.addWidget(self.month_combo)

        btn_filter = QPushButton("查询")
        btn_filter.setObjectName("secondary")
        btn_filter.setFixedWidth(64)
        btn_filter.clicked.connect(self.load_data)
        hdr.addWidget(btn_filter)

        root.addLayout(hdr)

        # table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "日期", "类型", "分类", "金额", "备注"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setColumnHidden(0, True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(self._edit_row)
        root.addWidget(self.table)

        # footer summary
        self.footer_lbl = QLabel("")
        self.footer_lbl.setObjectName("subtitle")
        root.addWidget(self.footer_lbl)

    def load_data(self):
        year  = int(self.year_combo.currentText())
        month = self.month_combo.currentData()
        if month == 0:
            rows = fetch_records()
        else:
            rows = fetch_records(year, month)

        self.table.setRowCount(len(rows))
        t = self.theme
        income_total = expense_total = 0.0

        for i, row in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(i, 1, QTableWidgetItem(row["date"]))

            type_item = QTableWidgetItem(row["type"])
            type_item.setTextAlignment(Qt.AlignCenter)
            if row["type"] == "收入":
                type_item.setForeground(QColor(t["income"]))
                income_total += row["amount"]
            else:
                type_item.setForeground(QColor(t["expense"]))
                expense_total += row["amount"]
            self.table.setItem(i, 2, type_item)

            self.table.setItem(i, 3, QTableWidgetItem(row["category"]))

            amount_item = QTableWidgetItem(f"¥ {row['amount']:,.2f}")
            amount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 4, amount_item)

            self.table.setItem(i, 5, QTableWidgetItem(row["note"] or ""))
            self.table.setRowHeight(i, 40)

        balance = income_total - expense_total
        sign = "+" if balance >= 0 else ""
        self.footer_lbl.setText(
            f"共 {len(rows)} 条  |  收入 ¥{income_total:,.2f}  |  "
            f"支出 ¥{expense_total:,.2f}  |  结余 {sign}¥{balance:,.2f}"
        )

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        rid = int(self.table.item(row, 0).text())
        menu = QMenu(self)
        edit_act   = menu.addAction("✏️  编辑")
        delete_act = menu.addAction("🗑  删除")
        action = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if action == edit_act:
            self._edit_by_id(rid)
        elif action == delete_act:
            self._delete_by_id(rid)

    def _edit_row(self, index):
        row = index.row()
        rid = int(self.table.item(row, 0).text())
        self._edit_by_id(rid)

    def _edit_by_id(self, rid):
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
        if not row:
            return
        dlg = EditDialog(row, self.theme, self)
        dlg.setStyleSheet(QApplication.instance().styleSheet())
        if dlg.exec_() == QDialog.Accepted:
            date_str, rec_type, cat, amount, note = dlg.get_values()
            update_record(rid, date_str, rec_type, cat, amount, note)
            self.load_data()

    def _delete_by_id(self, rid):
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除这条记录吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            delete_record(rid)
            self.load_data()

    def update_theme(self, theme):
        self.theme = theme
        self.load_data()


# ─────────────────────────────────────────────
#  数据看板 Tab
# ─────────────────────────────────────────────
class DashboardTab(QWidget):
    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # header row
        hdr = QHBoxLayout()
        title = QLabel("数据看板")
        title.setObjectName("title")
        hdr.addWidget(title)
        hdr.addStretch()

        self.month_label = QLabel()
        self.month_label.setObjectName("subtitle")
        hdr.addWidget(self.month_label)
        root.addLayout(hdr)

        # stat cards row
        stat_row = QHBoxLayout()
        stat_row.setSpacing(14)

        self.card_income  = self._stat_card("本月收入", "¥ 0", "stat_income")
        self.card_expense = self._stat_card("本月支出", "¥ 0", "stat_expense")
        self.card_balance = self._stat_card("本月结余", "¥ 0", "stat_balance")
        stat_row.addWidget(self.card_income)
        stat_row.addWidget(self.card_expense)
        stat_row.addWidget(self.card_balance)
        root.addLayout(stat_row)

        # charts row
        charts_row = QHBoxLayout()
        charts_row.setSpacing(16)

        # pie chart card
        pie_card = QFrame()
        pie_card.setObjectName("card")
        pie_layout = QVBoxLayout(pie_card)
        pie_layout.setContentsMargins(16, 14, 16, 14)
        pie_lbl = QLabel("本月支出分类")
        pie_lbl.setObjectName("subtitle")
        pie_layout.addWidget(pie_lbl)
        self.pie = PieChartWidget()
        pie_layout.addWidget(self.pie)
        charts_row.addWidget(pie_card, 3)

        # bar trend card
        bar_card = QFrame()
        bar_card.setObjectName("card")
        bar_layout = QVBoxLayout(bar_card)
        bar_layout.setContentsMargins(16, 14, 16, 14)
        bar_lbl = QLabel("近6个月收支对比")
        bar_lbl.setObjectName("subtitle")
        bar_layout.addWidget(bar_lbl)
        self.bar = BarTrendWidget()
        bar_layout.addWidget(self.bar)

        # legend
        legend = QHBoxLayout()
        legend.setSpacing(16)
        inc_dot = QLabel("● 收入")
        inc_dot.setStyleSheet(f"color: {self.theme['income']}; font-size: 11px;")
        exp_dot = QLabel("● 支出")
        exp_dot.setStyleSheet(f"color: {self.theme['expense']}; font-size: 11px;")
        legend.addStretch()
        legend.addWidget(inc_dot)
        legend.addWidget(exp_dot)
        legend.addStretch()
        bar_layout.addLayout(legend)
        charts_row.addWidget(bar_card, 2)

        root.addLayout(charts_row)
        root.addStretch()

        # save refs for theme update
        self._inc_dot = inc_dot
        self._exp_dot = exp_dot

    def _stat_card(self, label, value, value_obj):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)

        lbl = QLabel(label)
        lbl.setObjectName("subtitle")
        layout.addWidget(lbl)

        val = QLabel(value)
        val.setObjectName("stat_value")
        val.setProperty("color_class", value_obj)
        if value_obj == "stat_income":
            val.setObjectName("stat_income")
        elif value_obj == "stat_expense":
            val.setObjectName("stat_expense")
        else:
            val.setObjectName("stat_balance")
        layout.addWidget(val)

        card._value_label = val
        card._title_label = lbl
        return card

    def refresh(self):
        now = datetime.now()
        y, m = now.year, now.month
        self.month_label.setText(f"{y}年{m}月")

        summary = fetch_summary(y, m)
        income  = summary["收入"]
        expense = summary["支出"]
        balance = income - expense

        self.card_income._value_label.setText(f"¥ {income:,.2f}")
        self.card_expense._value_label.setText(f"¥ {expense:,.2f}")
        bal_sign = "+" if balance >= 0 else ""
        self.card_balance._value_label.setText(f"{bal_sign}¥ {balance:,.2f}")

        # pie
        pie_data = fetch_monthly_stats(y, m)
        self.pie.set_data(pie_data, self.theme)

        # bar trend (6 months)
        bars = []
        for delta in range(5, -1, -1):
            mm = m - delta
            yy = y
            while mm <= 0:
                mm += 12
                yy -= 1
            s = fetch_summary(yy, mm)
            bars.append((f"{mm}月", s["收入"], s["支出"]))
        self.bar.set_data(bars, self.theme)

    def update_theme(self, theme):
        self.theme = theme
        self._inc_dot.setStyleSheet(f"color: {theme['income']}; font-size: 11px;")
        self._exp_dot.setStyleSheet(f"color: {theme['expense']}; font-size: 11px;")
        self.refresh()


# ─────────────────────────────────────────────
#  主窗口
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._dark = False
        self._theme = LIGHT_THEME
        init_db()
        self._build_ui()
        self._apply_theme()
        self.setWindowTitle("记账本  💰")
        self.resize(900, 640)
        self.setMinimumSize(720, 520)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── top bar ──
        top_bar = QFrame()
        top_bar.setFixedHeight(52)
        top_bar.setObjectName("card")
        top_bar.setStyleSheet("border-radius:0; border-left:none; border-right:none; border-top:none;")
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(20, 0, 20, 0)

        logo = QLabel("💰 记账本")
        logo.setStyleSheet("font-size: 16px; font-weight: 700; letter-spacing: 1px;")
        tb_layout.addWidget(logo)
        tb_layout.addStretch()

        today_lbl = QLabel(datetime.now().strftime("%Y年%m月%d日  %A"))
        today_lbl.setObjectName("subtitle")
        tb_layout.addWidget(today_lbl)

        self.theme_btn = QPushButton("🌙  深色")
        self.theme_btn.setObjectName("theme_btn")
        self.theme_btn.setFixedHeight(32)
        self.theme_btn.clicked.connect(self._toggle_theme)
        tb_layout.addWidget(self.theme_btn)

        root.addWidget(top_bar)

        # ── tabs ──
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        t = self._theme
        self.record_tab    = RecordTab(t)
        self.list_tab      = ListTab(t)
        self.dashboard_tab = DashboardTab(t)

        self.tabs.addTab(self.dashboard_tab, "  📊 看板  ")
        self.tabs.addTab(self.record_tab,    "  ✏️ 记账  ")
        self.tabs.addTab(self.list_tab,      "  📋 明细  ")

        self.record_tab.record_saved.connect(self.list_tab.load_data)
        self.record_tab.record_saved.connect(self.dashboard_tab.refresh)

        root.addWidget(self.tabs)

    def _apply_theme(self):
        t = self._theme
        QApplication.instance().setStyleSheet(build_qss(t))

    def _toggle_theme(self):
        self._dark = not self._dark
        self._theme = DARK_THEME if self._dark else LIGHT_THEME
        self.theme_btn.setText("☀️  浅色" if self._dark else "🌙  深色")
        self._apply_theme()
        self.record_tab.update_theme(self._theme)
        self.list_tab.update_theme(self._theme)
        self.dashboard_tab.update_theme(self._theme)


# ─────────────────────────────────────────────
#  入口
# ─────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("记账本")
    # High DPI
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
