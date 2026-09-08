#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
excel_csv_converter.py
========================
Excel <-> CSV 互转小工具

功能：
1. split : 将一个 Excel 文件按 sheet 拆分为多个 CSV 文件（文件名 = sheet 名）
2. merge : 将一个文件夹下的多个 CSV 文件合并为一个 Excel 文件（sheet 名 = csv 文件名）

依赖：
    pip install pandas openpyxl

用法示例：
    # 拆分：把 data.xlsx 的每个 sheet 拆成一个 csv，输出到 ./output 目录
    python excel_csv_converter.py split data.xlsx -o ./output

    # 合并：把 ./csv_folder 下所有 csv 合并为 merged.xlsx
    python excel_csv_converter.py merge ./csv_folder -o merged.xlsx

    # 合并时指定编码 / 拆分时指定 CSV 编码
    python excel_csv_converter.py split data.xlsx -o ./output --encoding utf-8-sig
    python excel_csv_converter.py merge ./csv_folder -o merged.xlsx --encoding utf-8-sig
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd


# Excel sheet 名称非法字符：\ / ? * [ ] :，且长度不能超过 31
INVALID_SHEET_CHARS = r'[\\/\?\*\[\]:]'
MAX_SHEET_NAME_LEN = 31


def safe_filename(name: str) -> str:
    """将 sheet 名转换为安全的文件名（去掉 Windows/macOS 不允许的字符）"""
    invalid_chars = r'[\\/:*?"<>|]'
    cleaned = re.sub(invalid_chars, "_", name).strip()
    return cleaned if cleaned else "sheet"


def safe_sheet_name(name: str, used_names: set) -> str:
    """将文件名转换为安全且唯一的 Excel sheet 名（<=31字符，无非法字符）"""
    cleaned = re.sub(INVALID_SHEET_CHARS, "_", name).strip()
    if not cleaned:
        cleaned = "Sheet"
    cleaned = cleaned[:MAX_SHEET_NAME_LEN]

    # 处理重名：截断后加序号，保证不超过31字符且唯一
    original = cleaned
    suffix = 1
    while cleaned in used_names:
        suffix_str = f"_{suffix}"
        cleaned = original[: MAX_SHEET_NAME_LEN - len(suffix_str)] + suffix_str
        suffix += 1
    used_names.add(cleaned)
    return cleaned


def split_excel_to_csv(excel_path: str, output_dir: str, encoding: str = "utf-8-sig") -> None:
    """将 Excel 文件按 sheet 拆分为多个 CSV 文件"""
    excel_path = Path(excel_path)
    if not excel_path.exists():
        print(f"错误：找不到文件 {excel_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # sheet_name=None 表示读取所有 sheet，返回 dict[str, DataFrame]
        sheets = pd.read_excel(excel_path, sheet_name=None, engine="openpyxl")
    except Exception as e:
        print(f"错误：读取 Excel 文件失败 - {e}", file=sys.stderr)
        sys.exit(1)

    if not sheets:
        print("警告：该 Excel 文件不包含任何 sheet。")
        return

    used_filenames = set()
    for sheet_name, df in sheets.items():
        base_name = safe_filename(sheet_name)
        csv_name = base_name
        i = 1
        while csv_name in used_filenames:
            csv_name = f"{base_name}_{i}"
            i += 1
        used_filenames.add(csv_name)

        csv_path = out_dir / f"{csv_name}.csv"
        df.to_csv(csv_path, index=False, encoding=encoding)
        print(f"  [OK] sheet '{sheet_name}' -> {csv_path}  ({len(df)} 行)")

    print(f"\n完成：共拆分 {len(sheets)} 个 sheet，输出目录：{out_dir.resolve()}")


def merge_csv_to_excel(csv_dir: str, output_path: str, encoding: str = "utf-8-sig") -> None:
    """将一个目录下的所有 CSV 文件合并为一个 Excel 文件，每个 CSV 对应一个 sheet"""
    csv_dir_path = Path(csv_dir)

    if csv_dir_path.is_dir():
        csv_files = sorted(csv_dir_path.glob("*.csv"))
    elif csv_dir_path.is_file() and csv_dir_path.suffix.lower() == ".csv":
        # 也支持直接传单个 csv 文件（容错处理）
        csv_files = [csv_dir_path]
    else:
        print(f"错误：{csv_dir} 不是一个有效的目录或 CSV 文件", file=sys.stderr)
        sys.exit(1)

    if not csv_files:
        print(f"警告：目录 {csv_dir_path} 下没有找到任何 .csv 文件")
        return

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    used_sheet_names = set()
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file, encoding=encoding)
            except UnicodeDecodeError:
                # 常见于 GBK 编码的中文 csv，自动尝试兜底编码
                print(f"  [提示] {csv_file.name} 不是 {encoding} 编码，尝试使用 gbk 重新读取...")
                df = pd.read_csv(csv_file, encoding="gbk")

            sheet_name = safe_sheet_name(csv_file.stem, used_sheet_names)
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"  [OK] {csv_file.name} -> sheet '{sheet_name}'  ({len(df)} 行)")

    print(f"\n完成：共合并 {len(csv_files)} 个 CSV 文件，输出文件：{out_path.resolve()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Excel <-> CSV 互转工具：按 sheet 拆分 Excel 为多个 CSV，或将多个 CSV 合并为一个 Excel"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # split 子命令
    p_split = subparsers.add_parser("split", help="将 Excel 按 sheet 拆分为多个 CSV")
    p_split.add_argument("excel_file", help="源 Excel 文件路径 (.xlsx/.xls)")
    p_split.add_argument("-o", "--output", default="./output_csv", help="CSV 输出目录（默认 ./output_csv）")
    p_split.add_argument("--encoding", default="utf-8-sig", help="输出 CSV 编码（默认 utf-8-sig，Excel 打开中文不乱码）")

    # merge 子命令
    p_merge = subparsers.add_parser("merge", help="将多个 CSV 合并为一个 Excel（sheet 名 = csv 文件名）")
    p_merge.add_argument("csv_dir", help="包含多个 CSV 文件的目录（或单个 csv 文件）")
    p_merge.add_argument("-o", "--output", default="./merged.xlsx", help="输出 Excel 文件路径（默认 ./merged.xlsx）")
    p_merge.add_argument("--encoding", default="utf-8-sig", help="读取 CSV 时使用的编码（默认 utf-8-sig，若失败自动尝试 gbk）")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "split":
        print(f"开始拆分：{args.excel_file}")
        split_excel_to_csv(args.excel_file, args.output, args.encoding)
    elif args.command == "merge":
        print(f"开始合并：{args.csv_dir}")
        merge_csv_to_excel(args.csv_dir, args.output, args.encoding)


if __name__ == "__main__":
    main()
