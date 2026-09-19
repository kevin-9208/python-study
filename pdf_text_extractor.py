#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
pdf_text_extractor.py
========================
从"可复制文本"的 PDF 中提取文本 / 表格；遇到没有文本层的扫描页，
自动回退用 OCR 识别（可关闭）。

设计思路：
  - 正文提取默认用 PyMuPDF：速度快，按文本块坐标重排顺序，
    支持简单的多栏版面（--columns）和页眉页脚过滤（--margin-top/--margin-bottom）
  - 表格提取用 pdfplumber：它对表格线条的识别效果比 PyMuPDF 好得多
  - 每一页会自动判断"是否有文本层"：如果judge为无文本层的扫描页，
    默认自动切换成 OCR（需要装 pytesseract + tesseract 引擎），
    可以用 --no-ocr-fallback 关掉，改成只给出提示

依赖：
    pip install pymupdf pdfplumber
    # 如果要处理扫描页 OCR 回退，还需要：
    pip install pytesseract pillow
    # 以及系统安装 tesseract 引擎本体（pip 装不出来）：
    #   Ubuntu/Debian : sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
    #   macOS         : brew install tesseract tesseract-lang
    #   Windows       : https://github.com/UB-Mannheim/tesseract/wiki

============================================================
用法示例
============================================================
    # 提取单个 PDF 的正文，打印到终端
    python pdf_text_extractor.py report.pdf

    # 保存为同目录 report.txt
    python pdf_text_extractor.py report.pdf --save

    # 只提取第 1-3 页和第 5 页
    python pdf_text_extractor.py report.pdf --pages 1-3,5

    # 论文是双栏排版，按"先读完左栏再读右栏"的顺序重排
    python pdf_text_extractor.py paper.pdf --columns 2

    # 过滤页面顶部 8%、底部 8% 的内容（常见的页眉页脚区域）
    python pdf_text_extractor.py report.pdf --margin-top 0.08 --margin-bottom 0.08

    # 批量处理一个文件夹（含子目录）里的所有 PDF，每个存成同名 .txt
    python pdf_text_extractor.py ./docs --recursive --save

    # 批量处理，合并成一个文件
    python pdf_text_extractor.py ./docs --recursive -o all_text.txt

    # 提取表格，合并导出成一个 Excel（每张表一个 sheet）
    python pdf_text_extractor.py invoice.pdf --tables --tables-output tables.xlsx

    # 提取表格，导出成多个 CSV 文件到一个目录
    python pdf_text_extractor.py invoice.pdf --tables --tables-output ./tables_csv

    # 遇到没有文本层的扫描页，关闭自动 OCR，只提示不识别（更快）
    python pdf_text_extractor.py mixed.pdf --no-ocr-fallback

    # 扫描页 OCR 识别语言（沿用同一套 --lang 习惯）
    python pdf_text_extractor.py mixed.pdf --ocr-lang eng
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf  # 兼容旧版 PyMuPDF
    except ImportError:
        print("缺少依赖库：pymupdf")
        print("请先运行：pip install pymupdf")
        sys.exit(1)


PDF_EXT = ".pdf"
MIN_TEXT_CHARS_PER_PAGE = 15  # 一页里抽出的字符数低于这个值，就判定为"没有文本层"（可能是扫描页）


# ============================================================
# 页码范围解析
# ============================================================

def parse_page_range(spec: str, total_pages: int):
    """把 '1-3,5' 这种字符串解析成从 0 开始的页码索引列表；不传则返回全部页"""
    if not spec:
        return list(range(total_pages))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            for p in range(int(start_s), int(end_s) + 1):
                pages.add(p)
        else:
            pages.add(int(part))
    return sorted(p - 1 for p in pages if 1 <= p <= total_pages)


# ============================================================
# 正文提取（PyMuPDF）
# ============================================================

def page_has_text_layer(page, min_chars: int = MIN_TEXT_CHARS_PER_PAGE) -> bool:
    """粗略判断这一页是不是有文本层：抽出来的字符数太少，大概率是纯图片扫描页"""
    text = page.get_text("text")
    return len(text.strip()) >= min_chars


def dehyphenate(text: str) -> str:
    """把因排版换行断开的英文单词重新拼回去，比如 "infor-\\nmation" -> "information"
    只匹配"连字符+换行+紧跟小写字母"这种典型场景，避免误伤中文和正常的项目符号"-\""""
    return re.sub(r"-\n(?=[a-z])", "", text)


def sort_blocks(blocks, columns: int, page_width: float):
    """
    按阅读顺序重排文本块。
    columns=1（默认）：简单按 (y0, x0) 从上到下、从左到右排 —— 适合单栏排版。
    columns=N (N>1)：先把每个块按 x 坐标分配到 N 个列里，
                      同一列内按 y0 从上到下排，列与列之间"先读完左边整列，再读右边"——
                      适合论文/杂志那种规整的多栏排版。
    这是一个实用主义的启发式规则，不是真正的版面分析算法，
    遇到特别复杂或不规则的排版（图文混排、跨栏标题等）效果会打折扣，
    这种情况建议配合 --columns 1 的默认顺序自己再人工核对一下。
    """
    if columns <= 1:
        return sorted(blocks, key=lambda b: (round(b[1], 1), b[0]))

    col_width = page_width / columns

    def col_index(b):
        x0 = b[0]
        idx = int(x0 // col_width)
        return max(0, min(columns - 1, idx))

    return sorted(blocks, key=lambda b: (col_index(b), round(b[1], 1), b[0]))


def extract_text_blocks(page, columns: int, margin_top: float, margin_bottom: float) -> str:
    """从一页里提取文本，按版面顺序重排并过滤页眉页脚区域"""
    page_width = page.rect.width
    page_height = page.rect.height

    top_cut = page_height * margin_top
    bottom_cut = page_height * (1 - margin_bottom)

    raw_blocks = page.get_text("blocks")
    # PyMuPDF block 结构：(x0, y0, x1, y1, text, block_no, block_type)
    # block_type == 1 是图片块，这里只要文字块 (block_type == 0)；
    # 页眉/页脚判断用文字块的纵向中心点是否落在边距区域内，
    # 比"整个块必须完全落在区域内"更符合直觉——文字块本身有一定高度，
    # 卡在边界线附近时用中心点判断更不容易漏判
    text_blocks = []
    for b in raw_blocks:
        if len(b) < 7 or b[6] != 0 or not b[4].strip():
            continue
        y_center = (b[1] + b[3]) / 2
        if y_center <= top_cut or y_center >= bottom_cut:
            continue
        text_blocks.append(b)

    ordered = sort_blocks(text_blocks, columns, page_width)
    parts = [b[4].strip() for b in ordered]
    return "\n\n".join(parts)


# ============================================================
# 扫描页 OCR 回退（可选依赖，用到时才 import）
# ============================================================

def ocr_page_image(page, lang: str, dpi: int = 300) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            "该页是扫描页（没有文本层），需要 OCR 才能识别，"
            "但没装 pytesseract/pillow：pip install pytesseract pillow，"
            "并确保系统装了 tesseract 引擎本体"
        )

    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return pytesseract.image_to_string(img, lang=lang).strip()


# ============================================================
# 单个 PDF 的正文提取主流程
# ============================================================

def extract_pdf_text(path: Path, columns: int, margin_top: float, margin_bottom: float,
                      page_spec: str, dehyphen: bool, ocr_fallback: bool, ocr_lang: str,
                      log=print) -> str:
    doc = pymupdf.open(str(path))
    total_pages = doc.page_count
    page_indices = parse_page_range(page_spec, total_pages)

    if not page_indices:
        doc.close()
        log(f"警告：{path.name} 没有匹配到任何有效页码（共 {total_pages} 页），跳过")
        return ""

    results = []
    for idx in page_indices:
        page = doc.load_page(idx)

        if page_has_text_layer(page):
            text = extract_text_blocks(page, columns, margin_top, margin_bottom)
            if dehyphen:
                text = dehyphenate(text)
        else:
            if ocr_fallback:
                log(f"  第 {idx + 1} 页没有文本层，判定为扫描页，改用 OCR 识别...")
                try:
                    text = ocr_page_image(page, ocr_lang)
                except RuntimeError as e:
                    text = f"[OCR 未完成：{e}]"
            else:
                text = "[该页没有文本层（疑似扫描页），已跳过。去掉 --no-ocr-fallback 参数即可自动 OCR 识别]"

        results.append(f"----- 第 {idx + 1} 页 -----\n{text}")

    doc.close()
    return "\n\n".join(results)


# ============================================================
# 表格提取（pdfplumber）
# ============================================================

def extract_tables(path: Path, page_spec: str, log=print):
    """返回 [(页码(从1开始), 表格序号(从1开始), rows), ...]，rows 是二维 list（含表头）"""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("提取表格需要安装 pdfplumber：pip install pdfplumber")

    results = []
    with pdfplumber.open(str(path)) as pdf:
        total_pages = len(pdf.pages)
        page_indices = parse_page_range(page_spec, total_pages)
        for idx in page_indices:
            page = pdf.pages[idx]
            tables = page.extract_tables()
            if not tables:
                continue
            for t_i, table in enumerate(tables, start=1):
                log(f"  第 {idx + 1} 页发现表格 {t_i}：{len(table)} 行 x {len(table[0]) if table else 0} 列")
                results.append((idx + 1, t_i, table))
    return results


def safe_sheet_name(name: str, used_names: set) -> str:
    """Excel sheet 名限制：<=31字符，不能含 \\/?*[]:"""
    cleaned = re.sub(r'[\\/\?\*\[\]:]', "_", name).strip()[:31]
    original = cleaned
    suffix = 1
    while cleaned in used_names:
        suf = f"_{suffix}"
        cleaned = original[: 31 - len(suf)] + suf
        suffix += 1
    used_names.add(cleaned)
    return cleaned


def save_tables(tables, output_path: str, log=print):
    """tables: extract_tables() 的返回值。
    output_path 以 .xlsx 结尾 -> 每张表一个 sheet；
    否则视为目录 -> 每张表存一个 csv 文件
    """
    if not tables:
        log("没有提取到任何表格。")
        return 0

    out_path = Path(output_path)

    if out_path.suffix.lower() == ".xlsx":
        try:
            import pandas as pd
        except ImportError:
            raise RuntimeError("导出 Excel 需要安装 pandas + openpyxl：pip install pandas openpyxl")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        used_names = set()
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            for page_no, table_no, rows in tables:
                df = pd.DataFrame(rows[1:], columns=rows[0]) if len(rows) > 1 else pd.DataFrame(rows)
                sheet_name = safe_sheet_name(f"p{page_no}_t{table_no}", used_names)
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        log(f"完成：{len(tables)} 张表格已写入 {out_path}（每张表一个 sheet）")
    else:
        out_path.mkdir(parents=True, exist_ok=True)
        import csv
        for page_no, table_no, rows in tables:
            csv_path = out_path / f"page{page_no}_table{table_no}.csv"
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            log(f"  [OK] -> {csv_path.name}")
        log(f"完成：{len(tables)} 张表格已写入目录 {out_path}")

    return len(tables)


# ============================================================
# 文件收集 + CLI
# ============================================================

def collect_pdfs(input_path: Path, recursive: bool):
    if input_path.is_file():
        if input_path.suffix.lower() != PDF_EXT:
            raise ValueError(f"不是 PDF 文件：{input_path}")
        return [input_path]
    if input_path.is_dir():
        pattern = "**/*.pdf" if recursive else "*.pdf"
        return sorted(p for p in input_path.glob(pattern) if p.is_file())
    raise FileNotFoundError(f"路径不存在：{input_path}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="从可复制文本的 PDF 中提取文本/表格，扫描页可自动 OCR 回退",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="PDF 文件路径，或包含 PDF 的文件夹路径")
    parser.add_argument("-o", "--output", help="合并输出到指定文件（正文用 .txt；配合 --tables 用 .xlsx，或传一个目录导出多个 csv）")
    parser.add_argument("--save", action="store_true", help="每个 PDF 的正文保存为同名 .txt（与 -o 二选一，仅用于正文提取模式）")
    parser.add_argument("--recursive", action="store_true", help="处理文件夹时递归子目录")
    parser.add_argument("--pages", help="仅处理指定页码，如 '1-3,5'（从1开始，不指定则处理全部页）")

    parser.add_argument("--columns", type=int, default=1, help="按 N 栏顺序重排文本，默认 1（不做多栏处理）。论文/杂志双栏排版可试 --columns 2")
    parser.add_argument("--margin-top", type=float, default=0.0, help="过滤页面顶部这个比例区域的内容（0~1），用于去掉页眉，默认 0 不过滤")
    parser.add_argument("--margin-bottom", type=float, default=0.0, help="过滤页面底部这个比例区域的内容（0~1），用于去掉页脚，默认 0 不过滤")
    parser.add_argument("--no-dehyphenate", dest="dehyphenate", action="store_false", default=True, help="关闭英文断词重连（默认开启）")

    parser.add_argument("--no-ocr-fallback", dest="ocr_fallback", action="store_false", default=True, help="遇到没有文本层的扫描页时不自动 OCR，只给出提示（默认会自动 OCR）")
    parser.add_argument("--ocr-lang", default="chi_sim+eng", help="扫描页 OCR 识别语言，默认 chi_sim+eng")

    parser.add_argument("--tables", action="store_true", help="提取表格而不是正文，需配合 --tables-output 指定输出位置")
    parser.add_argument("--tables-output", help="表格输出路径：以 .xlsx 结尾则合并导出多sheet；否则视为目录，导出多个 csv")

    return parser


def run_text_mode(files, args):
    combined_parts = []
    error_count = 0

    for f in files:
        print(f"处理：{f}")
        try:
            text = extract_pdf_text(
                f, columns=args.columns, margin_top=args.margin_top, margin_bottom=args.margin_bottom,
                page_spec=args.pages, dehyphen=args.dehyphenate,
                ocr_fallback=args.ocr_fallback, ocr_lang=args.ocr_lang,
                log=print,
            )
        except Exception as e:
            print(f"  [失败] {f.name}：{e}", file=sys.stderr)
            error_count += 1
            continue

        if args.save:
            txt_path = f.with_suffix(".txt")
            txt_path.write_text(text, encoding="utf-8")
            print(f"  [OK] -> {txt_path.name}  ({len(text)} 字符)")
        elif args.output:
            combined_parts.append(f"===== {f} =====\n{text}")
            print(f"  [OK] ({len(text)} 字符)")
        else:
            print(f"\n===== {f} =====")
            print(text if text else "(未提取到文字)")

    if args.output and combined_parts:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n\n".join(combined_parts), encoding="utf-8")
        print(f"\n完成：结果已合并写入 {out_path}")

    return error_count


def run_tables_mode(files, args):
    if not args.tables_output:
        print("错误：--tables 模式需要用 --tables-output 指定输出位置（.xlsx 或目录）", file=sys.stderr)
        sys.exit(1)

    all_tables = []
    error_count = 0
    for f in files:
        print(f"提取表格：{f}")
        try:
            tables = extract_tables(f, args.pages, log=print)
            if len(files) > 1:
                # 多文件合并的场景，把源文件名也编码进表格标识里，避免sheet/文件名冲突
                tables = [(f"{f.stem}_p{p}", t, rows) for p, t, rows in tables]
            all_tables.extend(tables)
        except Exception as e:
            print(f"  [失败] {f.name}：{e}", file=sys.stderr)
            error_count += 1

    try:
        save_tables(all_tables, args.tables_output, log=print)
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    return error_count


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.save and args.output:
        print("错误：--save 和 -o/--output 不能同时使用，请二选一", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)
    try:
        files = collect_pdfs(input_path, args.recursive)
    except (FileNotFoundError, ValueError) as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    if not files:
        print("没有找到任何 PDF 文件。")
        return

    print(f"共找到 {len(files)} 个 PDF 文件")

    if args.tables:
        error_count = run_tables_mode(files, args)
    else:
        error_count = run_text_mode(files, args)

    if error_count:
        print(f"\n共 {error_count} 个文件处理失败，请检查以上错误信息。")
        sys.exit(1)


if __name__ == "__main__":
    main()
