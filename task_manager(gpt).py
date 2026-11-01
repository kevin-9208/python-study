# -*- coding: utf-8 -*-
"""轻量级桌面任务管理器（系统进程监控版）

运行环境：Python 3.9+
安装依赖：python -m pip install PyQt6 psutil
启动方式：python task_manager.py

功能：CPU / 内存 / 磁盘 / 网络概览、进程搜索与排序、手动刷新、结束进程、
进程详细信息，以及 CPU 和内存的近期使用率曲线。监控数据只在本机读取。
"""

import os
import sys
import time
import socket
import platform
from datetime import datetime
from collections import deque

try:
    import psutil
except ImportError:
    print("缺少依赖 psutil，请先运行：python -m pip install psutil")
    raise SystemExit(1)

try:
    from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
    from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QAction
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
        QLineEdit, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
        QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
        QMessageBox, QComboBox, QProgressBar, QDialog, QFormLayout,
        QTextEdit, QSizePolicy, QMenu, QSpacerItem
    )
except ImportError:
    print("缺少依赖 PyQt6，请先运行：python -m pip install PyQt6 psutil")
    raise SystemExit(1)

APP_NAME = "轻量任务管理器"
ACCENT = "#5B8DEF"


def format_bytes(num):
    """将字节数格式化为易读单位。"""
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def format_rate(num):
    return f"{format_bytes(max(0, num))}/s"


class NumericItem(QTableWidgetItem):
    """让表格按真实数值排序，而不是按显示文本排序。"""
    def __lt__(self, other):
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        if left is not None and right is not None:
            try:
                return float(left) < float(right)
            except (TypeError, ValueError):
                pass
        return self.text().casefold() < other.text().casefold()


class MetricCard(QFrame):
    def __init__(self, title, icon, show_progress=True, parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setMinimumHeight(122)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(17, 13, 17, 13)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.title_label = QLabel(f"{icon}  {title}")
        self.title_label.setObjectName("metricTitle")
        top.addWidget(self.title_label)
        top.addStretch(1)
        layout.addLayout(top)

        self.value_label = QLabel("--")
        self.value_label.setObjectName("metricValue")
        layout.addWidget(self.value_label)

        self.progress = QProgressBar()
        self.progress.setObjectName("metricProgress")
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setVisible(show_progress)
        layout.addWidget(self.progress)

        self.detail_label = QLabel("正在读取系统信息…")
        self.detail_label.setObjectName("metricDetail")
        layout.addWidget(self.detail_label)

    def update_metric(self, value, percent=None, detail=""):
        self.value_label.setText(value)
        if percent is not None:
            self.progress.setValue(max(0, min(100, int(percent))))
        self.detail_label.setText(detail)


class HistoryChart(QWidget):
    """不依赖第三方绘图库的轻量折线图。"""
    def __init__(self, title, color, parent=None):
        super().__init__(parent)
        self.title = title
        self.line_color = QColor(color)
        self.values = deque([0.0] * 60, maxlen=60)
        self.current_value = 0.0
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def add_value(self, value):
        self.current_value = max(0.0, min(100.0, float(value)))
        self.values.append(self.current_value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#263347"), 1))
        painter.setBrush(QColor("#111B2B"))
        painter.drawRoundedRect(QRectF(rect), 12, 12)

        title_font = QFont("Microsoft YaHei", 10)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor("#DCE6F4"))
        painter.drawText(18, 28, self.title)

        value_font = QFont("Segoe UI", 15)
        value_font.setWeight(QFont.Weight.Bold)
        painter.setFont(value_font)
        painter.setPen(self.line_color)
        painter.drawText(self.width() - 105, 29, f"{self.current_value:.1f}%")

        chart = QRectF(20, 48, max(20, self.width() - 40), max(30, self.height() - 76))
        grid_pen = QPen(QColor("#253247"), 1, Qt.PenStyle.DashLine)
        painter.setPen(grid_pen)
        for i in range(5):
            y = chart.top() + chart.height() * i / 4
            painter.drawLine(QPointF(chart.left(), y), QPointF(chart.right(), y))
        for i in range(6):
            x = chart.left() + chart.width() * i / 5
            painter.drawLine(QPointF(x, chart.top()), QPointF(x, chart.bottom()))

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#77869C"))
        for i, label in enumerate(("100%", "75%", "50%", "25%", "0%")):
            y = chart.top() + chart.height() * i / 4
            painter.drawText(QRectF(chart.left() + 3, y - 11, 35, 14),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

        points = []
        vals = list(self.values)
        usable_left = chart.left() + 36
        usable_width = chart.width() - 38
        for index, value in enumerate(vals):
            x = usable_left + usable_width * index / max(1, len(vals) - 1)
            y = chart.bottom() - chart.height() * value / 100.0
            points.append(QPointF(x, y))
        if len(points) > 1:
            # 半透明面积
            fill_points = [QPointF(points[0].x(), chart.bottom())] + points + [QPointF(points[-1].x(), chart.bottom())]
            from PyQt6.QtGui import QPolygonF
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            fill_color = QColor(self.line_color)
            fill_color.setAlpha(28)
            painter.setBrush(fill_color)
            painter.drawPolygon(QPolygonF(fill_points))
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.setPen(QPen(self.line_color, 2.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            from PyQt6.QtGui import QPolygonF
            painter.drawPolyline(QPolygonF(points))
        painter.end()


class ProcessDetailsDialog(QDialog):
    def __init__(self, process, parent=None):
        super().__init__(parent)
        self.setWindowTitle("进程详细信息")
        self.setMinimumWidth(560)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        layout = QVBoxLayout(self)
        title = QLabel("进程详细信息")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        try:
            with process.oneshot():
                data = [
                    ("进程名称", process.name()),
                    ("进程 PID", str(process.pid)),
                    ("父进程 PID", str(process.ppid())),
                    ("运行状态", process.status()),
                    ("用户名", process.username() or "—"),
                    ("线程数", str(process.num_threads())),
                    ("启动时间", datetime.fromtimestamp(process.create_time()).strftime("%Y-%m-%d %H:%M:%S")),
                    ("可执行文件", process.exe() or "无权限读取或路径不可用"),
                    ("命令行", " ".join(process.cmdline()) or "无权限读取或命令行为空"),
                ]
        except (psutil.Error, OSError) as exc:
            data = [("读取提示", f"部分信息无法读取：{exc}")]
        for key, value in data:
            key_label = QLabel(key)
            key_label.setObjectName("detailKey")
            value_label = QLabel(value)
            value_label.setObjectName("detailValue")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(key_label, value_label)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)


class TaskManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        self.setMinimumSize(1050, 680)
        self._last_net = psutil.net_io_counters()
        self._last_net_time = time.monotonic()
        self._last_disk = self._safe_disk_io()
        self._history_cpu = deque([0.0] * 60, maxlen=60)
        self._history_mem = deque([0.0] * 60, maxlen=60)
        self._current_processes = []
        self._paused = False
        self._last_update_text = "尚未更新"

        self._build_ui()
        self._apply_styles()
        self._populate_system_info()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_all)
        self.timer.start(2000)
        # 提前读取一次，避免应用启动后长时间空白
        self.refresh_all()

    def _safe_disk_io(self):
        try:
            return psutil.disk_io_counters()
        except (OSError, RuntimeError):
            return None

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧导航栏
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(17, 22, 17, 18)
        side_layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_icon = QLabel("◈")
        brand_icon.setObjectName("brandIcon")
        brand_icon.setFixedWidth(32)
        brand_name = QLabel("轻量任务管理器")
        brand_name.setObjectName("brandName")
        brand_row.addWidget(brand_icon)
        brand_row.addWidget(brand_name)
        brand_row.addStretch(1)
        side_layout.addLayout(brand_row)

        side_subtitle = QLabel("SYSTEM MONITOR")
        side_subtitle.setObjectName("sideSubtitle")
        side_subtitle.setContentsMargins(6, 4, 0, 18)
        side_layout.addWidget(side_subtitle)

        self.nav_buttons = []
        nav_specs = [("▦", "进程", 0), ("⌁", "性能", 1), ("ⓘ", "系统信息", 2)]
        for icon, label, index in nav_specs:
            button = QPushButton(f"  {icon}    {label}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            self.nav_buttons.append(button)
            side_layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)

        side_layout.addStretch(1)
        system_card = QFrame()
        system_card.setObjectName("sideInfoCard")
        system_layout = QVBoxLayout(system_card)
        system_layout.setContentsMargins(12, 13, 12, 13)
        sys_icon = QLabel("●  实时监控")
        sys_icon.setObjectName("liveLabel")
        self.side_cpu_label = QLabel("CPU  --%")
        self.side_mem_label = QLabel("内存 --%")
        self.side_cpu_label.setObjectName("sideStat")
        self.side_mem_label.setObjectName("sideStat")
        system_layout.addWidget(sys_icon)
        system_layout.addSpacing(7)
        system_layout.addWidget(self.side_cpu_label)
        system_layout.addWidget(self.side_mem_label)
        side_layout.addWidget(system_card)
        version_label = QLabel("LOCAL MONITOR  ·  v1.0")
        version_label.setObjectName("versionLabel")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(version_label)
        root.addWidget(sidebar)

        # 右侧工作区
        workspace = QWidget()
        work_layout = QVBoxLayout(workspace)
        work_layout.setContentsMargins(25, 20, 25, 14)
        work_layout.setSpacing(16)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        self.page_title = QLabel("进程")
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("查看正在运行的应用和后台进程")
        self.page_subtitle.setObjectName("pageSubtitle")
        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)
        header.addLayout(title_col)
        header.addStretch(1)
        self.pause_button = QPushButton("Ⅱ  暂停刷新")
        self.pause_button.setObjectName("secondaryButton")
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.clicked.connect(self.toggle_pause)
        header.addWidget(self.pause_button)
        self.refresh_button = QPushButton("↻  立即刷新")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_all)
        header.addWidget(self.refresh_button)
        work_layout.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(13)
        self.cpu_card = MetricCard("CPU 使用率", "◉")
        self.mem_card = MetricCard("内存使用率", "▤")
        self.disk_card = MetricCard("系统磁盘", "▱")
        self.net_card = MetricCard("网络吞吐", "⇅", show_progress=False)
        for card in (self.cpu_card, self.mem_card, self.disk_card, self.net_card):
            cards.addWidget(card, 1)
        work_layout.addLayout(cards)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_process_page())
        self.stack.addWidget(self._build_performance_page())
        self.stack.addWidget(self._build_system_page())
        work_layout.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("●  正在初始化系统信息")
        self.status_label.setObjectName("footerStatus")
        self.updated_label = QLabel("最后更新：--")
        self.updated_label.setObjectName("footerStatus")
        footer.addWidget(self.status_label)
        footer.addStretch(1)
        footer.addWidget(self.updated_label)
        work_layout.addLayout(footer)

        root.addWidget(workspace, 1)

    def _build_process_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("⌕   搜索进程名称、PID 或用户名…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.render_process_table)
        toolbar.addWidget(self.search_input, 1)

        self.process_count_label = QLabel("正在读取进程…")
        self.process_count_label.setObjectName("mutedLabel")
        toolbar.addWidget(self.process_count_label)

        self.end_button = QPushButton("■  结束进程")
        self.end_button.setObjectName("dangerButton")
        self.end_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.end_button.clicked.connect(self.end_selected_process)
        toolbar.addWidget(self.end_button)
        layout.addLayout(toolbar)

        self.process_table = QTableWidget(0, 6)
        self.process_table.setObjectName("processTable")
        self.process_table.setHorizontalHeaderLabels(["进程名称", "PID", "CPU", "内存", "状态", "用户名"])
        self.process_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.process_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.process_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.process_table.setShowGrid(False)
        self.process_table.setAlternatingRowColors(True)
        self.process_table.verticalHeader().setVisible(False)
        self.process_table.verticalHeader().setDefaultSectionSize(43)
        self.process_table.setSortingEnabled(True)
        self.process_table.setWordWrap(False)
        self.process_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.process_table.customContextMenuRequested.connect(self.show_process_context_menu)
        self.process_table.cellDoubleClicked.connect(self.show_selected_process_details)
        header = self.process_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        header.setSortIndicator(2, Qt.SortOrder.DescendingOrder)
        layout.addWidget(self.process_table, 1)

        hint = QLabel("提示：双击进程可查看详细信息；结束系统关键进程可能影响系统稳定性。")
        hint.setObjectName("hintLabel")
        layout.addWidget(hint)
        return page

    def _build_performance_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        intro = QLabel("性能趋势 · 最近约 2 分钟")
        intro.setObjectName("sectionTitle")
        layout.addWidget(intro)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.cpu_chart = HistoryChart("CPU 使用率", "#62A0FF")
        self.mem_chart = HistoryChart("内存使用率", "#5ED6B3")
        grid.addWidget(self._chart_card(self.cpu_chart), 0, 0)
        grid.addWidget(self._chart_card(self.mem_chart), 0, 1)
        layout.addLayout(grid, 1)

        note = QLabel("曲线由本程序定时采样绘制，仅保留当前运行期间的最近 60 个采样点。")
        note.setObjectName("hintLabel")
        layout.addWidget(note)
        return page

    def _chart_card(self, chart):
        card = QFrame()
        card.setObjectName("chartCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(chart)
        return card

    def _build_system_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        heading = QLabel("设备与运行环境")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self.system_grid = QGridLayout()
        self.system_grid.setSpacing(13)
        self.system_values = {}
        items = [
            ("操作系统", "os"), ("计算机名称", "host"),
            ("处理器", "cpu"), ("逻辑处理器", "logical"),
            ("物理处理器", "physical"), ("总内存", "memory"),
            ("系统启动时间", "boot"), ("Python 版本", "python"),
            ("系统架构", "arch"), ("磁盘读写累计", "disk_io"),
        ]
        for index, (label, key) in enumerate(items):
            card = QFrame()
            card.setObjectName("infoCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 15, 16, 15)
            title = QLabel(label)
            title.setObjectName("infoTitle")
            value = QLabel("读取中…")
            value.setObjectName("infoValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card_layout.addWidget(title)
            card_layout.addWidget(value)
            self.system_values[key] = value
            self.system_grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(self.system_grid)
        layout.addStretch(1)
        disclaimer = QLabel("本工具仅显示当前账户有权限读取的系统数据；不同操作系统显示的进程信息可能略有差异。")
        disclaimer.setObjectName("hintLabel")
        layout.addWidget(disclaimer)
        return page

    def _apply_styles(self):
        self.setStyleSheet(r"""
            QMainWindow, QWidget { background: #0B1220; color: #E5ECF7; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 13px; }
            #sidebar { background: #0E1728; border-right: 1px solid #1D2A3D; }
            #brandIcon { color: #6DA3FF; font-size: 28px; font-weight: 700; }
            #brandName { color: #F4F7FC; font-size: 15px; font-weight: 700; }
            #sideSubtitle { color: #61718A; font-size: 10px; letter-spacing: 2px; }
            #navButton { text-align: left; color: #9BAAC0; border: 0; border-radius: 8px; padding: 12px 9px; background: transparent; font-size: 13px; }
            #navButton:hover { color: #EAF1FB; background: #18253A; }
            #navButton:checked { color: #F5F8FF; background: #21375A; border-left: 3px solid #6DA3FF; padding-left: 6px; font-weight: 600; }
            #sideInfoCard { border: 1px solid #26364D; background: #121F32; border-radius: 10px; }
            #liveLabel { color: #72D6B4; font-size: 12px; font-weight: 600; }
            #sideStat { color: #AAB9CE; font-size: 12px; }
            #versionLabel { color: #4E5E74; font-size: 9px; padding-top: 12px; }
            #pageTitle { color: #F3F7FD; font-size: 25px; font-weight: 700; }
            #pageSubtitle { color: #7F8EA5; font-size: 12px; }
            #metricCard, #chartCard, #infoCard { background: #111B2B; border: 1px solid #263449; border-radius: 12px; }
            #metricTitle { color: #94A4BB; font-size: 12px; }
            #metricValue { color: #F0F5FD; font-family: "Segoe UI", sans-serif; font-size: 24px; font-weight: 700; }
            #metricDetail { color: #73849D; font-size: 11px; }
            #metricProgress { background: #263349; border: none; border-radius: 3px; }
            #metricProgress::chunk { background: #5B8DEF; border-radius: 3px; }
            #primaryButton { color: white; background: #477FE0; border: 1px solid #5A91EE; border-radius: 8px; padding: 10px 14px; font-weight: 600; }
            #primaryButton:hover { background: #568FEB; }
            #primaryButton:pressed { background: #346BCC; }
            #secondaryButton { color: #C5D2E5; background: #172438; border: 1px solid #2B3C55; border-radius: 8px; padding: 9px 13px; }
            #secondaryButton:hover { background: #20324A; }
            #dangerButton { color: #FFB9BC; background: #3A202A; border: 1px solid #67313C; border-radius: 8px; padding: 9px 13px; font-weight: 600; }
            #dangerButton:hover { background: #512832; }
            #searchInput { color: #E4ECF8; background: #111B2B; border: 1px solid #2A3A51; border-radius: 8px; padding: 11px 13px; selection-background-color: #477FE0; }
            #searchInput:focus { border: 1px solid #5B8DEF; }
            #processTable { background: #101A2A; alternate-background-color: #121E30; color: #DCE6F4; border: 1px solid #263449; border-radius: 9px; gridline-color: transparent; outline: none; selection-background-color: #203C66; selection-color: #FFFFFF; }
            #processTable::item { border: none; padding-left: 8px; padding-right: 8px; }
            #processTable::item:selected { background: #203C66; }
            QHeaderView::section { background: #162237; color: #8293AC; border: none; border-bottom: 1px solid #2A3A51; padding: 12px 9px; font-weight: 600; }
            #mutedLabel, #hintLabel { color: #6F8098; font-size: 11px; }
            #sectionTitle { color: #E6EDF8; font-size: 16px; font-weight: 600; padding: 3px 0; }
            #infoTitle { color: #8192AB; font-size: 12px; }
            #infoValue { color: #E4ECF8; font-size: 15px; font-weight: 600; padding-top: 7px; }
            #footerStatus { color: #687991; font-size: 10px; }
            #dialogTitle { color: #F0F5FD; font-size: 19px; font-weight: 700; padding-bottom: 8px; }
            #detailKey { color: #7E90A9; min-width: 90px; }
            #detailValue { color: #DEE7F3; }
            QMenu { background: #152237; color: #E4ECF8; border: 1px solid #31435D; padding: 4px; }
            QMenu::item { padding: 7px 24px 7px 12px; border-radius: 4px; }
            QMenu::item:selected { background: #29446A; }
            QMessageBox { background: #111B2B; }
            QMessageBox QLabel { color: #E5ECF7; }
            QScrollBar:vertical { background: #101A2A; width: 10px; margin: 0; }
            QScrollBar::handle:vertical { background: #33455F; min-height: 24px; border-radius: 4px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    def switch_page(self, index):
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        titles = [
            ("进程", "查看正在运行的应用和后台进程"),
            ("性能", "实时观察 CPU 与内存使用趋势"),
            ("系统信息", "查看设备、操作系统与运行环境信息"),
        ]
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])

    def toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.timer.stop()
            self.pause_button.setText("▶  恢复刷新")
            self.status_label.setText("Ⅱ  已暂停自动刷新")
        else:
            self.timer.start(2000)
            self.pause_button.setText("Ⅱ  暂停刷新")
            self.refresh_all()

    def refresh_all(self):
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            disk_root = os.path.abspath(os.sep)
            try:
                disk = psutil.disk_usage(disk_root)
            except (OSError, PermissionError):
                disk = psutil.disk_usage(os.path.expanduser("~"))

            now = time.monotonic()
            net = psutil.net_io_counters()
            elapsed = max(0.001, now - self._last_net_time)
            down_rate = (net.bytes_recv - self._last_net.bytes_recv) / elapsed
            up_rate = (net.bytes_sent - self._last_net.bytes_sent) / elapsed
            self._last_net = net
            self._last_net_time = now

            self.cpu_card.update_metric(f"{cpu:.1f}%", cpu,
                                        f"逻辑处理器：{psutil.cpu_count(logical=True) or '未知'} 核")
            self.mem_card.update_metric(f"{mem.percent:.1f}%", mem.percent,
                                        f"已用 {format_bytes(mem.used)} / 共 {format_bytes(mem.total)}")
            self.disk_card.update_metric(f"{disk.percent:.1f}%", disk.percent,
                                         f"已用 {format_bytes(disk.used)} / 共 {format_bytes(disk.total)}")
            self.net_card.update_metric(f"↓ {format_rate(down_rate)}",
                                        None,
                                        f"↑ {format_rate(up_rate)}  ·  收发累计 {format_bytes(net.bytes_recv + net.bytes_sent)}")
            self.side_cpu_label.setText(f"CPU  {cpu:.1f}%")
            self.side_mem_label.setText(f"内存 {mem.percent:.1f}%")
            self._history_cpu.append(cpu)
            self._history_mem.append(mem.percent)
            self.cpu_chart.add_value(cpu)
            self.mem_chart.add_value(mem.percent)
            self._update_disk_io_label()
            self._read_processes()

            self._last_update_text = datetime.now().strftime("%H:%M:%S")
            self.updated_label.setText(f"最后更新：{self._last_update_text}")
            self.status_label.setText("●  实时监控中" if not self._paused else "Ⅱ  已暂停自动刷新")
        except Exception as exc:
            self.status_label.setText(f"⚠  刷新部分失败：{exc}")

    def _read_processes(self):
        processes = []
        for proc in psutil.process_iter(attrs=["pid", "name", "username", "status", "memory_info"]):
            try:
                info = proc.info
                pid = int(info.get("pid") or proc.pid)
                name = info.get("name") or "<未知进程>"
                user = info.get("username") or "—"
                status = info.get("status") or "未知"
                mem_info = info.get("memory_info")
                rss = int(mem_info.rss) if mem_info else 0
                cpu = float(proc.cpu_percent(interval=None))
                processes.append({
                    "pid": pid, "name": name, "username": user,
                    "status": status, "rss": rss, "cpu": cpu,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                continue
        self._current_processes = processes
        self.render_process_table()

    def render_process_table(self):
        if not hasattr(self, "process_table"):
            return
        query = self.search_input.text().strip().casefold() if hasattr(self, "search_input") else ""
        filtered = [p for p in self._current_processes if
                    not query or query in p["name"].casefold() or query in str(p["pid"]) or query in p["username"].casefold()]
        selected_pid = self._selected_pid()
        header = self.process_table.horizontalHeader()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        self.process_table.setSortingEnabled(False)
        self.process_table.setRowCount(0)
        for p in filtered:
            row = self.process_table.rowCount()
            self.process_table.insertRow(row)
            values = [
                (p["name"], p["name"]),
                (str(p["pid"]), p["pid"]),
                (f'{p["cpu"]:.1f}%', p["cpu"]),
                (format_bytes(p["rss"]), p["rss"]),
                (p["status"], p["status"]),
                (p["username"], p["username"]),
            ]
            for col, (text, raw) in enumerate(values):
                item = NumericItem(text)
                item.setData(Qt.ItemDataRole.UserRole, raw)
                if col in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == 0:
                    item.setForeground(QColor("#E4ECF8"))
                elif col == 2:
                    item.setForeground(QColor("#8DB6FF" if p["cpu"] >= 30 else "#A9B9D0"))
                elif col == 4:
                    item.setForeground(QColor("#72D6B4" if p["status"] == psutil.STATUS_RUNNING else "#91A0B4"))
                self.process_table.setItem(row, col, item)
        self.process_table.setSortingEnabled(True)
        if sort_col >= 0:
            self.process_table.sortItems(sort_col, sort_order)
        if selected_pid is not None:
            for row in range(self.process_table.rowCount()):
                item = self.process_table.item(row, 1)
                if item and int(item.data(Qt.ItemDataRole.UserRole)) == selected_pid:
                    self.process_table.selectRow(row)
                    break
        self.process_count_label.setText(f"显示 {len(filtered)} / {len(self._current_processes)} 个进程")

    def _selected_pid(self):
        if not hasattr(self, "process_table"):
            return None
        rows = self.process_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.process_table.item(rows[0].row(), 1)
        try:
            return int(item.data(Qt.ItemDataRole.UserRole)) if item else None
        except (TypeError, ValueError):
            return None

    def end_selected_process(self):
        pid = self._selected_pid()
        if pid is None:
            QMessageBox.information(self, "尚未选择进程", "请先在进程列表中选择一个进程。")
            return
        if pid in (0, 1, os.getpid()):
            QMessageBox.warning(self, "操作已阻止", "为避免关闭系统或当前程序自身，不能结束该进程。")
            return
        try:
            proc = psutil.Process(pid)
            process_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            QMessageBox.warning(self, "无法读取进程", f"无法读取该进程：{exc}")
            self.refresh_all()
            return
        answer = QMessageBox.question(
            self, "确认结束进程",
            f"确定要结束进程吗？\n\n进程：{process_name}\nPID：{pid}\n\n未保存的数据可能丢失。结束系统进程可能影响系统稳定性。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            proc.terminate()
            QMessageBox.information(self, "已发送结束请求", f"已向“{process_name}”（PID {pid}）发送终止请求。")
        except psutil.NoSuchProcess:
            QMessageBox.information(self, "进程已退出", "该进程已经退出。")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "权限不足", "当前账户没有权限结束该进程。可尝试以管理员身份运行。")
        except psutil.Error as exc:
            QMessageBox.warning(self, "结束失败", f"结束进程失败：{exc}")
        QTimer.singleShot(600, self.refresh_all)

    def show_selected_process_details(self, row, column):
        pid_item = self.process_table.item(row, 1)
        if not pid_item:
            return
        try:
            pid = int(pid_item.data(Qt.ItemDataRole.UserRole))
            proc = psutil.Process(pid)
            dialog = ProcessDetailsDialog(proc, self)
            dialog.exec()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            QMessageBox.warning(self, "无法读取", f"进程可能已经退出，或当前账户没有权限读取：{exc}")

    def show_process_context_menu(self, point):
        item = self.process_table.itemAt(point)
        if not item:
            return
        self.process_table.selectRow(item.row())
        menu = QMenu(self)
        details_action = QAction("查看详细信息", self)
        end_action = QAction("结束进程", self)
        details_action.triggered.connect(lambda: self.show_selected_process_details(item.row(), item.column()))
        end_action.triggered.connect(self.end_selected_process)
        menu.addAction(details_action)
        menu.addAction(end_action)
        menu.exec(self.process_table.viewport().mapToGlobal(point))

    def _populate_system_info(self):
        try:
            physical = psutil.cpu_count(logical=False)
            logical = psutil.cpu_count(logical=True)
            mem = psutil.virtual_memory()
            boot = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
            values = {
                "os": f"{platform.system()} {platform.release()}\n{platform.version()}",
                "host": socket.gethostname(),
                "cpu": platform.processor() or "系统未提供处理器名称",
                "logical": str(logical or "未知"),
                "physical": str(physical or "未知"),
                "memory": format_bytes(mem.total),
                "boot": boot,
                "python": platform.python_version(),
                "arch": f"{platform.machine()} · {platform.architecture()[0]}",
                "disk_io": "读取中…",
            }
            for key, value in values.items():
                self.system_values[key].setText(value)
        except Exception as exc:
            if hasattr(self, "system_values"):
                self.system_values["os"].setText(f"读取失败：{exc}")

    def _update_disk_io_label(self):
        counters = self._safe_disk_io()
        if counters is None:
            text = "当前平台不提供磁盘 I/O 数据"
        else:
            text = f"读取 {format_bytes(counters.read_bytes)}\n写入 {format_bytes(counters.write_bytes)}"
        if hasattr(self, "system_values") and "disk_io" in self.system_values:
            self.system_values["disk_io"].setText(text)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    window = TaskManagerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
