"""Web 层测试：删除 / 文件管理器 / 剪贴板。

用 FastAPI 的 TestClient，无需真实起服务。
"""
from __future__ import annotations

import io
import pathlib
import struct

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from repkg.core.package import Package, PackageEntry, PackageWriter


def _make_pkg_bytes() -> bytes:
    """造一个含 PNG 贴图的 PKG（内存字节）。"""
    buf = io.BytesIO()
    Image.new("RGBA", (32, 16), (10, 200, 100, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    tex = io.BytesIO()
    tex.write(b"TEXV0005\x00")
    tex.write(b"TEXI0001\x00")
    tex.write(struct.pack("<iiiiiiI", 0, 0, 32, 16, 32, 16, 0))
    tex.write(b"TEXB0003\x00")
    tex.write(struct.pack("<i", 1))       # imageCount
    tex.write(struct.pack("<i", 13))      # imageFormat = PNG
    tex.write(struct.pack("<i", 1))       # mipmapCount
    tex.write(struct.pack("<ii", 32, 16))
    tex.write(struct.pack("<i", 0))       # not lz4
    tex.write(struct.pack("<i", 0))       # decompressed count
    tex.write(struct.pack("<i", len(png)))
    tex.write(png)

    package = Package(magic="PKGV0005")
    package.entries.append(
        PackageEntry(full_path="materials/bg.tex", data=tex.getvalue())
    )
    out = io.BytesIO()
    PackageWriter().write_to(out, package)
    return out.getvalue()


@pytest.fixture
def client():
    from repkg.web.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def pkg_bytes():
    return _make_pkg_bytes()


def _upload(client, pkg_bytes, name="scene.pkg") -> str:
    r = client.post(
        "/api/upload",
        files={"file": (name, pkg_bytes, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


# --------------------------------------------------------------------------
# 删除
# --------------------------------------------------------------------------


def test_delete_single_project(client, pkg_bytes):
    pid = _upload(client, pkg_bytes)

    r = client.post("/api/projects/delete", data={"ids": pid, "delete_files": "false"})
    assert r.status_code == 200
    assert r.json()["deleted_count"] == 1

    ids = [p["id"] for p in client.get("/api/projects").json()["projects"]]
    assert pid not in ids


def test_delete_multiple_projects(client, pkg_bytes):
    """多选删除。"""
    ids = [_upload(client, pkg_bytes, f"m{i}.pkg") for i in range(3)]

    r = client.post(
        "/api/projects/delete",
        data={"ids": ",".join(ids[:2]), "delete_files": "false"},
    )
    assert r.json()["deleted_count"] == 2

    remaining = {p["id"] for p in client.get("/api/projects").json()["projects"]}
    assert ids[2] in remaining
    assert ids[0] not in remaining
    assert ids[1] not in remaining


def test_delete_unknown_id(client):
    r = client.post(
        "/api/projects/delete", data={"ids": "nope", "delete_files": "false"}
    )
    assert r.status_code == 200
    assert r.json()["deleted_count"] == 0
    assert r.json()["not_found"] == ["nope"]


def test_delete_rejects_empty_ids(client):
    r = client.post(
        "/api/projects/delete", data={"ids": ",,,", "delete_files": "false"}
    )
    assert r.status_code == 400


def test_delete_removes_extracted_files(client, pkg_bytes):
    """勾选删除文件时，解包产物应从磁盘移除。"""
    pid = _upload(client, pkg_bytes)

    r = client.post(f"/api/extract/{pid}", data={"output_dir": ""})
    out_dir = pathlib.Path(r.json()["output_dir"])
    assert out_dir.exists()

    r = client.post(
        "/api/projects/delete", data={"ids": pid, "delete_files": "true"}
    )
    assert r.json()["deleted"][0]["removed_files"] > 0
    assert not out_dir.exists()


def test_delete_keeps_files_when_not_requested(client, pkg_bytes):
    """不勾选删除文件时，只从列表移除，磁盘文件保留。"""
    pid = _upload(client, pkg_bytes)
    r = client.post(f"/api/extract/{pid}", data={"output_dir": ""})
    out_dir = pathlib.Path(r.json()["output_dir"])

    client.post("/api/projects/delete", data={"ids": pid, "delete_files": "false"})
    assert out_dir.exists()


# --------------------------------------------------------------------------
# 文件管理器 / 剪贴板
# --------------------------------------------------------------------------


def test_reveal_missing_path(client):
    """不存在的路径应返回失败而非崩溃。"""
    r = client.post("/api/reveal", data={"path": "Z:/nonexistent/x.png"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_copy_to_clipboard(client):
    r = client.post("/api/copy", data={"text": "E:/some/path.png"})
    assert r.status_code == 200
    assert "message" in r.json()


def test_media_download_and_listing(client, pkg_bytes):
    """解包后媒体可下载，且带 attachment 头。"""
    pid = _upload(client, pkg_bytes)
    r = client.post(f"/api/extract/{pid}", data={"output_dir": ""})
    media = r.json()["media"]
    assert len(media) == 1

    # media 项应带上绝对路径（供「在文件夹中显示」使用）
    assert pathlib.Path(media[0]["path"]).exists()

    r = client.get(media[0]["url"])
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_media_path_traversal_rejected(client, pkg_bytes):
    """媒体下载接口不允许跳出 media/ 目录。"""
    pid = _upload(client, pkg_bytes)
    client.post(f"/api/extract/{pid}", data={"output_dir": ""})

    r = client.get(f"/api/media/{pid}/..%2F..%2Fapp.py")
    assert r.status_code in (400, 404)
