"""
Telegram Publisher — posts Twitter threads to a Telegram channel.

Strategy:
  - Tweet 1 (hook): sent as photo with card image + caption (1024 char limit)
  - Tweets 2-N: sent as individual text messages, each as a reply to previous
  - Final message: summary with hashtags + tweet count
"""

import logging
import json
import urllib.request
import urllib.parse
import urllib.error
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramPublisher:
    def __init__(self, settings):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_channel_id

    def _api(self, method: str, data: dict) -> dict:
        url = TELEGRAM_API.format(token=self.token, method=method)
        payload = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            logger.error("Telegram API error %d on %s: %s", e.code, method, body)
            raise Exception(f"Telegram {method} failed {e.code}: {body}")

    def _send_photo(self, photo_path: Path, caption: str,
                    reply_to: Optional[int] = None) -> int:
        """Upload photo + caption via multipart. Returns message_id."""
        import uuid
        url = TELEGRAM_API.format(token=self.token, method="sendPhoto")
        boundary = uuid.uuid4().hex
        caption_bytes = caption[:1024].encode("utf-8")

        with open(photo_path, "rb") as f:
            photo_bytes = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            f"{self.chat_id}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="parse_mode"\r\n\r\n'
            f"HTML\r\n"
        ).encode()

        if reply_to:
            body += (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="reply_to_message_id"\r\n\r\n'
                f"{reply_to}\r\n"
            ).encode()

        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n\r\n'
        ).encode() + caption_bytes + b"\r\n"

        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo"; filename="card.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + photo_bytes + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                msg_id = data["result"]["message_id"]
                logger.info("Photo sent, message_id=%d", msg_id)
                return msg_id
        except urllib.error.HTTPError as e:
            body_err = e.read().decode()
            logger.error("sendPhoto failed %d: %s | chat_id=%s | token_prefix=%s",
                         e.code, body_err, self.chat_id, self.token[:10])
            raise Exception(f"sendPhoto failed {e.code}: {body_err}")

    def _send_text(self, text: str, reply_to: Optional[int] = None) -> int:
        """Send text message. Returns message_id."""
        data = {
            "chat_id": self.chat_id,
            "text": text[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to:
            data["reply_to_message_id"] = reply_to

        result = self._api("sendMessage", data)
        msg_id = result["result"]["message_id"]
        logger.info("Text sent, message_id=%d", msg_id)
        return msg_id

    def verify_bot(self):
        """Test bot token and channel access before posting."""
        # 1. Check bot token is valid
        me = self._api("getMe", {})
        bot_name = me["result"]["username"]
        logger.info("Bot verified: @%s", bot_name)

        # 2. Check channel access
        try:
            chat = self._api("getChat", {"chat_id": self.chat_id})
            chat_title = chat["result"].get("title", self.chat_id)
            logger.info("Channel verified: %s (%s)", chat_title, self.chat_id)
        except Exception as e:
            raise Exception(
                f"Cannot access channel {self.chat_id}. "
                f"Make sure: 1) Channel exists 2) Bot is admin 3) TELEGRAM_CHANNEL_ID is correct. "
                f"Error: {e}"
            )

    def post_thread(self, tweets: list[str], card_path: Optional[Path] = None,
                    topic: str = "", niche: str = "") -> dict:
        """Post full thread to Telegram channel."""
        if not tweets:
            raise ValueError("No tweets to post")

        # Verify bot + channel before attempting to post
        self.verify_bot()

        first_msg_id = None
        last_msg_id = None

        # ── Message 1: Card + Hook ─────────────────────────────────────
        hook_text = tweets[0]
        caption = f"{hook_text}\n\n🧵 <i>Thread below ↓</i>"

        if card_path and card_path.exists():
            logger.info("Sending card + hook as photo")
            first_msg_id = self._send_photo(card_path, caption)
        else:
            logger.info("No card — sending hook as text")
            first_msg_id = self._send_text(caption)

        last_msg_id = first_msg_id
        time.sleep(0.5)

        # ── Messages 2-N: Thread replies ───────────────────────────────
        for i, tweet in enumerate(tweets[1:], start=2):
            logger.info("Sending tweet %d/%d", i, len(tweets))
            last_msg_id = self._send_text(tweet, reply_to=last_msg_id)
            time.sleep(0.5)

        # ── Final summary ──────────────────────────────────────────────
        hashtags = {
            "system_design": "#SystemDesign #SoftwareEngineering #Tech",
            "webdev": "#WebDev #Programming #BackendDev",
            "career": "#CareerAdvice #SoftwareEngineering #IndianDev",
        }.get(niche, "#Tech #Programming")

        summary = (
            f"📌 <b>Topic:</b> {topic}\n"
            f"🧵 <b>Thread:</b> {len(tweets)} tweets\n\n"
            f"{hashtags}"
        )
        self._send_text(summary, reply_to=last_msg_id)

        channel_url = f"https://t.me/{self.chat_id.lstrip('@')}" if self.chat_id.startswith("@") else ""
        logger.info("Thread posted: %d tweets, first_id=%d", len(tweets), first_msg_id)

        return {
            "first_message_id": first_msg_id,
            "tweet_count": len(tweets),
            "channel_url": channel_url,
        }

    def post_single(self, tweet: str, card_path: Optional[Path] = None,
                    niche: str = "") -> dict:
        """Post a single tweet to Telegram."""
        self.verify_bot()
        hashtags = {
            "system_design": "#SystemDesign #SoftwareEngineering",
            "webdev": "#WebDev #Programming",
            "career": "#CareerAdvice #IndianDev",
        }.get(niche, "#Tech")

        text = f"{tweet}\n\n{hashtags}"

        if card_path and card_path.exists():
            msg_id = self._send_photo(card_path, text)
        else:
            msg_id = self._send_text(text)

        return {"message_id": msg_id, "tweet_count": 1}
