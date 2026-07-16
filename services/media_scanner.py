"""本地媒体目录扫描与集号解析。

纯文件系统操作（os/pathlib），不调用任何网盘 API。
递归遍历 MEDIA_ROOT，找含视频文件的叶子目录，按关键词过滤。
"""
import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 视频扩展名（与飞牛/Emby 常见识别一致）
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".rmvb", ".wmv", ".ts", ".m2ts", ".flv", ".mpeg", ".mpg"}

# 集号解析正则：覆盖 S01E01 / E01 / EP01 / 第01集 / 第1集
EP_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})"),   # S01E01 → (季, 集)
    re.compile(r"[Ee][Pp]?(\d{1,3})\b"),          # E01 / EP01 → 集
    re.compile(r"第(\d{1,3})集"),                 # 第01集
]

# 忽略的非影视目录（样本、花絮等）
IGNORE_DIRS = {"sample", "samples", "extras", "@eaDir", ".@__thumb"}


@dataclass
class VideoFile:
    """单个视频文件信息。"""
    filename: str           # 完整文件名 "三国演义.E01.mkv"
    stem: str               # 去扩展名 "三国演义.E01"
    size: int               # 字节数
    episode: int | None     # 解析出的集号，电影为 None
    season: int | None      # 季号（仅 S01E01 格式有）


@dataclass
class MediaEntry:
    """一个含视频的叶子目录。"""
    name: str                       # 目录名 "三国演义 (1994)"
    path: str                       # 容器内完整路径
    rel_path: str                   # 相对 MEDIA_ROOT 的路径，用于展示
    is_tv: bool                     # 多视频=True（剧集）
    videos: list[VideoFile] = field(default_factory=list)


def _parse_episode(stem: str) -> tuple[int | None, int | None]:
    """从文件名解析季号和集号，解析失败返回 (None, None)。"""
    for pattern in EP_PATTERNS:
        m = pattern.search(stem)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                # S01E01 格式：返回 (季, 集)
                return int(groups[0]), int(groups[1])
            if len(groups) == 1:
                # E01/EP01/第01集 格式：集号，季号 None
                return None, int(groups[0])
    return None, None


def _is_video(filename: str) -> bool:
    """判断是否视频文件。"""
    return os.path.splitext(filename)[1].lower() in VIDEO_EXTS


def _scan_leaf_dirs(root: str) -> list[MediaEntry]:
    """递归遍历 root，收集所有含视频的叶子目录。"""
    entries: list[MediaEntry] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # 过滤忽略目录（原地修改 dirnames 影响 os.walk 递归）
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]

        # 收集当前目录的视频文件
        videos: list[VideoFile] = []
        for fn in filenames:
            if not _is_video(fn):
                continue
            full = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            stem = os.path.splitext(fn)[0]
            season, ep = _parse_episode(stem)
            videos.append(VideoFile(filename=fn, stem=stem, size=size, episode=ep, season=season))

        if not videos:
            continue

        # 这是一个含视频的叶子目录
        abs_path = os.path.abspath(dirpath)
        rel = os.path.relpath(dirpath, root)
        # 去掉开头的 "." 让展示更干净
        rel_clean = "" if rel == "." else rel
        name = os.path.basename(dirpath) or rel_clean or root

        entries.append(MediaEntry(
            name=name,
            path=abs_path,
            rel_path=rel_clean,
            is_tv=len(videos) > 1,
            videos=sorted(videos, key=lambda v: (v.season or 0, v.episode or 0, v.stem)),
        ))

    logger.info("扫描 %s 完成，共 %d 个含视频目录", root, len(entries))
    return entries


def scan_and_filter(keyword: str, media_root: str, max_results: int = 50) -> list[MediaEntry]:
    """
    扫描媒体根目录，按关键词模糊匹配目录名或视频文件名。

    参数:
        keyword: 搜索关键词（为空则返回前 max_results 个）
        media_root: 媒体根路径
        max_results: 最多返回条数

    返回:
        匹配的 MediaEntry 列表
    """
    if not os.path.isdir(media_root):
        logger.error("媒体根路径不存在或不可访问: %s", media_root)
        return []

    entries = _scan_leaf_dirs(media_root)

    kw = keyword.strip()
    if not kw:
        return entries[:max_results]

    kw_lower = kw.lower()
    matched: list[MediaEntry] = []
    for entry in entries:
        # 目录名匹配
        if kw_lower in entry.name.lower():
            matched.append(entry)
            continue
        # 视频文件名匹配
        if any(kw_lower in v.filename.lower() for v in entry.videos):
            matched.append(entry)
            continue
        # 相对路径匹配（含分类子目录名，如 "电视剧/国产"）
        if kw_lower in entry.rel_path.lower():
            matched.append(entry)

    logger.info("关键词「%s」匹配 %d 个目录", kw, len(matched))
    return matched[:max_results]


def get_entry_by_rel_path(rel_path: str, media_root: str) -> MediaEntry | None:
    """按相对路径查找单个 MediaEntry（用于 callback 还原选中目录）。"""
    if not os.path.isdir(media_root):
        return None
    entries = _scan_leaf_dirs(media_root)
    for entry in entries:
        if entry.rel_path == rel_path:
            return entry
    return None
