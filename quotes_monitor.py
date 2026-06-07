"""
名言监控工具 - Quotes Monitor
目标网站: quotes.toscrape.com
依赖安装: pip install PyQt5 requests beautifulsoup4

功能:
  - QThread 子线程爬取，主线程 UI 永不卡顿
  - 实时日志滚动显示
  - 开始/停止控制，可自定义抓取间隔
  - 随机 User-Agent + 随机延时防封策略
  - 数据自动追加写入 CSV
  - 界面内嵌数据预览表格
  - Bootstrap 明亮风格界面
"""

import sys
import csv
import time
import random
import os
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QSpinBox,
    QGroupBox, QFileDialog, QMessageBox, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette, QTextCursor

# ─────────────────────────────────────────────
#  常量
# ─────────────────────────────────────────────
DEFAULT_URL      = "https://quotes.toscrape.com/"
DEFAULT_INTERVAL = 30
MAX_ROWS_IN_TABLE = 200
CSV_FILENAME     = "quotes_monitor_data.csv"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6.1 Safari/605.1.15",
]


# ─────────────────────────────────────────────
#  爬虫 Worker（子线程，不触碰任何 UI）
# ─────────────────────────────────────────────
class ScraperWorker(QObject):
    log_signal    = pyqtSignal(str)
    data_signal   = pyqtSignal(list)
    status_signal = pyqtSignal(str)
    finished      = pyqtSignal()

    def __init__(self, url: str, interval: int, csv_path: str):
        super().__init__()
        self.url      = url
        self.interval = interval
        self.csv_path = csv_path
        self._running = False

    def stop(self):
        self._running = False

    # ── 主循环 ──────────────────────────────
    def run(self):
        self._running = True
        self.log_signal.emit(f"[启动] 目标URL: {self.url}")
        self.log_signal.emit(f"[启动] 抓取间隔: {self.interval} 秒")
        self.log_signal.emit(f"[启动] CSV 路径: {self.csv_path}")
        self.log_signal.emit("─" * 52)

        round_num = 0
        while self._running:
            round_num += 1
            self.log_signal.emit(f"[第 {round_num} 轮] 开始抓取 ...")
            self.status_signal.emit(f"抓取中 · 第 {round_num} 轮")

            try:
                items = self._scrape_quotes(self.url)
                if items:
                    self._save_to_csv(items)
                    self.data_signal.emit(items)
                    self.log_signal.emit(
                        f"[第 {round_num} 轮] ✅ 成功抓取 {len(items)} 条数据"
                    )
                else:
                    self.log_signal.emit(
                        f"[第 {round_num} 轮] ⚠️  未解析到数据，请检查 URL 或选择器"
                    )
            except requests.exceptions.ConnectionError:
                self.log_signal.emit(f"[第 {round_num} 轮] ❌ 网络连接失败，请检查网络")
            except requests.exceptions.Timeout:
                self.log_signal.emit(f"[第 {round_num} 轮] ❌ 请求超时（>15s）")
            except Exception as e:
                self.log_signal.emit(f"[第 {round_num} 轮] ❌ 异常: {e}")

            if not self._running:
                break

            self.log_signal.emit(f"[等待] 下次抓取倒计时 {self.interval} 秒 ...")
            self.status_signal.emit(f"等待中 · 下次抓取倒计时 {self.interval}s")
            for _ in range(self.interval * 2):
                if not self._running:
                    break
                time.sleep(0.5)

        self.log_signal.emit("─" * 52)
        self.log_signal.emit("[停止] 监控已停止")
        self.status_signal.emit("已停止")
        self.finished.emit()

    # ── 爬取 quotes.toscrape.com ────────────
    def _scrape_quotes(self, base_url: str) -> list:
        results      = []
        page_url     = base_url
        pages_scraped = 0
        max_pages    = 3   # 每轮最多抓 3 页（约 30 条名言）

        while page_url and pages_scraped < max_pages:
            if not self._running:
                break

            headers = {"User-Agent": random.choice(USER_AGENTS)}
            delay   = random.uniform(1.0, 3.0)
            self.log_signal.emit(f"  → 请求: {page_url}  (延时 {delay:.1f}s)")
            time.sleep(delay)

            resp          = requests.get(page_url, headers=headers, timeout=15)
            resp.raise_for_status()
            resp.encoding = "utf-8"

            soup   = BeautifulSoup(resp.text, "html.parser")
            quotes = soup.select("div.quote")
            ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for q in quotes:
                text_tag   = q.select_one("span.text")
                author_tag = q.select_one("small.author")
                tag_tags   = q.select("div.tags a.tag")

                quote  = text_tag.get_text(strip=True)   if text_tag   else "N/A"
                author = author_tag.get_text(strip=True) if author_tag else "N/A"
                tags   = " · ".join(t.get_text(strip=True) for t in tag_tags)

                results.append({
                    "timestamp": ts,
                    "url":       page_url,
                    "quote":     quote,
                    "author":    author,
                    "tags":      tags,
                })

            # 翻页（quotes 站直接用相对路径）
            next_btn = soup.select_one("li.next a")
            if next_btn:
                next_href = next_btn["href"]          # e.g. /page/2/
                if next_href.startswith("/"):
                    from urllib.parse import urlparse
                    parsed   = urlparse(base_url)
                    page_url = f"{parsed.scheme}://{parsed.netloc}{next_href}"
                else:
                    page_url = base_url.rstrip("/") + "/" + next_href
            else:
                page_url = None

            pages_scraped += 1
            self.log_signal.emit(
                f"  ✔ 第 {pages_scraped} 页解析完毕，共 {len(quotes)} 条名言"
            )

        return results

    # ── CSV 存储 ─────────────────────────────
    def _save_to_csv(self, items: list):
        file_exists = os.path.isfile(self.csv_path)
        with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["timestamp", "url", "quote", "author", "tags"]
            writer     = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerows(items)
        self.log_signal.emit(f"  💾 已追加写入 CSV: {len(items)} 条")


# ─────────────────────────────────────────────
#  主窗口 — Bootstrap 明亮风格
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread        = None
        self.worker        = None
        self.total_scraped = 0
        self.csv_path      = os.path.join(os.path.expanduser("~"), CSV_FILENAME)

        self._init_ui()
        self._apply_style()

    # ── 界面构建 ─────────────────────────────
    def _init_ui(self):
        self.setWindowTitle("💬 名言监控工具  |  Quotes Monitor")
        self.setMinimumSize(1020, 700)
        self.resize(1120, 760)

        central     = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(14, 10, 14, 6)
        root_layout.setSpacing(10)

        # ── 顶部 Navbar 风格标题栏 ──────────
        navbar = QFrame()
        navbar.setObjectName("navbar")
        navbar.setFixedHeight(48)
        nav_layout = QHBoxLayout(navbar)
        nav_layout.setContentsMargins(14, 0, 14, 0)

        brand = QLabel("💬  Quotes Monitor")
        brand.setObjectName("navBrand")
        nav_layout.addWidget(brand)
        nav_layout.addStretch()

        self._stat_label = QLabel("共抓取：0 条")
        self._stat_label.setObjectName("navStat")
        nav_layout.addWidget(self._stat_label)
        root_layout.addWidget(navbar)

        # ── 配置卡片 ─────────────────────────
        card_config = QFrame()
        card_config.setObjectName("card")
        card_layout = QVBoxLayout(card_config)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        # 卡片标题
        cfg_title = QLabel("监控配置")
        cfg_title.setObjectName("cardTitle")
        card_layout.addWidget(cfg_title)

        # 分割线
        line1 = QFrame(); line1.setFrameShape(QFrame.HLine)
        line1.setObjectName("divider")
        card_layout.addWidget(line1)

        # URL 行
        url_row = QHBoxLayout()
        lbl_url = QLabel("目标 URL")
        lbl_url.setObjectName("formLabel")
        lbl_url.setFixedWidth(80)
        url_row.addWidget(lbl_url)
        self.url_input = QLineEdit(DEFAULT_URL)
        self.url_input.setObjectName("formControl")
        self.url_input.setPlaceholderText("https://quotes.toscrape.com/")
        url_row.addWidget(self.url_input, 1)
        card_layout.addLayout(url_row)

        # 间隔 + CSV + 按钮 行
        opt_row = QHBoxLayout()
        opt_row.setSpacing(10)

        lbl_iv = QLabel("抓取间隔（秒）")
        lbl_iv.setObjectName("formLabel")
        lbl_iv.setFixedWidth(100)
        opt_row.addWidget(lbl_iv)

        self.interval_spin = QSpinBox()
        self.interval_spin.setObjectName("spinBox")
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(DEFAULT_INTERVAL)
        self.interval_spin.setFixedWidth(90)
        opt_row.addWidget(self.interval_spin)

        opt_row.addSpacing(16)
        lbl_csv = QLabel("CSV 路径")
        lbl_csv.setObjectName("formLabel")
        lbl_csv.setFixedWidth(68)
        opt_row.addWidget(lbl_csv)

        self.csv_label = QLineEdit(self.csv_path)
        self.csv_label.setObjectName("formControlReadonly")
        self.csv_label.setReadOnly(True)
        opt_row.addWidget(self.csv_label, 1)

        self.csv_btn = QPushButton("📂 更改")
        self.csv_btn.setObjectName("btnSecondary")
        self.csv_btn.setFixedWidth(78)
        self.csv_btn.clicked.connect(self._choose_csv)
        opt_row.addWidget(self.csv_btn)

        opt_row.addSpacing(16)

        self.start_btn = QPushButton("▶  开始监控")
        self.start_btn.setObjectName("btnSuccess")
        self.start_btn.setFixedWidth(118)
        self.start_btn.clicked.connect(self._start_monitor)
        opt_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■  停止监控")
        self.stop_btn.setObjectName("btnDanger")
        self.stop_btn.setFixedWidth(118)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_monitor)
        opt_row.addWidget(self.stop_btn)

        card_layout.addLayout(opt_row)
        root_layout.addWidget(card_config)

        # ── 主体：日志卡片 + 表格卡片 ───────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(8)
        splitter.setObjectName("mainSplitter")

        # 日志卡片
        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(14, 12, 14, 10)
        log_layout.setSpacing(8)

        log_title = QLabel("实时运行日志")
        log_title.setObjectName("cardTitle")
        log_layout.addWidget(log_title)
        line2 = QFrame(); line2.setFrameShape(QFrame.HLine)
        line2.setObjectName("divider")
        log_layout.addWidget(line2)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setObjectName("logBox")
        log_layout.addWidget(self.log_box, 1)

        log_btn_row = QHBoxLayout()
        log_btn_row.addStretch()
        clear_log_btn = QPushButton("🗑  清空日志")
        clear_log_btn.setObjectName("btnOutline")
        clear_log_btn.setFixedWidth(100)
        clear_log_btn.clicked.connect(self.log_box.clear)
        log_btn_row.addWidget(clear_log_btn)
        log_layout.addLayout(log_btn_row)
        splitter.addWidget(log_card)

        # 表格卡片
        tbl_card = QFrame()
        tbl_card.setObjectName("card")
        tbl_layout = QVBoxLayout(tbl_card)
        tbl_layout.setContentsMargins(14, 12, 14, 10)
        tbl_layout.setSpacing(8)

        tbl_title = QLabel("数据预览")
        tbl_title.setObjectName("cardTitle")
        tbl_layout.addWidget(tbl_title)
        line3 = QFrame(); line3.setFrameShape(QFrame.HLine)
        line3.setObjectName("divider")
        tbl_layout.addWidget(line3)

        self.table = QTableWidget()
        self.table.setObjectName("dataTable")
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["时间", "名言", "作者", "标签", "页面 URL"]
        )
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        tbl_layout.addWidget(self.table, 1)

        tbl_btn_row = QHBoxLayout()
        tbl_btn_row.addStretch()
        clear_tbl_btn = QPushButton("🗑  清空预览")
        clear_tbl_btn.setObjectName("btnOutline")
        clear_tbl_btn.setFixedWidth(100)
        clear_tbl_btn.clicked.connect(self._clear_table)
        tbl_btn_row.addWidget(clear_tbl_btn)
        tbl_layout.addLayout(tbl_btn_row)
        splitter.addWidget(tbl_card)

        splitter.setSizes([400, 660])
        root_layout.addWidget(splitter, 1)

        # ── 状态栏 ───────────────────────────
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("就绪  ·  目标: quotes.toscrape.com")

    # ── Bootstrap 明亮样式表 ─────────────────
    def _apply_style(self):
        # Bootstrap 色值参考
        # primary  #0d6efd   success #198754   danger  #dc3545
        # secondary#6c757d   light   #f8f9fa   white   #ffffff
        # border   #dee2e6   text    #212529   muted   #6c757d
        self.setStyleSheet("""
        /* ── 全局背景 ── */
        QMainWindow, QWidget {
            background-color: #f0f2f5;
            color: #212529;
            font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            font-size: 9pt;
        }

        /* ── Navbar ── */
        QFrame#navbar {
            background-color: #0d6efd;
            border-radius: 6px;
        }
        QLabel#navBrand {
            color: #ffffff;
            font-size: 13pt;
            font-weight: bold;
            letter-spacing: 0.5px;
        }
        QLabel#navStat {
            color: #cfe2ff;
            font-size: 9pt;
            font-weight: bold;
        }

        /* ── 卡片 ── */
        QFrame#card {
            background-color: #ffffff;
            border: 1px solid #dee2e6;
            border-radius: 8px;
        }
        QLabel#cardTitle {
            color: #0d6efd;
            font-size: 10pt;
            font-weight: bold;
            padding: 0;
        }
        QFrame#divider {
            color: #dee2e6;
            background-color: #dee2e6;
            border: none;
            max-height: 1px;
        }

        /* ── 表单控件 ── */
        QLabel#formLabel {
            color: #495057;
            font-weight: 600;
        }
        QLineEdit#formControl, QLineEdit#formControlReadonly {
            background-color: #ffffff;
            border: 1px solid #ced4da;
            border-radius: 5px;
            color: #212529;
            padding: 5px 9px;
            font-size: 9pt;
            selection-background-color: #0d6efd;
        }
        QLineEdit#formControl:focus {
            border-color: #86b7fe;
            outline: none;
        }
        QLineEdit#formControlReadonly {
            background-color: #e9ecef;
            color: #6c757d;
        }
        QSpinBox#spinBox {
            background-color: #ffffff;
            border: 1px solid #ced4da;
            border-radius: 5px;
            color: #212529;
            padding: 4px 8px;
            font-size: 9pt;
        }
        QSpinBox#spinBox:focus {
            border-color: #86b7fe;
        }

        /* ── 按钮通用 ── */
        QPushButton {
            border-radius: 5px;
            padding: 5px 14px;
            font-size: 9pt;
            font-weight: 600;
            border: none;
        }
        /* success = 开始 */
        QPushButton#btnSuccess {
            background-color: #198754;
            color: #ffffff;
        }
        QPushButton#btnSuccess:hover {
            background-color: #157347;
        }
        QPushButton#btnSuccess:pressed {
            background-color: #0f5132;
        }
        QPushButton#btnSuccess:disabled {
            background-color: #a3cfbb;
            color: #ffffff;
        }
        /* danger = 停止 */
        QPushButton#btnDanger {
            background-color: #dc3545;
            color: #ffffff;
        }
        QPushButton#btnDanger:hover {
            background-color: #bb2d3b;
        }
        QPushButton#btnDanger:pressed {
            background-color: #842029;
        }
        QPushButton#btnDanger:disabled {
            background-color: #f1aeb5;
            color: #ffffff;
        }
        /* secondary = 更改CSV */
        QPushButton#btnSecondary {
            background-color: #6c757d;
            color: #ffffff;
        }
        QPushButton#btnSecondary:hover {
            background-color: #5c636a;
        }
        QPushButton#btnSecondary:pressed {
            background-color: #4d5154;
        }
        /* outline = 清空 */
        QPushButton#btnOutline {
            background-color: transparent;
            border: 1px solid #ced4da;
            color: #6c757d;
        }
        QPushButton#btnOutline:hover {
            background-color: #f8f9fa;
            color: #495057;
            border-color: #adb5bd;
        }
        QPushButton#btnOutline:pressed {
            background-color: #e9ecef;
        }

        /* ── 日志框 ── */
        QTextEdit#logBox {
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 5px;
            color: #198754;
            font-family: Consolas, "Courier New", monospace;
            font-size: 9pt;
            padding: 4px;
            line-height: 1.5;
        }

        /* ── 数据表格 ── */
        QTableWidget#dataTable {
            background-color: #ffffff;
            alternate-background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 5px;
            gridline-color: #e9ecef;
            color: #212529;
            font-size: 9pt;
            selection-background-color: #cfe2ff;
            selection-color: #212529;
        }
        QTableWidget#dataTable::item:selected {
            background-color: #cfe2ff;
            color: #212529;
        }
        QHeaderView::section {
            background-color: #0d6efd;
            color: #ffffff;
            border: none;
            border-right: 1px solid #3d8bfd;
            border-bottom: 1px solid #3d8bfd;
            padding: 5px 8px;
            font-weight: bold;
            font-size: 9pt;
        }
        QHeaderView::section:last {
            border-right: none;
        }

        /* ── 滚动条 ── */
        QScrollBar:vertical {
            background: #f8f9fa;
            width: 10px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical {
            background: #adb5bd;
            border-radius: 5px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background: #6c757d;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }
        QScrollBar:horizontal {
            background: #f8f9fa;
            height: 10px;
            border-radius: 5px;
        }
        QScrollBar::handle:horizontal {
            background: #adb5bd;
            border-radius: 5px;
            min-width: 20px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #6c757d;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0;
        }

        /* ── 分割条 ── */
        QSplitter#mainSplitter::handle {
            background-color: #dee2e6;
            border-radius: 3px;
        }

        /* ── 状态栏 ── */
        QStatusBar {
            background-color: #e9ecef;
            color: #6c757d;
            border-top: 1px solid #dee2e6;
            font-size: 9pt;
            padding: 2px 6px;
        }
        """)

    # ── 按钮槽函数 ───────────────────────────
    def _choose_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "选择 CSV 保存位置", self.csv_path,
            "CSV 文件 (*.csv);;所有文件 (*)"
        )
        if path:
            if not path.endswith(".csv"):
                path += ".csv"
            self.csv_path = path
            self.csv_label.setText(path)

    def _start_monitor(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入目标 URL")
            return

        interval = self.interval_spin.value()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.url_input.setEnabled(False)
        self.interval_spin.setEnabled(False)

        self.thread = QThread()
        self.worker = ScraperWorker(url, interval, self.csv_path)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.log_signal.connect(self._append_log)
        self.worker.data_signal.connect(self._on_data)
        self.worker.status_signal.connect(self.status_bar.showMessage)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self._on_worker_finished)

        self.thread.start()

    def _stop_monitor(self):
        if self.worker:
            self.worker.stop()
        self.stop_btn.setEnabled(False)
        self._append_log("[用户] 已发送停止信号，等待当前任务结束...")

    def _on_worker_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.url_input.setEnabled(True)
        self.interval_spin.setEnabled(True)

    # ── 日志追加 ─────────────────────────────
    def _append_log(self, msg: str):
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}]  {msg}"
        self.log_box.append(line)
        cursor = self.log_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_box.setTextCursor(cursor)

    # ── 数据到达 ─────────────────────────────
    def _on_data(self, items: list):
        self.total_scraped += len(items)
        self._stat_label.setText(f"共抓取：{self.total_scraped} 条")

        for item in items:
            row = self.table.rowCount()
            if row >= MAX_ROWS_IN_TABLE:
                self.table.removeRow(0)
                row = self.table.rowCount()
            self.table.insertRow(row)

            def cell(text, align=Qt.AlignLeft | Qt.AlignVCenter):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align)
                return it

            self.table.setItem(row, 0, cell(item["timestamp"],
                                            Qt.AlignCenter | Qt.AlignVCenter))

            quote_item = cell(item["quote"])
            quote_item.setForeground(QColor("#0d6efd"))
            self.table.setItem(row, 1, quote_item)

            author_item = cell(item["author"], Qt.AlignCenter | Qt.AlignVCenter)
            author_item.setForeground(QColor("#198754"))
            self.table.setItem(row, 2, author_item)

            tags_item = cell(item["tags"], Qt.AlignCenter | Qt.AlignVCenter)
            tags_item.setForeground(QColor("#6c757d"))
            self.table.setItem(row, 3, tags_item)

            self.table.setItem(row, 4, cell(item["url"]))

        self.table.scrollToBottom()

    def _clear_table(self):
        self.table.setRowCount(0)

    # ── 关闭安全退出 ─────────────────────────
    def closeEvent(self, event):
        if self.worker and self.thread and self.thread.isRunning():
            self.worker.stop()
            self.thread.quit()
            self.thread.wait(3000)
        event.accept()


# ─────────────────────────────────────────────
#  程序入口
# ─────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 亮色 Palette（配合 Fusion + Bootstrap 样式表）
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor("#f0f2f5"))
    palette.setColor(QPalette.WindowText,      QColor("#212529"))
    palette.setColor(QPalette.Base,            QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase,   QColor("#f8f9fa"))
    palette.setColor(QPalette.ToolTipBase,     QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText,     QColor("#212529"))
    palette.setColor(QPalette.Text,            QColor("#212529"))
    palette.setColor(QPalette.Button,          QColor("#e9ecef"))
    palette.setColor(QPalette.ButtonText,      QColor("#212529"))
    palette.setColor(QPalette.BrightText,      QColor("#dc3545"))
    palette.setColor(QPalette.Link,            QColor("#0d6efd"))
    palette.setColor(QPalette.Highlight,       QColor("#0d6efd"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
