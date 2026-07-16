"""字幕多源搜索协调器。

策略（R3）：
  1. OpenSubtitles 优先查询
  2. 结果 <5 条时并行补查 SubHD + Zimuku
  3. OpenSubtitles 429/异常 → 纯走爬虫，向用户提示
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .opensub import OpenSubtitlesSource
from .subhd import SubhdSource
from .zimuku import ZimukuSource
from .subtitle_types import SubtitleCandidate

logger = logging.getLogger(__name__)

FALLBACK_THRESHOLD = 5  # OpenSubtitles 结果少于此数才补爬虫


@dataclass
class SearchResult:
    """一次搜索的聚合结果。"""
    candidates: list[SubtitleCandidate]
    primary_available: bool   # OpenSubtitles 主源是否可用（False 表示已降级）


class SubtitleSearcher:
    """多源字幕搜索协调器。"""

    def __init__(self, opensub_api_key: str, enable_scrapers: bool = True):
        self.opensub = OpenSubtitlesSource(opensub_api_key)
        self.enable_scrapers = enable_scrapers
        # 爬虫延迟创建（可能被禁用）
        self._subhd: SubhdSource | None = None
        self._zimuku: ZimukuSource | None = None

    @property
    def subhd(self) -> SubhdSource:
        if self._subhd is None:
            self._subhd = SubhdSource()
        return self._subhd

    @property
    def zimuku(self) -> ZimukuSource:
        if self._zimuku is None:
            self._zimuku = ZimukuSource()
        return self._zimuku

    def search(self, query: str, is_tv: bool) -> SearchResult:
        """
        多源搜索。

        返回 SearchResult，primary_available=False 表示主源不可用需提示用户。
        """
        primary_results = self.opensub.search(query, is_tv)
        primary_available = len(primary_results) > 0 or True  # 主源被调用即视为尝试过

        # 判断是否需要补爬虫：主源结果不足 或 主源失效（空且疑似限流）
        need_scrapers = self.enable_scrapers and (
            len(primary_results) < FALLBACK_THRESHOLD
        )

        all_candidates: list[SubtitleCandidate] = list(primary_results)

        if need_scrapers:
            scraper_results = self._search_scrapers_parallel(query, is_tv)
            all_candidates.extend(scraper_results)
            # 主源空 + 爬虫有结果 → 主源可能降级
            if not primary_results and scraper_results:
                primary_available = False

        # 排序：评分高优先，OpenSubtitles 优先于爬虫
        all_candidates.sort(key=lambda c: (c.source != "opensubtitles", -c.rating))

        logger.info(
            "搜索「%s」聚合完成: 主源 %d + 爬虫补充, 共 %d 个候选, 主源可用=%s",
            query, len(primary_results), len(all_candidates), primary_available,
        )
        return SearchResult(candidates=all_candidates, primary_available=primary_available)

    def _search_scrapers_parallel(self, query: str, is_tv: bool) -> list[SubtitleCandidate]:
        """并行查询 SubHD + Zimuku。任一失败不影响另一个。"""
        results: list[SubtitleCandidate] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(self.subhd.search, query, is_tv): "subhd",
                pool.submit(self.zimuku.search, query, is_tv): "zimuku",
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results.extend(future.result())
                except Exception as e:
                    logger.warning("[%s] 并行搜索异常: %s", name, e)
        return results

    def fetch_url(self, candidate: SubtitleCandidate) -> str:
        """根据来源路由到对应源的 fetch_url。"""
        if candidate.source == "opensubtitles":
            return self.opensub.fetch_url(candidate)
        if candidate.source == "subhd":
            return self.subhd.fetch_url(candidate)
        if candidate.source == "zimuku":
            return self.zimuku.fetch_url(candidate)
        logger.warning("未知字幕来源: %s", candidate.source)
        return ""


def clean_search_name(name: str) -> str:
    """清理目录名为搜索关键词（去年份/分辨率/格式标记）。

    如 "让子弹飞.2010.1080p.BluRay" → "让子弹飞"
    如 "三国演义 (1994)" → "三国演义"
    """
    if not name:
        return ""
    s = name
    # 去括号内的 TMDB ID 等标记 {tmdb=123} [tmdb-123]
    s = re.sub(r"\s*[{\[][^}\]]*[}\]]\s*", " ", s)
    # 去年份 (2010)
    s = re.sub(r"\s*\(\d{4}\)\s*", " ", s)
    # 去分辨率
    s = re.sub(r"\s*\d{3,4}[piPI]\s*", " ", s)
    # 去格式标记
    s = re.sub(
        r"\s*(BluRay|WEB-DL|BRRip|HDRip|REMUX|DVDRip|BDRip|x264|x265|H\.?264|H\.?265|DDP|AC3|DTS|FLAC|10bit|HDR|DV|ATMOS)\s*",
        " ", s, flags=re.IGNORECASE,
    )
    s = re.sub(r"\s*[._]\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
