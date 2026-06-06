# Twitter Dev Content Pipeline 🐦

Automated Twitter/X thread pipeline for Indian software engineers.

## Content Types
- **System Design threads** — How Netflix/WhatsApp/Uber works
- **WebDev tips** — NestJS, TypeScript, PostgreSQL, AWS
- **Career advice** — Interviews, salary, growth

## Run locally
```bash
# Dry run (no actual posting)
python -m src.pipeline --niche system_design --dry-run

# Post a thread
python -m src.pipeline --niche system_design --topic "how URL shortener works"

# Single tweet
python -m src.pipeline --niche webdev --type single
```

## Schedule (auto)
- 9 AM IST → System Design thread
- 1 PM IST → WebDev thread  
- 9 PM IST → Career thread

## GitHub Secrets Required
- TWITTER_API_KEY
- TWITTER_API_SECRET
- TWITTER_ACCESS_TOKEN
- TWITTER_ACCESS_TOKEN_SECRET
- TWITTER_BEARER_TOKEN
- GROQ_API_KEY
- GEMINI_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_ALLOWED_USER_ID
