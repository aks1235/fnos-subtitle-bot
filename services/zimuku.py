"""Zimuku (zimuku.org) 爬虫字幕源。

dedecms 结构，Selector 可能失效，失败返回空列表。
"""
import logging
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from .subtitle_types import SubtitleCandidate, normalize_lang, guess_format

logger = logging.getLogger(__name__)

BASE = "https://zimuku.org"
TIMEOUT = 15

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ZimukuSource:
    """Zimuku 爬虫字幕源。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def search(self, query: str, is_tv: bool) -> list[SubtitleCandidate]:
        """搜索页解析结果列表。失败返回空。"""
        url = f"{BASE}/search?q={quote(query)}"
        try:
            resp = self.session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("[Zimuku] 搜索请求失败: %s", e)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        candidates: list[SubtitleCandidate] = []

        # Zimuku 常见结构
        items = soup.select(".list-item, .sub-item, .search-item, .preview")
        if not items:
            items = soup.select("a[href*='/detail/'], a[href*='/subs/'], a[href*='/d/']")

        seen_urls: set[str] = set()
        for item in items[:10]:
            link = item if item.name == "a" else item.select_one("a[href*='/detail/'], a[href*='/subs/'], a[href*='/d/']")
            if not link:
                continue
            href = link.get("href", "")
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)
            detail_url = urljoin(BASE, href)
            title = link.get_text(strip=True) or query

            meta_text = item.get_text(" ", strip=True) if item.name != "a" else title
            lang = _detect_lang(meta_text)

            candidates.append(SubtitleCandidate(
                source="zimuku",
                title=title[:120],
                language=lang,
                lang_norm=normalize_lang(lang),
                fmt=guess_format(meta_text),
                rating=0.0,
                size="",
                file_ref=detail_url,
                is_season_pack=_is_pack(meta_text),
            ))

        logger.info("[Zimuku] 搜索「%s」找到 %d 个结果", query, len(candidates))
        return candidates

    def fetch_url(self, candidate: SubtitleCandidate) -> str:
        """进入详情页提取下载链接。失败返回原始 detail_url。"""
        detail_url = candidate.file_ref
        try:
            resp = self.session.get(detail_url, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("[Zimuku] 详情页请求失败: %s", e)
            return detail_url

        soup = BeautifulSoup(resp.text, "lxml")
        dl = soup.select_one("a[href*='down'], a[href*='/dl/'], a[href*='download'], a.btn-download, .download")
        if dl:
            href = dl.get("href", "")
            return urljoin(BASE, href) if href else detail_url

        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if any(ext in href.lower() for ext in (".zip", ".rar", ".7z", ".srt", ".ass")):
                return urljoin(BASE, href) if href else detail_url

        return detail_url


def _detect_lang(text: str) -> str:
    """从文本推断语言标签。"""
    t = text.lower()
    if any(w in t for w in ("中英", "双语", "简英", "繁英", "chs&eng")):
        return "zh-en"
    if any(w in t for w in ("繁体", "繁中", "cht", "tw")):
        return "zh-tw"
    if any(w in t for w in ("简体", "简中", "chs", "cn", "中文")):
        return "zh-cn"
    if any(w in t for w in ("英文", "english", "eng")):
        return "en"
    return "zh"


def _is_pack(text: str) -> bool:
    """判断是否整季包。"""
    t = text.lower()
    return any(m in t for m in ("全季", "整季", "complete", "season", "全集", "s01", "s02"))
