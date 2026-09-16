#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ocr_tool.py
============
基于 pytesseract 的 OCR 文字识别工具

支持：
  - 单张图片 (jpg/png/bmp/tiff/webp...) 识别
  - 扫描版 PDF（把每一页渲染成图片再识别，不需要装 poppler，用 PyMuPDF 纯 pip 安装）
  - 整个文件夹批量识别（可递归子目录）
  - 简单预处理（灰度 + 二值化）以提升识别率
  - 结果输出：打印到终端 / 每个文件旁边生成同名 .txt / 全部合并写入一个文件

============================================================
环境准备（重要，请先看这里）
============================================================
pytesseract 只是调用系统里的 tesseract 引擎的一个"遥控器"，
必须先在系统上单独安装 tesseract 本体，pip 装不出来这个引擎。

1) 安装 Python 依赖：
    pip install pytesseract pillow pymupdf

2) 安装 tesseract 引擎本体 + 语言包：
    - Windows : 到 https://github.com/UB-Mannheim/tesseract/wiki 下载安装包
                安装时勾选 "Chinese (Simplified)" 语言包
                装完后如果命令行里输入 tesseract -v 提示找不到命令，
                用 --tesseract-cmd 参数指定 exe 路径，例如：
                --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
    - macOS   : brew install tesseract tesseract-lang
    - Ubuntu/Debian:
                sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
                (chi_sim 是简体中文语言包，按需再装 tesseract-ocr-chi-tra 繁体等)

3) 验证安装：
    tesseract --version
    tesseract --list-langs      # 查看已装的语言包，脚本默认用 chi_sim+eng

============================================================
用法示例
============================================================
    # 识别单张图片，结果打印到终端
    python ocr_tool.py photo.jpg

    # 识别单张图片，结果保存为同目录下的 photo.txt
    python ocr_tool.py photo.jpg --save

    # 识别扫描版 PDF 的所有页
    python ocr_tool.py scan.pdf --save

    # 只识别 PDF 的第 1-3 页和第 5 页
    python ocr_tool.py scan.pdf --pages 1-3,5

    # 批量识别一个文件夹里的所有图片/PDF（含子目录），每个文件结果分别保存
    python ocr_tool.py ./scans --recursive --save

    # 批量识别，但把所有结果合并写入一个文件
    python ocr_tool.py ./scans --recursive -o all_text.txt

    # 只识别英文，用官方文档打印级别的图片可以试试 psm 3（整页排版）
    python ocr_tool.py photo.jpg --lang eng --psm 3

    # 遇到光照不均/低对比度/带噪点的疑难扫描件，可以试试打开预处理看效果是否更好
    # （默认关闭：tesseract v4/5 内置处理通常已经足够，手动预处理对干净图片有时反而帮倒忙）
    python ocr_tool.py bad_scan.jpg --preprocess

    # 查看本机已安装的语言包
    python ocr_tool.py --list-langs

依赖：
    pip install pytesseract pillow pymupdf
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import pytesseract
    from PIL import Image, ImageOps, ImageFilter
except ImportError as e:
    print(f"缺少依赖库：{e.name if hasattr(e, 'name') else e}")
    print("请先运行：pip install pytesseract pillow pymupdf")
    sys.exit(1)

try:
    import pymupdf  # PyMuPDF，新版推荐用这个名字导入（旧版是 import fitz）
except ImportError:
    try:
        import fitz as pymupdf  # 兼容旧版 PyMuPDF
    except ImportError:
        pymupdf = None  # 没装也没关系，只是不能处理 PDF，用到时再报错


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp", ".gif"}
PDF_EXTS = {".pdf"}
DEFAULT_LANG = "chi_sim+eng"


# ============================================================
# 环境检查
# ============================================================

def check_tesseract(tesseract_cmd: str = None):
    """检查 tesseract 引擎是否可用，给出清晰的安装指引而不是甩一堆看不懂的报错"""
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    try:
        version = pytesseract.get_tesseract_version()
        return version
    except Exception:
        print("错误：找不到 tesseract 引擎，请先安装：")
        print("  Windows : https://github.com/UB-Mannheim/tesseract/wiki")
        print("            装完后用 --tesseract-cmd 指定 tesseract.exe 路径")
        print("  macOS   : brew install tesseract tesseract-lang")
        print("  Ubuntu  : sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim")
        sys.exit(1)


def list_langs():
    try:
        langs = pytesseract.get_languages()
        print("本机已安装的语言包：")
        for lang in langs:
            print(f"  - {lang}")
    except Exception as e:
        print(f"获取语言包列表失败：{e}")
        sys.exit(1)


# ============================================================
# 图像预处理
# ============================================================

def _otsu_threshold(histogram) -> int:
    """Otsu 大津法：根据灰度直方图自动算出最佳二值化阈值，比固定阈值更能适应不同光照/对比度的图片"""
    total = sum(histogram)
    if total == 0:
        return 128

    sum_total = sum(i * h for i, h in enumerate(histogram))
    sum_bg, weight_bg = 0.0, 0
    max_variance = 0.0
    best_threshold = 128

    for t in range(256):
        weight_bg += histogram[t]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break

        sum_bg += t * histogram[t]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg

        between_variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if between_variance > max_variance:
            max_variance = between_variance
            best_threshold = t

    return best_threshold


def preprocess_image(img: Image.Image) -> Image.Image:
    """灰度 + 轻度去噪 + 自动对比度 + Otsu 自适应二值化。
    比固定阈值更稳健：不同图片的最佳亮暗分界点由直方图自动计算得出，
    避免用一个写死的数字应付光照/扫描质量差异很大的图片；
    中值滤波对扫描件常见的椒盐噪点（小黑点/白点）有明显效果。
    """
    gray = img.convert("L")
    gray = gray.filter(ImageFilter.MedianFilter(size=3))
    gray = ImageOps.autocontrast(gray)
    threshold = _otsu_threshold(gray.histogram())
    binary = gray.point(lambda p: 255 if p > threshold else 0)
    return binary


# ============================================================
# 页码范围解析（用于 PDF）
# ============================================================

def parse_page_range(spec: str, total_pages: int):
    """把 '1-3,5' 这种字符串解析成从 0 开始的页码列表"""
    if not spec:
        return list(range(total_pages))

    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            for p in range(start, end + 1):
                pages.add(p)
        else:
            pages.add(int(part))

    # 用户输入的是从1开始的页码，转成从0开始的索引，并过滤越界的页码
    result = sorted(p - 1 for p in pages if 1 <= p <= total_pages)
    return result


# ============================================================
# 核心 OCR 逻辑
# ============================================================

def ocr_single_image(img: Image.Image, lang: str, preprocess: bool, psm: int) -> str:
    if preprocess:
        img = preprocess_image(img)
    config = f"--psm {psm}"
    text = pytesseract.image_to_string(img, lang=lang, config=config)
    return text.strip()


def ocr_image_file(path: Path, lang: str, preprocess: bool, psm: int, log=print) -> str:
    log(f"识别图片：{path.name}")
    img = Image.open(path)
    return ocr_single_image(img, lang, preprocess, psm)


def ocr_pdf_file(path: Path, lang: str, preprocess: bool, psm: int, dpi: int,
                  page_spec: str = None, log=print) -> str:
    if pymupdf is None:
        raise RuntimeError("处理 PDF 需要安装 PyMuPDF：pip install pymupdf")

    doc = pymupdf.open(str(path))
    total_pages = doc.page_count
    page_indices = parse_page_range(page_spec, total_pages)

    if not page_indices:
        log(f"警告：{path.name} 没有匹配到任何有效页码（共 {total_pages} 页），跳过")
        return ""

    zoom = dpi / 72.0  # PDF 默认 72 dpi，按目标 dpi 计算缩放比例
    matrix = pymupdf.Matrix(zoom, zoom)

    results = []
    for idx in page_indices:
        page = doc.load_page(idx)
        pix = page.get_pixmap(matrix=matrix)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        log(f"识别 {path.name} 第 {idx + 1}/{total_pages} 页...")
        text = ocr_single_image(img, lang, preprocess, psm)
        results.append(f"----- 第 {idx + 1} 页 -----\n{text}")

    doc.close()
    return "\n\n".join(results)


def ocr_file(path: Path, lang: str, preprocess: bool, psm: int, dpi: int,
             page_spec: str = None, log=print) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return ocr_image_file(path, lang, preprocess, psm, log=log)
    if ext in PDF_EXTS:
        return ocr_pdf_file(path, lang, preprocess, psm, dpi, page_spec, log=log)
    raise ValueError(f"不支持的文件类型：{ext}（支持 {sorted(IMAGE_EXTS | PDF_EXTS)}）")


# ============================================================
# 文件收集（单文件 / 目录批量）
# ============================================================

def collect_files(input_path: Path, recursive: bool):
    if input_path.is_file():
        return [input_path]

    if input_path.is_dir():
        all_exts = IMAGE_EXTS | PDF_EXTS
        pattern = "**/*" if recursive else "*"
        files = sorted(
            p for p in input_path.glob(pattern)
            if p.is_file() and p.suffix.lower() in all_exts
        )
        return files

    raise FileNotFoundError(f"路径不存在：{input_path}")


# ============================================================
# CLI
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="基于 pytesseract 的 OCR 文字识别工具（支持图片和扫描版 PDF）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", nargs="?", help="图片/PDF 文件路径，或包含它们的文件夹路径")
    parser.add_argument("-o", "--output", help="合并输出到指定文件（不指定则打印到终端，或配合 --save 逐文件保存）")
    parser.add_argument("--save", action="store_true", help="每个输入文件的识别结果保存为同名 .txt（与 -o 二选一）")
    parser.add_argument("--lang", default=DEFAULT_LANG, help=f"识别语言，默认 {DEFAULT_LANG}（简中+英文）。多语言用+连接，如 chi_sim+chi_tra+eng")
    parser.add_argument("--recursive", action="store_true", help="处理文件夹时递归子目录")
    parser.add_argument("--preprocess", dest="preprocess", action="store_true", default=False,
                         help="识别前做灰度+去噪+Otsu二值化预处理，默认关闭。"
                              "现代 tesseract(v4/5) 内置的处理通常已经足够好，"
                              "手动预处理对干净图片有时反而帮倒忙；"
                              "对光照不均/低对比度/带噪点的疑难扫描件可以试试打开看效果是否更好")
    parser.add_argument("--no-preprocess", dest="preprocess", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--psm", type=int, default=6, help="tesseract 页面分割模式 (Page Segmentation Mode)，默认 6（假设是一段统一的文本块）。整页排版复杂可试 3，单行文字试 7")
    parser.add_argument("--dpi", type=int, default=300, help="PDF 转图片的渲染精度，默认 300，越高越清晰但越慢")
    parser.add_argument("--pages", help="仅处理 PDF 的指定页码，如 '1-3,5'（从1开始，不指定则处理全部页）")
    parser.add_argument("--tesseract-cmd", help="手动指定 tesseract 可执行文件路径（Windows 常用）")
    parser.add_argument("--list-langs", action="store_true", help="列出本机已安装的语言包后退出")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    check_tesseract(args.tesseract_cmd)

    if args.list_langs:
        list_langs()
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    if args.save and args.output:
        print("错误：--save 和 -o/--output 不能同时使用，请二选一", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)
    try:
        files = collect_files(input_path, args.recursive)
    except FileNotFoundError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    if not files:
        print("没有找到任何支持的图片或 PDF 文件。")
        return

    print(f"共找到 {len(files)} 个待识别文件，使用语言：{args.lang}")

    combined_parts = []
    error_count = 0

    for f in files:
        try:
            text = ocr_file(
                f, lang=args.lang, preprocess=args.preprocess,
                psm=args.psm, dpi=args.dpi, page_spec=args.pages,
            )
        except Exception as e:
            print(f"  [失败] {f.name}：{e}", file=sys.stderr)
            error_count += 1
            continue

        if args.save:
            txt_path = f.with_suffix(".txt")
            txt_path.write_text(text, encoding="utf-8")
            print(f"  [OK] {f.name} -> {txt_path.name}  ({len(text)} 字符)")
        elif args.output:
            combined_parts.append(f"===== {f} =====\n{text}")
            print(f"  [OK] {f.name}  ({len(text)} 字符)")
        else:
            print(f"\n===== {f} =====")
            print(text if text else "(未识别到文字)")

    if args.output and combined_parts:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n\n".join(combined_parts), encoding="utf-8")
        print(f"\n完成：结果已合并写入 {out_path}")

    if error_count:
        print(f"\n共 {error_count} 个文件识别失败，请检查以上错误信息。")
        sys.exit(1)


if __name__ == "__main__":
    main()
