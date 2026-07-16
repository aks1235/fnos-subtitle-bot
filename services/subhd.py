"""SubHD (subhd.tv) 爬虫字幕源。

纯网页爬取，Selector 可能随站点改版失效，失败返回空列表不停整个搜索。
"""
import logging
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from .subtitle_types import SubtitleCandidate, normalize_lang, guess_format

logger = logging.getLogger(__name__)

BASE = "https://subhd.tv"
TIMEOUT = 15

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class SubhdSource:
    """SubHD 爬虫字幕源。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def search(self, query: str, is_tv: bool) -> list[SubtitleCandidate]:
        """搜索页解析结果列表。失败返回空。"""
        url = f"{BASE}/search/{quote(query)}"
        try:
            resp = self.session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("[SubHD] 搜索请求失败: %s", e)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        candidates: list[SubtitleCandidate] = []

        # 多种选择器兜底，适应不同页面结构
        items = soup.select(".search-result-item, .subtitle-item, .list-item, .result-item")
        if not items:
            # 退化：找所有指向详情的链接
            items = soup.select("a[href*='/d/'], a[href*='/detail/']")

        for item in items[:10]:
            link = item if item.name == "a" else item.select_one("a[href*='/d/'], a[href*='/detail/']")
            if not link:
                continue
            href = link.get("href", "")
            if not href:
                continue
            detail_url = urljoin(BASE, href)
            title = link.get_text(strip=True) or query

            meta_text = item.get_text(" ", strip=True) if item.name != "a" else title
            lang = _detect_lang(meta_text)

            candidates.append(SubtitleCandidate(
                source="subhd",
                title=title[:120],
                language=lang,
                lang_norm=normalize_lang(lang),
                fmt=guess_format(meta_text),
                rating=0.0,
                size="",
                file_ref=detail_url,
                is_season_pack=_is_pack(meta_text),
            ))

        logger.info("[SubHD] 搜索「%s」找到 %d 个结果", query, len(candidates))
        return candidates

    def fetch_url(self, candidate: SubtitleCandidate) -> str:
        """进入详情页提取下载链接。失败返回原始 detail_url。"""
        detail_url = candidate.file_ref
        try:
            resp = self.session.get(detail_url, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("[SubHD] 详情页请求失败: %s", e)
            return detail_url

        soup = BeautifulSoup(resp.text, "lxml")
        # 下载按钮
        dl = soup.select_one("a.download-btn, a[href*='download'], a[href*='/dl/']")
        if dl:
            href = dl.get("href", "")
            return urljoin(BASE, href) if href else detail_url

        # 退化：找任何可能的直接下载链接
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if any(ext in href.lower() for ext in (".zip", ".rar", ".srt", ".ass", ".ssa")):
                return urljoin(BASE, href) if href else detail_url

        return detail_url


def _detect_lang(text: str) -> str:
    """从文本推断语言标签。"""
    t = text.lower()
    if any(w in t for w in ("中英", "双语", "简英", "繁英", "chs&eng", "cn&en", "中英双语")):
        return "zh-en"
    if any(w in t for w in ("繁体", "繁中", "cht", "tw")):
        return "zh-tw"
    if any(w in t for w in ("简体", "简中", "chs", "cn", "国语", "中文")):
        return "zh-cn"
    if any(w in t for w in ("英文", "英语", "english", "eng")):
        return "en"
    return "zh"


def _is_pack(text: str) -> bool:
    """判断是否整季包。"""
    t = text.lower()
    return any(m in t for m in ("全季", "整季", "complete", "season", "全集"))
