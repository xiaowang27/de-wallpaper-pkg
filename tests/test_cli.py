"""CLI 测试。

之前测试只覆盖了库层和 Web 层，CLI 完全没测 —— 导致 `extract` 命令
因 argparse 属性名不匹配（--ignoreexts -> args.ignoreexts vs args.ignore_exts）
而全线崩溃，却一直没人发现。
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest
from PIL import Image

from repkg.cli import build_parser, main


def _make_pkg(path: Path) -> Path:
    """造一个含 PNG 贴图和 .json 的 PKG。"""
    buf = io.BytesIO()
    Image.new("RGBA", (16, 8), (10, 200, 100, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    tex = io.BytesIO()
    tex.write(b"TEXV0005\x00")
    tex.write(b"TEXI0001\x00")
    tex.write(struct.pack("<iiiiiiI", 0, 0, 16, 8, 16, 8, 0))
    tex.write(b"TEXB0003\x00")
    tex.write(struct.pack("<i", 1))
    tex.write(struct.pack("<i", 13))
    tex.write(struct.pack("<i", 1))
    tex.write(struct.pack("<ii", 16, 8))
    tex.write(struct.pack("<i", 0))
    tex.write(struct.pack("<i", 0))
    tex.write(struct.pack("<i", len(png)))
    tex.write(png)

    from repkg.core.package import Package, PackageEntry, PackageWriter

    package = Package(magic="PKGV0005")
    package.entries.append(
        PackageEntry(full_path="materials/bg.tex", data=tex.getvalue())
    )
    package.entries.append(
        PackageEntry(full_path="scene.json", data=b'{"type":"scene"}')
    )
    PackageWriter().write_file(path, package)
    return path


@pytest.fixture
def pkg(tmp_path):
    return _make_pkg(tmp_path / "scene.pkg")


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------


def test_parser_dest_names_match_code():
    """argparse 的 dest 必须与 cmd_* 里读取的属性名一致。

    --ignoreexts 默认会变成 args.ignoreexts，但代码读的是 args.ignore_exts，
    不显式指定 dest 就会 AttributeError。
    """
    args = build_parser().parse_args(["extract", "x.pkg"])
    assert args.ignore_exts is None
    assert args.only_exts is None


def test_parser_accepts_ignore_and_only_exts():
    args = build_parser().parse_args(
        ["extract", "x.pkg", "-i", "tex,json", "-e", "tex"]
    )
    assert args.ignore_exts == "tex,json"
    assert args.only_exts == "tex"


def test_parser_long_options():
    args = build_parser().parse_args(
        ["extract", "x.pkg", "--ignoreexts", "tex", "--onlyexts", "json"]
    )
    assert args.ignore_exts == "tex"
    assert args.only_exts == "json"


def test_all_read_attributes_are_declared():
    """每个 cmd_* 里读取的 args.X 都必须有对应的 dest。

    argparse 默认用长选项名推导 dest（--singledir -> args.singledir），
    与代码里的 snake_case 读取名容易不一致，且崩溃发生在运行期才发现。
    这里做静态比对，把这类 bug 拦在测试阶段。
    """
    import argparse as ap
    import ast
    import inspect

    from repkg import cli

    # 1) 各 subcommand 实际声明的 dest
    parser = build_parser()
    sub_action = next(
        a for a in parser._actions if isinstance(a, ap._SubParsersAction)
    )
    declared = {
        name: {a.dest for a in sub._actions}
        for name, sub in sub_action.choices.items()
    }

    # 2) cmd_* 里读取的 args.X
    #    args.foo 在 AST 里是 Attribute(value=Name('args'), attr='foo')
    tree = ast.parse(inspect.getsource(cli))
    reads: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("cmd_"):
            attrs = {
                n.attr
                for n in ast.walk(node)
                if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name)
                and n.value.id == "args"
            }
            if attrs:
                reads[node.name] = attrs

    assert reads, "应能解析出 cmd_* 函数"

    missing = []
    for func_name, attrs in reads.items():
        cmd = func_name.replace("cmd_", "")
        avail = declared.get(cmd, set())
        for attr in sorted(attrs):
            if attr not in avail:
                missing.append(f"{func_name} 读取 args.{attr}，但 {cmd} 未声明该 dest")

    assert not missing, "argparse 属性名不匹配:\n" + "\n".join(missing)


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------


def test_extract_command(tmp_path, pkg, capsys):
    """extract 必须能真正跑通（曾经因属性名不匹配而崩溃）。"""
    out = tmp_path / "out"
    rc = main(["extract", str(pkg), "-o", str(out)])

    assert rc == 0
    assert out.exists()
    assert (out / "materials" / "bg.tex").exists()
    assert (out / "materials" / "bg.png").exists()
    assert (out / "media").is_dir()


def test_extract_with_ignore_exts(tmp_path, pkg):
    """-i 排除扩展名。"""
    out = tmp_path / "out"
    rc = main(["extract", str(pkg), "-o", str(out), "-i", "tex"])

    assert rc == 0
    assert (out / "scene.json").exists()
    assert not (out / "materials" / "bg.tex").exists()


def test_extract_with_only_exts(tmp_path, pkg):
    """-e 只保留指定扩展名。"""
    out = tmp_path / "out"
    rc = main(["extract", str(pkg), "-o", str(out), "-e", "tex"])

    assert rc == 0
    assert (out / "materials" / "bg.tex").exists()
    assert not (out / "scene.json").exists()


def test_extract_no_media_flag(tmp_path, pkg):
    """--no-media 不生成 media/ 目录。"""
    out = tmp_path / "out"
    rc = main(["extract", str(pkg), "-o", str(out), "--no-media"])

    assert rc == 0
    assert not (out / "media").exists()


def test_extract_missing_path(tmp_path):
    """不存在的路径应返回非 0，而不是抛异常。"""
    rc = main(["extract", str(tmp_path / "nope.pkg")])
    assert rc == 1


# --------------------------------------------------------------------------
# info / scan
# --------------------------------------------------------------------------


def test_info_command(tmp_path, pkg, capsys):
    rc = main(["info", str(pkg)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "PKGV0005" in out
    assert "materials/bg.tex" in out


def test_scan_command(tmp_path, pkg, capsys):
    rc = main(["scan", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "scene.pkg" in out


def test_convert_command(tmp_path, capsys):
    """convert 把 .tex 转成图片。"""
    pkg = _make_pkg(tmp_path / "scene.pkg")
    from repkg.core.package import PackageReader

    tex_data = next(
        e.data for e in PackageReader().read_file(pkg).entries
        if e.full_path.endswith(".tex")
    )
    tex_path = tmp_path / "bg.tex"
    tex_path.write_bytes(tex_data)

    out_dir = tmp_path / "out"
    rc = main(["convert", str(tex_path), "-o", str(out_dir)])

    assert rc == 0
    assert (out_dir / "bg.png").exists()
