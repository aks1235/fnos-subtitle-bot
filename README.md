# fnos-subtitle-bot

飞牛（fnOS）挂载网盘字幕搜索下载 Telegram Bot。

**核心特点：纯本地文件操作，零网盘 API 调用，规避风控，写入即生效。**

## 工作原理

飞牛已把网盘（夸克/115 等）挂载为本地可读写路径，本 Bot 通过 Telegram 交互式搜索字幕，下载后直接把字幕文件**写入挂载目录**（`os.listdir` + `open().write()`），飞牛媒体库 / Emby / Jellyfin 下次扫描自动识别。

不调用任何网盘官方 API，不依赖 Cookie，不触发网盘风控。

## 功能

- 🎬 **电影**：单字幕写入，命名 `{视频名}.zh.srt`
- 📺 **剧集**：整季字幕包下载解压，按集号匹配每集写入 `{剧集}.E01.zh.srt`
- 📡 **OpenSubtitles API** 为主源（有评分，质量高）
- 🌐 **SubHD / Zimuku 爬虫** 为 fallback（主源不足或限流时自动补充）
- ⏭️ 已有字幕默认跳过，`-f` 强制覆盖
- 📝 Emby/Jellyfin/飞牛通用命名（`.zh` / `.zh-en` / `.en`）

## 部署

### 1. 创建 Bot

Telegram 找 [@BotFather](https://t.me/BotFather) → `/newbot` → 获取 Token。

### 2. 获取 OpenSubtitles API Key

[opensubtitles.com](https://www.opensubtitles.com) 注册 → Profile → API Keys（免费 20下载/天）。

### 3. 配置 docker-compose.yml

```yaml
environment:
  - BOT_TOKEN=你的token
  - OPENSUB_API_KEY=你的key
volumes:
  - /vol02/1000-1-0519e45a:/media/cloud:rw   # ← 左侧改成你的网盘挂载路径
  - ./logs:/logs:rw
```

### 4. 启动

```bash
docker compose up -d --build
docker logs -f fnos-subtitle-bot
```

看到 `🎬 字幕搜索下载 Bot 启动中...` 即成功。

## 使用

```
/subtitle 三国          # 搜索匹配目录
/subtitle -f 三国       # 强制覆盖已有字幕
/cancel                 # 取消当前操作
/help                   # 帮助
```

流程：发关键词 → 选目录 → 选字幕候选 → 自动下载写入 → 完成报告。

## 目录结构要求

挂载根下有「电影」「电视剧」等分类子目录，每个影视一个文件夹：

```
/media/cloud/
├── 电影/
│   └── 让子弹飞 (2010)/
│       └── 让子弹飞.2010.1080p.mp4
└── 电视剧/
    └── 三国演义 (1994)/
        ├── 三国演义.E01.mkv
        └── 三国演义.E02.mkv
```

电影文件夹含单视频，剧集文件夹含多个视频。

## 配置项

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | - | 字幕 Bot 的 Telegram Token |
| `OPENSUB_API_KEY` | ✅ | - | OpenSubtitles API Key |
| `MEDIA_ROOT` | ❌ | `/media/cloud` | 容器内媒体根路径 |
| `BOT_ADMIN_ID` | ❌ | - | 管理员 user_id，限制访问 |
| `SUB_FORMAT_PREF` | ❌ | `srt` | 优先字幕格式 |
| `SUB_LANG_PREF` | ❌ | `zh` | 优先语言 |
| `ENABLE_SCRAPERS` | ❌ | `1` | 启用爬虫 fallback |
| `LOG_LEVEL` | ❌ | `INFO` | 日志级别 |

## 日志

- `docker logs -f fnos-subtitle-bot` — 实时
- `./logs/bot.log` — 历史（5MB × 3 份轮转）

## 换网盘

只需改 compose 中 volume 左侧路径，代码零改动（`/media/cloud` 为中性命名）。

## TODO（后置特性）

- 全量自动扫描缺字幕批量补齐
- 字幕评分/AI 质量判断与推荐
- 多用户并发会话隔离
- Web 配置页 / 统计面板
- 飞牛/Emby 媒体库写入后主动刷新通知

## 免责声明

仅用于个人媒体库字幕补齐，请确保拥有对应影视内容的合法使用权，遵守字幕站点与网盘服务条款。