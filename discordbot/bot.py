import os
import re
import time
import random
import discord
import tempfile
import logging
import datetime
import asyncio
import base64
from discord import app_commands
from cappuccino_agent import CappuccinoAgent
import json
import feedparser
import aiohttp
from bs4 import BeautifulSoup

# 音声読み上げや文字起こし機能は削除したため関連ライブラリは不要
from urllib.parse import urlparse, parse_qs, urlunparse
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

from dataclasses import dataclass
from typing import Any

from .poker import PokerMatch, PokerView


# ───────────────── TOKEN / KEY ─────────────────
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from .env if present
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# Load credentials from environment variables
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CAPP_API_URL = os.getenv("CAPP_API_URL", "http://163.43.113.161:8000/agent/run")


NEWS_CONF_FILE = os.path.join(ROOT_DIR, "news_channel.json")
EEW_CONF_FILE = os.path.join(ROOT_DIR, "eew_channel.json")
EEW_LAST_FILE = os.path.join(ROOT_DIR, "last_eew.txt")
WEATHER_CONF_FILE = os.path.join(ROOT_DIR, "weather_channel.json")

def _load_news_channel() -> int:
    try:
        with open(NEWS_CONF_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return int(data.get("channel_id", 0))
    except Exception:
        pass
    return 0

def _save_news_channel(ch_id: int) -> None:
    try:
        with open(NEWS_CONF_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"channel_id": ch_id}, f, ensure_ascii=False, indent=2)
        os.replace(NEWS_CONF_FILE + ".tmp", NEWS_CONF_FILE)
    except Exception as e:
        logger.error("failed to save news channel: %s", e)

def _load_eew_channel() -> int:
    try:
        with open(EEW_CONF_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return int(data.get("channel_id", 0))
    except Exception:
        pass
    return 0

def _save_eew_channel(ch_id: int) -> None:
    try:
        with open(EEW_CONF_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"channel_id": ch_id}, f, ensure_ascii=False, indent=2)
        os.replace(EEW_CONF_FILE + ".tmp", EEW_CONF_FILE)
    except Exception as e:
        logger.error("failed to save eew channel: %s", e)

def _load_weather_channel() -> int:
    try:
        with open(WEATHER_CONF_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return int(data.get("channel_id", 0))
    except Exception:
        pass
    return 0

def _save_weather_channel(ch_id: int) -> None:
    try:
        with open(WEATHER_CONF_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"channel_id": ch_id}, f, ensure_ascii=False, indent=2)
        os.replace(WEATHER_CONF_FILE + ".tmp", WEATHER_CONF_FILE)
    except Exception as e:
        logger.error("failed to save weather channel: %s", e)

def _load_last_eew() -> str:
    try:
        with open(EEW_LAST_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

def _save_last_eew(eid: str) -> None:
    try:
        with open(EEW_LAST_FILE, "w", encoding="utf-8") as f:
            f.write(eid)
    except Exception as e:
        logger.error("failed to save eew id: %s", e)

NEWS_CHANNEL_ID = _load_news_channel()
EEW_CHANNEL_ID = _load_eew_channel()
LAST_EEW_ID = _load_last_eew()
WEATHER_CHANNEL_ID = _load_weather_channel()

# Initialize CappuccinoAgent for GPT interactions
cappuccino_agent = CappuccinoAgent(api_key=OPENAI_API_KEY)

async def call_cappuccino_api(prompt: str) -> tuple[str, list[discord.File]]:
    """Send query to Cappuccino API and return text and image files."""
    async with aiohttp.ClientSession() as sess:
        async with sess.post(CAPP_API_URL, json={"query": prompt}, timeout=120) as resp:
            resp.raise_for_status()
            data = await resp.json()

    text = data.get("text", "")
    images = []
    for i, img in enumerate(data.get("images", [])):
        try:
            _, b64 = img.split(",", 1)
            binary = base64.b64decode(b64)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.write(binary)
            tmp.close()
            images.append(discord.File(tmp.name, filename=f"image_{i+1}.png"))
        except Exception as e:
            logger.error("failed to decode image: %s", e)
    return text, images

# ───────────────── Voice Transcription / TTS ─────────────────

# ───────────────── Logger ─────────────────
handler = RotatingFileHandler('bot.log', maxBytes=1_000_000, backupCount=5, encoding='utf-8')
logging.basicConfig(level=logging.INFO, handlers=[handler])
logging.getLogger('discord').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# チャンネル型の許可タプル (Text / Thread / Stage)
MESSAGE_CHANNEL_TYPES: tuple[type, ...] = (
    discord.TextChannel,
    discord.Thread,
    discord.StageChannel,
    discord.VoiceChannel,
)

# ───────────────── Logger ─────────────────

# ───────────────── Discord 初期化 ─────────────────
intents = discord.Intents.default()
intents.message_content = True          # メッセージ内容を取得
intents.reactions = True 
intents.members   = True
intents.presences = True 
intents.voice_states    = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ───────────────── 便利関数 ─────────────────
def parse_cmd(content: str):
    """
    y!cmd / y? 解析。戻り値 (cmd, arg) or (None, None)
    """
    if content.startswith("y?"):
        return "gpt", content[2:].strip()
    if not content.startswith("y!"):
        return None, None
    body = content[2:].strip()

    # Dice 記法 (例 3d6, d20, 1d100)
    if re.fullmatch(r"\d*d\d+", body, re.I):
        return "dice", body

    parts = body.split(maxsplit=1)
    return parts[0].lower(), parts[1] if len(parts) > 1 else ""


async def _gather_reply_chain(msg: discord.Message, limit: int | None = None) -> list[discord.Message]:
    """Return the full reply chain for ``msg``.

    If ``limit`` is given, stop after that many messages. When ``limit`` is
    ``None`` (default) the chain is collected until no reference is present.
    ``SlashMessage`` instances are ignored because interactions cannot reply to
    other messages.
    """
    chain: list[discord.Message] = []
    current = msg
    while getattr(current, "reference", None):
        if limit is not None and len(chain) >= limit:
            break
        try:
            current = await current.channel.fetch_message(current.reference.message_id)
        except Exception:
            break
        chain.append(current)
    chain.reverse()
    return chain


def _strip_bot_mention(text: str) -> str:
    if client.user is None:
        return text.strip()
    return re.sub(fr"<@!?{client.user.id}>", "", text).strip()


class _SlashChannel:
    """Proxy object for sending/typing via Interaction."""

    def __init__(self, interaction: discord.Interaction):
        self._itx = interaction
        self._channel = interaction.channel

    def __getattr__(self, name):
        return getattr(self._channel, name)

    async def send(self, *args, **kwargs):
        delete_after = kwargs.pop("delete_after", None)

        if not self._itx.response.is_done():
            await self._itx.response.send_message(*args, **kwargs)
            message = await self._itx.original_response()
        else:
            message = await self._itx.followup.send(*args, **kwargs)

        if delete_after is not None:
            await asyncio.sleep(delete_after)
            try:
                await message.delete()
            except discord.NotFound:
                pass

        return message


    def typing(self):
        return self._channel.typing()


class SlashMessage:
    """Wrap discord.Interaction to mimic discord.Message."""

    def __init__(self, interaction: discord.Interaction, attachments: list[discord.Attachment] | None = None):
        self._itx = interaction
        self.channel = _SlashChannel(interaction)
        self.guild = interaction.guild
        self.author = interaction.user
        self.id = interaction.id
        self.attachments: list[discord.Attachment] = attachments or []

    async def reply(self, *args, **kwargs):
        return await self.channel.send(*args, **kwargs)

    async def add_reaction(self, emoji):
        await self.channel.send(emoji)


from yt_dlp import YoutubeDL
YTDL_OPTS = {
    "quiet": True,
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "default_search": "ytsearch",
}

WMO_CODES = {
    0: "快晴",
    1: "晴れ",
    2: "晴れ時々曇り",
    3: "曇り",
    45: "霧",
    48: "霧",
    51: "弱い霧雨",
    53: "霧雨",
    55: "強い霧雨",
    56: "氷霧雨",
    57: "強い氷霧雨",
    61: "弱い雨",
    63: "雨",
    65: "強い雨",
    66: "弱いみぞれ",
    67: "強いみぞれ",
    71: "弱い雪",
    73: "雪",
    75: "強い雪",
    77: "細かい雪",
    80: "にわか雨",
    81: "にわか雨",
    82: "激しいにわか雨",
    85: "にわか雪",
    86: "激しいにわか雪",
    95: "雷雨",
    96: "雷雨(弱い雹)",
    99: "雷雨(強い雹)",
}

# ──────────────── Help Pages ────────────────
# Embed titles and descriptions for each help category
HELP_PAGES: list[tuple[str, str]] = [
    (
        "すべて",
        "\n".join(
            [
                "🎵 音楽機能",
                "y!play … 添付ファイルを先に、テキストはカンマ区切りで順に追加",
                "/play … query/file 引数を入力した順に追加 (query 内のカンマは分割されません)",
                "/queue, y!queue : キューの表示や操作（Skip/Shuffle/Loop/Pause/Resume/Leaveなど）",
                "/remove <番号>, y!remove <番号> : 指定した曲をキューから削除",
                "/keep <番号>, y!keep <番号> : 指定番号以外の曲をまとめて削除",
                "/stop, y!stop : VCから退出",
                "/seek <時間>, y!seek <時間> : 再生位置を変更",
                "/rewind <時間>, y!rewind <時間> : 再生位置を指定秒数だけ巻き戻し",
                "/forward <時間>, y!forward <時間> : 再生位置を指定秒数だけ早送り",
                "　※例: y!rewind 1分, y!forward 30, /rewind 1:10",
                "",
                "💬 翻訳機能",
                "国旗リアクションで自動翻訳",
                "",
                "🤖 AI/ツール",
                "/gpt <質問>, y? <質問> : ChatGPT（GPT-4.1）で質問や相談ができるAI回答",
                "",
                "🧑 ユーザー情報",
                "/user [ユーザー], y!user <@メンション|ID> : プロフィール表示",
                "/server, y!server : サーバー情報表示",
                "",
                "🕹️ その他",
                "/ping, y!ping : 応答速度",
                "/say <text>, y!say <text> : エコー",
                "/date, y!date : 日時表示（/dateはtimestampオプションもOK）",
                "/dice, y!XdY : ダイス（例: 2d6）",
                "/qr <text>, y!qr <text> : QRコード画像を生成",
                "/barcode <text>, y!barcode <text> : バーコード画像を生成",
                "/tex <式>, y!tex <式> : TeX 数式を画像に変換",

                "/news <#channel>, y!news <#channel> : ニュース投稿チャンネルを設定",
                "/eew <#channel>, y!eew <#channel> : 地震速報チャンネルを設定",
                "/weather <#channel>, y!weather <#channel> : 天気予報チャンネルを設定",

                "/poker [@user], y!poker [@user] : 1vs1 ポーカーで対戦",

                "/purge <n|link>, y!purge <n|link> : メッセージ一括削除",
                "/help, y!help : このヘルプ",
                "y!? … 返信で使うと名言化",
                "",
                "🔰 コマンドの使い方",
                "テキストコマンド: y!やy?などで始めて送信",
                "　例: y!play Never Gonna Give You Up",
                "スラッシュコマンド: /で始めてコマンド名を選択",
                "　例: /play /queue /remove 1 2 3 /keep 2 /gpt 猫とは？",
            ]
        ),
    ),
    (
        "🎵 音楽",
        "\n".join(
            [
                "y!play <URL|キーワード> : 再生キューに追加 (カンマ区切りで複数指定可)",
                "　例: y!play Never Gonna Give You Up, Bad Apple!!",
                "/play はファイル添付もOK、入力順に再生",
                "/queue でキューを表示、ボタンから Skip/Loop など操作",
                "/remove 2 で2番目を削除、/keep 1 で1曲だけ残す",
                "/seek 1:30 で1分30秒へ移動、/forward 30 で30秒早送り",
                "/stop または y!stop でボイスチャンネルから退出",
            ]
        ),
    ),
    (
        "💬 翻訳",
        "\n".join(
            [
                "メッセージに国旗リアクションを付けるとその言語へ自動翻訳",
                "　例: 🇺🇸 を押すと英語に翻訳、🇰🇷 なら韓国語に翻訳",
                "GPT-4.1 が翻訳文を生成し返信します (2000文字制限あり)",
            ]
        ),
    ),
    (
        "🤖 AI/ツール",
        "\n".join(
            [
                "/gpt <質問>, y? <質問> : ChatGPT（GPT-4.1）へ質問",
                "　例: /gpt Pythonとは？",
                "/qr <text>, y!qr <text> : QRコード画像を生成",
                "/barcode <text>, y!barcode <text> : Code128 バーコードを生成",
                "/tex <式>, y!tex <式> : TeX 数式を画像化",
                "どのコマンドもテキスト/スラッシュ形式に対応",
            ]
        ),
    ),
    (
        "🧑 ユーザー情報",
        "\n".join(
            [
                "/user [ユーザー] : 指定ユーザーのプロフィールを表示",
                "　例: /user @someone または y!user 1234567890",
                "/server : 現在のサーバー情報を表示",
                "自分にも他人にも使用できます",
            ]
        ),
    ),
    (
        "🕹️ その他",
        "\n".join(
            [
                "/ping : BOTの応答速度を測定",
                "/say <text> : 入力内容をそのまま返答 (2000文字超はファイル)",
                "/date [timestamp] : 日付を表示。省略時は現在時刻",
                "/dice または y!XdY : サイコロを振る (例: 2d6)",
                "/news <#channel> : ニュース投稿先を設定 (管理者のみ)",
                "/eew <#channel> : 地震速報の通知先を設定 (管理者のみ)",
                "/weather <#channel> : 天気予報の投稿先を設定 (管理者のみ)",
                "/poker [@user] : 友達やBOTと1vs1ポーカー対戦",
                "/purge <n|link> : メッセージをまとめて削除",
                "返信で y!? と送るとその内容を名言化",
            ]
        ),
    ),
    (
        "🔰 使い方",
        "\n".join(
            [
                "テキストコマンドは y! または y? から入力",
                "スラッシュコマンドは / を押してコマンド名を選択",
                "音楽系はボイスチャンネルに参加してから実行してね",
                "複数曲追加はカンマ区切り: y!play 曲1, 曲2",
                "/news や /eew など一部コマンドは管理者専用",
                "分からなくなったら /help または y!help でこの画面を表示",
            ]
        ),
    ),
]



@dataclass
class Track:
    title: str
    url: str
    duration: int | None = None

def yt_extract(url_or_term: str) -> list[Track]:
    """URL か検索語から Track 一覧を返す (単曲の場合は長さ1)"""
    with YoutubeDL(YTDL_OPTS) as ydl:
        info = ydl.extract_info(url_or_term, download=False)
        if "entries" in info:
            if info.get("_type") == "playlist":
                results = []
                for ent in info.get("entries", []):
                    if ent:
                        results.append(Track(ent.get("title", "?"), ent.get("url", ""), ent.get("duration")))
                return results
            info = info["entries"][0]
        return [Track(info.get("title", "?"), info.get("url", ""), info.get("duration"))]


async def attachment_to_track(att: discord.Attachment) -> Track:
    """Discord 添付ファイルを一時保存して Track に変換"""
    fd, path = tempfile.mkstemp(prefix="yone_", suffix=os.path.splitext(att.filename)[1])
    os.close(fd)
    await att.save(path)
    return Track(att.filename, path)


async def attachments_to_tracks(attachments: list[discord.Attachment]) -> list[Track]:
    """複数添付ファイルを並列で Track に変換"""
    tasks = [attachment_to_track(a) for a in attachments]
    return await asyncio.gather(*tasks)


def yt_extract_multiple(urls: list[str]) -> list[Track]:
    """複数 URL を順に yt_extract して Track をまとめて返す"""
    tracks: list[Track] = []
    for url in urls:
        try:
            tracks.extend(yt_extract(url))
        except Exception as e:
            logger.error("取得失敗 (%s): %s", url, e)
    return tracks


def is_http_source(path_or_url: str) -> bool:
    """http/https から始まる URL か判定"""
    return path_or_url.startswith(("http://", "https://"))


def is_playlist_url(url: str) -> bool:
    """URL に playlist パラメータが含まれるか簡易判定"""
    try:
        qs = parse_qs(urlparse(url).query)
        return 'list' in qs
    except Exception:
        return False




def is_http_url(url: str) -> bool:
    """http/https から始まる URL か判定"""
    return url.startswith("http://") or url.startswith("https://")


def parse_urls_and_text(query: str) -> tuple[list[str], str]:
    """文字列から URL 一覧と残りのテキストを返す"""
    urls = re.findall(r"https?://\S+", query)
    text = re.sub(r"https?://\S+", "", query).strip()
    return urls, text


def split_by_commas(text: str) -> list[str]:
    """カンマ区切りで分割し、空要素は除外"""
    return [t.strip() for t in text.split(",") if t.strip()]


async def add_playlist_lazy(state: "MusicState", playlist_url: str,
                            voice: discord.VoiceClient,
                            channel: discord.TextChannel):
    """プレイリストの曲を逐次取得してキューへ追加"""
    task = asyncio.current_task()
    qs = parse_qs(urlparse(playlist_url).query)
    list_id = qs.get("list", [None])[0]
    if list_id:
        playlist_url = f"https://www.youtube.com/playlist?list={list_id}"
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(
        None,
        lambda: YoutubeDL({**YTDL_OPTS, "extract_flat": True}).extract_info(
            playlist_url, download=False)
    )
    entries = info.get("entries", [])
    if not entries:
        await channel.send("⚠️ プレイリストに曲が見つかりませんでした。", delete_after=5)
        return
    await channel.send(f"⏱️ プレイリストを読み込み中... ({len(entries)}曲)")
    for ent in entries:
        if task.cancelled() or not voice.is_connected():
            break
        url = ent.get("url")
        if not url:
            continue
        try:
            tracks = await loop.run_in_executor(None, yt_extract, url)
        except Exception as e:
            logger.error("取得失敗 (%s): %s", url, e)
            continue
        if not tracks:
            continue
        state.queue.append(tracks[0])
        await refresh_queue(state)
        if not voice.is_playing() and not state.play_next.is_set():
            client.loop.create_task(state.player_loop(voice, channel))
    await channel.send(f"✅ プレイリストの読み込みが完了しました ({len(entries)}曲)", delete_after=10)


def cleanup_track(track: Track | None):
    """ローカルファイルの場合は削除"""
    if track and os.path.exists(track.url):
        try:
            os.remove(track.url)
        except Exception as e:
            logger.error("cleanup failed for %s: %s", track.url, e)


def parse_message_link(link: str) -> tuple[int, int, int] | None:
    """Discord メッセージリンクを guild, channel, message ID に分解"""
    m = re.search(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)", link)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))
    
import collections

def fmt_time(sec: int) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def parse_seek_time(text: str) -> int:
    """文字列から秒数を取得 (hms または : 区切り)"""
    t = text.lower().replace(" ", "")
    if any(c in t for c in "hms"):
        matches = re.findall(r"(\d+)([hms])", t)
        if not matches or "".join(num+unit for num, unit in matches) != t:
            raise ValueError
        values = {}
        for num, unit in matches:
            if unit in values:
                raise ValueError
            values[unit] = int(num)
        h = values.get("h", 0)
        m = values.get("m", 0)
        s = values.get("s", 0)
        if h == m == s == 0:
            raise ValueError
        return h*3600 + m*60 + s
    else:
        clean = "".join(c for c in t if c.isdigit() or c == ":")
        parts = clean.split(":")
        if not (1 <= len(parts) <= 3):
            raise ValueError
        try:
            nums = [int(x) for x in parts]
        except Exception:
            raise ValueError
        while len(nums) < 3:
            nums.insert(0, 0)
        h, m, s = nums
        return h*3600 + m*60 + s

def fmt_time_jp(sec: int) -> str:
    """秒数を日本語で表現"""
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}時間")
    if m:
        parts.append(f"{m}分")
    if s or not parts:
        parts.append(f"{s}秒")
    return "".join(parts)

def make_bar(pos: int, total: int, width: int = 15) -> str:
    if total <= 0:
        return "".ljust(width, "─")
    index = round(pos / total * (width - 1))
    return "━" * index + "⚪" + "─" * (width - index - 1)

def num_emoji(n: int) -> str:
    emojis = ["0️⃣","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    return emojis[n] if 0 <= n < len(emojis) else f'[{n}]'

class MusicState:
    def __init__(self):
        self.queue   = collections.deque()   # 再生待ち Track 一覧
        self.loop    = 0  # 0:OFF,1:SONG,2:QUEUE
        self.auto_leave = True             # 全員退出時に自動で切断するか
        self.current: Track | None = None
        self.play_next = asyncio.Event()
        self.queue_msg: discord.Message | None = None
        self.panel_owner: int | None = None
        self.start_time: float | None = None
        self.pause_offset: float = 0.0
        self.is_paused: bool = False
        self.playlist_task: asyncio.Task | None = None
        self.seek_to: int | None = None
        self.seeking: bool = False

    async def player_loop(self, voice: discord.VoiceClient, channel: discord.TextChannel):
        """
        キューが続く限り再生し続けるループ。
        self.current に再生中タプル (title,url) をセットし、
        曲が変わるたびに refresh_queue() を呼んで Embed を更新。
        """
        while True:
            self.play_next.clear()

            # キューが空なら 5 秒待機→まだ空なら切断
            if not self.queue:
                await asyncio.sleep(5)
                if not self.queue:
                    await voice.disconnect()
                    if self.queue_msg:
                        try:
                            await self.queue_msg.delete()
                        except Exception:
                            pass
                        self.queue_msg = None
                        self.panel_owner = None
                    return

            # 再生準備
            self.current = self.queue[0]
            seek_pos = self.seek_to
            announce = not self.seeking
            self.seek_to = None
            self.seeking = False
            title, url = self.current.title, self.current.url
            self.is_paused = False
            self.pause_offset = 0

            before_opts = ""
            if seek_pos is not None:
                before_opts += f"-ss {seek_pos} "
            before_opts += (
                "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                if is_http_source(url) else ""
            )
            try:
                ffmpeg_audio = discord.FFmpegPCMAudio(
                    source=url,
                    executable="ffmpeg",
                    before_options=before_opts.strip(),
                    options='-vn -loglevel warning -af "volume=0.9"'
                )
                voice.play(ffmpeg_audio, after=lambda _: self.play_next.set())
            except FileNotFoundError:
                logger.error("ffmpeg executable not found")
                await channel.send(
                    "⚠️ **ffmpeg が見つかりません** — サーバーに ffmpeg をインストールして再試行してください。",
                    delete_after=5
                )
                cleanup_track(self.queue.popleft())
                continue
            except Exception as e:
                logger.error(f"ffmpeg 再生エラー: {e}")
                await channel.send(
                    f"⚠️ `{title}` の再生に失敗しました（{e}）",
                    delete_after=5
                )
                cleanup_track(self.queue.popleft())
                continue

            self.start_time = time.time() - (seek_pos or 0)




            # チャット通知 & Embed 更新
            if announce:
                await channel.send(f"▶️ **Now playing**: {title}")
            await refresh_queue(self)

            progress_task = asyncio.create_task(progress_updater(self))

            # 次曲まで待機
            await self.play_next.wait()
            progress_task.cancel()
            self.start_time = None
            if self.seek_to is not None:
                await refresh_queue(self)
                continue

            # ループOFFなら再生し終えた曲をキューから外す
            if self.loop == 0 and self.queue:
                finished = self.queue.popleft()
                cleanup_track(finished)
            elif self.loop == 2 and self.queue:
                self.queue.rotate(-1)

            await refresh_queue(self)


# クラス外でOK
async def refresh_queue(state: "MusicState"):
    """既存のキュー Embed と View を最新内容に書き換える"""
    if not state.queue_msg:
        return
    try:
        vc = state.queue_msg.guild.voice_client
        if not vc or not vc.is_connected():
            await state.queue_msg.delete()
            state.queue_msg = None
            state.panel_owner = None
            return
        owner = state.panel_owner or state.queue_msg.author.id
        view = QueueRemoveView(state, vc, owner)
        await state.queue_msg.edit(embed=make_embed(state), view=view)
    except discord.HTTPException:
        pass

async def progress_updater(state: "MusicState"):
    """再生中は1秒ごとにシークバーを更新"""
    try:
        while True:
            await asyncio.sleep(1)
            await refresh_queue(state)
    except asyncio.CancelledError:
        pass

# ──────────── 🖼 名言化 APIヘルパ ────────────
import pathlib

FAKEQUOTE_URL = "https://api.voids.top/fakequote"

async def make_quote_image(user, text, color=False) -> pathlib.Path:
    """FakeQuote API で名言カードを生成しローカル保存 → Path を返す"""
    payload = {
        "username"    : user.name,
        "display_name": user.display_name,
        "text"        : text[:200],
        "avatar"      : user.display_avatar.url,
        "color"       : color,
    }

    async with aiohttp.ClientSession() as sess:
        async with sess.post(
            FAKEQUOTE_URL,
            json=payload,
            headers={"Accept": "text/plain"},
            timeout=10
        ) as r:
            # 200, 201 どちらも成功扱いにする
            raw = await r.text()
            # Content-Type が text/plain でも JSON が来るので自前でパースを試みる
            try:
                data = json.loads(raw)
                if not data.get("success", True):
                    raise RuntimeError(data)
                img_url = data["url"]
            except json.JSONDecodeError:
                # プレーンで URL だけ返ってきた場合
                img_url = raw.strip()

        async with sess.get(img_url) as img:
            img_bytes = await img.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(img_bytes)
        tmp_path = pathlib.Path(tmp.name)

    return tmp_path

# ──────────── ボタン付き View ────────────

class QuoteView(discord.ui.View):
    def __init__(self, invoker: discord.User, payload: dict):
        super().__init__(timeout=None)
        self.invoker = invoker    # 操作できる人
        self.payload = payload    # {user, text, color}

    # ── 作った人だけ操作可能 ──
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                "このボタンはコマンドを実行した人だけ使えます！",
                ephemeral=True,
            )
            return False
        return True


    async def _regen(self, interaction: discord.Interaction):
        path = await make_quote_image(**self.payload)
        await interaction.response.edit_message(
            attachments=[discord.File(path, filename=path.name)],
            view=self
        )
        try:
            path.unlink()
        except Exception:
            pass


    @discord.ui.button(label="🎨 カラー", style=discord.ButtonStyle.success)
    async def btn_color(self, inter: discord.Interaction, _):
        try:
            self.payload["color"] = True
            await self._regen(inter)
        except Exception:
            await inter.response.send_message(
                "⚠️ この操作パネルは無効です。\n"
                "`y!?` をもう一度返信してみてね！",
                ephemeral=True,
            )

    @discord.ui.button(label="⚫ モノクロ", style=discord.ButtonStyle.secondary)
    async def btn_mono(self, inter: discord.Interaction, _):
        try:
            self.payload["color"] = False
            await self._regen(inter)
        except Exception:
            await inter.response.send_message(
                "⚠️ この操作パネルは無効です。\n"
                "`y!?` をもう一度返信してみてね！",
                ephemeral=True,
            )




# ──────────── 🎵  VCユーティリティ ────────────
guild_states: dict[int, "MusicState"] = {}
voice_lock = asyncio.Lock()
last_4022: dict[int, float] = {}

class YoneVoiceClient(discord.VoiceClient):
    async def poll_voice_ws(self, reconnect: bool) -> None:
        backoff = discord.utils.ExponentialBackoff()
        while True:
            try:
                await self.ws.poll_event()
            except (discord.errors.ConnectionClosed, asyncio.TimeoutError) as exc:
                if isinstance(exc, discord.errors.ConnectionClosed):
                    if exc.code in (1000, 4015):
                        logger.info('Disconnecting from voice normally, close code %d.', exc.code)
                        await self.disconnect()
                        break
                    if exc.code == 4014:
                        logger.info('Disconnected from voice by force... potentially reconnecting.')
                        successful = await self.potential_reconnect()
                        if not successful:
                            logger.info('Reconnect was unsuccessful, disconnecting from voice normally...')
                            await self.disconnect()
                            break
                        else:
                            continue
                    if exc.code == 4022:
                        last_4022[self.guild.id] = time.time()
                        logger.warning('Received 4022, suppressing reconnect for 60s')
                        await self.disconnect()
                        break
                if not reconnect:
                    await self.disconnect()
                    raise

                retry = backoff.delay()
                logger.exception('Disconnected from voice... Reconnecting in %.2fs.', retry)
                self._connected.clear()
                await asyncio.sleep(retry)
                await self.voice_disconnect()
                try:
                    await self.connect(reconnect=True, timeout=self.timeout)
                except asyncio.TimeoutError:
                    logger.warning('Could not connect to voice... Retrying...')
                    continue


async def ensure_voice(msg: discord.Message, self_deaf: bool = True) -> discord.VoiceClient | None:
    """発話者が入っている VC へ Bot を接続（既に接続済みならそれを返す）"""
    if msg.author.voice is None or msg.author.voice.channel is None:
        await msg.reply("🎤 まず VC に入室してからコマンドを実行してね！")
        return None

    if time.time() - last_4022.get(msg.guild.id, 0) < 60:
        return None

    voice = msg.guild.voice_client
    if voice and voice.is_connected():                 # すでに接続済み
        if voice.channel != msg.author.voice.channel:  # 別チャンネルなら移動
            await voice.move_to(msg.author.voice.channel)
        return voice

    # 未接続 → 接続を試みる（10 秒タイムアウト）
    try:
        async with voice_lock:
            if msg.guild.voice_client and msg.guild.voice_client.is_connected():
                return msg.guild.voice_client
            return await asyncio.wait_for(
                msg.author.voice.channel.connect(self_deaf=self_deaf, cls=YoneVoiceClient),
                timeout=10
            )
    except discord.errors.ConnectionClosed as e:
        if e.code == 4022:
            last_4022[msg.guild.id] = time.time()
        await msg.reply("⚠️ VC への接続に失敗しました。", delete_after=5)
        return None
    except asyncio.TimeoutError:
        await msg.reply(
            "⚠️ VC への接続に失敗しました。もう一度試してね！",
            delete_after=5
        )
        return None


# ──────────── 🎵  Queue UI ここから ────────────
def make_embed(state: "MusicState") -> discord.Embed:
    emb = discord.Embed(title="🎶 Queue")

    # Now Playing
    if state.current:
        emb.add_field(name="▶️ Now Playing:", value=state.current.title, inline=False)
        if state.start_time is not None and state.current.duration:
            if state.is_paused:
                pos = int(state.pause_offset)
            else:
                pos = int(time.time() - state.start_time)
            pos = max(0, min(pos, state.current.duration))
            bar = make_bar(pos, state.current.duration)
            emb.add_field(
                name=f"[{bar}] {fmt_time(pos)} / {fmt_time(state.current.duration)}",
                value="\u200b",
                inline=False
            )
    else:
        emb.add_field(name="Now Playing", value="Nothing", inline=False)

    # Up Next
    queue_list = list(state.queue)
    if state.current in queue_list:   # どこにあっても 1 回だけ除外
        queue_list.remove(state.current)

    if queue_list:
        lines, chars = [], 0
        for i, tr in enumerate(queue_list, 1):
            line = f"{num_emoji(i)} {tr.title}"
            if chars + len(line) + 1 > 800:
                lines.append(f"…and **{len(queue_list)-i+1}** more")
                break
            lines.append(line)
            chars += len(line) + 1
        body = "\n".join(lines)
    else:
        body = "Empty"

    emb.add_field(name="Up Next", value=body, inline=False)
    loop_map = {0: "OFF", 1: "Song", 2: "Queue"}
    footer = f"Loop: {loop_map.get(state.loop, 'OFF')} | Auto Leave: {'ON' if state.auto_leave else 'OFF'}"
    emb.set_footer(text=footer)
    return emb


class ControlView(discord.ui.View):
    """再生操作やループ・自動退出の切替ボタンをまとめた View"""
    def __init__(self, state: "MusicState", vc: discord.VoiceClient, owner_id: int):
        super().__init__(timeout=None)
        self.state, self.vc, self.owner_id = state, vc, owner_id
        self._update_labels()


    def _update_labels(self):
        """各ボタンの表示を現在の状態に合わせて更新"""
        labels = {0: "OFF", 1: "Song", 2: "Queue"}
        self.loop_toggle.label = f"🔁 Loop: {labels[self.state.loop]}"
        self.leave_toggle.label = f"👋 Auto Leave: {'ON' if self.state.auto_leave else 'OFF'}"


    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.owner_id:
            await itx.response.send_message(
                "このボタンはコマンドを実行した人だけ使えます！",
                ephemeral=True,
            )
            return False
        return True

    # --- ボタン定義 ---
    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.primary)
    async def _skip(self, itx: discord.Interaction, _: discord.ui.Button):
        try:
            if self.vc.is_playing():
                self.vc.stop()
            new_view = QueueRemoveView(self.state, self.vc, self.owner_id)
            await itx.response.edit_message(embed=make_embed(self.state), view=new_view)
            self.state.queue_msg = itx.message

            self.state.panel_owner = self.owner_id
        except Exception:
            await itx.response.send_message(
                "⚠️ この操作パネルは無効です。\n"
                "`y!queue` で新しいパネルを表示してね！",
                ephemeral=True,
            )

    @discord.ui.button(label="🔀 Shuffle", style=discord.ButtonStyle.primary)
    async def _shuffle(self, itx: discord.Interaction, _: discord.ui.Button):
        try:
            random.shuffle(self.state.queue)
            new_view = QueueRemoveView(self.state, self.vc, self.owner_id)
            await itx.response.edit_message(embed=make_embed(self.state), view=new_view)
            self.state.queue_msg = itx.message

            self.state.panel_owner = self.owner_id

        except Exception:
            await itx.response.send_message(
                "⚠️ この操作パネルは無効です。\n"
                "`y!queue` で新しいパネルを表示してね！",
                ephemeral=True,
            )

    @discord.ui.button(label="⏯ Pause/Resume", style=discord.ButtonStyle.secondary)
    async def _pause_resume(self, itx: discord.Interaction, _: discord.ui.Button):
        try:
            if self.vc.is_playing():
                self.vc.pause()
                self.state.is_paused = True
                if self.state.start_time is not None:
                    self.state.pause_offset = time.time() - self.state.start_time
            elif self.vc.is_paused():
                self.vc.resume()
                self.state.is_paused = False
                if self.state.start_time is not None:
                    self.state.start_time = time.time() - self.state.pause_offset
            new_view = QueueRemoveView(self.state, self.vc, self.owner_id)
            await itx.response.edit_message(embed=make_embed(self.state), view=new_view)
            self.state.queue_msg = itx.message

            self.state.panel_owner = self.owner_id

        except Exception:
            await itx.response.send_message(
                "⚠️ この操作パネルは無効です。\n"
                "`y!queue` で新しいパネルを表示してね！",
                ephemeral=True,
            )

    @discord.ui.button(label="🔁 Loop: OFF", style=discord.ButtonStyle.success)
    async def loop_toggle(self, itx: discord.Interaction, btn: discord.ui.Button):
        try:

            self.state.loop = (self.state.loop + 1) % 3
            self._update_labels()
            await itx.response.edit_message(embed=make_embed(self.state), view=self)
            self.state.queue_msg = itx.message
            self.state.panel_owner = self.owner_id

        except Exception:
            await itx.response.send_message(
                "⚠️ この操作パネルは無効です。\n"
                "`y!queue` で新しいパネルを表示してね！",
                ephemeral=True,
            )

    @discord.ui.button(label="👋 Auto Leave: ON", style=discord.ButtonStyle.success)
    async def leave_toggle(self, itx: discord.Interaction, btn: discord.ui.Button):
        try:

            self.state.auto_leave = not self.state.auto_leave
            self._update_labels()
            await itx.response.edit_message(embed=make_embed(self.state), view=self)
            self.state.queue_msg = itx.message
            self.state.panel_owner = self.owner_id

        except Exception:
            await itx.response.send_message(
                "⚠️ この操作パネルは無効です。\n"
                "`y!queue` で新しいパネルを表示してね！",
                ephemeral=True,
            )


# ──────────── 削除ボタン付き View ──────────
class RemoveButton(discord.ui.Button):
    def __init__(self, index: int):
        super().__init__(label=f"🗑 {index}", style=discord.ButtonStyle.danger, row=1 + (index - 1) // 5)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: QueueRemoveView = self.view  # type: ignore
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                "このボタンはコマンドを実行した人だけ使えます！",
                ephemeral=True,
            )
            return
        base = 1 if view.state.current and view.state.current in view.state.queue else 0
        remove_index = base + self.index - 1
        if remove_index >= len(view.state.queue):
            await interaction.response.send_message(
                "⚠️ この操作パネルは無効です。\n`y!queue` で再表示してね！",
                ephemeral=True,
            )
            return
        tr = list(view.state.queue)[remove_index]
        del view.state.queue[remove_index]
        cleanup_track(tr)
        new_view = QueueRemoveView(view.state, view.vc, view.owner_id)
        await interaction.response.edit_message(embed=make_embed(view.state), view=new_view)
        view.state.queue_msg = interaction.message
        view.state.panel_owner = view.owner_id
        await refresh_queue(view.state)


class QueueRemoveView(ControlView):
    def __init__(self, state: "MusicState", vc: discord.VoiceClient, owner_id: int):
        super().__init__(state, vc, owner_id)

        qlist = list(state.queue)
        if state.current in qlist:
            qlist.remove(state.current)
        for i, _ in enumerate(qlist[:10], 1):
            self.add_item(RemoveButton(i))



# ──────────── 🎵  Queue UI ここまで ──────────

class HelpView(discord.ui.View):
    """Paginated help message with navigation buttons"""

    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.index = 0

    def _embed(self) -> discord.Embed:
        title, desc = HELP_PAGES[self.index]
        return discord.Embed(title=title, description=desc, colour=0x5865F2)

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.owner_id:
            await itx.response.send_message(
                "このボタンはコマンドを実行した人だけ使えます！",
                ephemeral=True,
            )
            return False
        return True

    async def _update(self, itx: discord.Interaction):
        await itx.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="⬅️前のページ", style=discord.ButtonStyle.secondary)
    async def prev_page(self, itx: discord.Interaction, _: discord.ui.Button):
        self.index = (self.index - 1) % len(HELP_PAGES)
        await self._update(itx)

    @discord.ui.button(label="➡️次のページ", style=discord.ButtonStyle.primary)
    async def next_page(self, itx: discord.Interaction, _: discord.ui.Button):
        self.index = (self.index + 1) % len(HELP_PAGES)
        await self._update(itx)

    @discord.ui.button(label="すべて", style=discord.ButtonStyle.success, row=1)
    async def goto_all(self, itx: discord.Interaction, _: discord.ui.Button):
        self.index = 0
        await self._update(itx)

    @discord.ui.button(label="🎵音楽", style=discord.ButtonStyle.success, row=1)
    async def goto_music(self, itx: discord.Interaction, _: discord.ui.Button):
        self.index = 1
        await self._update(itx)

    @discord.ui.button(label="💬翻訳", style=discord.ButtonStyle.success, row=1)
    async def goto_trans(self, itx: discord.Interaction, _: discord.ui.Button):
        self.index = 2
        await self._update(itx)

    @discord.ui.button(label="🤖AI/ツール", style=discord.ButtonStyle.success, row=1)
    async def goto_ai(self, itx: discord.Interaction, _: discord.ui.Button):
        self.index = 3
        await self._update(itx)

    @discord.ui.button(label="🧑ユーザー情報", style=discord.ButtonStyle.success, row=1)
    async def goto_user(self, itx: discord.Interaction, _: discord.ui.Button):
        self.index = 4
        await self._update(itx)

    @discord.ui.button(label="🕹️その他", style=discord.ButtonStyle.success, row=2)
    async def goto_other(self, itx: discord.Interaction, _: discord.ui.Button):
        self.index = 5
        await self._update(itx)

    @discord.ui.button(label="🔰使い方", style=discord.ButtonStyle.success, row=2)
    async def goto_usage(self, itx: discord.Interaction, _: discord.ui.Button):
        self.index = 6
        await self._update(itx)


# ───────────────── コマンド実装 ─────────────────
async def cmd_ping(msg: discord.Message):
    ms = client.latency * 1000
    await msg.channel.send(f"Pong! `{ms:.0f} ms` 🏓")

async def cmd_queue(msg: discord.Message, _):
    state = guild_states.get(msg.guild.id)
    if not state:
        await msg.reply("キューは空だよ！"); return
    vc   = msg.guild.voice_client
    view = QueueRemoveView(state, vc, msg.author.id)
    if state.queue_msg:
        try:

            await state.queue_msg.delete()
        except Exception:
            pass

    state.queue_msg = await msg.channel.send(embed=make_embed(state), view=view)
    state.panel_owner = msg.author.id


async def cmd_say(msg: discord.Message, text: str):
    if not text.strip():
        await msg.channel.send("何を言えばいい？")
        return
    if len(text) <= 2000:
        await msg.channel.send(text)
    else:
        await msg.channel.send(file=discord.File(fp=text.encode(), filename="say.txt"))

async def cmd_date(msg: discord.Message, arg: str):
    ts = int(arg) if arg.isdecimal() else int(time.time())
    await msg.channel.send(f"<t:{ts}:F>")              # 例：2025年6月28日 土曜日 15:30

async def build_user_embed(target: discord.User | discord.Member,
                           member: discord.Member | None,
                           channel: discord.abc.Messageable) -> discord.Embed:
    # Keep the provided Member instance to preserve presence information.
    # Fetching via HTTP would discard presence data.
    embed = discord.Embed(title="ユーザー情報", colour=0x2ecc71)
    embed.set_thumbnail(url=target.display_avatar.url)

    # 基本情報
    embed.add_field(name="表示名", value=target.display_name, inline=False)
    tag = f"{target.name}#{target.discriminator}" if target.discriminator != "0" else target.name
    embed.add_field(name="Discordタグ", value=tag, inline=False)
    embed.add_field(name="ID", value=str(target.id))
    embed.add_field(name="BOTかどうか", value="✅" if target.bot else "❌")
    embed.add_field(name="アカウント作成日",
                    value=target.created_at.strftime('%Y年%m月%d日 %a %H:%M'),
                    inline=False)

    # サーバー固有
    if member:
        joined = member.joined_at.strftime('%Y年%m月%d日 %a %H:%M') if member.joined_at else '—'
        embed.add_field(name="サーバー参加日", value=joined, inline=False)
        embed.add_field(name="ステータス", value=str(member.status))
        embed.add_field(name="デバイス別ステータス",
                        value=f"PC:{member.desktop_status} / Mobile:{member.mobile_status} / Web:{member.web_status}",
                        inline=False)
        embed.add_field(name="ニックネーム", value=member.nick or '—')
        roles = [r for r in member.roles if r.name != '@everyone']
        embed.add_field(name="役職数", value=str(len(roles)))
        highest_role = member.top_role.mention
        embed.add_field(name="最高ロール", value=highest_role)
        perms = ", ".join([name for name, v in member.guild_permissions if v]) or '—'
        embed.add_field(name="権限一覧", value=perms, inline=False)
        vc = member.voice.channel.name if member.voice else '—'
        embed.add_field(name="VC参加中", value=vc)
    else:
        embed.add_field(name="サーバー参加日", value='—', inline=False)
        embed.add_field(name="ステータス", value='—')
        embed.add_field(name="デバイス別ステータス", value='—', inline=False)
        embed.add_field(name="ニックネーム", value='—')
        embed.add_field(name="役職数", value='—')
        embed.add_field(name="最高ロール", value='—')
        embed.add_field(name="権限一覧", value='—', inline=False)
        embed.add_field(name="VC参加中", value='—')

    last = '—'
    try:
        async for m in channel.history(limit=100):
            if m.author.id == target.id:
                last = m.created_at.strftime('%Y年%m月%d日 %a %H:%M')
                break
    except Exception:
        pass
    embed.add_field(name="最後の発言", value=last, inline=False)
    return embed


async def cmd_user(msg: discord.Message, arg: str = ""):
    """ユーザー情報を表示"""
    arg = arg.strip()
    if arg and len(arg.split()) > 1:
        await msg.reply("ユーザーは1人だけ指定してください")
        return

    target: discord.User | discord.Member

    if not arg:
        target = msg.author
    elif arg.isdigit():
        try:
            target = await client.fetch_user(int(arg))
        except discord.NotFound:
            await msg.reply("その ID のユーザーは見つかりませんでした。")
            return
    elif arg.startswith("<@") and arg.endswith(">"):
        uid = arg.removeprefix("<@").removeprefix("!").removesuffix(">")
        try:
            target = await client.fetch_user(int(uid))
        except discord.NotFound:
            await msg.reply("そのユーザーは見つかりませんでした。")
            return
    else:
        await msg.reply("`y!user @メンション` または `y!user 1234567890` の形式で指定してね！")
        return

    member: discord.Member | None = None
    if msg.guild:
        try:
            member = await msg.guild.fetch_member(target.id)
        except discord.NotFound:
            member = None

    embed = await build_user_embed(target, member, msg.channel)
    await msg.channel.send(embed=embed)

async def cmd_server(msg: discord.Message):
    """サーバー情報を表示"""
    if not msg.guild:
        await msg.reply("このコマンドはサーバー内専用です")
        return

    g = msg.guild
    emb = discord.Embed(title="サーバー情報", colour=0x3498db)
    if g.icon:
        emb.set_thumbnail(url=g.icon.url)

    emb.add_field(name="サーバー名", value=g.name, inline=False)
    emb.add_field(name="ID", value=str(g.id))
    if g.owner:
        emb.add_field(name="オーナー", value=g.owner.mention, inline=False)
    emb.add_field(name="作成日", value=g.created_at.strftime('%Y年%m月%d日'))
    emb.add_field(name="メンバー数", value=str(g.member_count))
    online = sum(1 for m in g.members if m.status != discord.Status.offline)
    emb.add_field(name="オンライン数", value=str(online))
    emb.add_field(name="テキストCH数", value=str(len(g.text_channels)))
    emb.add_field(name="ボイスCH数", value=str(len(g.voice_channels)))
    emb.add_field(name="役職数", value=str(len(g.roles)))
    emb.add_field(name="絵文字数", value=str(len(g.emojis)))
    emb.add_field(name="ブーストLv", value=str(g.premium_tier))
    emb.add_field(name="ブースター数", value=str(g.premium_subscription_count))
    emb.add_field(name="検証レベル", value=str(g.verification_level))
    emb.add_field(name="AFKチャンネル", value=g.afk_channel.name if g.afk_channel else '—')
    emb.add_field(name="バナーURL", value=g.banner.url if g.banner else '—', inline=False)
    features = ", ".join(g.features) if g.features else '—'
    emb.add_field(name="機能フラグ", value=features, inline=False)

    await msg.channel.send(embed=emb)

async def cmd_dice(msg: discord.Message, nota: str):
    m = re.fullmatch(r"(\d*)d(\d+)", nota, re.I)
    if not m:
        await msg.channel.send("書式は `XdY` だよ（例 2d6, d20, 1d100）")
        return
    cnt = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    if not (1 <= cnt <= 10):
        await msg.channel.send("ダイスは 1〜10 個まで！"); return
    rolls = [random.randint(1, sides) for _ in range(cnt)]
    total = sum(rolls)
    txt = ", ".join(map(str, rolls))

    class Reroll(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        async def interaction_check(self, itx: discord.Interaction) -> bool:
            if itx.user.id != msg.author.id:
                await itx.response.send_message(
                    "このボタンはコマンドを実行した人だけ使えます！",
                    ephemeral=True,
                )
                return False
            return True

        @discord.ui.button(label="🎲もう一回振る", style=discord.ButtonStyle.primary)
        async def reroll(self, inter: discord.Interaction, btn: discord.ui.Button):
            try:
                new = [random.randint(1, sides) for _ in range(cnt)]
                await inter.response.edit_message(
                    content=f"🎲 {nota} → {', '.join(map(str,new))} 【合計 {sum(new)}】",
                    view=self
                )
            except Exception:
                await inter.response.send_message(
                    "⚠️ この操作パネルは無効です。\n"
                    "もう一度コマンドを実行してね！",
                    ephemeral=True,
                )

    await msg.channel.send(f"🎲 {nota} → {txt} 【合計 {total}】", view=Reroll())

import asyncio


async def cmd_gpt(msg: discord.Message, user_text: str):
    """Handle the gpt command with tools and short conversation history."""
    if not user_text.strip():
        await msg.reply("質問を書いてね！")
        return

    history = await _gather_reply_chain(msg, limit=20)

    def format_history(messages: list[discord.Message]) -> str:
        lines = []
        for m in messages:
            ts = m.created_at.strftime("%Y-%m-%d %H:%M")
            content = _strip_bot_mention(m.content)
            if content:
                lines.append(f"{m.author.display_name} {ts} {content}")
        return "\n".join(lines)

    history_txt = format_history(history)
    if history_txt:
        prompt = f"###会話履歴\n{history_txt}\n###今回のメッセージ\n{user_text}"
    else:
        prompt = user_text

    reply = await msg.reply("…")
    try:
        response_text, files = await call_cappuccino_api(prompt)
    except Exception as exc:
        await reply.edit(content=f"Error: {exc}")
        return

    await reply.edit(content=response_text[:1900], attachments=files if files else [])

# ──────────── 🎵  コマンド郡 ────────────

async def cmd_play(msg: discord.Message, query: str = "", *, first_query: bool = False, split_commas: bool = False):
    """曲をキューに追加して再生を開始

    Parameters
    ----------
    msg: discord.Message
        コマンドを送信したメッセージ
    query: str
        URL や検索ワード (任意)
    first_query: bool
        True のとき query → 添付ファイルの順で追加する
        False のときは従来通り添付ファイル → query
    """
    queries = split_by_commas(query) if split_commas else ([query.strip()] if query.strip() else [])
    attachments = msg.attachments
    if not queries and not attachments:
        await msg.reply("URLまたは添付ファイルを指定してね！")
        return

    voice = await ensure_voice(msg)
    if not voice:
        return

    state = guild_states.setdefault(msg.guild.id, MusicState())

    if state.playlist_task and not state.playlist_task.done():
        state.playlist_task.cancel()
        state.playlist_task = None

    tracks_query: list[Track] = []
    tracks_attach: list[Track] = []

    def handle_query() -> None:
        nonlocal playlist_handled, tracks_query
        for q in queries:
            urls, text_query = parse_urls_and_text(q)
            for u in urls:
                if is_playlist_url(u):
                    state.playlist_task = client.loop.create_task(
                        add_playlist_lazy(state, u, voice, msg.channel)
                    )
                    playlist_handled = True
                else:
                    try:
                        tracks_query += yt_extract(u)
                    except Exception:
                        client.loop.create_task(
                            msg.reply("URLから曲を取得できませんでした。", delete_after=5)
                        )

            if text_query:
                try:
                    tracks_query += yt_extract(text_query)
                except Exception:
                    client.loop.create_task(
                        msg.reply("URLから曲を取得できませんでした。", delete_after=5)
                    )

    async def handle_attachments() -> None:
        nonlocal tracks_attach
        if attachments:
            try:
                tracks_attach += await attachments_to_tracks(attachments)
            except Exception as e:
                await msg.reply(f"添付ファイル取得エラー: {e}", delete_after=5)
                raise

    playlist_handled = False
    if first_query:
        handle_query()
        await handle_attachments()
    else:
        await handle_attachments()
        handle_query()

    if not tracks_query and not tracks_attach and not playlist_handled:
        return

    tracks = (tracks_query + tracks_attach) if first_query else (tracks_attach + tracks_query)

    if not tracks and not playlist_handled:
        return

    if tracks:
        state.queue.extend(tracks)
        await refresh_queue(state)
        await msg.channel.send(f"⏱️ **{len(tracks)}曲** をキューに追加しました！")


    # 再生していなければループを起動
    if state.queue and not voice.is_playing() and not state.play_next.is_set():
        client.loop.create_task(state.player_loop(voice, msg.channel))




async def cmd_stop(msg: discord.Message, _):
    """Bot を VC から切断し、キュー初期化"""
    if vc := msg.guild.voice_client:
        await vc.disconnect()
    state = guild_states.pop(msg.guild.id, None)
    if state:
        if state.playlist_task and not state.playlist_task.done():
            state.playlist_task.cancel()
        cleanup_track(state.current)
        for tr in state.queue:
            cleanup_track(tr)
        if state.queue_msg:
            try:
                await state.queue_msg.delete()
            except Exception:
                pass
            state.queue_msg = None
            state.panel_owner = None
    await msg.add_reaction("⏹️")


async def cmd_remove(msg: discord.Message, arg: str):
    state = guild_states.get(msg.guild.id)
    if not state or not state.queue:
        await msg.reply("キューは空だよ！")
        return
    nums = [int(x) for x in arg.split() if x.isdecimal()]
    if not nums:
        await msg.reply("番号を指定してね！")
        return
    q = list(state.queue)
    removed = []
    for i in sorted(set(nums), reverse=True):
        if 1 <= i <= len(q):
            removed.append(q.pop(i-1))
    state.queue = collections.deque(q)
    for tr in removed:
        cleanup_track(tr)
    await refresh_queue(state)
    await msg.channel.send(f"🗑️ {len(removed)}件削除しました！")


async def cmd_keep(msg: discord.Message, arg: str):
    state = guild_states.get(msg.guild.id)
    if not state or not state.queue:
        await msg.reply("キューは空だよ！")
        return
    nums = {int(x) for x in arg.split() if x.isdecimal()}
    if not nums:
        await msg.reply("番号を指定してね！")
        return
    q = list(state.queue)
    kept = []
    removed = []
    for i, tr in enumerate(q, 1):
        if i in nums:
            kept.append(tr)
        else:
            removed.append(tr)
    state.queue = collections.deque(kept)
    for tr in removed:
        cleanup_track(tr)
    await refresh_queue(state)
    await msg.channel.send(f"🗑️ {len(removed)}件削除しました！")


async def cmd_seek(msg: discord.Message, arg: str):
    arg = arg.strip()
    if not arg:
        await msg.reply("時間を指定してください。例：y!seek 2m30s")
        return
    try:
        pos = parse_seek_time(arg)
    except Exception:
        await msg.reply("時間指定が不正です。例：1m30s, 2m, 1h2m3s, 120, 2:00, 0:02:00")
        return

    state = guild_states.get(msg.guild.id)
    voice = msg.guild.voice_client
    if not state or not state.current or not voice or not voice.is_connected():
        await msg.reply("再生中の曲がありません")
        return

    if state.current.duration and pos >= state.current.duration:
        dur = state.current.duration
        await msg.reply(f"曲の長さは {dur//60}分{dur%60}秒です。短い時間を指定してください")
        return

    state.seek_to = pos
    state.seeking = True
    voice.stop()
    await msg.channel.send(f"{fmt_time_jp(pos)}から再生します")


async def cmd_rewind(msg: discord.Message, arg: str):
    """現在位置から指定時間だけ巻き戻す"""
    arg = arg.strip()
    if arg:
        try:
            delta = parse_seek_time(arg)
        except Exception:
            await msg.reply("時間指定が不正です。例：10s, 1m, 1:00")
            return
    else:
        delta = 10

    state = guild_states.get(msg.guild.id)
    voice = msg.guild.voice_client
    if not state or not state.current or not voice or not voice.is_connected():
        await msg.reply("再生中の曲がありません")
        return

    if state.start_time is not None:
        cur = state.pause_offset if state.is_paused else time.time() - state.start_time
    else:
        cur = 0
    cur = max(0, int(cur))
    if state.current.duration:
        cur = min(cur, state.current.duration)

    new_pos = max(0, cur - delta)
    await cmd_seek(msg, str(new_pos))


async def cmd_forward(msg: discord.Message, arg: str):
    """現在位置から指定時間だけ早送り"""
    arg = arg.strip()
    if arg:
        try:
            delta = parse_seek_time(arg)
        except Exception:
            await msg.reply("時間指定が不正です。例：10s, 1m, 1:00")
            return
    else:
        delta = 10

    state = guild_states.get(msg.guild.id)
    voice = msg.guild.voice_client
    if not state or not state.current or not voice or not voice.is_connected():
        await msg.reply("再生中の曲がありません")
        return

    if state.start_time is not None:
        cur = state.pause_offset if state.is_paused else time.time() - state.start_time
    else:
        cur = 0
    cur = max(0, int(cur))
    if state.current.duration:
        cur = min(cur, state.current.duration)
        new_pos = min(cur + delta, state.current.duration)
    else:
        new_pos = cur + delta

    await cmd_seek(msg, str(new_pos))


async def cmd_purge(msg: discord.Message, arg: str):
    """指定数またはリンク以降のメッセージを一括削除"""
    if not msg.guild:
        await msg.reply("サーバー内でのみ使用できます。")
        return

    target_channel: discord.abc.GuildChannel = msg.channel
    target_message: discord.Message | None = None
    arg = arg.strip()
    if not arg:
        await msg.reply("`y!purge <数>` または `y!purge <メッセージリンク>` の形式で指定してね！")
        return

    if arg.isdigit():
        limit = min(int(arg), 1000)
    else:
        ids = parse_message_link(arg)
        if not ids:
            await msg.reply("形式が正しくないよ！")
            return
        gid, cid, mid = ids
        if gid != msg.guild.id:
            await msg.reply("このサーバーのメッセージリンクを指定してね！")
            return
        ch = msg.guild.get_channel(cid)
        if ch is None or not isinstance(ch, MESSAGE_CHANNEL_TYPES):
            await msg.reply(
                f"リンク先チャンネルが見つかりません (取得型: {type(ch).__name__ if ch else 'None'})。"
            )
            return
        target_channel = ch
        if isinstance(ch, (discord.TextChannel, discord.Thread)):
            try:
                target_message = await ch.fetch_message(mid)
            except discord.NotFound:
                await msg.reply("指定メッセージが存在しません。")
                return
        else:
            try:
                target_message = await ch.fetch_message(mid)
            except Exception:
                await msg.reply("このチャンネル型では purge が未対応です。")
                return
        limit = None

    # 権限チェック
    perms_user = target_channel.permissions_for(msg.author)
    perms_bot = target_channel.permissions_for(msg.guild.me)
    if not (perms_user.manage_messages and perms_bot.manage_messages):
        await msg.reply("管理メッセージ権限が足りません。", delete_after=5)
        return

    deleted_total = 0

    def _skip_cmd(m: discord.Message) -> bool:
        if m.id == msg.id:
            return False
        if (
            m.type
            in (
                discord.MessageType.chat_input_command,
                discord.MessageType.context_menu_command,
            )
            and m.interaction
            and m.interaction.id == msg.id
        ):
            return False
        return True

    try:
        if target_message is None:
            if hasattr(target_channel, "purge"):
                try:
                    deleted = await target_channel.purge(limit=limit, check=_skip_cmd)
                except discord.NotFound:
                    deleted = []
                deleted_total = len(deleted)
            else:
                msgs = [
                    m
                    async for m in target_channel.history(limit=limit)
                    if _skip_cmd(m)
                ]
                try:
                    await target_channel.delete_messages(msgs)
                except discord.NotFound:
                    pass
                deleted_total = len(msgs)
        else:
            after = target_message
            while True:
                if hasattr(target_channel, "purge"):
                    try:
                        batch = await target_channel.purge(after=after, limit=100, check=_skip_cmd)
                    except discord.NotFound:
                        batch = []
                else:
                    batch = [
                        m
                        async for m in target_channel.history(after=after, limit=100)
                        if _skip_cmd(m)
                    ]
                    try:
                        await target_channel.delete_messages(batch)
                    except discord.NotFound:
                        pass
                if not batch:
                    break
                deleted_total += len(batch)
                after = batch[-1]
            try:
                await target_message.delete()
                deleted_total += 1
            except (discord.HTTPException, discord.NotFound):
                pass
    except discord.Forbidden:
        await msg.reply("権限不足で削除できませんでした。", delete_after=5)
        return

    await msg.channel.send(f"🧹 {deleted_total}件削除しました！", delete_after=5)


async def cmd_qr(msg: discord.Message, text: str) -> None:
    """指定テキストのQRコードを生成"""
    text = text.strip()
    if not text:
        await msg.reply("QRコードにする文字列を指定してね！")
        return

    try:
        import qrcode
    except ModuleNotFoundError:
        await msg.reply("qrcode モジュールが見つかりません。`pip install qrcode` を実行してください。")
        return

    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    path = tmp.name
    tmp.close()
    await asyncio.to_thread(img.save, path)

    try:
        await msg.channel.send(file=discord.File(path))
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


async def cmd_barcode(msg: discord.Message, text: str) -> None:
    """指定テキストのバーコード(Code128)を生成"""
    text = text.strip()
    if not text:
        await msg.reply("バーコードにする文字列を指定してね！")
        return

    try:
        import barcode
        from barcode.writer import ImageWriter
        from barcode.errors import IllegalCharacterError
    except ModuleNotFoundError:
        await msg.reply("barcode モジュールが見つかりません。`pip install python-barcode` を実行してください。")
        return
    try:
        code = barcode.get("code128", text, writer=ImageWriter())
    except IllegalCharacterError:
        await msg.reply("Code128 では英数字など ASCII 文字のみ利用できます。", delete_after=5)
        return
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    path = tmp.name
    tmp.close()
    await asyncio.to_thread(code.write, path)

    try:
        await msg.channel.send(file=discord.File(path))
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


async def cmd_tex(msg: discord.Message, formula: str) -> None:
    """Render TeX formula to an image."""
    formula = formula.strip()
    if not formula:
        await msg.reply("数式を指定してね！")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        await msg.reply(
            "matplotlib モジュールが見つかりません。`pip install matplotlib` を実行してください。"
        )
        return

    fig = plt.figure()
    fig.text(0.5, 0.5, f"${formula}$", fontsize=20, ha="center", va="center")
    plt.axis("off")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    path = tmp.name
    tmp.close()
    await asyncio.to_thread(fig.savefig, path, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)

    try:
        await msg.channel.send(file=discord.File(path))
    finally:
        try:
            os.remove(path)
        except Exception:
            pass




# ──────────── 🎵  自動切断ハンドラ ────────────

@client.event
async def on_voice_state_update(member, before, after):
    """誰かが VC から抜けた時、条件に応じて Bot を切断"""
    state = guild_states.get(member.guild.id)
    if not state:
        return

    voice: discord.VoiceClient | None = member.guild.voice_client
    if not voice or not voice.is_connected():
        return

    # VC 内のヒト(≠bot) が 0 人になった & auto_leave が有効？
    if len([m for m in voice.channel.members if not m.bot]) == 0 and state.auto_leave:
        try:
            await voice.disconnect()
        finally:
            st = guild_states.pop(member.guild.id, None)
            if st:
                if st.playlist_task and not st.playlist_task.done():
                    st.playlist_task.cancel()
                cleanup_track(st.current)
                for tr in st.queue:
                    cleanup_track(tr)
                if st.queue_msg:
                    try:
                        await st.queue_msg.delete()
                    except Exception:
                        pass
                    st.queue_msg = None
                    st.panel_owner = None



async def cmd_poker(msg: discord.Message, arg: str = ""):
    """Start a heads-up poker match."""
    arg = arg.strip()
    opponent: discord.User | None = None
    if arg:
        if arg.isdigit():
            try:
                opponent = await client.fetch_user(int(arg))
            except discord.NotFound:
                await msg.reply("その ID のユーザーは見つかりませんでした。")
                return
        elif arg.startswith("<@") and arg.endswith(">"):
            uid = arg.removeprefix("<@").removeprefix("!").removesuffix(">")
            try:
                opponent = await client.fetch_user(int(uid))
            except discord.NotFound:
                await msg.reply("そのユーザーは見つかりませんでした。")
                return
        else:
            await msg.reply("対戦相手は @メンション または ID で指定してください。")
            return
    if opponent is None:
        opponent = client.user

    game = PokerMatch(msg.author, opponent, client.user)
    view = PokerView(game)
    await game.start(msg.channel)
    await msg.channel.send("Poker game started!", view=view)


async def cmd_help(msg: discord.Message):
    view = HelpView(msg.author.id)
    await msg.channel.send(embed=view._embed(), view=view)


def _parse_channel(arg: str, guild: discord.Guild | None) -> discord.TextChannel | None:
    """Return channel from mention or ID, or None if not found or not text channel."""
    if not guild or not arg:
        return None
    cid = arg.strip()
    if cid.startswith("<#") and cid.endswith(">"):
        cid = cid[2:-1]
    if not cid.isdigit():
        return None
    ch = guild.get_channel(int(cid))
    if isinstance(ch, discord.TextChannel):
        return ch
    return None


async def cmd_news(msg: discord.Message, arg: str) -> None:
    """ニュース送信先チャンネルを設定"""
    if not msg.guild:
        await msg.reply("サーバー内でのみ使用できます。")
        return
    if not msg.author.guild_permissions.administrator:
        await msg.reply("管理者専用コマンドです。", delete_after=5)
        return
    channel = _parse_channel(arg, msg.guild) or (
        msg.channel if isinstance(msg.channel, discord.TextChannel) else None
    )
    if channel is None:
        await msg.reply("`y!news #チャンネル` の形式で指定してね！")
        return
    global NEWS_CHANNEL_ID
    NEWS_CHANNEL_ID = channel.id
    _save_news_channel(NEWS_CHANNEL_ID)
    await msg.channel.send(f"ニュースチャンネルを {channel.mention} に設定しました。")
    try:
        await send_latest_news(channel)
    except Exception as e:
        await msg.channel.send(f"テスト送信に失敗: {e}")


async def cmd_eew(msg: discord.Message, arg: str) -> None:
    """地震速報送信先チャンネルを設定"""
    if not msg.guild:
        await msg.reply("サーバー内でのみ使用できます。")
        return
    if not msg.author.guild_permissions.administrator:
        await msg.reply("管理者専用コマンドです.", delete_after=5)
        return
    channel = _parse_channel(arg, msg.guild) or (
        msg.channel if isinstance(msg.channel, discord.TextChannel) else None
    )
    if channel is None:
        await msg.reply("`y!eew #チャンネル` の形式で指定してね！")
        return
    global EEW_CHANNEL_ID
    EEW_CHANNEL_ID = channel.id
    _save_eew_channel(EEW_CHANNEL_ID)
    await msg.channel.send(f"地震速報チャンネルを {channel.mention} に設定しました。")
    try:
        await send_latest_eew(channel)
    except Exception as e:
        await msg.channel.send(f"テスト送信に失敗: {e}")

async def cmd_weather(msg: discord.Message, arg: str) -> None:
    """天気予報送信先チャンネルを設定"""
    if not msg.guild:
        await msg.reply("サーバー内でのみ使用できます。")
        return
    if not msg.author.guild_permissions.administrator:
        await msg.reply("管理者専用コマンドです。", delete_after=5)
        return
    channel = _parse_channel(arg, msg.guild) or (
        msg.channel if isinstance(msg.channel, discord.TextChannel) else None
    )
    if channel is None:
        await msg.reply("`y!weather #チャンネル` の形式で指定してね！")
        return
    global WEATHER_CHANNEL_ID
    WEATHER_CHANNEL_ID = channel.id
    _save_weather_channel(WEATHER_CHANNEL_ID)
    await msg.channel.send(f"天気予報チャンネルを {channel.mention} に設定しました。")
    try:
        target = datetime.datetime.now(JST).replace(minute=0, second=0, microsecond=0)
        await send_weather(channel, target)
    except Exception as e:
        await msg.channel.send(f"テスト送信に失敗: {e}")


# ───────────────── ニュース自動送信 ─────────────────
NEWS_FEED_URL = "https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja"
NEWS_FILE = os.path.join(ROOT_DIR, "sent_news.json")
DAILY_NEWS_FILE = os.path.join(ROOT_DIR, "daily_news.json")

def _load_sent_news() -> dict:
    try:
        with open(NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}

def _save_sent_news(data: dict) -> None:
    try:
        with open(NEWS_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(NEWS_FILE + ".tmp", NEWS_FILE)
    except Exception as e:
        logger.error("failed to save news file: %s", e)

sent_news = _load_sent_news()

def _load_daily_news() -> dict:
    try:
        with open(DAILY_NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}

def _save_daily_news(data: dict) -> None:
    try:
        with open(DAILY_NEWS_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(DAILY_NEWS_FILE + ".tmp", DAILY_NEWS_FILE)
    except Exception as e:
        logger.error("failed to save daily news file: %s", e)

daily_news = _load_daily_news()

async def _summarize(text: str) -> str:
    prompt = (
        "Summarize the text below in Japanese, using about two concise sentences. "
        "Unless otherwise instructed, reply in Japanese.\n" + text
    )
    try:
        return await cappuccino_agent.call_llm(prompt)
    except Exception as e:
        logger.error("summary failed: %s", e)
        return text[:200]

def _shorten_url(url: str) -> str:
    """Remove query and fragment from URL for display"""
    try:
        p = urlparse(url)
        return urlunparse(p._replace(query="", fragment=""))
    except Exception:
        return url

def _resolve_google_news_url(url: str) -> str:
    """Return original article URL from Google News redirect"""
    try:
        p = urlparse(url)
        if "news.google.com" in p.netloc:
            q = parse_qs(p.query)
            if "url" in q and q["url"]:
                return q["url"][0]
    except Exception:
        pass
    return url

async def _fetch_thumbnail(url: str) -> str | None:
    """Fetch og:image from article page"""
    try:
        url = _resolve_google_news_url(url)
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=10) as resp:
                html = await resp.text()
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if not m:
            m = re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:image["\']', html, re.IGNORECASE)
        return m.group(1) if m else None
    except Exception as e:
        logger.error("thumb fetch failed for %s: %s", url, e)
        return None

async def _fetch_article_text(url: str) -> str | None:
    """Fetch article body text"""
    try:
        url = _resolve_google_news_url(url)
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=10) as resp:
                html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        article = soup.find("article")
        if article:
            text = article.get_text(separator=" ", strip=True)
        else:
            text = " ".join(p.get_text(strip=True) for p in soup.find_all("p"))
        return text[:5000]
    except Exception as e:
        logger.error("article fetch failed for %s: %s", url, e)
        return None

async def send_latest_news(channel: discord.TextChannel):
    feed = feedparser.parse(NEWS_FEED_URL)
    today = datetime.date.today().isoformat()
    sent_urls: list[str] = sent_news.get(today, [])
    new_entries = []
    for ent in feed.entries:
        url = ent.link
        if url in sent_urls:
            continue
        new_entries.append(ent)
        sent_urls.append(url)
        if len(new_entries) >= 7:
            break
    if not new_entries:
        return
    sent_news[today] = sent_urls
    _save_sent_news(sent_news)
    for ent in new_entries:
        article_url = _resolve_google_news_url(ent.link)
        text = await _fetch_article_text(article_url)
        if not text:
            text = re.sub(r"<.*?>", "", ent.get("summary", ""))
        summary = await _summarize(text)
        day_list = daily_news.get(today, [])
        day_list.append(f"{ent.title}。{summary}")
        daily_news[today] = day_list
        article_url = _resolve_google_news_url(ent.link)
        emb = discord.Embed(
            title=ent.title,
            url=_shorten_url(article_url),
            description=summary,
            colour=0x3498db,
        )
        if getattr(ent, "source", None) and getattr(ent.source, "title", None):
            emb.set_footer(text=ent.source.title)
        thumb = await _fetch_thumbnail(article_url)
        if thumb:
            emb.set_thumbnail(url=thumb)
        await channel.send(embed=emb)
    _save_daily_news(daily_news)

async def send_daily_digest(channel: discord.TextChannel):
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    items = daily_news.get(yesterday)
    if not items:
        return
    text = "\n".join(items)
    summary = await _summarize(text)
    emb = discord.Embed(
        title=f"{yesterday} のニュースまとめ",
        description=summary,
        colour=0x95a5a6,
    )
    await channel.send(embed=emb)
    del daily_news[yesterday]
    _save_daily_news(daily_news)

news_task: asyncio.Task | None = None

async def hourly_news() -> None:
    await client.wait_until_ready()
    while True:
        now = datetime.datetime.now()
        next_hour = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_hour - now).total_seconds())
        if not NEWS_CHANNEL_ID:
            continue
        channel = client.get_channel(NEWS_CHANNEL_ID)
        if channel is None:
            try:
                channel = await client.fetch_channel(NEWS_CHANNEL_ID)
            except Exception as e:
                logger.error("failed to fetch news channel: %s", e)
                continue
        if isinstance(channel, MESSAGE_CHANNEL_TYPES):
            try:
                await send_latest_news(channel)
                current_hour = datetime.datetime.now().hour
                if current_hour == 0:
                    await send_daily_digest(channel)
            except Exception as e:
                logger.error("failed to send news: %s", e)

eew_task: asyncio.Task | None = None
EEW_LIST_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"
EEW_BASE_URL = "https://www.jma.go.jp/bosai/quake/data/"

async def send_latest_eew(channel: discord.TextChannel):
    async with aiohttp.ClientSession() as sess:
        async with sess.get(EEW_LIST_URL, timeout=10) as resp:
            data = await resp.json()
        if not data:
            return
        latest = data[0]
        await _send_eew(channel, latest)

async def _send_eew(channel: discord.TextChannel, item: dict):
    url = EEW_BASE_URL + item.get("json", "")
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url, timeout=10) as resp:
            detail = await resp.json(content_type=None)
    head = detail.get("Head", {})
    body = detail.get("Body", {})
    area = (
        body.get("Earthquake", {})
        .get("Hypocenter", {})
        .get("Area", {})
        .get("Name", "")
    )
    mag = body.get("Earthquake", {}).get("Magnitude", "")
    maxint = body.get("Intensity", {}).get("Observation", {}).get("MaxInt", "")
    ctt = item.get("ctt")
    dt = head.get("TargetDateTime", "")
    formatted_dt = dt
    if ctt:
        try:
            dt_obj = datetime.datetime.strptime(ctt, "%Y%m%d%H%M%S")
            formatted_dt = dt_obj.strftime("%Y年%m月%d日(%a)%H:%M:%S")
        except Exception:
            pass
    elif dt:
        try:
            dt_obj = datetime.datetime.fromisoformat(dt)
            formatted_dt = dt_obj.strftime("%Y年%m月%d日(%a)%H:%M:%S")
        except Exception:
            pass
    title = item.get("ttl") or head.get("Title", "地震情報")

    # ---- Embed Construction ----
    intensity_map = {
        "1": 1,
        "2": 2,
        "3": 3,
        "4": 4,
        "5-": 5,
        "5+": 5.5,
        "6-": 6,
        "6+": 6.5,
        "7": 7,
    }
    value = None
    if isinstance(maxint, str) and maxint in intensity_map:
        value = intensity_map[maxint]
    else:
        try:
            value = float(mag)
        except Exception:
            value = None

    if value is None:
        colour = discord.Colour.light_grey()
    elif value >= 6:
        colour = discord.Colour.red()
    elif value >= 4:
        colour = discord.Colour.orange()
    elif value >= 3:
        colour = discord.Colour.gold()
    else:
        colour = discord.Colour.green()

    embed = discord.Embed(title=title, colour=colour)
    embed.add_field(name="発生時刻", value=formatted_dt or "N/A", inline=False)
    embed.add_field(name="震源地", value=area or "N/A")
    embed.add_field(name="マグニチュード", value=str(mag) or "N/A")
    embed.add_field(name="最大震度", value=str(maxint) or "N/A")

    img_path = item.get("img") or item.get("json", "").replace(".json", ".png")
    if img_path:
        embed.set_image(url=EEW_BASE_URL + img_path)

    await channel.send(embed=embed)

async def watch_eew() -> None:
    await client.wait_until_ready()
    global LAST_EEW_ID
    while True:
        try:
            async with aiohttp.ClientSession() as sess:
                try:
                    async with sess.get(EEW_LIST_URL, timeout=10) as resp:
                        if resp.status == 429:
                            logger.warning("EEW API rate limited; backing off")
                            await asyncio.sleep(60)
                            continue
                        resp.raise_for_status()
                        data = await resp.json()
                except aiohttp.ClientError as e:
                    logger.error("EEW fetch network error: %s", e)
                    await asyncio.sleep(30)
                    continue
            if data:
                latest = data[0]
                eid = latest.get("json", "")
                if eid and eid != LAST_EEW_ID:
                    LAST_EEW_ID = eid
                    _save_last_eew(eid)
                    if EEW_CHANNEL_ID:
                        ch = client.get_channel(EEW_CHANNEL_ID)
                        if ch is None:
                            try:
                                ch = await client.fetch_channel(EEW_CHANNEL_ID)
                            except Exception as e:
                                logger.error("failed to fetch eew channel: %s", e)
                                ch = None
                        if isinstance(ch, MESSAGE_CHANNEL_TYPES):
                            try:
                                await _send_eew(ch, latest)
                            except Exception as e:
                                logger.error("failed to send eew: %s", e)
        except Exception as e:
            logger.error("EEW monitor error: %s", e)
        # poll for new alerts roughly every 15 seconds
        await asyncio.sleep(15)


weather_task: asyncio.Task | None = None
CITIES = {
    "札幌": (43.0667, 141.3500),
    "東京": (35.6895, 139.6917),
    "大阪": (34.6937, 135.5023),
    "福岡": (33.5902, 130.4017),
}
JST = datetime.timezone(datetime.timedelta(hours=9))

async def _fetch_json(url: str) -> dict:
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url, timeout=10) as resp:
            return await resp.json()

async def _fetch_overview() -> str | None:
    url = "https://www.jma.go.jp/bosai/forecast/data/overview_forecast/130000.json"
    try:
        data = await _fetch_json(url)
        text = data.get("text", "")
        return text.split("。", 1)[0] + "。" if text else None
    except Exception as e:
        logger.error("weather overview fetch failed: %s", e)
        return None

async def _get_city_weather(lat: float, lon: float, target: datetime.datetime) -> tuple[str, float, float] | None:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&hourly=temperature_2m,surface_pressure,weathercode"
        "&timezone=Asia%2FTokyo&forecast_days=2"
    )
    try:
        data = await _fetch_json(url)
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        press = hourly.get("surface_pressure", [])
        codes = hourly.get("weathercode", [])
        target_str = target.strftime("%Y-%m-%dT%H:00")
        if target_str in times:
            i = times.index(target_str)
            return WMO_CODES.get(codes[i], str(codes[i])), temps[i], press[i]
    except Exception as e:
        logger.error("weather fetch failed: %s", e)
    return None

async def send_weather(channel: discord.TextChannel, target: datetime.datetime):
    lines = []
    for name, (lat, lon) in CITIES.items():
        info = await _get_city_weather(lat, lon, target)
        if info:
            desc, temp, pres = info
            lines.append(f"{name}: {desc} {temp:.1f}℃ {pres:.0f}hPa")
    if not lines:
        return
    title = target.strftime("%Y-%m-%d %H:%M の天気")
    emb = discord.Embed(title=title, description="\n".join(lines), colour=0x3498db)
    await channel.send(embed=emb)
    overview = await _fetch_overview()
    if overview:
        await channel.send(overview)

async def scheduled_weather() -> None:
    await client.wait_until_ready()
    while True:
        now = datetime.datetime.now(JST)
        hours = [0, 6, 12, 18]
        future = [
            datetime.datetime.combine(now.date(), datetime.time(h, tzinfo=JST))
            for h in hours
            if datetime.datetime.combine(now.date(), datetime.time(h, tzinfo=JST)) > now
        ]
        if future:
            next_run = min(future)
        else:
            next_run = datetime.datetime.combine(now.date() + datetime.timedelta(days=1), datetime.time(0, tzinfo=JST))
        await asyncio.sleep((next_run - now).total_seconds())
        if not WEATHER_CHANNEL_ID:
            continue
        ch = client.get_channel(WEATHER_CHANNEL_ID)
        if ch is None:
            try:
                ch = await client.fetch_channel(WEATHER_CHANNEL_ID)
            except Exception as e:
                logger.error("failed to fetch weather channel: %s", e)
                continue
        if isinstance(ch, MESSAGE_CHANNEL_TYPES):
            try:
                await send_weather(ch, next_run)
            except Exception as e:
                logger.error("failed to send weather: %s", e)



# ───────────────── イベント ─────────────────
from discord import Activity, ActivityType, Status

# 起動時に 1 回設定
@client.event
async def on_ready():
    await client.change_presence(
        status=Status.online,
        activity=Activity(type=ActivityType.playing,
                          name="y!help で使い方を見る")
    )
    try:
        await tree.sync()
    except Exception as e:
        logger.error("Slash command sync failed: %s", e)
    logger.info("LOGIN: %s", client.user)
    global news_task
    if news_task is None or news_task.done():
        news_task = asyncio.create_task(hourly_news())
    global eew_task
    if eew_task is None or eew_task.done():
        eew_task = asyncio.create_task(watch_eew())
    global weather_task
    if weather_task is None or weather_task.done():
        weather_task = asyncio.create_task(scheduled_weather())

# ----- Slash command wrappers -----
@tree.command(name="ping", description="Botの応答速度を表示")
async def sc_ping(itx: discord.Interaction):

    try:
        await itx.response.defer()
        await cmd_ping(SlashMessage(itx))
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")



@tree.command(name="say", description="Botに発言させます")
@app_commands.describe(text="送信するテキスト")
async def sc_say(itx: discord.Interaction, text: str):

    try:
        await itx.response.defer()
        await cmd_say(SlashMessage(itx), text)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")



@tree.command(name="date", description="Unix 時刻をDiscord形式で表示")
@app_commands.describe(timestamp="Unixタイムスタンプ")
async def sc_date(itx: discord.Interaction, timestamp: int | None = None):

    try:
        await itx.response.defer()
        arg = str(timestamp) if timestamp is not None else ""
        await cmd_date(SlashMessage(itx), arg)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")



@tree.command(name="user", description="ユーザー情報を表示")
@app_commands.describe(user="表示するユーザー")
async def sc_user(itx: discord.Interaction, user: discord.User | None = None):

    try:
        await itx.response.defer()
        target = user or itx.user
        member = target if isinstance(target, discord.Member) else (itx.guild.get_member(target.id) if itx.guild else None)
        emb = await build_user_embed(target, member, itx.channel)
        await itx.followup.send(embed=emb)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="server", description="サーバー情報を表示")
async def sc_server(itx: discord.Interaction):

    try:
        await itx.response.defer()
        msg = SlashMessage(itx)
        await cmd_server(msg)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")



@tree.command(name="dice", description="ダイスを振ります")
@app_commands.describe(nota="(例: 2d6, d20)")
async def sc_dice(itx: discord.Interaction, nota: str):

    try:
        await itx.response.defer()
        await cmd_dice(SlashMessage(itx), nota)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="qr", description="QR コードを生成")
@app_commands.describe(text="QRコードにする文字列")
async def sc_qr(itx: discord.Interaction, text: str):

    try:
        await itx.response.defer()
        await cmd_qr(SlashMessage(itx), text)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="barcode", description="バーコードを生成")
@app_commands.describe(text="バーコードにする文字列")
async def sc_barcode(itx: discord.Interaction, text: str):

    try:
        await itx.response.defer()
        await cmd_barcode(SlashMessage(itx), text)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")



@tree.command(name="gpt", description="ChatGPT に質問")
@app_commands.describe(text="質問内容")
async def sc_gpt(itx: discord.Interaction, text: str):

    try:
        await itx.response.defer()
        msg = SlashMessage(itx)
        await cmd_gpt(msg, text)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="tex", description="TeX 数式を画像に変換")
@app_commands.describe(expr="TeX 数式")
async def sc_tex(itx: discord.Interaction, expr: str):

    try:
        await itx.response.defer()
        await cmd_tex(SlashMessage(itx), expr)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="news", description="ニュース送信先チャンネルを設定")
@app_commands.describe(channel="投稿先チャンネル")
async def sc_news(itx: discord.Interaction, channel: discord.TextChannel):

    if not itx.user.guild_permissions.administrator:
        await itx.response.send_message("管理者専用コマンドです。", ephemeral=True)
        return
    global NEWS_CHANNEL_ID
    NEWS_CHANNEL_ID = channel.id
    _save_news_channel(NEWS_CHANNEL_ID)
    await itx.response.send_message(
        f"ニュースチャンネルを {channel.mention} に設定しました。"
    )
    try:
        await send_latest_news(channel)
    except Exception as e:
        await itx.followup.send(f"テスト送信に失敗: {e}")


@tree.command(name="eew", description="地震速報送信先チャンネルを設定")
@app_commands.describe(channel="投稿先チャンネル")
async def sc_eew(itx: discord.Interaction, channel: discord.TextChannel):

    if not itx.user.guild_permissions.administrator:
        await itx.response.send_message("管理者専用コマンドです。", ephemeral=True)
        return
    global EEW_CHANNEL_ID
    EEW_CHANNEL_ID = channel.id
    _save_eew_channel(EEW_CHANNEL_ID)
    await itx.response.send_message(
        f"地震速報チャンネルを {channel.mention} に設定しました。"
    )
    try:
        await send_latest_eew(channel)
    except Exception as e:
        await itx.followup.send(f"テスト送信に失敗: {e}")


@tree.command(name="weather", description="天気予報送信先チャンネルを設定")
@app_commands.describe(channel="投稿先チャンネル")
async def sc_weather(itx: discord.Interaction, channel: discord.TextChannel):

    if not itx.user.guild_permissions.administrator:
        await itx.response.send_message("管理者専用コマンドです。", ephemeral=True)
        return
    global WEATHER_CHANNEL_ID
    WEATHER_CHANNEL_ID = channel.id
    _save_weather_channel(WEATHER_CHANNEL_ID)
    await itx.response.send_message(
        f"天気予報チャンネルを {channel.mention} に設定しました。"
    )
    try:
        target = datetime.datetime.now(JST).replace(minute=0, second=0, microsecond=0)
        await send_weather(channel, target)
    except Exception as e:
        await itx.followup.send(f"テスト送信に失敗: {e}")


@tree.command(name="poker", description="BOTやプレイヤーとポーカーで遊ぶ")

@app_commands.describe(opponent="対戦相手。省略するとBOT")
async def sc_poker(itx: discord.Interaction, opponent: discord.User | None = None):

    try:
        await itx.response.defer()
        arg = opponent.mention if opponent else ""
        await cmd_poker(SlashMessage(itx), arg)

    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="play", description="曲を再生キューに追加")
@app_commands.describe(
    query1="URLや検索キーワード",
    file1="(任意)添付ファイル",
    query2="追加のキーワードまたはURL",
    file2="追加の添付ファイル",
    query3="追加のキーワードまたはURL",
    file3="追加の添付ファイル",
)
async def sc_play(
    itx: discord.Interaction,
    query1: str | None = None,
    file1: discord.Attachment | None = None,
    query2: str | None = None,
    file2: discord.Attachment | None = None,
    query3: str | None = None,
    file3: discord.Attachment | None = None,
):
    try:
        await itx.response.defer()
        opts = itx.data.get("options", [])
        values = {
            "query1": query1,
            "file1": file1,
            "query2": query2,
            "file2": file2,
            "query3": query3,
            "file3": file3,
        }
        order: list[tuple[str, Any]] = []
        for op in opts:
            name = op.get("name")
            if name.startswith("query") and values.get(name):
                order.append(("query", values[name]))
            elif name.startswith("file"):
                att = values.get(name)
                if att:
                    order.append(("file", att))
        if not order:
            if query1:
                order.append(("query", query1))
            for key in ("file1", "file2", "file3"):
                att = values.get(key)
                if att:
                    order.append(("file", att))
        for kind, val in order:
            if kind == "query":
                msg = SlashMessage(itx)
                await cmd_play(msg, val, first_query=True)
            else:
                msg = SlashMessage(itx, [val])
                await cmd_play(msg, "", first_query=False)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")



@tree.command(name="queue", description="再生キューを表示")
async def sc_queue(itx: discord.Interaction):

    try:
        await itx.response.defer()
        await cmd_queue(SlashMessage(itx), "")
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")



@tree.command(name="remove", description="キューから曲を削除")
@app_commands.describe(numbers="削除する番号 (スペース区切り)")
async def sc_remove(itx: discord.Interaction, numbers: str):

    try:
        await itx.response.defer()
        await cmd_remove(SlashMessage(itx), numbers)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")



@tree.command(name="keep", description="指定番号以外を削除")
@app_commands.describe(numbers="残す番号 (スペース区切り)")
async def sc_keep(itx: discord.Interaction, numbers: str):

    try:
        await itx.response.defer()
        await cmd_keep(SlashMessage(itx), numbers)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="seek", description="再生位置を指定")
@app_commands.describe(position="例: 1m30s, 2:00")
async def sc_seek(itx: discord.Interaction, position: str):

    try:
        await itx.response.defer()
        await cmd_seek(SlashMessage(itx), position)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="rewind", description="再生位置を巻き戻し")
@app_commands.describe(time="例: 10s, 1m, 1:00 (省略可)")
async def sc_rewind(itx: discord.Interaction, time: str | None = None):

    try:
        await itx.response.defer()
        await cmd_rewind(SlashMessage(itx), time or "")
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="forward", description="再生位置を早送り")
@app_commands.describe(time="例: 10s, 1m, 1:00 (省略可)")
async def sc_forward(itx: discord.Interaction, time: str | None = None):

    try:
        await itx.response.defer()
        await cmd_forward(SlashMessage(itx), time or "")
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


@tree.command(name="purge", description="メッセージを一括削除")
@app_commands.describe(arg="削除数またはメッセージリンク")
async def sc_purge(itx: discord.Interaction, arg: str):

    try:
        await itx.response.defer()
        await cmd_purge(SlashMessage(itx), arg)
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")



@tree.command(name="stop", description="VC から退出")
async def sc_stop(itx: discord.Interaction):

    try:
        await itx.response.defer()
        await cmd_stop(SlashMessage(itx), "")
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")





@tree.command(name="help", description="コマンド一覧を表示")
async def sc_help(itx: discord.Interaction):

    try:
        await itx.response.defer()
        await cmd_help(SlashMessage(itx))
    except Exception as e:
        await itx.followup.send(f"エラー発生: {e}")


# ------------ 翻訳リアクション機能ここから ------------

# flags.txt を読み込み「絵文字 ➜ ISO 国コード」を作る
SPECIAL_EMOJI_ISO: dict[str, str] = {}
try:
    with open("flags.txt", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                emoji = parts[0]                  # 例 🇯🇵
                shortcode = parts[1]              # 例 :flag_jp:
                if shortcode.startswith(":flag_") and shortcode.endswith(":"):
                    iso = shortcode[6:-1].upper() # jp -> JP
                    SPECIAL_EMOJI_ISO[emoji] = iso
except FileNotFoundError:
    logger.warning("flags.txt not found. Flag translation reactions disabled")

ISO_TO_LANG = {
    # A
    "AW": "Dutch",
    "AF": "Dari Persian",
    "AO": "Portuguese",
    "AI": "English",
    "AX": "Swedish",
    "AL": "Albanian",
    "AD": "Catalan",
    "AE": "Arabic",
    "AR": "Spanish",
    "AM": "Armenian",
    "AS": "Samoan",
    "AQ": "English",
    "TF": "French",
    "AG": "English",
    "AU": "English",
    "AT": "German",
    "AZ": "Azerbaijani",
    # B
    "BI": "Kirundi",
    "BE": "French",        # (also Dutch, German)
    "BJ": "French",
    "BQ": "Dutch",
    "BF": "French",
    "BD": "Bengali",
    "BG": "Bulgarian",
    "BH": "Arabic",
    "BS": "English",
    "BA": "Bosnian",
    "BL": "French",
    "BY": "Belarusian",
    "BZ": "English",
    "BM": "English",
    "BO": "Spanish",
    "BR": "Portuguese",
    "BB": "English",
    "BN": "Malay",
    "BT": "Dzongkha",
    "BV": "Norwegian",
    "BW": "English",
    # C
    "CF": "French",
    "CA": "English",
    "CC": "English",
    "CH": "German",        # (also French, Italian, Romansh)
    "CL": "Spanish",
    "CN": "Chinese (Simplified)",
    "CI": "French",
    "CM": "French",
    "CD": "French",
    "CG": "French",
    "CK": "English",
    "CO": "Spanish",
    "KM": "Comorian",
    "CV": "Portuguese",
    "CR": "Spanish",
    "CU": "Spanish",
    "CW": "Dutch",
    "CX": "English",
    "KY": "English",
    "CY": "Greek",         # (also Turkish)
    "CZ": "Czech",
    # D
    "DE": "German",
    "DJ": "French",
    "DM": "English",
    "DK": "Danish",
    "DO": "Spanish",
    "DZ": "Arabic",
    # E
    "EC": "Spanish",
    "EG": "Arabic",
    "ER": "Tigrinya",
    "EH": "Arabic",
    "ES": "Spanish",
    "EE": "Estonian",
    "ET": "Amharic",
    # F
    "FI": "Finnish",
    "FJ": "English",
    "FK": "English",
    "FR": "French",
    "FO": "Faroese",
    "FM": "English",
    # G
    "GA": "French",
    "GB": "English",
    "GE": "Georgian",
    "GG": "English",
    "GH": "English",
    "GI": "English",
    "GN": "French",
    "GP": "French",
    "GM": "English",
    "GW": "Portuguese",
    "GQ": "Spanish",
    "GR": "Greek",
    "GD": "English",
    "GL": "Greenlandic",
    "GT": "Spanish",
    "GF": "French",
    "GU": "English",
    "GY": "English",
    # H
    "HK": "Chinese (Traditional)",
    "HM": "English",
    "HN": "Spanish",
    "HR": "Croatian",
    "HT": "Haitian Creole",
    "HU": "Hungarian",
    # I
    "ID": "Indonesian",
    "IM": "English",
    "IN": "Hindi",
    "IO": "English",
    "IE": "English",
    "IR": "Persian",
    "IQ": "Arabic",
    "IS": "Icelandic",
    "IL": "Hebrew",
    "IT": "Italian",
    # J
    "JM": "English",
    "JE": "English",
    "JO": "Arabic",
    "JP": "Japanese",
    # K
    "KZ": "Kazakh",
    "KE": "Swahili",
    "KG": "Kyrgyz",
    "KH": "Khmer",
    "KI": "English",
    "KN": "English",
    "KR": "Korean",
    "KW": "Arabic",
    # L
    "LA": "Lao",
    "LB": "Arabic",
    "LR": "English",
    "LY": "Arabic",
    "LC": "English",
    "LI": "German",
    "LK": "Sinhala",
    "LS": "Sesotho",
    "LT": "Lithuanian",
    "LU": "Luxembourgish",
    "LV": "Latvian",
    # M
    "MO": "Chinese (Traditional)",
    "MF": "French",
    "MA": "Arabic",
    "MC": "French",
    "MD": "Romanian",
    "MG": "Malagasy",
    "MV": "Dhivehi",
    "MX": "Spanish",
    "MH": "Marshallese",
    "MK": "Macedonian",
    "ML": "French",
    "MT": "Maltese",
    "MM": "Burmese",
    "ME": "Montenegrin",
    "MN": "Mongolian",
    "MP": "English",
    "MZ": "Portuguese",
    "MR": "Arabic",
    "MS": "English",
    "MQ": "French",
    "MU": "English",
    "MW": "English",
    "MY": "Malay",
    "YT": "French",
    # N
    "NA": "English",
    "NC": "French",
    "NE": "French",
    "NF": "English",
    "NG": "English",
    "NI": "Spanish",
    "NU": "English",
    "NL": "Dutch",
    "NO": "Norwegian",
    "NP": "Nepali",
    "NR": "Nauruan",
    "NZ": "English",
    # O
    "OM": "Arabic",
    # P
    "PK": "Urdu",
    "PA": "Spanish",
    "PN": "English",
    "PE": "Spanish",
    "PH": "Filipino",
    "PW": "Palauan",
    "PG": "Tok Pisin",
    "PL": "Polish",
    "PR": "Spanish",
    "KP": "Korean",
    "PT": "Portuguese",
    "PY": "Spanish",
    "PS": "Arabic",
    "PF": "French",
    # Q
    "QA": "Arabic",
    # R
    "RE": "French",
    "RO": "Romanian",
    "RU": "Russian",
    "RW": "Kinyarwanda",
    # S
    "SA": "Arabic",
    "SD": "Arabic",
    "SN": "French",
    "SG": "English",
    "GS": "English",
    "SH": "English",
    "SJ": "Norwegian",
    "SB": "English",
    "SL": "English",
    "SV": "Spanish",
    "SM": "Italian",
    "SO": "Somali",
    "PM": "French",
    "RS": "Serbian",
    "SS": "English",
    "ST": "Portuguese",
    "SR": "Dutch",
    "SK": "Slovak",
    "SI": "Slovene",
    "SE": "Swedish",
    "SZ": "English",
    "SX": "Dutch",
    "SC": "English",
    "SY": "Arabic",
    # T
    "TC": "English",
    "TD": "French",
    "TG": "French",
    "TH": "Thai",
    "TJ": "Tajik",
    "TK": "Tokelauan",
    "TM": "Turkmen",
    "TL": "Tetum",
    "TO": "Tongan",
    "TT": "English",
    "TN": "Arabic",
    "TR": "Turkish",
    "TV": "Tuvaluan",
    "TW": "Chinese (Traditional)",
    "TZ": "Swahili",
    # U
    "UG": "English",
    "UA": "Ukrainian",
    "UM": "English",
    "UY": "Spanish",
    "US": "English",
    "UZ": "Uzbek",
    # V
    "VA": "Italian",
    "VC": "English",
    "VE": "Spanish",
    "VG": "English",
    "VI": "English",
    "VN": "Vietnamese",
    "VU": "Bislama",
    # W
    "WF": "French",
    "WS": "Samoan",
    # Y
    "YE": "Arabic",
    # Z
    "ZA": "English",
    "ZM": "English",
    "ZW": "English",
}


def flag_to_iso(emoji: str) -> str | None:
    """絵文字2文字なら regional-indicator → ISO に変換"""
    if len(emoji) != 2:
        return None
    base = 0x1F1E6
    try:
        return ''.join(chr(ord(c) - base + 65) for c in emoji)
    except:
        return None

@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """メッセージに付いた国旗リアクションで自動翻訳"""

    # 1. BOT 自身のリアクションは無視
    if payload.member and payload.member.bot:
        return

    emoji = str(payload.emoji)

    # 2. 国旗 ⇒ ISO2 文字
    iso = SPECIAL_EMOJI_ISO.get(emoji) or flag_to_iso(emoji)
    if not iso:
        return

    # 3. ISO ⇒ 使用する言語名（例: "English"）
    lang = ISO_TO_LANG.get(iso)
    if not lang:
        logger.debug("未登録 ISO: %s", iso)
        return

    # 4. 元メッセージ取得
    channel  = await client.fetch_channel(payload.channel_id)
    message  = await channel.fetch_message(payload.message_id)
    original = message.content.strip()
    if not original:
        return

    # 5. GPT-4.1 で翻訳
    async with channel.typing():
        try:
            prompt = (
                f"Translate the following message into {lang}, considering the regional variant indicated by this flag {emoji}. "
                "Provide only the translation, and keep it concise.\n" + original
            )
            translated = await cappuccino_agent.call_llm(prompt)

            # 6. Discord 2000 文字制限に合わせて 1 通で送信
            header     = f"💬 **{lang}** translation:\n"
            available  = 2000 - len(header)
            if len(translated) > available:
                # ヘッダーを含めて 2000 文字ちょうどになるように丸める
                translated = translated[:available - 3] + "..."

            await channel.send(header + translated)

        except Exception as e:
            # 失敗したらメッセージ主へリプライ（失敗した場合はチャンネルに通知）
            try:
                await message.reply(f"翻訳エラー: {e}", delete_after=5)
            except Exception:
                await channel.send(f"翻訳エラー: {e}", delete_after=5)
            logger.error("翻訳失敗: %s", e)


@client.event
async def on_message(msg: discord.Message):
    # ① Bot の発言は無視
    if msg.author.bot:
        return

    # ② y!? で名言カード化
    if msg.content.strip().lower() == "y!?" and msg.reference:
        try:
            # 返信元メッセージ取得
            src = await msg.channel.fetch_message(msg.reference.message_id)
            if not src.content:          # 空メッセージはスキップ
                return

            # 画像生成（初期はモノクロ）
            img_path = await make_quote_image(src.author, src.content, color=False)

            # ボタン用ペイロード
            payload = {
                "user":  src.author,
                "text":  src.content[:200],
                "color": False
            }
            view = QuoteView(invoker=msg.author, payload=payload)

            # 元メッセージへ画像リプライ
            await src.reply(
                content=f"🖼️ made by {msg.author.mention}",
                file=discord.File(img_path, filename=img_path.name),
                view=view
            )
            try:
                img_path.unlink()
            except Exception:
                pass

            # y!? コマンドを削除
            await msg.delete()

        except Exception as e:
            await msg.reply(f"名言化に失敗: {e}", delete_after=10)
        return  # ← ここで終了し、既存コマンド解析へ進まない

    # ③ 既存コマンド解析
    cmd, arg = parse_cmd(msg.content)
    if cmd == "ping":   await cmd_ping(msg)
    elif cmd == "say":  await cmd_say(msg, arg)
    elif cmd == "date": await cmd_date(msg, arg)
    elif cmd == "user": await cmd_user(msg, arg)
    elif cmd == "dice": await cmd_dice(msg, arg or "1d100")
    elif cmd == "gpt":
        await cmd_gpt(msg, arg)
    elif cmd == "help": await cmd_help(msg)
    elif cmd == "play": await cmd_play(msg, arg, split_commas=True)
    elif cmd == "queue":await cmd_queue(msg, arg)
    elif cmd == "remove":await cmd_remove(msg, arg)
    elif cmd == "keep": await cmd_keep(msg, arg)
    elif cmd == "seek": await cmd_seek(msg, arg)
    elif cmd == "rewind": await cmd_rewind(msg, arg)
    elif cmd == "forward": await cmd_forward(msg, arg)
    elif cmd == "server": await cmd_server(msg)
    elif cmd == "purge":await cmd_purge(msg, arg)
    elif cmd == "qr": await cmd_qr(msg, arg)
    elif cmd == "barcode": await cmd_barcode(msg, arg)
    elif cmd == "tex": await cmd_tex(msg, arg)
    elif cmd == "news": await cmd_news(msg, arg)
    elif cmd == "eew": await cmd_eew(msg, arg)
    elif cmd == "weather": await cmd_weather(msg, arg)

    elif cmd == "poker": await cmd_poker(msg, arg)

    else:
        mention = client.user and any(m.id == client.user.id for m in msg.mentions)
        history = await _gather_reply_chain(msg)
        replied = any(m.author.id == client.user.id for m in history)
        if mention or replied:
            text = _strip_bot_mention(msg.content)
            if text:
                await cmd_gpt(msg, text)


# ───────────────── 起動 ─────────────────
async def start_bot():
    """Start the Discord bot."""
    if not TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set. Check your environment variables or .env file")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set. Check your environment variables or .env file")
    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(start_bot())
