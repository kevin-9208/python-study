"""
网页价格监控工具 - Price Monitor
目标网站: books.toscrape.com
依赖安装: pip install PyQt5 requests beautifulsoup4

功能:
  - QThread 子线程爬取，主线程 UI 永不卡顿
  - 实时日志滚动显示
  - 开始/停止控制，可自定义抓取间隔
  - 随机 User-Agent + 随机延时防封策略
  - 数据自动追加写入 CSV
  - 界面内嵌数据预览表格
"""

import sys
import csv
import time
import random
import os
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QFrame, QSpinBox,
    QGroupBox, QStatusBar, QFileDialog, QMessageBox
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QObject, QTimer
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QTextCursor, QIcon
)

# ─────────────────────────────────────────────
#  常量
# ─────────────────────────────────────────────
DEFAULT_URL = "https://books.toscrape.com/"
DEFAULT_INTERVAL = 30          # 默认抓取间隔（秒）
MAX_ROWS_IN_TABLE = 200        # 界面表格最多显示行数
CSV_FILENAME = "price_monitor_data.csv"

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

STAR_MAP = {
    "One": "⭐",
    "Two": "⭐⭐",
    "Three": "⭐⭐⭐",
    "Four": "⭐⭐⭐⭐",
    "Five": "⭐⭐⭐⭐⭐",
}


# ─────────────────────────────────────────────
#  爬虫 Worker（运行在 QThread 子线程）
# ─────────────────────────────────────────────
class ScraperWorker(QObject):
    """
    所有网络请求和解析逻辑都在这里。
    通过 pyqtSignal 向主线程传递数据，绝不直接操作 UI。
    """
    log_signal    = pyqtSignal(str)          # 日志消息
    data_signal   = pyqtSignal(list)         # 一批抓取结果 [dict, ...]
    status_signal = pyqtSignal(str)          # 状态栏文字
    finished      = pyqtSignal()             # 任务结束

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
        self.log_signal.emit("─" * 50)

        round_num = 0
        while self._running:
            round_num += 1
            self.log_signal.emit(f"[第 {round_num} 轮] 开始抓取 ...")
            self.status_signal.emit(f"抓取中... 第 {round_num} 轮")

            try:
                items = self._scrape_books(self.url)
                if items:
                    self._save_to_csv(items)
                    self.data_signal.emit(items)
                    self.log_signal.emit(
                        f"[第 {round_num} 轮] ✅ 成功抓取 {len(items)} 条数据"
                    )
                else:
                    self.log_signal.emit(f"[第 {round_num} 轮] ⚠️  未解析到数据，请检查URL或选择器")
            except requests.exceptions.ConnectionError:
                self.log_signal.emit(f"[第 {round_num} 轮] ❌ 网络连接失败，请检查网络")
            except requests.exceptions.Timeout:
                self.log_signal.emit(f"[第 {round_num} 轮] ❌ 请求超时（>15s）")
            except Exception as e:
                self.log_signal.emit(f"[第 {round_num} 轮] ❌ 异常: {e}")

            if not self._running:
                break

            # 倒计时等待（可被 stop 提前打断）
            self.log_signal.emit(f"[等待] 下次抓取倒计时 {self.interval} 秒 ...")
            self.status_signal.emit(f"等待中... 下次抓取倒计时 {self.interval}s")
            for _ in range(self.interval * 2):        # 每 0.5s 检查一次
                if not self._running:
                    break
                time.sleep(0.5)

        self.log_signal.emit("─" * 50)
        self.log_signal.emit("[停止] 监控已停止")
        self.status_signal.emit("已停止")
        self.finished.emit()

    # ── 抓取逻辑 ────────────────────────────
    def _scrape_books(self, base_url: str) -> list:
        """抓取 books.toscrape.com 的书目列表（含翻页，最多5页）"""
        results = []
        page_url = base_url
        pages_scraped = 0
        max_pages = 3   # 演示限制3页，约60条

        while page_url and pages_scraped < max_pages:
            if not self._running:
                break

            headers = {"User-Agent": random.choice(USER_AGENTS)}
            # 随机延时 1~3 秒（防封基本礼仪）
            delay = random.uniform(1.0, 3.0)
            self.log_signal.emit(f"  → 请求: {page_url}  (延时 {delay:.1f}s)")
            time.sleep(delay)

            resp = requests.get(page_url, headers=headers, timeout=15)
            resp.raise_for_status()
            resp.encoding = "utf-8"

            soup = BeautifulSoup(resp.text, "html.parser")
            books = soup.select("article.product_pod")

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for book in books:
                title_tag = book.select_one("h3 a")
                price_tag = book.select_one("p.price_color")
                stock_tag = book.select_one("p.availability")
                rating_tag = book.select_one("p.star-rating")

                title  = title_tag["title"] if title_tag else "N/A"
                price  = price_tag.get_text(strip=True) if price_tag else "N/A"
                stock  = stock_tag.get_text(strip=True) if stock_tag else "N/A"
                rating_class = rating_tag["class"][1] if rating_tag else ""
                rating = STAR_MAP.get(rating_class, rating_class)

                results.append({
                    "timestamp": ts,
                    "url":       page_url,
                    "title":     title,
                    "price":     price,
                    "stock":     stock,
                    "rating":    rating,
                })

            # 翻页
            next_btn = soup.select_one("li.next a")
            if next_btn:
                # 拼接相对路径
                next_href = next_btn["href"]
                if next_href.startswith("catalogue/"):
                    page_url = base_url.rstrip("/") + "/catalogue/" + next_href.replace("catalogue/", "")
                elif "catalogue" not in next_href:
                    page_url = base_url.rstrip("/") + "/catalogue/" + next_href
                else:
                    page_url = base_url.rstrip("/") + "/" + next_href
            else:
                page_url = None

            pages_scraped += 1
            self.log_signal.emit(f"  ✔ 第 {pages_scraped} 页解析完毕，共 {len(books)} 本书")

        return results

    # ── CSV 存储 ─────────────────────────────
    def _save_to_csv(self, items: list):
        file_exists = os.path.isfile(self.csv_path)
        with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["timestamp", "url", "title", "price", "stock", "rating"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerows(items)
        self.log_signal.emit(f"  💾 已追加写入 CSV: {len(items)} 条")


# ─────────────────────────────────────────────
#  主窗口
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread  = None
        self.worker  = None
        self.total_scraped = 0
        self.csv_path = os.path.join(os.path.expanduser("~"), CSV_FILENAME)

        self._init_ui()
        self._apply_style()

    # ── 界面构建 ─────────────────────────────
    def _init_ui(self):
        self.setWindowTitle("📦 网页价格监控工具  |  Price Monitor")
        self.setMinimumSize(1000, 720)
        self.resize(1100, 780)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 8)
        root_layout.setSpacing(10)

        # ── 顶部控制区 ──────────────────────
        ctrl_group = QGroupBox("监控配置")
        ctrl_layout = QVBoxLayout(ctrl_group)
        ctrl_layout.setSpacing(8)

        # URL 行
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("目标 URL："))
        self.url_input = QLineEdit(DEFAULT_URL)
        self.url_input.setPlaceholderText("https://books.toscrape.com/")
        url_row.addWidget(self.url_input, 1)
        ctrl_layout.addLayout(url_row)

        # 间隔 + CSV + 按钮 行
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("抓取间隔（秒）："))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(DEFAULT_INTERVAL)
        self.interval_spin.setFixedWidth(80)
        opt_row.addWidget(self.interval_spin)

        opt_row.addSpacing(20)
        opt_row.addWidget(QLabel("CSV 路径："))
        self.csv_label = QLineEdit(self.csv_path)
        self.csv_label.setReadOnly(True)
        opt_row.addWidget(self.csv_label, 1)
        self.csv_btn = QPushButton("📂 更改")
        self.csv_btn.setFixedWidth(72)
        self.csv_btn.clicked.connect(self._choose_csv)
        opt_row.addWidget(self.csv_btn)

        opt_row.addSpacing(20)
        self.start_btn = QPushButton("▶  开始监控")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setFixedWidth(120)
        self.start_btn.clicked.connect(self._start_monitor)
        opt_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■  停止监控")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setFixedWidth(120)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_monitor)
        opt_row.addWidget(self.stop_btn)

        ctrl_layout.addLayout(opt_row)
        root_layout.addWidget(ctrl_group)

        # ── 主体区（日志 + 表格 左右分割）──
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)

        # 日志区
        log_frame = QGroupBox("实时运行日志")
        log_layout = QVBoxLayout(log_frame)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 9))
        log_btn_row = QHBoxLayout()
        clear_btn = QPushButton("🗑 清空日志")
        clear_btn.setFixedWidth(100)
        clear_btn.clicked.connect(self.log_box.clear)
        log_btn_row.addStretch()
        log_btn_row.addWidget(clear_btn)
        log_layout.addWidget(self.log_box)
        log_layout.addLayout(log_btn_row)
        splitter.addWidget(log_frame)

        # 数据表格区
        table_frame = QGroupBox("数据预览")
        table_layout = QVBoxLayout(table_frame)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["时间", "标题", "价格", "库存", "评分", "页面URL"]
        )
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(24)

        table_clear_btn = QPushButton("🗑 清空预览")
        table_clear_btn.setFixedWidth(100)
        table_clear_btn.clicked.connect(self._clear_table)
        table_btn_row = QHBoxLayout()
        table_btn_row.addStretch()
        table_btn_row.addWidget(table_clear_btn)

        table_layout.addWidget(self.table)
        table_layout.addLayout(table_btn_row)
        splitter.addWidget(table_frame)

        splitter.setSizes([420, 600])
        root_layout.addWidget(splitter, 1)

        # ── 状态栏 ───────────────────────────
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("就绪  |  目标: books.toscrape.com")
        self._stat_label = QLabel("共抓取：0 条")
        self.status_bar.addPermanentWidget(self._stat_label)

    # ── 样式表 ───────────────────────────────
    def _apply_style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #1e1e2e;
            color: #cdd6f4;
        }
        QGroupBox {
            border: 1px solid #313244;
            border-radius: 6px;
            margin-top: 10px;
            font-weight: bold;
            font-size: 10pt;
            color: #89b4fa;
            padding: 8px 6px 6px 6px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }
        QLineEdit, QSpinBox {
            background: #313244;
            border: 1px solid #45475a;
            border-radius: 4px;
            color: #cdd6f4;
            padding: 4px 6px;
            font-size: 9pt;
        }
        QLineEdit:focus, QSpinBox:focus {
            border-color: #89b4fa;
        }
        QPushButton {
            background-color: #45475a;
            color: #cdd6f4;
            border: none;
            border-radius: 5px;
            padding: 5px 12px;
            font-size: 9pt;
        }
        QPushButton:hover {
            background-color: #585b70;
        }
        QPushButton:pressed {
            background-color: #313244;
        }
        QPushButton#startBtn {
            background-color: #a6e3a1;
            color: #1e1e2e;
            font-weight: bold;
        }
        QPushButton#startBtn:hover {
            background-color: #94e2a0;
        }
        QPushButton#startBtn:disabled {
            background-color: #313244;
            color: #585b70;
        }
        QPushButton#stopBtn {
            background-color: #f38ba8;
            color: #1e1e2e;
            font-weight: bold;
        }
        QPushButton#stopBtn:hover {
            background-color: #f07a99;
        }
        QPushButton#stopBtn:disabled {
            background-color: #313244;
            color: #585b70;
        }
        QTextEdit {
            background-color: #11111b;
            border: 1px solid #313244;
            border-radius: 4px;
            color: #a6e3a1;
            font-family: Consolas, "Courier New", monospace;
            font-size: 9pt;
            line-height: 1.4;
        }
        QTableWidget {
            background-color: #181825;
            alternate-background-color: #1e1e2e;
            border: 1px solid #313244;
            border-radius: 4px;
            gridline-color: #313244;
            color: #cdd6f4;
            font-size: 9pt;
        }
        QTableWidget::item:selected {
            background-color: #45475a;
        }
        QHeaderView::section {
            background-color: #313244;
            color: #89b4fa;
            border: none;
            border-right: 1px solid #45475a;
            border-bottom: 1px solid #45475a;
            padding: 4px 6px;
            font-weight: bold;
            font-size: 9pt;
        }
        QScrollBar:vertical {
            background: #1e1e2e;
            width: 8px;
        }
        QScrollBar::handle:vertical {
            background: #45475a;
            border-radius: 4px;
        }
        QScrollBar:horizontal {
            background: #1e1e2e;
            height: 8px;
        }
        QScrollBar::handle:horizontal {
            background: #45475a;
            border-radius: 4px;
        }
        QSplitter::handle {
            background: #313244;
        }
        QStatusBar {
            background: #11111b;
            color: #6c7086;
            border-top: 1px solid #313244;
            font-size: 9pt;
        }
        QLabel {
            font-size: 9pt;
            color: #bac2de;
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

        # 创建线程和 worker
        self.thread = QThread()
        self.worker = ScraperWorker(url, interval, self.csv_path)
        self.worker.moveToThread(self.thread)

        # 连接信号
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

    # ── 日志追加（主线程槽）────────────────
    def _append_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}]  {msg}"
        self.log_box.append(line)
        # 自动滚到底部
        cursor = self.log_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_box.setTextCursor(cursor)

    # ── 数据到达（主线程槽）────────────────
    def _on_data(self, items: list):
        self.total_scraped += len(items)
        self._stat_label.setText(f"共抓取：{self.total_scraped} 条")

        for item in items:
            row = self.table.rowCount()
            if row >= MAX_ROWS_IN_TABLE:
                self.table.removeRow(0)    # 超出最大行数删掉最旧的
                row = self.table.rowCount()
            self.table.insertRow(row)

            def cell(text, align=Qt.AlignLeft | Qt.AlignVCenter):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align)
                return it

            self.table.setItem(row, 0, cell(item["timestamp"],
                                            Qt.AlignCenter | Qt.AlignVCenter))
            self.table.setItem(row, 1, cell(item["title"]))
            price_item = cell(item["price"], Qt.AlignCenter | Qt.AlignVCenter)
            price_item.setForeground(QColor("#f9e2af"))
            self.table.setItem(row, 2, price_item)

            stock_item = cell(item["stock"], Qt.AlignCenter | Qt.AlignVCenter)
            if "In stock" in item["stock"]:
                stock_item.setForeground(QColor("#a6e3a1"))
            else:
                stock_item.setForeground(QColor("#f38ba8"))
            self.table.setItem(row, 3, stock_item)

            self.table.setItem(row, 4, cell(item["rating"],
                                            Qt.AlignCenter | Qt.AlignVCenter))
            self.table.setItem(row, 5, cell(item["url"]))

        # 滚到最新行
        self.table.scrollToBottom()

    def _clear_table(self):
        self.table.setRowCount(0)

    # ── 关闭事件 ─────────────────────────────
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

    # 设置全局深色 Palette（配合 Fusion 风格）
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor("#1e1e2e"))
    palette.setColor(QPalette.WindowText,      QColor("#cdd6f4"))
    palette.setColor(QPalette.Base,            QColor("#181825"))
    palette.setColor(QPalette.AlternateBase,   QColor("#1e1e2e"))
    palette.setColor(QPalette.ToolTipBase,     QColor("#313244"))
    palette.setColor(QPalette.ToolTipText,     QColor("#cdd6f4"))
    palette.setColor(QPalette.Text,            QColor("#cdd6f4"))
    palette.setColor(QPalette.Button,          QColor("#313244"))
    palette.setColor(QPalette.ButtonText,      QColor("#cdd6f4"))
    palette.setColor(QPalette.BrightText,      QColor("#f38ba8"))
    palette.setColor(QPalette.Link,            QColor("#89b4fa"))
    palette.setColor(QPalette.Highlight,       QColor("#89b4fa"))
    palette.setColor(QPalette.HighlightedText, QColor("#1e1e2e"))
    app.setPalette(palette)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
