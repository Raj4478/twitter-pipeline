"""Twitter Dev Content — Topic Bank"""

import json
import random
from pathlib import Path

TOPICS = {
    "system_design": [
        "how WhatsApp handles 100B messages per day",
        "database sharding explained simply",
        "CAP theorem in plain English",
        "how URL shortener works",
        "rate limiting strategies",
        "message queues vs event streaming",
        "SQL vs NoSQL when to use which",
        "load balancer types explained",
        "how CDN works",
        "microservices vs monolith tradeoffs",
        "consistent hashing explained",
        "how Twitter timeline works",
        "designing a notification system",
        "database indexing strategies",
        "caching strategies LRU LFU",
        "how Netflix recommendation works",
        "distributed transactions explained",
        "API gateway pattern",
        "event driven architecture",
        "how Uber surge pricing works technically",
    ],
    "webdev": [
        "NestJS dependency injection explained",
        "PostgreSQL indexing strategies",
        "REST vs GraphQL vs gRPC",
        "AWS SQS FIFO vs standard queue",
        "TypeScript utility types cheatsheet",
        "Docker basics for backend developers",
        "JWT vs session authentication",
        "Redis caching strategies",
        "TypeORM query optimization",
        "Node.js event loop explained",
        "AWS Lambda cold start problem",
        "database connection pooling",
        "HTTP vs WebSocket vs SSE",
        "SOLID principles with examples",
        "design patterns in TypeScript",
        "async await error handling patterns",
        "API rate limiting implementation",
        "environment variables best practices",
        "API versioning strategies",
        "CI/CD pipeline explained",
    ],
    "career": [
        "SDE-1 to SDE-2 promotion tips",
        "how to crack system design interview",
        "DSA topics that actually appear in interviews",
        "how to negotiate salary as SDE in India",
        "resume tips for software engineers India",
        "how to get referrals at top companies",
        "side projects that impress interviewers",
        "how to answer behavioral questions STAR method",
        "FAANG vs startups India which to choose",
        "open source contribution for career growth",
    ]
}

USED_TOPICS_FILE = Path("data/used_topics.json")


class TopicBank:
    def __init__(self):
        USED_TOPICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._used = json.loads(USED_TOPICS_FILE.read_text()) if USED_TOPICS_FILE.exists() else {}

    def pick_unused(self, niche: str) -> str:
        all_topics = TOPICS.get(niche, [])
        used = set(self._used.get(niche, []))
        unused = [t for t in all_topics if t not in used]
        if not unused:
            unused = all_topics
            self._used[niche] = []
        topic = random.choice(unused)
        self._used.setdefault(niche, []).append(topic)
        USED_TOPICS_FILE.write_text(json.dumps(self._used, indent=2))
        return topic

    def mark_used(self, niche: str, topic: str) -> None:
        self._used.setdefault(niche, [])
        if topic not in self._used[niche]:
            self._used[niche].append(topic)
        USED_TOPICS_FILE.write_text(json.dumps(self._used, indent=2))
