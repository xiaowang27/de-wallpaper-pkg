"""Wallpaper Engine 元数据：年龄分级、场景分类、标签。

数据来源是 PKG 旁边的 project.json（Wallpaper Engine 工程描述文件）。
本模块只负责「读懂并归一化」，不关心 UI。

注意 project.json 里 same 字段在不同版本的工程里格式并不统一，
例如 general.properties 可能是 list 也可能是 dict，这里都兼容。

真实素材统计（586 个工程）暴露的两个坑：
    - type 大小写不统一：既有 "scene" 也有 "Scene"
    - contentrating 取值比预期多：Everyone / Mature / Questionable
所以这里统一做大小写归一化 + 补全分级表。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Wallpaper Engine 的工程类型（已归一化为小写）
TYPE_SCENE = "scene"
TYPE_WALLPAPER = "wallpaper"
TYPE_VIDEO = "video"
TYPE_WEB = "web"

#: 类型的中文名（用于界面展示）
TYPE_LABELS = {
    TYPE_SCENE: "场景",
    TYPE_WALLPAPER: "壁纸",
    TYPE_VIDEO: "视频",
    TYPE_WEB: "网页",
}

#: 内容分级（已归一化）
RATING_EVERYONE = "Everyone"
RATING_TEEN = "Teen"
RATING_QUESTIONABLE = "Questionable"
RATING_MATURE = "Mature"
RATING_ADULT = "Adult"

#: 分级的中文名
RATING_LABELS = {
    RATING_EVERYONE: "所有人",
    RATING_TEEN: "青少年",
    RATING_QUESTIONABLE: "存疑",
    RATING_MATURE: "成熟",
    RATING_ADULT: "成人",
}

#: 分级严重程度排序（用于前端排序）
RATING_ORDER = [
    RATING_EVERYONE,
    RATING_TEEN,
    RATING_QUESTIONABLE,
    RATING_MATURE,
    RATING_ADULT,
]

#: 细分标记（ratingsex / ratingviolence）
MARKER_LABELS = {
    "none": "无",
    "true": "有",
    "yes": "有",
}


@dataclass
class WallpaperMeta:
    """从 project.json 提取出的分类元数据。"""

    #: 工程类型：scene / wallpaper / video / ""（未知）
    kind: str = ""

    #: 内容分级：Everyone / Teen / Adult / ""
    content_rating: str = ""

    #: 细分标记：性相关 / 暴力
    rating_sex: str = ""
    rating_violence: str = ""

    #: 作者标签
    tags: list[str] = field(default_factory=list)

    #: 场景内的布尔属性（场景作者自定义的开关）
    properties: list[dict[str, Any]] = field(default_factory=list)

    #: 原始 project.json
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def kind_label(self) -> str:
        return TYPE_LABELS.get(self.kind, self.kind or "未知")

    @property
    def rating_label(self) -> str:
        return RATING_LABELS.get(self.content_rating, self.content_rating or "未标注")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "kind_label": self.kind_label,
            "content_rating": self.content_rating,
            "content_rating_label": self.rating_label,
            "rating_sex": self.rating_sex,
            "rating_violence": self.rating_violence,
            "tags": list(self.tags),
            "properties": list(self.properties),
        }


def _normalize_kind(value: Any) -> str:
    """归一化工程类型。

    真实素材里 "scene" 和 "Scene" 都存在，不归一化会在筛选框里
    出现两个几乎一样的选项。
    """
    kind = str(value or "").strip().lower()
    if kind in TYPE_LABELS:
        return kind
    return kind


def _normalize_rating(value: Any) -> str:
    """归一化内容分级（保持首字母大写的标准写法）。"""
    rating = str(value or "").strip()
    if not rating:
        return ""
    for known in RATING_ORDER:
        if rating.lower() == known.lower():
            return known
    return rating


def _normalize_properties(general: Any) -> list[dict[str, Any]]:
    """归一化 general.properties。

    Wallpaper Engine 不同版本写出的格式不一致：
        {"properties": [ {...}, {...} ]}      <- 列表
        {"properties": { "name": {...} }}     <- 字典
    这里两种都支持，输出统一的 list。
    """
    if not isinstance(general, dict):
        return []

    props = general.get("properties")
    if isinstance(props, list):
        return [p for p in props if isinstance(p, dict)]

    if isinstance(props, dict):
        result = []
        for name, value in props.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("text", name)
                result.append(item)
            else:
                result.append({"text": name, "value": value})
        return result

    return []


def parse_project_json(data: Any) -> WallpaperMeta:
    """从已解析的 project.json 字典提取元数据。"""
    if not isinstance(data, dict):
        return WallpaperMeta()

    general = data.get("general")
    props = _normalize_properties(general)

    raw_tags = data.get("tags")
    tags: list[str] = []
    if isinstance(raw_tags, list):
        tags = [str(t) for t in raw_tags if isinstance(t, (str, int, float))]
    elif isinstance(raw_tags, str):
        tags = [raw_tags]

    return WallpaperMeta(
        kind=_normalize_kind(data.get("type")),
        content_rating=_normalize_rating(data.get("contentrating")),
        rating_sex=str(data.get("ratingsex") or ""),
        rating_violence=str(data.get("ratingviolence") or ""),
        tags=tags,
        properties=props,
        raw=data,
    )


def read_meta(pkg_path: Path) -> WallpaperMeta:
    """读取 PKG 旁边的 project.json 并解析元数据。

    没有 project.json 时返回空对象（不报错）。
    """
    project_json = Path(pkg_path).parent / "project.json"
    if not project_json.exists():
        return WallpaperMeta()

    try:
        data = json.loads(project_json.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return WallpaperMeta()

    return parse_project_json(data)
