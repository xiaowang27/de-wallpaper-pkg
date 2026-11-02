"""Web 层：FastAPI 应用。

提供：
    POST /api/upload      拖拽上传 .pkg（也支持 .tex）
    POST /api/scan        提交一个服务器端目录，自动递归扫描其中的 .pkg
    GET  /api/projects    列出已扫描/已上传的工程
    GET  /api/preview/{id} 返回预览图（PNG/GIF/MP4）
    GET  /api/entries/{id} 列出包内条目
    POST /api/extract/{id} 把工程解包到输出目录
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..core.converter import ConversionError, TexToImageConverter
from ..core.extractor import (
    ExtractOptions,
    Extractor,
    is_video_path,
    media_mime_type,
)
from ..core.history import add_directory, list_directories, remove_directory
from ..core.metadata import RATING_ORDER, WallpaperMeta, read_meta
from ..core.package import PackageReader
from ..core.paths import resolve_out_dir
from ..core.tasks import _tasks
from ..core.tex import TexError, TexReader
from .explorer import copy_to_clipboard, reveal_in_file_manager

app = FastAPI(title="RePKG Web", version="0.1.0")

# --------------------------------------------------------------------------
# 内存中的工程注册表
# --------------------------------------------------------------------------


@dataclass
class Project:
    """一个已导入的壁纸工程。"""

    id: str
    name: str
    source: str          # "upload" 或 "scan"
    pkg_path: Path
    added_at: datetime = field(default_factory=datetime.now)
    preview_path: Path | None = None
    preview_type: str | None = None   # png / gif / mp4
    entry_count: int = 0
    project_json: dict[str, Any] = field(default_factory=dict)
    output_dir: Path | None = None      # 解包输出目录
    media: list[dict[str, Any]] = field(default_factory=list)   # 解出的图片/视频
    meta: WallpaperMeta = field(default_factory=WallpaperMeta)  # 年龄分级/场景分类

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "added_at": self.added_at.isoformat(),
            "entry_count": self.entry_count,
            "has_preview": self.preview_path is not None,
            "preview_type": self.preview_type,
            "title": self.project_json.get("title", self.name),
            "description": self.project_json.get("description", ""),
            "author": self.project_json.get("author", ""),
            "output_dir": str(self.output_dir) if self.output_dir else "",
            "extracted": self.is_extracted(),
            "media": self.media,
            "meta": self.meta.to_dict(),
        }

    def is_extracted(self) -> bool:
        """是否已解包。

        output_dir 只在本次会话解包后才有值，服务重启后会丢失，
        所以这里按磁盘上的实际产物判断，保证标记始终准确。
        """
        if self.output_dir is not None and self.output_dir.exists():
            return True
        # 回退：按 <输出根>/<工程 id> 找
        candidate = OUTPUT_DIR / self.id
        return candidate.exists() and any(candidate.iterdir())


# 存储根目录
STORAGE_ROOT = Path(tempfile.gettempdir()) / "repkg_web_storage"
UPLOAD_DIR = STORAGE_ROOT / "uploads"
SCAN_DIR = STORAGE_ROOT / "scans"

#: 解包输出目录：<项目根>/out （与 CLI 保持一致）
OUTPUT_DIR = resolve_out_dir()
for _d in (UPLOAD_DIR, SCAN_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

_projects: dict[str, Project] = {}

_extractor = Extractor()
_tex_reader = TexReader()
_package_reader = PackageReader()
_converter = TexToImageConverter()


def _find_preview(pkg_path: Path) -> tuple[Path | None, str | None]:
    """在工程目录里找预览图：优先 project.json 指定的 preview，其次 preview.jpg/png。"""
    parent = pkg_path.parent

    preview_name = None
    project_json = parent / "project.json"
    if project_json.exists():
        try:
            data = json.loads(project_json.read_text(encoding="utf-8"))
            preview_name = data.get("preview")
        except (json.JSONDecodeError, OSError):
            pass

    if preview_name:
        candidate = parent / preview_name
        if candidate.exists():
            return candidate, candidate.suffix.lstrip(".").lower()

    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        candidate = parent / f"preview{ext}"
        if candidate.exists():
            return candidate, ext.lstrip(".").lower()

    return None, None


def _extract_tex_preview(pkg_path: Path) -> tuple[Path | None, str | None]:
    """从 PKG 里找 .tex 条目并转成图片作为预览。"""
    try:
        package = _package_reader.read_file(pkg_path)
    except Exception:
        return None, None

    for entry in package.entries:
        if not entry.full_path.lower().endswith(".tex"):
            continue
        try:
            tex = _tex_reader.read_bytes(entry.data)
            result = _converter.convert_to_image(tex)
        except (TexError, ConversionError, Exception):
            continue

        out = pkg_path.parent / f"__preview__{Path(entry.full_path).stem}.{result.extension}"
        try:
            out.write_bytes(result.data)
        except OSError:
            return None, None
        return out, result.extension

    return None, None


def _register(pkg_path: Path, source: str, name: str | None = None) -> Project:
    """把一个 PKG 注册为工程，并尝试生成预览。"""
    project_id = uuid.uuid4().hex[:12]

    project = Project(
        id=project_id,
        name=name or pkg_path.parent.name or pkg_path.stem,
        source=source,
        pkg_path=pkg_path,
    )

    # 读取 project.json（可能就在 PKG 旁边）
    project_json = pkg_path.parent / "project.json"
    if project_json.exists():
        try:
            project.project_json = json.loads(project_json.read_text(encoding="utf-8"))
            title = project.project_json.get("title")
            if title:
                project.name = str(title)
        except (json.JSONDecodeError, OSError):
            pass

    # 提取年龄分级 / 场景分类等元数据
    project.meta = read_meta(pkg_path)

    # 统计条目数
    try:
        package = _package_reader.read_file(pkg_path, read_entry_bytes=False)
        project.entry_count = len(package.entries)
    except Exception:
        project.entry_count = 0

    # 预览：先找现成的图片，否则从 PKG 内的 tex 生成
    preview, preview_type = _find_preview(pkg_path)
    if preview is None:
        preview, preview_type = _extract_tex_preview(pkg_path)

    project.preview_path = preview
    project.preview_type = preview_type

    _projects[project_id] = project
    return project


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    """拖拽上传 .pkg 或 .tex 文件。"""
    filename = file.filename or "upload.bin"
    suffix = Path(filename).suffix.lower()

    if suffix not in (".pkg", ".tex"):
        raise HTTPException(400, f"只支持 .pkg 或 .tex 文件，收到: {suffix or '无扩展名'}")

    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")

    work_dir = UPLOAD_DIR / uuid.uuid4().hex[:12]
    work_dir.mkdir(parents=True, exist_ok=True)
    saved = work_dir / Path(filename).name
    saved.write_bytes(data)

    if suffix == ".tex":
        # 单个 tex：转成图片后作为预览
        try:
            tex = _tex_reader.read_bytes(data)
            result = _converter.convert_to_image(tex)
        except (TexError, ConversionError) as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise HTTPException(400, f"TEX 解析失败: {exc}") from exc

        preview = work_dir / f"preview.{result.extension}"
        preview.write_bytes(result.data)
        project = Project(
            id=uuid.uuid4().hex[:12],
            name=Path(filename).stem,
            source="upload",
            pkg_path=saved,
            preview_path=preview,
            preview_type=result.extension,
            entry_count=1,
        )
        _projects[project.id] = project
        return JSONResponse({"ok": True, "project": project.to_dict()})

    # pkg：注册工程
    project = _register(saved, "upload")
    return JSONResponse({"ok": True, "project": project.to_dict()})


@app.post("/api/scan")
async def scan(directory: str = Form(...), recursive: bool = Form(True)) -> JSONResponse:
    """提交服务器端目录，递归扫描其中的所有 .pkg 并注册为工程。"""
    root = Path(directory).expanduser()
    if not root.exists():
        raise HTTPException(400, f"目录不存在: {root}")
    if not root.is_dir():
        raise HTTPException(400, f"不是目录: {root}")

    packages = _extractor.scan_directory(root, recursive=recursive)
    # 记入目录历史，方便下次直接选
    add_directory(root, count=len(packages))

    if not packages:
        return JSONResponse(
            {
                "ok": True,
                "count": 0,
                "projects": [],
                "message": "该目录下没有 .pkg 文件",
                "history": list_directories(),
            }
        )

    projects = []
    for pkg_path in packages:
        try:
            project = _register(pkg_path, "scan")
            projects.append(project.to_dict())
        except Exception as exc:
            print(f"注册失败 {pkg_path}: {exc}")

    return JSONResponse(
        {
            "ok": True,
            "count": len(projects),
            "projects": projects,
            "history": list_directories(),
        }
    )


@app.get("/api/scan/history")
async def scan_history() -> JSONResponse:
    """返回扫描目录历史。"""
    return JSONResponse({"ok": True, "history": list_directories()})


@app.post("/api/scan/history/delete")
async def delete_scan_history(path: str = Form(...)) -> JSONResponse:
    """从历史中删除一条记录。"""
    entries = remove_directory(path)
    return JSONResponse({"ok": True, "history": entries})


def _ordered(values: set[str], preferred: list[str]) -> list[str]:
    """按偏好顺序排序，已知项在前，未知项按字母序在后。"""
    known = [v for v in preferred if v in values]
    rest = sorted(v for v in values if v not in preferred)
    return known + rest


@app.get("/api/projects")
async def list_projects(
    kind: str | None = None,
    rating: str | None = None,
    tag: str | None = None,
    keyword: str | None = None,
) -> JSONResponse:
    """列出所有已注册的工程（支持按分类筛选）。

    Args:
        kind: 工程类型 scene / wallpaper / video。
        rating: 内容分级 Everyone / Teen / Adult。
        tag: 作者标签。
        keyword: 标题关键字。
    """
    projects = list(_projects.values())

    def matched(p: Project) -> bool:
        meta = p.meta
        if kind and meta.kind != kind:
            return False
        if rating and meta.content_rating != rating:
            return False
        if tag and tag not in meta.tags:
            return False
        if keyword:
            haystack = f"{p.name} {p.project_json.get('title', '')}".lower()
            if keyword.lower() not in haystack:
                return False
        return True

    filtered = [p for p in projects if matched(p)]

    # 汇总可用的筛选项，方便前端渲染下拉框
    # 按「已知顺序优先，未知在后」排序，保证下拉框顺序稳定可预期
    kinds = _ordered(
        {p.meta.kind for p in projects if p.meta.kind},
        ["scene", "wallpaper", "video", "web"],
    )
    ratings = _ordered(
        {p.meta.content_rating for p in projects if p.meta.content_rating},
        RATING_ORDER,
    )
    tags = sorted({t for p in projects for t in p.meta.tags}, key=str.lower)

    return JSONResponse(
        {
            "ok": True,
            "projects": [p.to_dict() for p in filtered],
            "total": len(projects),
            "filters": {"kinds": kinds, "ratings": ratings, "tags": tags},
        }
    )


@app.get("/api/preview/{project_id}")
async def preview(project_id: str) -> Response:
    """返回预览图。"""
    project = _projects.get(project_id)
    if project is None:
        raise HTTPException(404, "工程不存在")
    if project.preview_path is None or not project.preview_path.exists():
        raise HTTPException(404, "该工程没有预览图")

    media_type = media_mime_type(project.preview_path)
    return FileResponse(project.preview_path, media_type=media_type)


@app.get("/api/entries/{project_id}")
async def entries(project_id: str) -> JSONResponse:
    """列出包内条目。"""
    project = _projects.get(project_id)
    if project is None:
        raise HTTPException(404, "工程不存在")

    try:
        package = _package_reader.read_file(project.pkg_path, read_entry_bytes=False)
    except Exception as exc:
        raise HTTPException(500, f"读取 PKG 失败: {exc}") from exc

    return JSONResponse(
        {
            "ok": True,
            "magic": package.magic,
            "header_size": package.header_size,
            "entries": [
                {
                    "path": e.full_path,
                    "offset": e.offset,
                    "length": e.length,
                    "type": e.entry_type.name.lower(),
                }
                for e in package.entries
            ],
        }
    )


def _task_payload(task) -> dict[str, Any]:
    """任务的可序列化信息（含已解出的媒体清单）。

    完成后把 media 挂到任务上，这样右侧「已完成」列表能直接显示
    下载 / 复制路径按钮，不必再回查工程接口。
    """
    data = task.to_dict()

    if task.finished and task.result is not None:
        project = _projects.get(task.project_id)
        if project is not None:
            target = task.output_dir or (OUTPUT_DIR / project.name)
            media = [
                {
                    "name": path.name,
                    "kind": "video" if is_video_path(path) else "image",
                    "extension": path.suffix.lstrip(".").lower(),
                    "size": path.stat().st_size,
                    "path": str(path),
                    "url": f"/api/media/{project.id}/{path.name}",
                }
                for path in task.result.media_files
                if path.exists()
            ]
            project.output_dir = target
            project.media = media
            data["media"] = media
            data["media_count"] = len(media)

    return data


@app.post("/api/extract/{project_id}")
async def extract(
    project_id: str,
    output_dir: str | None = Form(None),
    single_dir: bool = Form(False),
    convert_tex: bool = Form(True),
    overwrite: bool = Form(False),
) -> JSONResponse:
    """启动解包任务（后台线程执行）。

    立即返回 task_id，进度通过 GET /api/task/{task_id} 查询。
    """
    project = _projects.get(project_id)
    if project is None:
        raise HTTPException(404, "工程不存在")

    out_root = Path(output_dir).expanduser().resolve() if output_dir else OUTPUT_DIR
    target = out_root / project.name if not single_dir else out_root

    options = ExtractOptions(
        output_dir=target,
        single_dir=single_dir,
        convert_tex=convert_tex,
        overwrite=overwrite,
        collect_media=True,
    )

    task = _tasks.create(project_id, project.name, project.pkg_path, options)
    return JSONResponse(
        {
            "ok": True,
            "task_id": task.id,
            "output_dir": str(target),
            "message": "解包任务已启动",
        }
    )


@app.get("/api/task/{task_id}")
async def task_status(task_id: str) -> JSONResponse:
    """查询解包任务进度。"""
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")

    return JSONResponse({"ok": True, "task": _task_payload(task)})


@app.get("/api/task/{task_id}/logs")
async def task_logs(task_id: str, limit: int = 200) -> JSONResponse:
    """获取任务日志。"""
    return JSONResponse({"ok": True, "logs": _tasks.get_logs(task_id, limit)})


@app.get("/api/tasks")
async def active_tasks() -> JSONResponse:
    """列出进行中（左侧栏）与已完成（右侧栏）的任务。"""
    return JSONResponse(
        {
            "ok": True,
            "running": [_task_payload(t) for t in _tasks.list_tasks()],
            "finished": [_task_payload(t) for t in _tasks.list_finished()],
        }
    )


@app.get("/api/media/{project_id}/{filename}")
async def download_media(project_id: str, filename: str) -> FileResponse:
    """下载解包出来的图片/视频。"""
    project = _projects.get(project_id)
    if project is None:
        raise HTTPException(404, "工程不存在")
    if project.output_dir is None:
        raise HTTPException(404, "该工程还没有解包")

    # 防路径穿越：只允许 media 目录下的直接子文件
    media_root = (project.output_dir / "media").resolve()
    target = (media_root / filename).resolve()

    if media_root not in target.parents:
        raise HTTPException(400, "非法文件名")
    if not target.is_file():
        raise HTTPException(404, "文件不存在")

    return FileResponse(
        target, media_type=media_mime_type(target), filename=target.name
    )


@app.get("/api/media/{project_id}")
async def list_media(project_id: str) -> JSONResponse:
    """列出该工程解包出来的所有图片/视频。"""
    project = _projects.get(project_id)
    if project is None:
        raise HTTPException(404, "工程不存在")

    return JSONResponse({"ok": True, "media": project.media})


@app.get("/api/health")
async def health() -> JSONResponse:
    """健康检查。"""
    return JSONResponse(
        {"ok": True, "projects": len(_projects), "output_dir": str(OUTPUT_DIR)}
    )


# --------------------------------------------------------------------------
# 删除 / 文件管理器 / 剪贴板
# --------------------------------------------------------------------------


def _remove_project(project: Project, delete_files: bool) -> dict[str, Any]:
    """删除一个工程：可选连同解包产物一起删除。"""
    removed_files = 0

    if delete_files:
        # 1) 删除解包输出目录
        if project.output_dir is not None and project.output_dir.exists():
            try:
                shutil.rmtree(project.output_dir)
                removed_files += 1
            except OSError as exc:
                print(f"删除输出目录失败 {project.output_dir}: {exc}")

        # 2) 删除上传/扫描时保存的 pkg 副本
        #    只删我们自己创建的副本，绝不删用户原始目录里的文件
        try:
            pkg_path = project.pkg_path.resolve()
            upload_root = UPLOAD_DIR.resolve()
            if upload_root in pkg_path.parents:
                shutil.rmtree(pkg_path.parent, ignore_errors=True)
                removed_files += 1
        except OSError as exc:
            print(f"删除上传副本失败 {project.pkg_path}: {exc}")

    # 3) 从注册表移除
    _projects.pop(project.id, None)

    return {
        "id": project.id,
        "name": project.name,
        "removed_files": removed_files,
    }


@app.post("/api/projects/delete")
async def delete_projects(
    ids: str = Form(...),
    delete_files: bool = Form(True),
) -> JSONResponse:
    """批量删除工程（支持多选）。

    Args:
        ids: 逗号分隔的工程 id。
        delete_files: 是否同时删除已解包的输出目录。
    """
    project_ids = [i.strip() for i in ids.split(",") if i.strip()]
    if not project_ids:
        raise HTTPException(400, "未指定要删除的工程")

    deleted = []
    not_found = []

    for pid in project_ids:
        project = _projects.get(pid)
        if project is None:
            not_found.append(pid)
            continue
        deleted.append(_remove_project(project, delete_files))

    return JSONResponse(
        {
            "ok": True,
            "deleted": deleted,
            "deleted_count": len(deleted),
            "not_found": not_found,
        }
    )


@app.post("/api/reveal")
async def reveal(
    path: str = Form(""),
    project_id: str = Form(""),
) -> JSONResponse:
    """在系统文件管理器中定位/打开路径。

    Args:
        path: 要定位的文件或目录。
        project_id: 若给定且 path 为空，则打开该工程的解包输出目录。

    注意：path 允许为空字符串。FastAPI 对必填 Form 字段收到空值时
    会当作 missing 报 422，所以这里给默认值而不是 Form(...)。
    """
    # 按工程 id 打开输出目录
    if project_id and not path:
        project = _projects.get(project_id)
        if project is None:
            return JSONResponse({"ok": False, "message": "工程不存在", "path": ""})

        target = project.output_dir or (OUTPUT_DIR / project.id)
        if not target.exists():
            return JSONResponse(
                {"ok": False, "message": "该工程尚未解包", "path": str(target)}
            )
        ok, message = reveal_in_file_manager(target)
        return JSONResponse({"ok": ok, "message": message, "path": str(target)})

    if not path:
        return JSONResponse({"ok": False, "message": "未指定路径", "path": ""})

    ok, message = reveal_in_file_manager(path)
    return JSONResponse({"ok": ok, "message": message, "path": path})


@app.post("/api/copy")
async def copy_text(text: str = Form(...)) -> JSONResponse:
    """复制文本到系统剪贴板。"""
    ok = copy_to_clipboard(text)
    return JSONResponse(
        {"ok": ok, "message": "已复制到剪贴板" if ok else "复制失败", "text": text}
    )


# 静态前端
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
