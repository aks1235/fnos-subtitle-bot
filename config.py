"""配置加载与校验。

从环境变量读取配置，启动时校验必填项，缺失则退出并提示。
"""
import logging
import os
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    """运行配置（启动时一次性读取，不可变）。"""

    bot_token: str                 # 必填：字幕 Bot 的 Telegram Token
    opensub_api_key: str           # 必填：OpenSubtitles API Key
    media_root: str                # 媒体根路径（容器内，默认 /media/cloud）
    bot_admin_id: int | None       # 可选：管理员 user_id，配置后只允许该用户使用
    sub_format_pref: str           # 优先字幕格式，默认 srt
    sub_lang_pref: str             # 优先语言，默认 zh
    enable_scrapers: bool          # 是否启用 SubHD/Zimuku 爬虫 fallback
    log_level: str                 # 日志级别


def _get_bool(name: str, default: bool) -> bool:
    """读取布尔型环境变量。"""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int | None) -> int | None:
    """读取整型环境变量，空则返回 default。"""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("环境变量 %s 不是有效整数，使用默认值 %s", name, default)
        return default


def load_config() -> Config:
    """加载并校验配置。必填项缺失则 sys.exit(1)。"""
    # 收集缺失的必填项
    missing: list[str] = []

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        missing.append("BOT_TOKEN（字幕 Bot 的 Telegram Token）")

    opensub_api_key = os.getenv("OPENSUB_API_KEY", "").strip()
    if not opensub_api_key:
        missing.append("OPENSUB_API_KEY（OpenSubtitles API Key）")

    if missing:
        # 必填项缺失，打印明确提示后退出
        print("=" * 60, file=sys.stderr)
        print("❌ 配置不完整，Bot 无法启动。请补齐以下必填环境变量：", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        print("可在 docker-compose.yml 的 environment 段配置。", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        sys.exit(1)

    cfg = Config(
        bot_token=bot_token,
        opensub_api_key=opensub_api_key,
        media_root=os.getenv("MEDIA_ROOT", "/media/cloud").strip(),
        bot_admin_id=_get_int("BOT_ADMIN_ID", None),
        sub_format_pref=os.getenv("SUB_FORMAT_PREF", "srt").strip().lower() or "srt",
        sub_lang_pref=os.getenv("SUB_LANG_PREF", "zh").strip().lower() or "zh",
        enable_scrapers=_get_bool("ENABLE_SCRAPERS", True),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )

    logger.info(
        "配置加载完成: media_root=%s, scrapers=%s, log_level=%s",
        cfg.media_root, cfg.enable_scrapers, cfg.log_level,
    )
    return cfg
