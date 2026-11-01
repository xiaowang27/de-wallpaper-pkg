"""PKG 包的读取与写入。

PKG 是 Wallpaper Engine 的资源包，结构为「索引表 + 裸数据」：

    int32  magicLength
    bytes  magic[ magicLength ]
    int32  entryCount
    重复 entryCount 次:
        int32  pathLength
        bytes  path[ pathLength ]      (UTF-8)
        int32  offset                  (相对 body 起点！)
        int32  length
    == body 起点 ==
    bytes  entry[0].data[ length ]
    bytes  entry[1].data[ length ]
    ...

关键点：entry 的 offset 是相对 body 起点（header 结束处），不是文件开头。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterator, Sequence

from .enums import EntryType, entry_type_from_filename


@dataclass
class PackageEntry:
    """包内的一个文件。"""

    full_path: str
    data: bytes = b""
    offset: int = 0
    length: int = 0
    entry_type: EntryType = EntryType.BINARY

    @property
    def name(self) -> str:
        """不含扩展名的文件名。"""
        return _posix_path(self.full_path)[1]

    @property
    def extension(self) -> str:
        """含点号的扩展名，如 '.tex'。"""
        return _posix_path(self.full_path)[2]

    @property
    def directory_path(self) -> str:
        """所在目录（不含文件名）。

        PKG 内部路径统一使用正斜杠，这里也保持一致，避免 Windows 上
        Path.parent 产生反斜杠导致行为差异。
        """
        return _posix_path(self.full_path)[0]


def _posix_path(path: str) -> tuple[str, str, str]:
    """把路径拆成 (目录, 不含扩展名的文件名, 含点号的扩展名)。

    同时识别正斜杠和反斜杠作为分隔符，输出统一为正斜杠。
    """
    normalized = path.replace("\\", "/")
    directory, _, filename = normalized.rpartition("/")

    stem = filename
    extension = ""
    dot = filename.rfind(".")
    if dot > 0:
        stem = filename[:dot]
        extension = filename[dot:]
    else:
        stem = filename

    return directory, stem, extension


@dataclass
class Package:
    """一个 PKG 包。"""

    magic: str = "PKGV0005"
    header_size: int = 0
    entries: list[PackageEntry] = field(default_factory=list)

    def get(self, full_path: str) -> PackageEntry | None:
        for entry in self.entries:
            if entry.full_path == full_path:
                return entry
        return None

    def __iter__(self) -> Iterator[PackageEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


class PackageReader:
    """PKG 读取器。"""

    MAGIC_MAX_LENGTH = 32
    PATH_MAX_LENGTH = 255

    def read_from(self, stream: BinaryIO, read_entry_bytes: bool = True) -> Package:
        """从流中读取一个包。

        Args:
            stream: 二进制流，定位在包起始位置。
            read_entry_bytes: 是否把 entry 数据读进内存。False 时只读索引。
        """
        package_start = stream.tell()

        magic = self._read_string_i32(stream, self.MAGIC_MAX_LENGTH)
        package = Package(magic=magic)

        entry_count = struct.unpack("<i", stream.read(4))[0]
        if entry_count < 0:
            raise ValueError(f"entry 数量为负数: {entry_count}")

        for _ in range(entry_count):
            full_path = self._read_string_i32(stream, self.PATH_MAX_LENGTH)
            offset, length = struct.unpack("<ii", stream.read(8))
            package.entries.append(
                PackageEntry(
                    full_path=full_path,
                    offset=offset,
                    length=length,
                    entry_type=entry_type_from_filename(full_path),
                )
            )

        data_start = stream.tell()
        package.header_size = data_start - package_start

        if read_entry_bytes:
            self._populate_entries(package.entries, data_start, stream)

        return package

    def read_file(self, path: str | Path, read_entry_bytes: bool = True) -> Package:
        """从文件路径读取一个包。"""
        with open(path, "rb") as f:
            return self.read_from(f, read_entry_bytes=read_entry_bytes)

    def _populate_entries(self, entries: Sequence[PackageEntry], data_start: int, stream: BinaryIO) -> None:
        for entry in entries:
            stream.seek(entry.offset + data_start)
            data = stream.read(entry.length)
            if len(data) != entry.length:
                raise ValueError(
                    f"entry '{entry.full_path}' 数据不完整: 期望 {entry.length} 字节, 实际 {len(data)}"
                )
            entry.data = data

    @staticmethod
    def _read_string_i32(stream: BinaryIO, max_length: int = -1) -> str:
        """读取 int32 长度前缀 + UTF-8 字节的字符串。"""
        size = struct.unpack("<i", stream.read(4))[0]
        if max_length > -1:
            size = min(size, max_length)
        if size < 0:
            raise ValueError("字符串长度不能为负数")
        raw = stream.read(size)
        return raw.decode("utf-8", errors="replace")


class PackageWriter:
    """PKG 写入器。

    写入时会把 entry.offset 回填为相对 body 起点的偏移。
    """

    def write_to(self, stream: BinaryIO, package: Package) -> None:
        if not package.entries:
            raise ValueError("包内没有 entry")

        self._write_string_i32(stream, package.magic)
        self._write_entries_header(package.entries, stream)
        self._write_body(package.entries, stream)

    def write_file(self, path: str | Path, package: Package) -> None:
        with open(path, "wb") as f:
            self.write_to(f, package)

    def _write_entries_header(self, entries: Sequence[PackageEntry], stream: BinaryIO) -> None:
        stream.write(struct.pack("<i", len(entries)))

        current_offset = 0
        for entry in entries:
            if not entry.full_path:
                raise ValueError("entry 的 full_path 为空")
            if entry.data is None:
                raise ValueError("entry 的 data 为 None")

            self._write_string_i32(stream, entry.full_path)
            stream.write(struct.pack("<ii", current_offset, len(entry.data)))

            entry.offset = current_offset
            entry.length = len(entry.data)
            current_offset += len(entry.data)

    def _write_body(self, entries: Sequence[PackageEntry], stream: BinaryIO) -> None:
        for entry in entries:
            stream.write(entry.data)

    @staticmethod
    def _write_string_i32(stream: BinaryIO, text: str) -> None:
        """写入 int32 长度前缀 + UTF-8 字节。

        注意：长度前缀必须是**字节数**而不是字符数，否则非 ASCII 路径会损坏整个包。
        （C# 原版 WriteStringI32Size 写的是 input.Length，是个 bug，此处已修正。）
        """
        raw = text.encode("utf-8")
        stream.write(struct.pack("<i", len(raw)))
        stream.write(raw)
