"""
Thread Generator — creates viral Twitter/X threads about system design + webdev.
Supports two formats:
  - thread: 6-8 tweet educational thread
  - single: one powerful tweet with key insight
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal
import httpx

logger = logging.getLogger(__name__)

THREAD_SYSTEM_PROMPT = """
You are a viral tech Twitter/X educator for Indian software engineers (SDE-1 to SDE-3).
Write educational threads about system design, backend development, and career growth.

AUDIENCE: Indian developers, 22-30 years, working at startups/product companies.

STRICT RULES:
- Every tweet must have a SPECIFIC fact, number, or code example
- Use simple English — no jargon without explanation
- Relatable Indian context where possible (mention Zomato, Swiggy, CRED, Zepto, Meesho as examples)
- Each tweet max 270 characters (leave room for thread numbering)
- Hook tweet must be shocking/curiosity-driven — makes them click "Show more"
- End with a CTA tweet asking for follows/RTs
- No vague advice — always show HOW, not just WHAT
- Include emojis sparingly but effectively

TWEET FORMATS THAT WORK:
- "X does Y million requests. Here's how: 🧵"
- "Most devs get [X] wrong. Here's the truth:"
- "I spent 3 months learning [X]. TL;DR:"
- "This [X] interview question stumps 80% of candidates:"

Respond ONLY with valid JSON. No markdown.
""".strip()

SINGLE_TWEET_PROMPT = """
You are a viral tech Twitter/X educator for Indian software engineers.
Write ONE powerful tweet about the given topic.

Rules:
- Max 270 characters
- Must have ONE specific fact/number
- Ends with a question OR "RT if you agree" OR "Bookmark this"
- Simple English, no jargon
- Can use Indian tech companies as examples
- 1-2 emojis max

Respond ONLY with JSON: {"tweet": "your tweet here", "hashtags": ["tag1", "tag2"]}
""".strip()

THREAD_SCHEMA = """
{
  "hook": "opening tweet — shocking fact or question, max 270 chars",
  "tweets": [
    "tweet 2 — first point with specific detail, max 270 chars",
    "tweet 3 — second point with example/number, max 270 chars",
    "tweet 4 — third point with code snippet or comparison, max 270 chars",
    "tweet 5 — fourth point — the surprising insight, max 270 chars",
    "tweet 6 — fifth point — practical takeaway, max 270 chars",
    "tweet 7 — summary + key lesson, max 270 chars"
  ],
  "cta": "final tweet — follow for more + RT ask, max 270 chars",
  "hashtags": ["SystemDesign", "WebDev", "SoftwareEngineering"],
  "image_text": "3-5 word summary for infographic card"
}
""".strip()


@dataclass
class Thread:
    topic: str
    niche: str
    hook: str
    tweets: list[str]
    cta: str
    hashtags: list[str]
    image_text: str
    all_tweets: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.all_tweets = [self.hook] + self.tweets + [self.cta]

    def format_for_posting(self) -> list[str]:
        """Format tweets with numbering for thread."""
        formatted = []
        total = len(self.all_tweets)
        for i, tweet in enumerate(self.all_tweets):
            if i == 0:
                # Hook — no number
                formatted.append(f"{tweet}\n\n🧵 {i+1}/{total}")
            elif i == total - 1:
                # CTA — no number
                formatted.append(tweet)
            else:
                formatted.append(f"{i+1}/{total} {tweet}")
        return formatted


@dataclass
class SingleTweet:
    topic: str
    niche: str
    tweet: str
    hashtags: list[str]

    def format_for_posting(self) -> str:
        tags = " ".join(f"#{t}" for t in self.hashtags[:3])
        return f"{self.tweet}\n\n{tags}"


class ThreadGenerator:
    def __init__(self, settings):
        self.settings = settings

    async def generate_thread(self, topic: str, niche: str) -> Thread:
        """Generate a full Twitter thread."""
        logger.info("Generating thread: %s", topic)
        prompt = (
            f"Topic: {topic}\n"
            f"Niche: {niche}\n"
            f"Create an educational thread with specific facts and Indian examples.\n"
            f"Schema:\n{THREAD_SCHEMA}"
        )
        raw = await self._call_llm(THREAD_SYSTEM_PROMPT, prompt)
        return self._parse_thread(raw, topic, niche)

    async def generate_single(self, topic: str, niche: str) -> SingleTweet:
        """Generate a single power tweet."""
        logger.info("Generating single tweet: %s", topic)
        prompt = f"Topic: {topic}\nNiche: {niche}\nWrite one viral tweet."
        raw = await self._call_llm(SINGLE_TWEET_PROMPT, prompt)
        return SingleTweet(
            topic=topic,
            niche=niche,
            tweet=raw.get("tweet", "").strip(),
            hashtags=raw.get("hashtags", ["WebDev", "SystemDesign"]),
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
                json={"contents": [{"parts": [{"text": full}]}],
                      "generationConfig": {"temperature": 0.8,
                                           "maxOutputTokens": 1500,
                                           "responseMimeType": "application/json"}},
            )
            r.raise_for_status()
            return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])

    async def _groq(self, system: str, prompt: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.settings.groq_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                json={"model": self.settings.groq_model,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": prompt}],
                      "temperature": 0.8, "max_tokens": 1500,
                      "response_format": {"type": "json_object"}},
            )
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])

    def _parse_thread(self, raw: dict, topic: str, niche: str) -> Thread:
        return Thread(
            topic=topic,
            niche=niche,
            hook=raw.get("hook", "").strip(),
            tweets=[t.strip() for t in raw.get("tweets", [])],
            cta=raw.get("cta", "Follow for daily dev tips! RT if useful 🙏").strip(),
            hashtags=raw.get("hashtags", ["SystemDesign", "WebDev"]),
            image_text=raw.get("image_text", topic[:30]),
        )
