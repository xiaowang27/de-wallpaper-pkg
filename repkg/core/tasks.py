"""解包任务管理：后台线程执行 + 进度查询。

解决「解包时只能看到卡片上的沙漏」的问题：
前端提交解包请求后立即返回 task_id，之后轮询 /api/task/{id}
获取实时进度（当前条目 / 总数 / 状态），在侧边栏展示。

设计要点：
- 任务在后台线程里跑，不阻塞 HTTP 请求
- 进度状态用锁保护，避免竞态
- 任务完成后保留结果一小段时间，方便前端取最终信息
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .extractor import ExtractOptions, ExtractResult, Extractor

#: 任务状态
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"

#: 完成后保留结果的秒数（右侧「已完成」列表要用）
KEEP_SECONDS = 1800


@dataclass
class ExtractTask:
    """一次解包任务的状态。"""

    id: str
    project_id: str
    name: str
    status: str = STATUS_PENDING
    current: int = 0
    total: int = 0
    current_entry: str = ""
    message: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    result: ExtractResult | None = None
    output_dir: Path | None = None
    logs: list[str] = field(default_factory=list)

    @property
    def percent(self) -> int:
        """完成百分比（0-100）。"""
        if self.status == STATUS_DONE:
            return 100
        if self.total <= 0:
            return 0
        return min(99, int(self.current * 100 / self.total))

    @property
    def finished(self) -> bool:
        return self.status in (STATUS_DONE, STATUS_ERROR)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status,
            "current": self.current,
            "total": self.total,
            "percent": self.percent,
            "current_entry": self.current_entry,
            "message": self.message,
            "error": self.error,
            "finished": self.finished,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if self.result is not None:
            data["files_written"] = len(self.result.files_written)
            data["images_written"] = len(self.result.images_written)
            data["media_count"] = len(self.result.media_files)
            data["skipped"] = len(self.result.skipped)
            data["errors"] = self.result.errors
        if self.output_dir is not None:
            data["output_dir"] = str(self.output_dir)
        return data


class TaskManager:
    """管理所有解包任务。"""

    def __init__(self) -> None:
        self._tasks: dict[str, ExtractTask] = {}
        self._lock = threading.Lock()
        self._extractor = Extractor()

    def create(self, project_id: str, name: str, pkg_path: Path, options: ExtractOptions) -> ExtractTask:
        """创建并启动一个解包任务（后台线程）。"""
        task = ExtractTask(
            id=uuid.uuid4().hex[:12],
            project_id=project_id,
            name=name,
            status=STATUS_RUNNING,
        )
        with self._lock:
            self._tasks[task.id] = task

        thread = threading.Thread(
            target=self._run, args=(task, pkg_path, options), daemon=True
        )
        thread.start()
        return task

    def _run(self, task: ExtractTask, pkg_path: Path, options: ExtractOptions) -> None:
        """任务主体（跑在后台线程）。"""

        def on_log(msg: str) -> None:
            with self._lock:
                task.logs.append(msg)
                if len(task.logs) > 500:
                    del task.logs[:-500]

        def on_progress(current: int, total: int, entry_path: str) -> None:
            with self._lock:
                task.current = current
                task.total = total
                task.current_entry = entry_path

        try:
            result = self._extractor.extract_package(
                pkg_path, options, log=on_log, progress=on_progress
            )
            with self._lock:
                task.result = result
                task.output_dir = options.output_dir
                task.status = STATUS_DONE if result.ok else STATUS_ERROR
                if not result.ok:
                    task.error = "; ".join(result.errors[:5])
                task.finished_at = time.time()
        except Exception as exc:
            with self._lock:
                task.status = STATUS_ERROR
                task.error = str(exc)
                task.finished_at = time.time()

    def get(self, task_id: str) -> ExtractTask | None:
        with self._lock:
            self._cleanup()
            return self._tasks.get(task_id)

    def list_tasks(self) -> list[ExtractTask]:
        """列出所有未完成任务（左侧栏用）。"""
        with self._lock:
            self._cleanup()
            return [t for t in self._tasks.values() if not t.finished]

    def list_finished(self) -> list[ExtractTask]:
        """列出已完成任务（右侧栏用），按完成时间倒序。"""
        with self._lock:
            self._cleanup()
            done = [t for t in self._tasks.values() if t.finished]
            done.sort(key=lambda t: t.finished_at, reverse=True)
            return done

    def get_logs(self, task_id: str, limit: int = 200) -> list[str]:
        with self._lock:
            task = self._tasks.get(task_id)
            return list(task.logs[-limit:]) if task else []

    def _cleanup(self) -> None:
        """清理过期的已完成任务（需持有锁）。"""
        now = time.time()
        stale = [
            tid
            for tid, t in self._tasks.items()
            if t.finished and now - t.finished_at > KEEP_SECONDS
        ]
        for tid in stale:
            del self._tasks[tid]


#: 全局任务管理器
_tasks = TaskManager()
