# Telegram News Content Pipeline

## Project purpose

Build a content pipeline that collects structured news messages from a Telegram group or channel, filters advertisements and unrelated messages, normalizes news items, and produces two downstream formats:

- daily short-news videos with animation and Azure TTS;
- WeChat Official Account articles, using the existing publishing plugin when appropriate.

## Current phase

The project is currently in the architecture and requirements discussion phase. Do not implement production code, connect to Telegram, publish content, or use real credentials unless the user explicitly requests that work.

## Working principles

- Preserve raw Telegram messages and source message IDs for traceability.
- Make ingestion idempotent and keep filtering, normalization, generation, and publishing as separate stages.
- Treat advertisement filtering as a reviewable classification decision; retain confidence and reason rather than silently deleting data.
- Keep video generation and WeChat publishing independent so a failure in one output does not block the other.
- Prefer human review before public publishing until classification and generated content quality are validated.
- Never commit Telegram sessions, API keys, Azure credentials, Supabase secrets, WeChat credentials, or generated private tokens.

## Existing infrastructure to consider

- Telegram automation has previously been deployed with GitHub Actions.
- Supabase has previously been used for persistence.
- Telegram login credentials are already configured in GitHub Actions.
- An existing WeChat publishing plugin can serve as the publishing integration reference.

## Expected future stages

1. Telegram incremental ingestion and raw-message storage.
2. News, advertisement, duplicate, and unrelated-message classification.
3. Structured news records, deduplication, event merging, and review workflow.
4. Shared editorial content model for downstream outputs.
5. Daily video generation and quality checks.
6. WeChat article generation, draft creation, review, and publishing.

