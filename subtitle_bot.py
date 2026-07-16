"""字幕搜索下载 Bot 入口。

启动流程：加载配置 → 初始化日志 → 创建 searcher/bot/handlers → polling。
"""
import logging
import sys

import telebot

from config import load_config
from logging_setup import setup_logging
from services.subtitle_searcher import SubtitleSearcher
from handlers.subtitle_cmd import BotHandlers


def main():
    # 先用基础日志加载配置（配置校验可能退出）
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cfg = load_config()

    # 正式初始化日志（stdout + 轮转文件）
    setup_logging(cfg.log_level)
    logger = logging.getLogger("subtitle_bot")
    logger.info("🎬 字幕搜索下载 Bot 启动中...")

    # 创建 Bot
    bot = telebot.TeleBot(cfg.bot_token, threaded=True, num_threads=4)

    # 设置命令菜单
    try:
        bot.set_my_commands([
            telebot.types.BotCommand("subtitle", "搜索字幕并写入挂载目录"),
            telebot.types.BotCommand("cancel", "取消当前操作"),
            telebot.types.BotCommand("help", "使用帮助"),
        ])
        logger.info("命令菜单已设置")
    except Exception as e:
        logger.warning("设置命令菜单失败: %s", e)

    # 创建 searcher 与 handlers
    searcher = SubtitleSearcher(cfg.opensub_api_key, cfg.enable_scrapers)
    handlers = BotHandlers(bot, cfg, searcher)
    logger.info(
        "Bot 就绪: media_root=%s, scrapers=%s, admin_only=%s",
        cfg.media_root, cfg.enable_scrapers, cfg.bot_admin_id is not None,
    )

    # 启动轮询（自带重连）
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=60)
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出")
    except Exception as e:
        logger.error("Bot 异常: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
