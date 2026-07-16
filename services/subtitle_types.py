"""字幕源通用类型与归一化函数。"""
import re
from dataclasses import dataclass
from typing import Protocol


@dataclass
class SubtitleCandidate:
    """字幕搜索候选结果。"""
    source: str          # "opensubtitles" | "subhd" | "zimuku"
    title: str           # 显示标题
    language: str        # 来源原始语言标签
    lang_norm: str       # 归一化后的语言: "zh" | "zh-en" | "en"
    fmt: str             # 格式: srt/ass/ssa/vtt
    rating: float        # 评分（OpenSubtitles 有，爬虫为 0）
    size: str            # 文件大小展示
    file_ref: str        # 下载句柄: OpenSubtitles file_id 或爬虫 detail_url
    is_season_pack: bool # 是否整季包


# 语言归一化映射（保留简繁通用为 .zh，符合飞牛/Emby 最稳识别）
LANG_NORM_MAP = {
    # 中文类
    "zh": "zh", "zh-cn": "zh", "zh-cn-hans": "zh", "zh-hans": "zh",
    "zh-tw": "zh", "zh-cn-hant": "zh", "zh-hant": "zh",
    "zho": "zh", "chi": "zh", "chinese": "zh",
    "简体": "zh", "简中": "zh", "chs": "zh", "cn": "zh", "国语": "zh", "中文": "zh",
    "繁体": "zh", "繁中": "zh", "cht": "zh", "tw": "zh",
    # 双语
    "zh-en": "zh-en", "en-zh": "zh-en", "zh,en": "zh-en", "zh_cn,en": "zh-en",
    "dual": "zh-en", "双语": "zh-en", "中英": "zh-en", "简英": "zh-en", "繁英": "zh-en",
    "chs&eng": "zh-en", "cht&eng": "zh-en", "中英双语": "zh-en",
    # 英文
    "en": "en", "eng": "en", "english": "en", "英文": "en", "英语": "en",
}


def normalize_lang(raw: str | None) -> str:
    """将来源语言标签归一化为 zh / zh-en / en，默认 zh。"""
    if not raw:
        return "zh"
    key = raw.strip().lower()
    # 直接命中
    if key in LANG_NORM_MAP:
        return LANG_NORM_MAP[key]
    # 复合标签尝试拆分匹配（如 "zh,en-US" → 含中英 → 双语）
    parts = re.split(r"[,;|/&\s]+", key)
    has_zh = any(normalize_lang(p) == "zh" for p in parts)
    has_en = any(normalize_lang(p) == "en" for p in parts)
    if has_zh and has_en:
        return "zh-en"
    if has_en and not has_zh:
        return "en"
    if has_zh:
        return "zh"
    return "zh"


# 字幕格式扩展名集合
SUB_EXTS = {"srt", "ass", "ssa", "vtt", "sub"}


def guess_format(text: str) -> str:
    """从文本推断字幕格式，默认 srt。"""
    t = text.lower()
    for fmt in ("ass", "ssa", "srt", "vtt", "sub"):
        if fmt in t:
            return fmt
    return "srt"


class SubtitleSource(Protocol):
    """字幕源统一接口。"""
    def search(self, query: str, is_tv: bool) -> list[SubtitleCandidate]:
        ...
    def fetch_url(self, candidate: SubtitleCandidate) -> str:
        ...
