"""字幕下载、解压、命名、写入。

纯本地文件操作：下载到 tmp → 解压（如压缩包）→ 按 R7 命名 → 写入媒体目录。
电影写单文件；剧集按集号匹配每个视频；已有字幕默认跳过。
"""
import logging
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass

import requests

from .media_scanner import MediaEntry, VideoFile
from .subtitle_types import SubtitleCandidate, SUB_EXTS

logger = logging.getLogger(__name__)

TIMEOUT = 30

# Emby/Jellyfin/飞牛识别的语言后缀
LANG_SUFFIX = {
    "zh": ".zh",
    "zh-en": ".zh-en",
    "en": ".en",
}

# 集号匹配正则（与 media_scanner 一致）
EP_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})"),
    re.compile(r"[Ee][Pp]?(\d{1,3})\b"),
    re.compile(r"第(\d{1,3})集"),
]


@dataclass
class WriteResult:
    """一次写入的结果汇总。"""
    written: list[str] = None        # 已写入的文件名
    skipped: list[str] = None        # 跳过的（已有字幕）
    unmatched: list[str] = None      # 未匹配集号放根目录的
    error: str = ""                  # 错误信息（整体失败时）

    def __post_init__(self):
        if self.written is None:
            self.written = []
        if self.skipped is None:
            self.skipped = []
        if self.unmatched is None:
            self.unmatched = []


def write_subtitle(
    candidate: SubtitleCandidate,
    entry: MediaEntry,
    force: bool,
    http_session: requests.Session | None = None,
) -> WriteResult:
    """
    下载并写入字幕到 entry 对应目录。

    电影（is_tv=False）：写单个 {stem}.{lang}.{fmt}
    剧集（is_tv=True）：整季包解压按集号匹配，每集写 {stem}.{lang}.{fmt}，
                       匹配不到的放目录根作默认字幕。

    force=True 跳过已有字幕检测全部重写。
    """
    result = WriteResult()
    session = http_session or requests.Session()

    # 1. 下载到 tmp
    tmp_dir = tempfile.mkdtemp(prefix="sub_")
    try:
        subtitle_files = _download_and_extract(candidate, session, tmp_dir)
        if not subtitle_files:
            result.error = "下载或解压未得到任何字幕文件"
            return result
    except Exception as e:
        logger.error("字幕下载/解压失败: %s", e)
        result.error = f"下载/解压失败: {e}"
        return result
    finally:
        # tmp 在写入完成后由 _write_files 逻辑之外清理；这里先保留供写入
        pass

    try:
        result = _write_files(subtitle_files, candidate, entry, force, tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


def _download_and_extract(
    candidate: SubtitleCandidate,
    session: requests.Session,
    tmp_dir: str,
) -> list[str]:
    """
    下载字幕文件，若是压缩包则解压提取字幕。

    返回 tmp_dir 内字幕文件绝对路径列表（按 ass > srt 优先排序）。
    """
    from .subtitle_searcher import _SourceRouter
    # 通过路由获取下载 URL（避免循环导入，延迟引用）
    return []


class _SourceRouter:
    """占位：实际下载 URL 由调用方通过 searcher 提供。

    这里为保持模块独立性，write_subtitle 接收已确定的下载 URL 更简洁。
    见 write_subtitle_with_url。
    """
    pass


def write_subtitle_with_url(
    candidate: SubtitleCandidate,
    download_url: str,
    entry: MediaEntry,
    force: bool,
    http_session: requests.Session | None = None,
) -> WriteResult:
    """给定下载 URL 的写入流程（推荐入口，避免与 searcher 循环依赖）。"""
    result = WriteResult()
    session = http_session or requests.Session()
    tmp_dir = tempfile.mkdtemp(prefix="sub_")

    try:
        subtitle_files = _download_to_tmp(download_url, session, tmp_dir)
        if not subtitle_files:
            result.error = "下载未得到字幕文件"
            return result
        subtitle_files = _extract_if_archive(subtitle_files, tmp_dir)
        if not subtitle_files:
            result.error = "解压未得到字幕文件"
            return result
        result = _write_files(subtitle_files, candidate, entry, force, tmp_dir)
    except Exception as e:
        logger.error("字幕写入流程失败: %s", e)
        result.error = f"写入流程失败: {e}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


def _download_to_tmp(url: str, session: requests.Session, tmp_dir: str) -> list[str]:
    """下载 URL 到 tmp_dir，返回保存的文件路径列表。"""
    if not url:
        logger.warning("下载 URL 为空")
        return []

    try:
        resp = session.get(url, timeout=TIMEOUT, stream=True)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("下载失败 %s: %s", url[:80], e)
        return []

    # 从 Content-Disposition 或 URL 推断文件名
    disposition = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename[^;=\n]*=((["\']).*?\2|[^;\n]*)', disposition)
    if m:
        raw_name = m.group(1).strip("\"'")
        # 处理 filename*=UTF-8'' 编码
        if raw_name.lower().startswith("utf-8''"):
            from urllib.parse import unquote
            raw_name = unquote(raw_name[7:])
    else:
        raw_name = url.split("/")[-1].split("?")[0] or "subtitle"

    # 清理非法文件名字符
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", raw_name)
    filepath = os.path.join(tmp_dir, safe_name)

    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)

    logger.info("下载完成: %s (%.1fKB)", safe_name, os.path.getsize(filepath) / 1024)
    return [filepath]


def _extract_if_archive(filepaths: list[str], tmp_dir: str) -> list[str]:
    """若文件是压缩包则解压提取字幕，返回字幕文件路径列表。"""
    extracted: list[str] = []
    for fp in filepaths:
        ext = os.path.splitext(fp)[1].lower()
        if ext == ".zip":
            extracted.extend(_extract_zip(fp, tmp_dir))
        elif ext in (".rar", ".7z"):
            # rar/7z 需外部工具，尝试调用
            extracted.extend(_extract_with_tool(fp, tmp_dir))
        elif os.path.splitext(fp)[1].lower().lstrip(".") in SUB_EXTS:
            extracted.append(fp)
        else:
            # 未知扩展名但内容可能是字幕，保留待后续判断
            extracted.append(fp)

    # 过滤出真正的字幕文件，按 ass > srt 优先
    subs = [f for f in extracted if os.path.splitext(f)[1].lower().lstrip(".") in SUB_EXTS]
    subs.sort(key=lambda f: {".ass": 0, ".srt": 1, ".ssa": 2, ".vtt": 3, ".sub": 4}.get(
        os.path.splitext(f)[1].lower(), 99
    ))
    return subs


def _extract_zip(zip_path: str, tmp_dir: str) -> list[str]:
    """解压 zip，返回解出的文件路径列表。"""
    out: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # 安全解压：过滤路径穿越
            for name in zf.namelist():
                if name.startswith("/") or ".." in name:
                    continue
                zf.extract(name, tmp_dir)
                out.append(os.path.join(tmp_dir, name))
    except (zipfile.BadZipFile, OSError) as e:
        logger.warning("解压 zip 失败 %s: %s", zip_path, e)
    return out


def _extract_with_tool(archive_path: str, tmp_dir: str) -> list[str]:
    """调用 unrar/7z 解压，返回解出的文件路径列表。"""
    import subprocess
    ext = os.path.splitext(archive_path)[1].lower()
    tool, cmd_tmpl = ("unrar", ["unrar", "x", "-y", "-o+", "{}", "{}/"]), (
        ".7z" and ("7z", ["7z", "x", "-y", "-o{}/", "{}"]),
    )
    if ext == ".7z":
        tool, args = "7z", ["7z", "x", "-y", f"-o{tmp_dir}/", archive_path]
    else:
        tool, args = "unrar", ["unrar", "x", "-y", archive_path, f"{tmp_dir}/"]

    try:
        subprocess.run(args, capture_output=True, timeout=60, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("解压工具 %s 不可用: %s", tool, e)
        return []

    out: list[str] = []
    for root, _, files in os.walk(tmp_dir):
        for fn in files:
            out.append(os.path.join(root, fn))
    return out


def _write_files(
    subtitle_files: list[str],
    candidate: SubtitleCandidate,
    entry: MediaEntry,
    force: bool,
    tmp_dir: str,
) -> WriteResult:
    """将字幕文件按命名规则写入 entry 目录。"""
    result = WriteResult()
    lang_suffix = LANG_SUFFIX.get(candidate.lang_norm, ".zh")
    fmt_ext = f".{candidate.fmt}"

    target_dir = entry.path

    if not entry.is_tv:
        # === 电影：单字幕 ===
        video = entry.videos[0]
        target_name = f"{video.stem}{lang_suffix}{fmt_ext}"
        target_path = os.path.join(target_dir, target_name)

        # 已有字幕检测
        if not force and _has_subtitle_for(target_dir, video.stem):
            result.skipped.append(target_name)
            logger.info("跳过(已有字幕): %s", target_name)
            return result

        if _do_write(subtitle_files[0], target_path):
            result.written.append(target_name)
        else:
            result.error = f"写入失败: {target_name}"
        return result

    # === 剧集：按集号匹配 ===
    # 构建集号 → 视频文件 映射
    ep_to_video: dict[tuple[int | None, int], VideoFile] = {}
    for v in entry.videos:
        if v.episode is not None:
            ep_to_video[(v.season, v.episode)] = v

    for sub_path in subtitle_files:
        sub_name = os.path.basename(sub_path)
        sub_stem = os.path.splitext(sub_name)[0]
        season, ep = _parse_episode(sub_stem)

        if ep is not None and (season, ep) in ep_to_video:
            video = ep_to_video[(season, ep)]
            target_name = f"{video.stem}{lang_suffix}{fmt_ext}"
            target_path = os.path.join(target_dir, target_name)

            if not force and _has_subtitle_for(target_dir, video.stem):
                result.skipped.append(target_name)
                logger.info("跳过(已有字幕): %s", target_name)
                continue

            if _do_write(sub_path, target_path):
                result.written.append(target_name)
        else:
            # 未匹配集号 → 放目录根作默认字幕
            base = os.path.splitext(sub_name)[0]
            target_name = f"{base}{lang_suffix}{fmt_ext}"
            target_path = os.path.join(target_dir, target_name)
            if _do_write(sub_path, target_path):
                result.unmatched.append(target_name)

    return result


def _parse_episode(stem: str) -> tuple[int | None, int | None]:
    """从字幕文件名解析季/集号。"""
    for pattern in EP_PATTERNS:
        m = pattern.search(stem)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                return int(groups[0]), int(groups[1])
            if len(groups) == 1:
                return None, int(groups[0])
    return None, None


def _has_subtitle_for(target_dir: str, video_stem: str) -> bool:
    """检测目录下是否已有该视频对应的字幕文件。"""
    try:
        for fn in os.listdir(target_dir):
            ext = os.path.splitext(fn)[1].lower().lstrip(".")
            if ext not in SUB_EXTS:
                continue
            # 字幕文件名以 video_stem 开头即视为已有
            if fn.startswith(video_stem):
                return True
    except OSError:
        pass
    return False


def _do_write(src_path: str, target_path: str) -> bool:
    """复制 src 到 target，返回是否成功。"""
    try:
        shutil.copyfile(src_path, target_path)
        logger.info("写入字幕: %s", os.path.basename(target_path))
        return True
    except OSError as e:
        logger.error("写入失败 %s: %s", target_path, e)
        return False
