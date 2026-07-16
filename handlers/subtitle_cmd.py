"""Bot 命令与回调处理：/subtitle 流程 + /help /cancel。"""
import logging

import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import Config
from services.media_scanner import scan_and_filter
from services.session import get_session, reset_session
from services.subtitle_searcher import SubtitleSearcher, clean_search_name
from services.subtitle_writer import write_subtitle_with_url
from services.subtitle_types import SubtitleCandidate
from services.media_scanner import MediaEntry

logger = logging.getLogger(__name__)

DIRS_PER_PAGE = 10
SUBS_PER_PAGE = 8

SOURCE_EMOJI = {
    "opensubtitles": "📡",
    "subhd": "🌐",
    "zimuku": "🌐",
}
LANG_LABEL = {
    "zh": "中文", "zh-en": "中英双语", "en": "英文",
}


class BotHandlers:
    """封装所有命令与回调处理，绑定到给定 bot。"""

    def __init__(self, bot: telebot.TeleBot, config: Config, searcher: SubtitleSearcher):
        self.bot = bot
        self.config = config
        self.searcher = searcher
        self._register()

    def _register(self) -> None:
        """注册全部 handler。"""
        self.bot.message_handler(commands=["start", "help"])(self.on_help)
        self.bot.message_handler(commands=["cancel"])(self.on_cancel)
        self.bot.message_handler(commands=["subtitle"])(self.on_subtitle)
        self.bot.callback_query_handler(func=lambda c: c.data.startswith("dir_"))(self.on_dir_callback)
        self.bot.callback_query_handler(func=lambda c: c.data.startswith("sub_"))(self.on_sub_callback)

    # ---------- 命令 ----------

    def on_help(self, message):
        self.bot.send_message(
            message.chat.id,
            (
                "🎬 <b>字幕搜索下载 Bot</b>\n\n"
                "<b>命令</b>\n"
                "<code>/subtitle 关键词</code> — 搜索匹配目录并下载字幕\n"
                "<code>/subtitle -f 关键词</code> — 强制覆盖已有字幕\n"
                "<code>/cancel</code> — 取消当前操作\n\n"
                "<b>流程</b>\n"
                "1. 发送 <code>/subtitle 电影名</code>\n"
                "2. 选择对应影视目录\n"
                "3. 选择字幕候选\n"
                "4. 自动下载并写入挂载目录\n\n"
                "字幕源：📡 OpenSubtitles + 🌐 SubHD / Zimuku\n"
                "写入即生效，飞牛/Emby 下次扫描自动识别。"
            ),
            parse_mode="HTML",
        )

    def on_cancel(self, message):
        reset_session(message.chat.id)
        self.bot.send_message(message.chat.id, "✅ 已取消当前操作")

    def on_subtitle(self, message):
        chat_id = message.chat.id

        # 管理员鉴权
        if self.config.bot_admin_id is not None and message.from_user.id != self.config.bot_admin_id:
            self.bot.send_message(chat_id, "❌ 无权使用该 Bot")
            return

        # 解析 -f 和关键词
        text = (message.text or "").strip()
        force = "-f" in text.split()
        clean_text = " ".join(w for w in text.split() if w != "-f")
        # 去掉 /subtitle 命令本身
        parts = clean_text.split(maxsplit=1)
        keyword = parts[1].strip() if len(parts) > 1 else ""

        if not keyword:
            self.bot.send_message(
                chat_id,
                "请输入搜索关键词，例如：\n<code>/subtitle 三国</code>\n"
                "强制覆盖已有字幕：<code>/subtitle -f 三国</code>",
                parse_mode="HTML",
            )
            return

        session = get_session(chat_id)
        session.stage = "pick_dir"
        session.keyword = keyword
        session.force = force
        session.entry_page = 0
        session.selected_entry = None
        session.candidates = []

        status = self.bot.send_message(chat_id, "🔍 正在扫描媒体目录...")

        try:
            entries = scan_and_filter(keyword, self.config.media_root)
            session.entries = entries
        except Exception as e:
            logger.error("目录扫描异常: %s", e)
            self.bot.edit_message_text(
                f"❌ 目录扫描失败: {e}", chat_id, status.message_id
            )
            reset_session(chat_id)
            return

        if not entries:
            self.bot.edit_message_text(
                f"❌ 未找到匹配「<b>{keyword}</b>」的目录\n\n"
                "请检查关键词拼写或 <code>MEDIA_ROOT</code> 配置。",
                chat_id, status.message_id, parse_mode="HTML",
            )
            reset_session(chat_id)
            return

        self._render_dirs(chat_id, session, status.message_id)

    # ---------- 目录选择回调 ----------

    def on_dir_callback(self, call):
        chat_id = call.message.chat.id
        msg_id = call.message.message_id
        session = get_session(chat_id)
        data = call.data

        if data == "dir_cancel":
            reset_session(chat_id)
            self.bot.edit_message_text("❌ 已取消", chat_id, msg_id)
            return
        if data == "dir_prev":
            session.entry_page = max(0, session.entry_page - 1)
            self._render_dirs(chat_id, session, msg_id)
            return
        if data == "dir_next":
            max_page = max(0, (len(session.entries) - 1) // DIRS_PER_PAGE)
            session.entry_page = min(max_page, session.entry_page + 1)
            self._render_dirs(chat_id, session, msg_id)
            return

        # 选具体目录 dir_<idx>
        try:
            idx = int(data.removeprefix("dir_")) - 1
        except ValueError:
            self.bot.answer_callback_query(call.id, "无效选择")
            return

        if idx < 0 or idx >= len(session.entries):
            self.bot.answer_callback_query(call.id, "无效选择")
            return

        entry = session.entries[idx]
        session.selected_entry = entry
        session.stage = "pick_sub"

        search_name = clean_search_name(entry.name)
        self.bot.edit_message_text(
            f"✅ 已选择: <b>{entry.name}</b>\n"
            f"📁 路径: {entry.rel_path or entry.name}\n"
            f"🎬 类型: {'剧集' if entry.is_tv else '电影'} "
            f"({len(entry.videos)} 个视频)\n\n"
            f"🔍 搜索字幕 «{search_name}» ...",
            chat_id, msg_id, parse_mode="HTML",
        )

        try:
            sr = self.searcher.search(search_name, entry.is_tv)
            session.candidates = sr.candidates
            session.primary_available = sr.primary_available
        except Exception as e:
            logger.error("字幕搜索异常: %s", e)
            self.bot.send_message(chat_id, f"❌ 字幕搜索失败: {e}")
            reset_session(chat_id)
            return

        if not session.candidates:
            self.bot.send_message(
                chat_id,
                f"❌ 未找到「<b>{search_name}</b>」的字幕\n"
                "可尝试英文名或其他关键词。",
                parse_mode="HTML",
            )
            reset_session(chat_id)
            return

        self._render_subs(chat_id, session)

    # ---------- 字幕选择回调 ----------

    def on_sub_callback(self, call):
        chat_id = call.message.chat.id
        msg_id = call.message.message_id
        session = get_session(chat_id)
        data = call.data

        if data == "sub_cancel":
            reset_session(chat_id)
            self.bot.edit_message_text("❌ 已取消", chat_id, msg_id)
            return

        # 处理翻页 sub_next/sub_prev
        if data in ("sub_prev", "sub_next"):
            if data == "sub_prev":
                session.sub_page = max(0, session.sub_page - 1)
            else:
                max_page = max(0, (len(session.candidates) - 1) // SUBS_PER_PAGE)
                session.sub_page = min(max_page, session.sub_page + 1)
            self._render_subs(chat_id, session, msg_id)
            return

        try:
            idx = int(data.removeprefix("sub_")) - 1
        except ValueError:
            self.bot.answer_callback_query(call.id, "无效选择")
            return

        if idx < 0 or idx >= len(session.candidates):
            self.bot.answer_callback_query(call.id, "无效选择")
            return

        candidate = session.candidates[idx]
        entry = session.selected_entry
        if entry is None:
            self.bot.answer_callback_query(call.id, "会话失效，请重新搜索")
            reset_session(chat_id)
            return

        self.bot.edit_message_text(
            f"⬇️ 下载中...\n📄 {candidate.title[:60]}\n📡 {candidate.source}",
            chat_id, msg_id,
        )

        # 获取下载 URL 并写入
        try:
            url = self.searcher.fetch_url(candidate)
            if not url:
                self.bot.send_message(chat_id, "❌ 无法获取下载链接，请选其他候选")
                reset_session(chat_id)
                return

            result = write_subtitle_with_url(candidate, url, entry, session.force)
        except Exception as e:
            logger.error("字幕写入异常: %s", e)
            self.bot.send_message(chat_id, f"❌ 写入失败: {e}")
            reset_session(chat_id)
            return

        self._report_result(chat_id, candidate, entry, result)
        reset_session(chat_id)

    # ---------- 渲染 ----------

    def _render_dirs(self, chat_id, session, msg_id=0):
        entries = session.entries
        total = len(entries)
        start = session.entry_page * DIRS_PER_PAGE
        end = min(start + DIRS_PER_PAGE, total)
        page = entries[start:end]

        lines = [
            f"🔍 匹配「<b>{session.keyword}</b>」",
            f"找到 <b>{total}</b> 个目录（第 {session.entry_page + 1} 页）\n",
        ]
        kb = InlineKeyboardMarkup(row_width=1)
        for i, e in enumerate(page):
            idx = start + i + 1
            tag = "📺" if e.is_tv else "🎬"
            label = f"{idx}. {tag} {e.name}"[:60]
            lines.append(f"{idx}. {tag} {e.name}  <i>{e.rel_path}</i>")
            kb.add(InlineKeyboardButton(label, callback_data=f"dir_{idx}"))

        nav = []
        if session.entry_page > 0:
            nav.append(InlineKeyboardButton("◀️ 上一页", callback_data="dir_prev"))
        if end < total:
            nav.append(InlineKeyboardButton("▶️ 下一页", callback_data="dir_next"))
        if nav:
            kb.row(*nav)
        kb.row(InlineKeyboardButton("❌ 取消", callback_data="dir_cancel"))

        text = "\n".join(lines)
        if msg_id:
            try:
                self.bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb, parse_mode="HTML")
                return
            except Exception:
                pass
        self.bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

    def _render_subs(self, chat_id, session, msg_id=0):
        cands = session.candidates
        total = len(cands)
        start = session.sub_page * SUBS_PER_PAGE
        end = min(start + SUBS_PER_PAGE, total)
        page = cands[start:end]

        prefix = "🔄 强制覆盖模式" if session.force else ""
        warning = "" if session.primary_available else "\n⚠️ 主源不可用，使用备用源"
        lines = [
            f"🔍 「<b>{session.selected_entry.name}</b>」字幕候选 {prefix}{warning}",
            f"共 <b>{total}</b> 个（第 {session.sub_page + 1} 页）\n",
        ]
        kb = InlineKeyboardMarkup(row_width=1)
        for i, c in enumerate(page):
            idx = start + i + 1
            emoji = SOURCE_EMOJI.get(c.source, "📄")
            lang = LANG_LABEL.get(c.lang_norm, c.lang_norm)
            star = f" ⭐{c.rating:.1f}" if c.rating > 0 else ""
            pack = " [整季]" if c.is_season_pack else ""
            lines.append(
                f"{idx}. {c.title[:50]}{star}{pack}\n"
                f"   {emoji} {c.source} | {lang} | {c.fmt.upper()}"
            )
            label = f"{idx}. [{c.fmt.upper()}]{lang}{pack} {c.title[:30]}"[:64]
            kb.add(InlineKeyboardButton(label, callback_data=f"sub_{idx}"))

        nav = []
        if session.sub_page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data="sub_prev"))
        if end < total:
            nav.append(InlineKeyboardButton("▶️", callback_data="sub_next"))
        if nav:
            kb.row(*nav)
        kb.row(InlineKeyboardButton("❌ 取消", callback_data="sub_cancel"))

        text = "\n".join(lines)
        if msg_id:
            try:
                self.bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb, parse_mode="HTML")
                return
            except Exception:
                pass
        self.bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

    def _report_result(self, chat_id, candidate: SubtitleCandidate, entry: MediaEntry, result):
        if result.error:
            self.bot.send_message(
                chat_id,
                f"❌ 失败: {result.error}\n请尝试其他候选。",
            )
            return

        parts = [f"✅ <b>字幕处理完成</b>\n📁 {entry.rel_path or entry.name}"]
        if result.written:
            parts.append(f"\n📝 写入 {len(result.written)} 个：")
            for fn in result.written[:10]:
                parts.append(f"  • {fn}")
            if len(result.written) > 10:
                parts.append(f"  ... 共 {len(result.written)} 个")
        if result.skipped:
            parts.append(f"\n⏭️ 跳过 {len(result.skipped)} 个（已有字幕）")
        if result.unmatched:
            parts.append(f"\n⚠️ {len(result.unmatched)} 个未匹配集号，已放目录根")
        if not result.written and not result.unmatched:
            parts.append("\n（无字幕写入）")

        parts.append(f"\n📡 来源: {candidate.source} | 🌐 {candidate.lang_norm}")
        self.bot.send_message(chat_id, "\n".join(parts), parse_mode="HTML")
