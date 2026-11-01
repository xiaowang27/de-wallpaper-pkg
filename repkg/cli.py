"""命令行入口。

用法示例：
    python -m repkg.cli extract E:\\path\\to\\scene.pkg -o ./output
    python -m repkg.cli extract -r E:\\steamapps\\workshop\\content\\123 -o ./out
    python -m repkg.cli convert E:\\path\\to\\texture.tex -o ./out
    python -m repkg.cli scan E:\\steamapps\\workshop\\content\\123
    python -m repkg.cli info E:\\path\\to\\scene.pkg
    python -m repkg.cli web

也可以直接在 IDE 里运行本文件（PyCharm: 右键 -> Run 'cli.py'），
此时会自动把项目根加入 sys.path。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 支持被直接执行（python repkg/cli.py 或 IDE 里 Run），此时相对导入不可用。
# 做法是把项目根（含 repkg/ 包目录的父目录）加入 sys.path，然后按绝对包路径导入。
if __package__ in (None, ""):
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    from repkg.core.extractor import ExtractOptions, Extractor
    from repkg.core.package import PackageReader
    from repkg.core.paths import resolve_out_dir
else:
    from .core.extractor import ExtractOptions, Extractor
    from .core.package import PackageReader
    from .core.paths import resolve_out_dir


def cmd_extract(args: argparse.Namespace) -> int:
    extractor = Extractor()
    options = ExtractOptions(
        output_dir=resolve_out_dir(args.output),
        ignore_exts=[e for e in (args.ignore_exts or "").split(",") if e],
        only_exts=[e for e in (args.only_exts or "").split(",") if e],
        single_dir=args.single_dir,
        convert_tex=not args.no_tex_convert,
        copy_project=args.copy_project,
        overwrite=args.overwrite,
        recursive=args.recursive,
        collect_media=not args.no_media,
    )

    target = Path(args.input).expanduser()
    if target.is_file():
        result = extractor.extract_package(target, options, log=print)
    elif target.is_dir():
        result = extractor.extract_directory(target, options, log=print)
    else:
        print(f"路径不存在: {target}")
        return 1

    print()
    print(f"输出目录: {options.output_dir}")
    print(
        f"解出文件 {len(result.files_written)} · 图片 {len(result.images_written)} "
        f"· 媒体 {len(result.media_files)} · 跳过 {len(result.skipped)}"
    )
    if result.media_files:
        print(f"图片/视频目录: {options.output_dir / 'media'}")
    for err in result.errors:
        print(f"  [错误] {err}")
    return 0 if result.ok else 1


def cmd_convert(args: argparse.Namespace) -> int:
    extractor = Extractor()
    target = Path(args.input).expanduser()
    out = resolve_out_dir(args.output)

    if target.is_dir():
        files = extractor.scan_tex_directory(target, recursive=args.recursive)
        if not files:
            print(f"{target} 下没有 .tex 文件")
            return 1
        for f in files:
            r = extractor.convert_tex_file(f, out)
            print(f"{'OK ' if r else '失败'} {f.name}")
        return 0

    result = extractor.convert_tex_file(target, out)
    if result is None:
        return 1
    print(f"已输出: {out / (target.stem + '.' + result.extension)}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    extractor = Extractor()
    target = Path(args.input).expanduser()
    packages = extractor.scan_directory(target, recursive=args.recursive)
    print(f"找到 {len(packages)} 个 .pkg：")
    for p in packages:
        print(f"  {p}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    reader = PackageReader()
    target = Path(args.input).expanduser()
    package = reader.read_file(target, read_entry_bytes=False)

    print(f"magic: {package.magic}")
    print(f"header_size: {package.header_size}")
    print(f"entries: {len(package.entries)}")
    print()
    for entry in package.entries:
        print(f"  {entry.full_path:<50} {entry.length:>10} B  {entry.entry_type.name.lower()}")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("缺少 uvicorn，请先 pip install uvicorn")
        return 1

    from .web.app import app

    print(f"启动 Web 服务: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repkg", description="Wallpaper Engine PKG/TEX 解包工具"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="解包 PKG")
    p_extract.add_argument("input", help="PKG 文件或目录")
    p_extract.add_argument(
        "-o", "--output", default=None,
        help="输出目录（默认 <项目根>/out）",
    )
    p_extract.add_argument("-i", "--ignoreexts", help="排除的扩展名（逗号分隔）")
    p_extract.add_argument("-e", "--onlyexts", help="只保留的扩展名（逗号分隔）")
    p_extract.add_argument("-s", "--singledir", action="store_true", help="全部文件放同一目录")
    p_extract.add_argument("-c", "--copyproject", action="store_true", help="复制 project.json 和预览图")
    p_extract.add_argument("--no-tex-convert", action="store_true", help="不转换 TEX")
    p_extract.add_argument("--no-media", action="store_true", help="不收集图片/视频到 media/ 目录")
    p_extract.add_argument("--overwrite", action="store_true", help="覆盖已有文件")
    p_extract.add_argument("-r", "--recursive", action="store_true", default=True, help="递归扫描")
    p_extract.set_defaults(func=cmd_extract)

    p_convert = sub.add_parser("convert", help="TEX 转图片")
    p_convert.add_argument("input", help="TEX 文件或目录")
    p_convert.add_argument(
        "-o", "--output", default=None,
        help="输出目录（默认 <项目根>/out）",
    )
    p_convert.add_argument("-r", "--recursive", action="store_true", default=True)
    p_convert.set_defaults(func=cmd_convert)

    p_scan = sub.add_parser("scan", help="扫描目录中的 PKG")
    p_scan.add_argument("input", help="目录")
    p_scan.add_argument("-r", "--recursive", action="store_true", default=True)
    p_scan.set_defaults(func=cmd_scan)

    p_info = sub.add_parser("info", help="查看 PKG 信息")
    p_info.add_argument("input", help="PKG 文件")
    p_info.set_defaults(func=cmd_info)

    p_web = sub.add_parser("web", help="启动 Web 服务")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8000)
    p_web.add_argument("--reload", action="store_true", help="开发模式（热重载）")
    p_web.set_defaults(func=cmd_web)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
