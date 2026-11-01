"""媒体收集（media/ 目录）的行为测试。"""
from __future__ import annotations

import pathlib

from repkg.core.extractor import ExtractOptions, Extractor
from repkg.core.package import Package, PackageEntry, PackageWriter


def _make_pkg(tmp_path: pathlib.Path, name: str = "scene.pkg") -> pathlib.Path:
    """造一个含 mp4 和二进制文件的 PKG。"""
    package = Package(magic="PKGV0005")
    package.entries.append(
        PackageEntry(full_path="video/bg.mp4", data=b"\x00\x00\x00\x18ftypmp42" + bytes(2048))
    )
    package.entries.append(
        PackageEntry(full_path="data/x.bin", data=bytes(512))
    )
    pkg_path = tmp_path / name
    PackageWriter().write_file(pkg_path, package)
    return pkg_path


def test_media_collects_embedded_media(tmp_path):
    """包内自带的 mp4 也要被收集到 media/。"""
    pkg = _make_pkg(tmp_path)
    out = tmp_path / "out"

    result = Extractor().extract_package(
        pkg, ExtractOptions(output_dir=out, overwrite=True)
    )

    media = result.media_files
    assert len(media) == 1
    assert media[0].name == "video_bg.mp4"
    assert media[0].exists()


def test_media_flat_name_uses_posix_separator(tmp_path):
    """扁平命名用下划线替换路径分隔符。"""
    pkg = _make_pkg(tmp_path)
    out = tmp_path / "out"

    result = Extractor().extract_package(
        pkg, ExtractOptions(output_dir=out, overwrite=True)
    )

    assert result.media_files[0].name == "video_bg.mp4"
    assert "/" not in result.media_files[0].name


def test_media_uses_hardlink_not_copy(tmp_path):
    """media/ 里的文件应为硬链接（零额外磁盘占用），而非完整副本。

    4K 视频壁纸单个 mp4 可达数百 MB，复制一份会白白翻倍占用磁盘。
    """
    pkg = _make_pkg(tmp_path)
    out = tmp_path / "out"

    result = Extractor().extract_package(
        pkg, ExtractOptions(output_dir=out, overwrite=True)
    )

    source = out / "video" / "bg.mp4"
    media = result.media_files[0]

    assert source.exists()
    assert media.exists()

    s, m = source.stat(), media.stat()
    assert s.st_ino == m.st_ino, "media 文件应是硬链接（共享 inode）"
    assert m.st_nlink >= 2

    # 硬链接语义：删掉源，副本依然完好
    source.unlink()
    assert media.exists()
    assert media.stat().st_size == m.st_size


def test_media_disabled(tmp_path):
    """collect_media=False 时不生成 media/ 目录。"""
    pkg = _make_pkg(tmp_path)
    out = tmp_path / "out"

    result = Extractor().extract_package(
        pkg, ExtractOptions(output_dir=out, overwrite=True, collect_media=False)
    )

    assert not result.media_files
    assert not (out / "media").exists()


def test_non_media_entries_not_collected(tmp_path):
    """非媒体文件（.bin/.json）不该进 media/。"""
    pkg = _make_pkg(tmp_path)
    out = tmp_path / "out"

    result = Extractor().extract_package(
        pkg, ExtractOptions(output_dir=out, overwrite=True)
    )

    names = [m.name for m in result.media_files]
    assert "data_x.bin" not in names
