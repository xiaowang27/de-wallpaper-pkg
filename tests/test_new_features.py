"""新功能测试：解包进度、分类筛选、目录历史、元数据解析。"""
from __future__ import annotations

import io
import json
import pathlib
import struct
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from repkg.core.history import (
    HISTORY_FILE,
    add_directory,
    clear,
    list_directories,
    remove_directory,
)
from repkg.core.metadata import parse_project_json
from repkg.core.package import Package, PackageEntry, PackageWriter


def _pkg_bytes(extra_entries: int = 0) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (32, 16), (10, 200, 100, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    tex = io.BytesIO()
    tex.write(b"TEXV0005\x00")
    tex.write(b"TEXI0001\x00")
    tex.write(struct.pack("<iiiiiiI", 0, 0, 32, 16, 32, 16, 0))
    tex.write(b"TEXB0003\x00")
    tex.write(struct.pack("<i", 1))
    tex.write(struct.pack("<i", 13))
    tex.write(struct.pack("<i", 1))
    tex.write(struct.pack("<ii", 32, 16))
    tex.write(struct.pack("<i", 0))
    tex.write(struct.pack("<i", 0))
    tex.write(struct.pack("<i", len(png)))
    tex.write(png)

    package = Package(magic="PKGV0005")
    package.entries.append(PackageEntry(full_path="materials/bg.tex", data=tex.getvalue()))
    for i in range(extra_entries):
        package.entries.append(
            PackageEntry(full_path=f"data/f{i:03d}.bin", data=bytes(128))
        )
    out = io.BytesIO()
    PackageWriter().write_to(out, package)
    return out.getvalue()


@pytest.fixture
def client():
    from repkg.web.app import app

    with TestClient(app) as c:
        yield c


def _extract(client, pid) -> dict:
    """启动解包任务并等待完成，返回最终的任务状态。"""
    r = client.post(f"/api/extract/{pid}", data={"output_dir": ""})
    assert r.status_code == 200, r.text
    task_id = r.json()["task_id"]

    for _ in range(400):
        tr = client.get(f"/api/task/{task_id}").json()["task"]
        if tr["finished"]:
            return tr
        time.sleep(0.02)

    raise AssertionError("解包任务超时未完成")


# --------------------------------------------------------------------------
# 元数据解析
# --------------------------------------------------------------------------


def test_meta_parses_real_sample():
    """真实素材的 project.json 应能解析出分级与类型。"""
    sample = pathlib.Path(__file__).resolve().parent.parent / "tests" / "3276927533" / "scene.pkg"
    from repkg.core.metadata import read_meta

    meta = read_meta(sample)
    assert meta.kind == "scene"
    assert meta.content_rating == "Everyone"
    assert meta.rating_sex == "none"
    assert "Anime" in meta.tags
    assert meta.kind_label == "场景"
    assert meta.rating_label == "所有人"


def test_meta_handles_properties_as_list():
    """general.properties 是列表时的解析。"""
    data = {
        "type": "scene",
        "contentrating": "Teen",
        "general": {"properties": [
            {"type": "bool", "text": "阳光", "value": True},
            {"type": "bool", "text": "雨天", "value": False},
        ]},
    }
    meta = parse_project_json(data)
    assert len(meta.properties) == 2
    assert meta.properties[0]["text"] == "阳光"
    assert meta.content_rating == "Teen"


def test_meta_handles_properties_as_dict():
    """general.properties 是字典时的解析（真实样本就是这种）。

    Wallpaper Engine 不同版本写出的格式不一致，两种都要支持。
    """
    data = {
        "type": "scene",
        "general": {"properties": {
            "newproperty": {"index": 0, "text": "阳光", "type": "bool", "value": True},
        }},
    }
    meta = parse_project_json(data)
    assert len(meta.properties) == 1
    assert meta.properties[0]["text"] == "阳光"


def test_meta_handles_missing_fields():
    """字段缺失时不应崩溃。"""
    meta = parse_project_json({})
    assert meta.kind == ""
    assert meta.tags == []
    assert meta.kind_label == "未知"


def test_meta_handles_bad_input():
    """非字典输入应安全返回空。"""
    assert parse_project_json(None).kind == ""
    assert parse_project_json([]).kind == ""
    assert parse_project_json("x").kind == ""


def test_meta_normalizes_kind_case():
    """真实素材里 scene 和 Scene 都存在，应归一化成同一个。

    不归一化的话筛选框会出现两个几乎一样的选项。
    """
    assert parse_project_json({"type": "scene"}).kind == "scene"
    assert parse_project_json({"type": "Scene"}).kind == "scene"
    assert parse_project_json({"type": "SCENE"}).kind == "scene"
    assert parse_project_json({"type": "Video"}).kind == "video"
    assert parse_project_json({"type": "Web"}).kind == "web"


def test_meta_normalizes_rating():
    """分级大小写归一化，未知值保留原样。"""
    assert parse_project_json({"contentrating": "everyone"}).content_rating == "Everyone"
    assert parse_project_json({"contentrating": "MATURE"}).content_rating == "Mature"
    assert parse_project_json({"contentrating": "Questionable"}).content_rating == "Questionable"
    # 未知分级保留原样，不丢信息
    assert parse_project_json({"contentrating": "Whatever"}).content_rating == "Whatever"


def test_meta_kind_label_covers_web():
    """网页类型也要有中文名。"""
    from repkg.core.metadata import TYPE_LABELS

    assert TYPE_LABELS["web"] == "网页"
    assert parse_project_json({"type": "web"}).kind_label == "网页"


# --------------------------------------------------------------------------
# 解包进度
# --------------------------------------------------------------------------


def test_extract_returns_task_id(client):
    """解包应立即返回 task_id，而不是阻塞到结束。"""
    r = client.post(
        "/api/upload",
        files={"file": ("scene.pkg", _pkg_bytes(20), "application/octet-stream")},
    )
    pid = r.json()["project"]["id"]

    r = client.post(f"/api/extract/{pid}", data={"output_dir": ""})
    j = r.json()
    assert j["ok"] is True
    assert j["task_id"]
    assert "output_dir" in j


def test_task_progress_reaches_100(client):
    """任务进度应走到 100% 并标记完成。"""
    r = client.post(
        "/api/upload",
        files={"file": ("scene.pkg", _pkg_bytes(20), "application/octet-stream")},
    )
    pid = r.json()["project"]["id"]
    task_id = client.post(f"/api/extract/{pid}", data={"output_dir": ""}).json()["task_id"]

    for _ in range(400):
        tr = client.get(f"/api/task/{task_id}").json()["task"]
        if tr["finished"]:
            break
        time.sleep(0.02)

    assert tr["status"] == "done"
    assert tr["percent"] == 100
    assert tr["current"] == tr["total"]
    assert tr["total"] > 0
    assert tr["media_count"] >= 1


def test_task_not_found(client):
    """未知任务返回 404。"""
    r = client.get("/api/task/nope")
    assert r.status_code == 404


def test_task_logs_available(client):
    """任务日志可查。"""
    r = client.post(
        "/api/upload",
        files={"file": ("scene.pkg", _pkg_bytes(5), "application/octet-stream")},
    )
    pid = r.json()["project"]["id"]
    task_id = client.post(f"/api/extract/{pid}", data={"output_dir": ""}).json()["task_id"]

    for _ in range(400):
        tr = client.get(f"/api/task/{task_id}").json()["task"]
        if tr["finished"]:
            break
        time.sleep(0.02)

    logs = client.get(f"/api/task/{task_id}/logs").json()["logs"]
    assert len(logs) > 0


def test_active_tasks_endpoint(client):
    """进行中/已完成任务列表接口可用。"""
    r = client.get("/api/tasks")
    assert r.status_code == 200
    j = r.json()
    assert "running" in j
    assert "finished" in j
    assert isinstance(j["running"], list)
    assert isinstance(j["finished"], list)


def test_finished_tasks_include_media(client):
    """已完成任务应带上媒体清单，右侧栏可直接渲染下载按钮。"""
    r = client.post(
        "/api/upload",
        files={"file": ("scene.pkg", _pkg_bytes(), "application/octet-stream")},
    )
    pid = r.json()["project"]["id"]
    _extract(client, pid)

    j = client.get("/api/tasks").json()
    finished = [t for t in j["finished"] if t["project_id"] == pid]
    assert finished, "已完成任务应出现在 finished 列表"
    assert finished[0]["media_count"] >= 1
    assert finished[0]["media"][0]["url"]
    assert finished[0]["output_dir"]


# --------------------------------------------------------------------------
# 分类筛选
# --------------------------------------------------------------------------


def test_projects_include_meta(client):
    """工程列表应带上 meta 字段。"""
    r = client.post(
        "/api/upload",
        files={"file": ("scene.pkg", _pkg_bytes(), "application/octet-stream")},
    )
    pid = r.json()["project"]["id"]
    proj = next(p for p in client.get("/api/projects").json()["projects"] if p["id"] == pid)
    assert "meta" in proj
    assert "kind" in proj["meta"]
    assert "content_rating" in proj["meta"]


def test_projects_filter_by_kind(client):
    """按类型筛选。"""
    r = client.get("/api/projects", params={"kind": "scene"})
    assert r.status_code == 200
    assert all(p["meta"]["kind"] == "scene" for p in r.json()["projects"])


def test_projects_filter_by_rating(client):
    """按内容分级筛选。"""
    r = client.get("/api/projects", params={"rating": "Everyone"})
    assert r.status_code == 200
    assert all(p["meta"]["content_rating"] == "Everyone" for p in r.json()["projects"])


def test_projects_filter_by_keyword(client):
    """按标题关键字筛选。"""
    r = client.get("/api/projects", params={"keyword": "不存在的关键字zzz"})
    assert r.status_code == 200
    assert r.json()["projects"] == []


def test_projects_expose_filter_options(client):
    """接口应返回可用的筛选项。"""
    r = client.get("/api/projects")
    j = r.json()
    assert "filters" in j
    assert "kinds" in j["filters"]
    assert "ratings" in j["filters"]
    assert "tags" in j["filters"]


def test_projects_total_is_unfiltered_count(client):
    """total 应是未筛选前的总数。"""
    r = client.get("/api/projects", params={"kind": "scene"})
    j = r.json()
    assert j["total"] >= len(j["projects"])


# --------------------------------------------------------------------------
# 目录历史
# --------------------------------------------------------------------------


@pytest.fixture
def clean_history():
    """确保测试结束后历史被还原。"""
    backup = HISTORY_FILE.read_text(encoding="utf-8") if HISTORY_FILE.exists() else None
    clear()
    yield
    if backup is not None:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(backup, encoding="utf-8")
    else:
        clear()


def test_history_add_and_list(clean_history):
    """添加目录后应出现在历史里。

    注意路径会被规范化为 Windows 形式（斜杠 -> 反斜杠），
    这样前端回填到输入框时是可直接使用的绝对路径。
    """
    add_directory("E:/test/path", count=5)
    entries = list_directories()
    assert len(entries) == 1
    assert entries[0]["path"] == str(pathlib.Path("E:/test/path"))
    assert entries[0]["count"] == 5


def test_history_dedupes(clean_history):
    """同一目录只保留一条，最新的在前。"""
    add_directory("E:/a")
    add_directory("E:/b")
    add_directory("E:/a", count=9)
    entries = list_directories()
    assert len(entries) == 2
    assert entries[0]["path"] == str(pathlib.Path("E:/a"))
    assert entries[0]["count"] == 9


def test_history_case_insensitive_dedup(clean_history):
    """Windows 路径不区分大小写，应视为同一目录。"""
    add_directory("E:/Test")
    add_directory("e:/test")
    assert len(list_directories()) == 1


def test_history_remove(clean_history):
    """移除历史条目。"""
    add_directory("E:/a")
    add_directory("E:/b")
    remove_directory("E:/a")
    entries = list_directories()
    assert len(entries) == 1
    assert entries[0]["path"] == str(pathlib.Path("E:/b"))


def test_history_persisted_to_disk(clean_history):
    """历史应落盘到 data/scan_history.json。"""
    add_directory("E:/persisted")
    assert HISTORY_FILE.exists()
    data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data[0]["path"] == str(pathlib.Path("E:/persisted"))


def test_history_api(client, clean_history):
    """历史接口可用。"""
    add_directory("E:/api_test", count=3)
    expected = str(pathlib.Path("E:/api_test"))

    r = client.get("/api/scan/history")
    assert r.status_code == 200
    assert any(e["path"] == expected for e in r.json()["history"])

    r = client.post("/api/scan/history/delete", data={"path": expected})
    assert r.status_code == 200
    assert not any(e["path"] == expected for e in r.json()["history"])
