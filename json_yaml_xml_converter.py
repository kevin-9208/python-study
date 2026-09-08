#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
json_yaml_xml_converter.py
============================
JSON / YAML / XML 格式互转与校验工具

功能：
1. validate : 校验单个文件的语法是否正确（json/yaml/xml），报错时给出具体行列位置
2. convert  : 在 JSON / YAML / XML 三种格式之间任意互转

依赖：
    pip install pyyaml xmltodict

用法示例：
    # 自动根据扩展名判断格式并校验
    python json_yaml_xml_converter.py validate config.json
    python json_yaml_xml_converter.py validate config.yaml
    python json_yaml_xml_converter.py validate config.xml

    # 扩展名不规范时手动指定格式
    python json_yaml_xml_converter.py validate data.txt --format yaml

    # 互转，格式默认由文件扩展名自动识别
    python json_yaml_xml_converter.py convert data.json data.yaml
    python json_yaml_xml_converter.py convert data.yaml data.xml
    python json_yaml_xml_converter.py convert data.xml data.json

    # JSON/YAML 转 XML 时，如果顶层不是单一 key 的字典（比如是列表），
    # 需要一个根标签把内容包起来，默认叫 "root"，可自定义：
    python json_yaml_xml_converter.py convert list.json list.xml --root-tag items

    # 手动指定输入/输出格式（不依赖扩展名）
    python json_yaml_xml_converter.py convert a.txt b.txt --from-format json --to-format yaml
"""

import argparse
import json
import sys
from pathlib import Path

import yaml
import xmltodict


SUPPORTED_FORMATS = ("json", "yaml", "xml")
EXT_TO_FORMAT = {
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
}


# ------------------------- 格式探测 -------------------------

def detect_format(path: str) -> str:
    """根据文件扩展名推断格式，无法识别时返回 None"""
    ext = Path(path).suffix.lower()
    return EXT_TO_FORMAT.get(ext)


def resolve_format(path: str, explicit_format: str, role: str) -> str:
    """确定文件的格式：优先用户显式指定，其次按扩展名推断，都不行则报错退出"""
    if explicit_format:
        return explicit_format
    fmt = detect_format(path)
    if fmt is None:
        print(
            f"错误：无法从文件名 '{path}' 推断{role}格式，"
            f"请用 --format / --from-format / --to-format 显式指定 ({'/'.join(SUPPORTED_FORMATS)})",
            file=sys.stderr,
        )
        sys.exit(1)
    return fmt


# ------------------------- 校验 -------------------------

def validate_json(text: str):
    """返回 (是否合法, 错误信息或None)"""
    try:
        json.loads(text)
        return True, None
    except json.JSONDecodeError as e:
        return False, f"JSON 语法错误：第 {e.lineno} 行第 {e.colno} 列 - {e.msg}"


def validate_yaml(text: str):
    try:
        yaml.safe_load(text)
        return True, None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            return False, f"YAML 语法错误：第 {mark.line + 1} 行第 {mark.column + 1} 列 - {getattr(e, 'problem', str(e))}"
        return False, f"YAML 语法错误：{e}"


def validate_xml(text: str):
    try:
        xmltodict.parse(text)
        return True, None
    except Exception as e:
        # xmltodict 底层用 expat，异常通常带 lineno/offset
        lineno = getattr(e, "lineno", None)
        offset = getattr(e, "offset", None)
        if lineno is not None:
            return False, f"XML 语法错误：第 {lineno} 行第 offset {offset} - {e}"
        return False, f"XML 语法错误：{e}"


VALIDATORS = {
    "json": validate_json,
    "yaml": validate_yaml,
    "xml": validate_xml,
}


def cmd_validate(args):
    path = Path(args.file)
    if not path.exists():
        print(f"错误：找不到文件 {path}", file=sys.stderr)
        sys.exit(1)

    fmt = resolve_format(str(path), args.format, "文件")
    text = path.read_text(encoding=args.encoding)

    is_valid, error = VALIDATORS[fmt](text)
    if is_valid:
        print(f"[通过] {path} 是合法的 {fmt.upper()}")
    else:
        print(f"[失败] {path} 不是合法的 {fmt.upper()}")
        print(f"  {error}")
        sys.exit(1)


# ------------------------- 加载 / 输出 -------------------------

def load_data(text: str, fmt: str):
    """把文本解析为 Python 对象 (dict / list / 基本类型)"""
    if fmt == "json":
        return json.loads(text)
    if fmt == "yaml":
        return yaml.safe_load(text)
    if fmt == "xml":
        # xmltodict.parse 返回 OrderedDict，保留原始的单一根标签
        return xmltodict.parse(text)
    raise ValueError(f"不支持的格式：{fmt}")


def dump_data(data, fmt: str, root_tag: str = "root") -> str:
    """把 Python 对象序列化为目标格式文本"""
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    if fmt == "yaml":
        return yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)

    if fmt == "xml":
        # xmltodict.unparse 要求最外层是恰好一个 key 的 dict（即XML的根元素），
        # 且这个 key 对应的值不能直接是 list（XML 的重复元素需要一个子标签名）。
        # 根据数据形状自动包裹：
        #   - dict 且只有一个 key           -> 直接作为根元素使用
        #   - list（顶层是数组）             -> <root_tag><item>...</item><item>...</item></root_tag>
        #   - 其他（多 key 的 dict / 标量）  -> <root_tag>...</root_tag>
        if isinstance(data, dict) and len(data) == 1:
            wrapped = data
        elif isinstance(data, list):
            wrapped = {root_tag: {"item": data}}
        else:
            wrapped = {root_tag: data}
        return xmltodict.unparse(wrapped, pretty=True, indent="  ") + "\n"

    raise ValueError(f"不支持的格式：{fmt}")


# ------------------------- 转换命令 -------------------------

def cmd_convert(args):
    in_path = Path(args.input)
    if not in_path.exists():
        print(f"错误：找不到文件 {in_path}", file=sys.stderr)
        sys.exit(1)

    from_fmt = resolve_format(str(in_path), args.from_format, "输入")
    to_fmt = resolve_format(str(args.output), args.to_format, "输出")

    text = in_path.read_text(encoding=args.encoding)

    # 转换前先校验，避免把错误的语法“转换”成看似正常的输出
    is_valid, error = VALIDATORS[from_fmt](text)
    if not is_valid:
        print(f"错误：输入文件不是合法的 {from_fmt.upper()}，已终止转换", file=sys.stderr)
        print(f"  {error}", file=sys.stderr)
        sys.exit(1)

    try:
        data = load_data(text, from_fmt)
        output_text = dump_data(data, to_fmt, root_tag=args.root_tag)
    except Exception as e:
        print(f"错误：转换过程中出错 - {e}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output_text, encoding=args.encoding)

    print(f"完成：{in_path} ({from_fmt.upper()}) -> {out_path} ({to_fmt.upper()})")


# ------------------------- CLI -------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="JSON / YAML / XML 格式互转与校验工具"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    p_validate = subparsers.add_parser("validate", help="校验文件语法是否合法")
    p_validate.add_argument("file", help="待校验的文件路径")
    p_validate.add_argument(
        "--format", choices=SUPPORTED_FORMATS, default=None,
        help="显式指定格式；不指定则根据扩展名 (.json/.yaml/.yml/.xml) 自动判断",
    )
    p_validate.add_argument("--encoding", default="utf-8", help="文件编码（默认 utf-8）")

    # convert
    p_convert = subparsers.add_parser("convert", help="在 JSON/YAML/XML 之间互相转换")
    p_convert.add_argument("input", help="输入文件路径")
    p_convert.add_argument("output", help="输出文件路径")
    p_convert.add_argument(
        "--from-format", choices=SUPPORTED_FORMATS, default=None,
        help="显式指定输入格式；不指定则根据输入文件扩展名自动判断",
    )
    p_convert.add_argument(
        "--to-format", choices=SUPPORTED_FORMATS, default=None,
        help="显式指定输出格式；不指定则根据输出文件扩展名自动判断",
    )
    p_convert.add_argument(
        "--root-tag", default="root",
        help="转换目标为 XML 且数据顶层不是单一根节点时，用于包裹数据的根标签名（默认 root）",
    )
    p_convert.add_argument("--encoding", default="utf-8", help="文件读写编码（默认 utf-8）")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "validate":
        cmd_validate(args)
    elif args.command == "convert":
        cmd_convert(args)


if __name__ == "__main__":
    main()
