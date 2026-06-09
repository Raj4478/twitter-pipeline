"""
Twitter Dev Content Pipeline — now posts to Telegram channel instead of Twitter.
Generates thread → creates card → posts to Telegram as a threaded chain.
"""

import asyncio
import logging
import sys
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from src.generators.thread_generator import ThreadGenerator
from src.generators.card_generator import CardGenerator
from src.publishers.telegram_publisher import TelegramPublisher
from config.settings import Settings
from config.topics import TopicBank

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


def send_telegram_notification(token: str, chat_id: str, msg: str):
    """Send a plain notification message (to personal chat, not channel)."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.warning("Telegram notification failed: %s", e)


async def run_pipeline(
    niche: str = "system_design",
    topic: Optional[str] = None,
    content_type: str = "thread",
    dry_run: bool = False,
) -> dict:
    settings = Settings()

    logger.info("=" * 60)
    logger.info(
        "PIPELINE STARTED | niche=%s type=%s dry_run=%s",
        niche, content_type, dry_run
    )
    logger.info("=" * 60)

    try:
        # ── 1. Pick topic ──────────────────────────────────────────────
        topic_bank = TopicBank()
        selected_topic = topic or topic_bank.pick_unused(niche)
        logger.info("[1/4] ✅ Topic: %s", selected_topic)

        # ── 2. Generate content ────────────────────────────────────────
        gen = ThreadGenerator(settings)
        card_gen = CardGenerator(settings)

        if content_type == "thread":
            content = await gen.generate_thread(selected_topic, niche)
            tweets = content.format_for_posting()
            logger.info("[2/4] ✅ Thread: %d tweets | hook: %s",
                        len(tweets), content.hook[:60])

            card_path = card_gen.generate(
                topic=selected_topic,
                image_text=content.image_text,
                niche=niche,
                facts=content.tweets[:4],
            )
            logger.info("[2/4] ✅ Card: %s", card_path)
        else:
            content = await gen.generate_single(selected_topic, niche)
            tweets = [content.format_for_posting()]
            card_path = None
            logger.info("[2/4] ✅ Single tweet: %s", tweets[0][:60])

        # ── 3. Post to Telegram channel ────────────────────────────────
        channel_url = ""

        if not dry_run:
            publisher = TelegramPublisher(settings)
            logger.info("[3/4] Posting to Telegram channel...")

            if content_type == "thread":
                result = publisher.post_thread(
                    tweets=tweets,
                    card_path=card_path,
                    topic=selected_topic,
                    niche=niche,
                )
            else:
                result = publisher.post_single(
                    tweet=tweets[0],
                    card_path=card_path,
                    niche=niche,
                )

            channel_url = result.get("channel_url", "")
            logger.info("[3/4] ✅ Posted %d messages to Telegram",
                        result.get("tweet_count", 0))
        else:
            logger.info("[3/4] ⏭️  Dry run — skipping post")
            logger.info("Preview:\n%s", "\n---\n".join(tweets[:3]))

        # ── 4. Notify personal Telegram chat ──────────────────────────
        topic_bank.mark_used(niche, selected_topic)

        hook_text = content.hook if hasattr(content, "hook") else tweets[0]
        msg = (
            f"✅ Telegram thread posted!\n"
            f"Topic: {selected_topic}\n"
            f"Niche: {niche}\n"
            f"Tweets: {len(tweets)}\n"
            f"Hook: {hook_text[:80]}\n"
            f"Channel: {channel_url or 'dry-run'}"
        )
        send_telegram_notification(
            settings.telegram_bot_token,
            settings.telegram_allowed_user_id,
            msg,
        )

        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE ✅")
        logger.info("=" * 60)

        return {
            "status": "success",
            "topic": selected_topic,
            "niche": niche,
            "channel_url": channel_url,
            "tweet_count": len(tweets),
            "dry_run": dry_run,
        }

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error("PIPELINE FAILED ❌: %s\n%s", exc, tb)
        send_telegram_notification(
            settings.telegram_bot_token,
            settings.telegram_allowed_user_id,
            f"❌ Pipeline failed!\nTopic: {topic}\nError: {str(exc)[:200]}",
        )
        raise


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", default="system_design",
                        choices=["system_design", "webdev", "career"])
    parser.add_argument("--topic", default="")
    parser.add_argument("--type", dest="content_type", default="thread",
                        choices=["thread", "single"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                log_dir / f"pipeline_{now_ist().strftime('%Y%m%d')}.log",
                encoding="utf-8",
            ),
        ],
    )

    result = asyncio.run(run_pipeline(
        niche=args.niche,
        topic=args.topic or None,
        content_type=args.content_type,
        dry_run=args.dry_run,
    ))
    print(f"\n✅ Done | topic={result['topic']} | tweets={result['tweet_count']}")


if __name__ == "__main__":
    main()
