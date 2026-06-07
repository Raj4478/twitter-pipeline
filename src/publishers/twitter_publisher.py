"""
Twitter/X Publisher — posts threads and single tweets via Twitter API v2.
Uses OAuth 1.0a (free tier compatible).
"""

import logging
import time
import hmac
import hashlib
import base64
import urllib.parse
import uuid
import asyncio
from pathlib import Path
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"


class TwitterPublisher:
    def __init__(self, settings):
        self.settings = settings

    def _auth_headers(self, method: str, url: str) -> dict:
        """Generate OAuth 1.0a headers for Twitter API v2 JSON requests.
        
        NOTE: For JSON body requests, body params are NOT included in the
        OAuth signature base string (only applies to form-encoded requests).
        """
        oauth_params = {
            "oauth_consumer_key": self.settings.twitter_api_key,
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self.settings.twitter_access_token,
            "oauth_version": "1.0",
        }

        # For JSON requests: sign ONLY oauth params — never include JSON body
        sorted_params = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted(oauth_params.items())
        )
        base_string = "&".join([
            method.upper(),
            urllib.parse.quote(url, safe=""),
            urllib.parse.quote(sorted_params, safe=""),
        ])

        signing_key = (
            urllib.parse.quote(self.settings.twitter_api_secret, safe="") + "&" +
            urllib.parse.quote(self.settings.twitter_access_token_secret, safe="")
        )
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        ).decode()

        oauth_params["oauth_signature"] = signature
        auth_header = "OAuth " + ", ".join(
            f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
            for k, v in sorted(oauth_params.items())
        )
        return {"Authorization": auth_header, "Content-Type": "application/json"}

    async def post_tweet(self, text: str, reply_to_id: Optional[str] = None) -> dict:
        """Post a single tweet. Returns tweet data including id."""
        url = f"{TWITTER_API_BASE}/tweets"
        body = {"text": text[:280]}
        if reply_to_id:
            body["reply"] = {"in_reply_to_tweet_id": reply_to_id}

        # Body is NOT passed to _auth_headers — JSON bodies excluded from OAuth signing
        headers = self._auth_headers("POST", url)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code == 429:
                logger.warning("Rate limited — waiting 60s")
                await asyncio.sleep(60)
                resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Tweet posted: %s", data["data"]["id"])
            return data["data"]

    async def post_thread(self, tweets: list[str]) -> list[dict]:
        """Post a full thread. Returns list of tweet data."""
        posted = []
        reply_to_id = None

        for i, tweet_text in enumerate(tweets):
            logger.info("Posting tweet %d/%d", i + 1, len(tweets))
            try:
                tweet_data = await self.post_tweet(tweet_text, reply_to_id)
                posted.append(tweet_data)
                reply_to_id = tweet_data["id"]
                if i < len(tweets) - 1:
                    await asyncio.sleep(3)
            except Exception as e:
                logger.error("Tweet %d failed: %s", i + 1, e)
                break

        logger.info("Thread posted: %d/%d tweets", len(posted), len(tweets))
        return posted

    async def post_with_image(self, text: str, image_path=None,
                               reply_to_id: Optional[str] = None) -> dict:
        """Post tweet (image upload disabled — just posts text)."""
        logger.info("Posting tweet as text (image upload skipped)")
        return await self.post_tweet(text, reply_to_id)

    async def _upload_media(self, image_path: Path) -> str:
        """Upload image to Twitter media upload endpoint."""
        upload_url = "https://upload.twitter.com/1.1/media/upload.json"
        headers = self._auth_headers("POST", upload_url)

        with open(image_path, "rb") as f:
            media_data = base64.b64encode(f.read()).decode()

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                upload_url,
                data={"media_data": media_data, "media_category": "tweet_image"},
                headers={"Authorization": headers["Authorization"]},
            )
            resp.raise_for_status()
            media_id = resp.json()["media_id_string"]
            logger.info("Media uploaded: %s", media_id)
            return media_id
