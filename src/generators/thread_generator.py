"""
Thread Generator — creates viral Twitter/X threads about system design + webdev.

2025/2026 X Best Practices Applied:
  - Hook tweet: no number, ends with 🧵 to signal thread
  - Body tweets: numbered X/N format, 260 char max (leaves room for numbering)
  - 1-2 hashtags only — placed on LAST tweet only (keeps body clean)
  - CTA: clear follow/bookmark/RT ask on final tweet
  - No hashtag spam in body tweets — X algorithm penalises it
  - Questions in CTA drive comment engagement (algo boost)
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal
import httpx

logger = logging.getLogger(__name__)

# ── Hashtags by niche — 2 max, highly relevant ────────────────────────────────
NICHE_HASHTAGS = {
    "system_design": ["SystemDesign", "SoftwareEngineering"],
    "webdev":        ["WebDev", "BackendDev"],
    "career":        ["SoftwareEngineering", "IndianDev"],
}

# ── System prompt — updated for X 2025/2026 best practices ────────────────────
THREAD_SYSTEM_PROMPT = """
You are a viral tech educator on X (Twitter) for Indian software engineers (SDE-1 to SDE-3).
Write educational threads about system design, backend development, and career growth.

AUDIENCE: Indian developers, 22-30 years, working at startups/product companies.

STRICT CHARACTER RULES:
- Hook tweet: max 240 characters (thread label added after)
- Body tweets: max 255 characters (numbering added after)
- CTA tweet: max 260 characters (hashtags added after)
- Count characters carefully — going over 280 will truncate on X

CONTENT RULES:
- Every tweet must have ONE specific fact, number, or concrete example
- Simple English — no jargon without a quick explanation
- Indian context where natural: Zomato, Swiggy, CRED, Zepto, Razorpay, PhonePe
- Hook must be a shocking stat, bold claim, or curiosity gap
- End with a question in the CTA to drive comments (algo boost)
- No vague advice — always show HOW, not just WHAT
- 1-2 emojis per tweet max — don't overdo it
- NO hashtags in body tweets — hashtags go on last tweet only

HOOK FORMULAS THAT WORK:
- "Zomato handles X million orders/day. Here's the system behind it 🧵"
- "Most devs get [X] wrong. Here's what actually happens:"
- "I spent 3 months studying [X]. Here's the TL;DR:"
- "[Shocking number] about [topic] that will change how you code:"

CTA FORMULA:
- Recap the key lesson in 1 sentence
- Ask a specific question to drive comments
- End with follow/bookmark ask

Respond ONLY with valid JSON. No markdown.
""".strip()

SINGLE_TWEET_PROMPT = """
You are a viral tech educator on X (Twitter) for Indian software engineers.
Write ONE powerful tweet about the given topic.

Rules:
- Max 260 characters (hashtags added separately)
- Must have ONE specific fact/number
- Ends with a question OR "RT if you agree" OR "Bookmark this"
- Simple English, no jargon
- Indian tech companies as examples where natural
- 1-2 emojis max
- NO hashtags in the tweet body

Respond ONLY with JSON: {"tweet": "your tweet here"}
""".strip()

THREAD_SCHEMA = """
{
  "hook": "opening tweet — shocking fact or curiosity gap, MAX 240 chars, no hashtags",
  "tweets": [
    "tweet 2 — first point with specific detail, MAX 255 chars",
    "tweet 3 — second point with example or number, MAX 255 chars",
    "tweet 4 — third point with code snippet or comparison, MAX 255 chars",
    "tweet 5 — fourth point — the surprising insight, MAX 255 chars",
    "tweet 6 — fifth point — practical takeaway, MAX 255 chars",
    "tweet 7 — real-world example (Indian company if possible), MAX 255 chars"
  ],
  "cta": "final tweet — key lesson recap + specific question + follow/bookmark ask, MAX 260 chars",
  "image_text": "3-5 word summary for infographic card"
}
""".strip()


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class Thread:
    topic: str
    niche: str
    hook: str
    tweets: list[str]
    cta: str
    image_text: str
    all_tweets: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.all_tweets = [self.hook] + self.tweets + [self.cta]

    def format_for_posting(self) -> list[str]:
        """
        Format per X 2025/2026 best practices:
          Tweet 1 (hook):   "{hook}\n\n🧵 1/{total}"
          Tweet 2-N-1:      "{i}/{total} {tweet}"
          Tweet N (CTA):    "{cta}\n\n#{tag1} #{tag2}"

        Hashtags on last tweet only — keeps body clean, maximises reach.
        """
        formatted = []
        total = len(self.all_tweets)
        hashtags = NICHE_HASHTAGS.get(self.niche, ["SoftwareEngineering", "Tech"])
        tag_str = " ".join(f"#{t}" for t in hashtags[:2])

        for i, tweet in enumerate(self.all_tweets):
            # Truncate safety — strip to fit X limit
            tweet = tweet.strip()

            if i == 0:
                # Hook: clean text + thread signal
                text = f"{tweet[:240]}\n\n🧵 1/{total}"
            elif i == total - 1:
                # CTA: recap + hashtags (2 max)
                text = f"{tweet[:255]}\n\n{tag_str}"
            else:
                # Body: numbered
                prefix = f"{i+1}/{total} "
                max_body = 278 - len(prefix)
                text = f"{prefix}{tweet[:max_body]}"

            formatted.append(text)

        return formatted


@dataclass
class SingleTweet:
    topic: str
    niche: str
    tweet: str

    def format_for_posting(self) -> str:
        hashtags = NICHE_HASHTAGS.get(self.niche, ["Tech"])
        tag_str = " ".join(f"#{t}" for t in hashtags[:2])
        return f"{self.tweet[:255]}\n\n{tag_str}"


# ── Generator ──────────────────────────────────────────────────────────────────

class ThreadGenerator:
    def __init__(self, settings):
        self.settings = settings

    async def generate_thread(self, topic: str, niche: str) -> Thread:
        logger.info("Generating thread: %s", topic)
        prompt = (
            f"Topic: {topic}\n"
            f"Niche: {niche}\n"
            f"Create a viral educational thread with specific facts and Indian examples.\n"
            f"Schema:\n{THREAD_SCHEMA}"
        )
        raw = await self._call_llm(THREAD_SYSTEM_PROMPT, prompt)
        return self._parse_thread(raw, topic, niche)

    async def generate_single(self, topic: str, niche: str) -> SingleTweet:
        logger.info("Generating single tweet: %s", topic)
        prompt = f"Topic: {topic}\nNiche: {niche}\nWrite one viral tweet."
        raw = await self._call_llm(SINGLE_TWEET_PROMPT, prompt)
        return SingleTweet(
            topic=topic,
            niche=niche,
            tweet=raw.get("tweet", "").strip(),
        )

    async def _call_llm(self, system: str, prompt: str) -> dict:
        for caller in [self._gemini, self._groq]:
            try:
                return await caller(system, prompt)
            except Exception as e:
                logger.warning("LLM failed: %s — trying next", e)
        raise RuntimeError("All LLMs failed for thread generation")

    async def _gemini(self, system: str, prompt: str) -> dict:
        full = f"{system}\n\n{prompt}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.settings.gemini_model}:generateContent"
                f"?key={self.settings.gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": full}]}],
                    "generationConfig": {
                        "temperature": 0.85,
                        "maxOutputTokens": 1800,
                        "responseMimeType": "application/json",
                    },
                },
            )
            r.raise_for_status()
            return json.loads(
                r.json()["candidates"][0]["content"]["parts"][0]["text"]
            )

    async def _groq(self, system: str, prompt: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.settings.groq_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                json={
                    "model": self.settings.groq_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature": 0.85,
                    "max_tokens": 1800,
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            return json.loads(
                r.json()["choices"][0]["message"]["content"]
            )

    def _parse_thread(self, raw: dict, topic: str, niche: str) -> Thread:
        return Thread(
            topic=topic,
            niche=niche,
            hook=raw.get("hook", "").strip(),
            tweets=[t.strip() for t in raw.get("tweets", [])],
            cta=raw.get(
                "cta",
                "Follow for daily system design content! What's your biggest architecture challenge? 👇"
            ).strip(),
            image_text=raw.get("image_text", topic[:30]),
        )
