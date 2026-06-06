"""
Twitter Dev Content Pipeline
Generates and posts system design + webdev threads to Twitter/X.
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
from src.publishers.twitter_publisher import TwitterPublisher
from config.settings import Settings
from config.topics import TopicBank

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist(): return datetime.now(IST)


def send_telegram(token: str, chat_id: str, msg: str):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
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
    token = settings.telegram_bot_token
    chat_id = settings.telegram_allowed_user_id

    logger.info("=" * 60)
    logger.info("TWITTER PIPELINE STARTED | niche=%s type=%s dry_run=%s",
                niche, content_type, dry_run)
    logger.info("=" * 60)

    try:
        # ── 1. Topic ───────────────────────────────────────────────────
        topic_bank = TopicBank()
        selected_topic = topic or topic_bank.pick_unused(niche)
        logger.info("[1/4] ✅ Topic: %s", selected_topic)

        # ── 2. Generate content ────────────────────────────────────────
        gen = ThreadGenerator(settings)
        card_gen = CardGenerator()

        if content_type == "thread":
            content = await gen.generate_thread(selected_topic, niche)
            tweets = content.format_for_posting()
            logger.info("[2/4] ✅ Thread: %d tweets | hook: %s",
                        len(tweets), content.hook[:60])

            # Generate card for hook tweet
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
            logger.info("[2/4] ✅ Single tweet: %s", content.tweet[:60])

        # ── 3. Post to Twitter ─────────────────────────────────────────
        posted_ids = []
        tweet_url = ""

        if not dry_run:
            publisher = TwitterPublisher(settings)
            logger.info("[3/4] Posting to Twitter...")

            if content_type == "thread":
                # Post hook with card image
                if card_path and card_path.exists():
                    first = await publisher.post_with_image(tweets[0], card_path)
                else:
                    first = await publisher.post_tweet(tweets[0])
                posted_ids.append(first["id"])

                # Post remaining tweets as replies
                reply_id = first["id"]
                for tweet_text in tweets[1:]:
                    t = await publisher.post_tweet(tweet_text, reply_id)
                    posted_ids.append(t["id"])
                    reply_id = t["id"]
            else:
                t = await publisher.post_tweet(tweets[0])
                posted_ids.append(t["id"])

            tweet_url = f"https://twitter.com/i/web/status/{posted_ids[0]}"
            logger.info("[3/4] ✅ Posted: %s", tweet_url)
        else:
            logger.info("[3/4] ⏭️  Dry run — skipping post")
            logger.info("Preview:\n%s", "\n---\n".join(tweets[:3]))

        # ── 4. Notify Telegram ─────────────────────────────────────────
        topic_bank.mark_used(niche, selected_topic)

        hook_text = content.hook if hasattr(content, 'hook') else content.tweet
        msg = (
            f"🐦 Twitter thread posted!\n"
            f"Topic: {selected_topic}\n"
            f"Niche: {niche}\n"
            f"Tweets: {len(tweets)}\n"
            f"Hook: {hook_text[:80]}\n"
            f"URL: {tweet_url or 'dry-run'}"
        )
        send_telegram(token, chat_id, msg)

        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE ✅")
        logger.info("=" * 60)

        return {
            "status": "success",
            "topic": selected_topic,
            "niche": niche,
            "tweet_url": tweet_url,
            "tweet_count": len(tweets),
            "dry_run": dry_run,
        }

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error("PIPELINE FAILED ❌: %s\n%s", exc, tb)
        send_telegram(token, chat_id,
                      f"❌ Twitter pipeline failed!\nTopic: {topic}\nError: {str(exc)[:200]}")
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
                log_dir / f"twitter_{now_ist().strftime('%Y%m%d')}.log",
                encoding="utf-8"
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
