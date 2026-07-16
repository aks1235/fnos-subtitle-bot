"""OpenSubtitles REST API 封装。

接口:
  GET  /api/v1/subtitles  搜索
  POST /api/v1/download   获取一次性下载链接

免费层: 20 download/day + 40 search/day，429 触发 fallback。
"""
import logging
import requests

from .subtitle_types import SubtitleCandidate, normalize_lang, guess_format

logger = logging.getLogger(__name__)

API_BASE = "https://api.opensubtitles.com/api/v1"
TIMEOUT = 15

# 视为整季包的标题关键词
SEASON_PACK_MARKERS = ("complete", "season", "s01", "s02", "全季", "整季")


class OpenSubtitlesSource:
    """OpenSubtitles REST API 字幕源。"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        # OpenSubtitles 要求 Accept 头匹配,否则 /download 返回 406 Not Acceptable
        # UA 格式需合规(官方建议 "AppName/Version")
        self.session.headers.update({
            "Api-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "fnos-subtitle-bot/0.1",
        })

    def search(self, query: str, is_tv: bool) -> list[SubtitleCandidate]:
        """搜索字幕，返回候选列表。429/异常返回空。"""
        params = {
            "query": query,
            "languages": "zh,zh-cn,zh-tw,zho,en",
            "order_by": "download_count",
            "page": 1,
        }
        try:
            resp = self.session.get(f"{API_BASE}/subtitles", params=params, timeout=TIMEOUT)
            if resp.status_code == 429:
                logger.warning("[OpenSubtitles] 触发限流(429)，建议降级到爬虫")
                return []
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.warning("[OpenSubtitles] 搜索请求失败: %s", e)
            return []
        except ValueError as e:
            logger.warning("[OpenSubtitles] 响应解析失败: %s", e)
            return []

        candidates: list[SubtitleCandidate] = []
        for item in data.get("data", []):
            attrs = item.get("attributes", {})
            lang = attrs.get("language", "zh")
            fmt = (attrs.get("format") or "srt").lower()
            release = attrs.get("release", "")
            title = release or attrs.get("feature_details", {}).get("title", query)

            # 文件大小
            filesize = attrs.get("filesize", 0) or 0
            size_str = _format_size(int(filesize))

            # 整季包判定
            is_pack = _is_season_pack(release, filesize)

            candidates.append(SubtitleCandidate(
                source="opensubtitles",
                title=title[:120],
                language=lang,
                lang_norm=normalize_lang(lang),
                fmt=fmt,
                rating=float(attrs.get("ratings", 0) or 0),
                size=size_str,
                file_ref=str(item.get("id", "")),
                is_season_pack=is_pack,
            ))

        logger.info("[OpenSubtitles] 搜索「%s」找到 %d 个结果", query, len(candidates))
        return candidates

    def fetch_url(self, candidate: SubtitleCandidate) -> str:
        """通过 /download 端点获取一次性下载链接。失败返回空串。"""
        try:
            file_id = int(candidate.file_ref)
        except (ValueError, TypeError):
            logger.warning("[OpenSubtitles] 无效 file_id: %s", candidate.file_ref)
            return ""

        try:
            resp = self.session.post(
                f"{API_BASE}/download",
                json={"file_id": file_id},
                timeout=TIMEOUT,
            )
            if resp.status_code == 429:
                logger.warning("[OpenSubtitles] 下载触发限流(429)")
                return ""
            resp.raise_for_status()
            link = resp.json().get("link", "")
            if not link:
                logger.warning("[OpenSubtitles] /download 未返回 link")
            return link
        except (requests.RequestException, ValueError) as e:
            logger.warning("[OpenSubtitles] 获取下载链接失败: %s", e)
            return ""


def _format_size(size_bytes: int) -> str:
    """字节数转可读大小。"""
    if size_bytes <= 0:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def _is_season_pack(release: str, filesize: int) -> bool:
    """判断是否整季字幕包（标题含标记或文件偏大）。"""
    release_lower = (release or "").lower()
    if any(m in release_lower for m in SEASON_PACK_MARKERS):
        return True
    # 大于 500KB 的字幕大概率是整季合集
    if filesize > 500 * 1024:
        return True
    return False
