# Telegram News Content Pipeline

## Project purpose

Build a content pipeline that collects structured news messages from a Telegram group or channel, filters advertisements and unrelated messages, normalizes news items, and produces two downstream formats:

- daily short-news videos with animation and Azure TTS;
- WeChat Official Account articles, using the existing publishing plugin when appropriate.

## Current phase

The production Telegram news pipeline is being consolidated and validated locally before each external run. The current focus is reliable ingestion, deterministic cleaning, conservative AI fallback, idempotent Supabase persistence, and operational recovery. The local AI morning-brief video pipeline is implemented and is now in template refinement and real-data validation; its daily automation is intentionally paused until the user approves the revised template.

Production code, Telegram connections, and real credentials are allowed only when the user explicitly requests that work. Never commit credentials or session files.

Do not resume, recreate, or manually trigger the daily AI morning-brief automation while it is paused. A template preview made with a local fixture is not a production news edition and must never be reported as one.

## Shared repository scope and non-interference rule

The GitHub repository used for deployment is `ZhongBintao/tgpdf-scraper-online`. It contains two separate pipelines. Every task must identify which pipeline it belongs to before editing files.

### Protected PDF pipeline — never change during news work

The PDF scraping pipeline is the existing root-level project. Unless the user explicitly asks for a PDF-pipeline change, do not edit, delete, rename, reformat, or otherwise alter any of these files or their behavior:

- `telegram_scraper.py`
- root `requirements.txt`
- `.github/workflows/main.yml`
- root-level PDF scripts, configuration, schedules, dependencies, secrets, and Supabase/Storage operations

Do not change the PDF workflow's trigger schedule, `telegram-user-session` concurrency behavior, environment-variable mapping, or dependency versions as part of a news-pipeline task. Do not merge news changes by modifying the PDF workflow. Before delivery, verify that protected files are unchanged on the news branch.

### Explicit exception: cross-pipeline Groq stabilization

When the user explicitly requests the approved cross-pipeline Groq
stabilization, the following narrowly scoped changes are allowed in the PDF
pipeline: update the Groq SDK pin in the root `requirements.txt`, replace the
Groq model/configuration in `telegram_scraper.py`, add strict tag-response
validation, and expose secret-free Groq error statistics. These changes must
not alter Telegram selection or pagination, PDF discovery/download, image
upload, Supabase writes or table names, scheduling, workflow triggers,
environment-variable mapping, or the `telegram-user-session` concurrency
lock. The same model and SDK policy applies to the news pipeline. No other
PDF business logic may be changed under this exception.

### Replaceable news pipeline — in scope for news work

The existing `news_pipeline/` directory and `.github/workflows/telegram-news-extract.yml` are the old Telegram news pipeline and are the intended replacement target. They may be updated when the user asks for news ingestion, cleaning, classification, normalization, deduplication, or review work.

The active news path must be:

```text
Telegram → news_pipeline/fetch_news.py → news_pipeline/process_news.py → Groq fallback → Supabase → artifacts
```

The replacement news workflow must call `python -m news_pipeline.pipeline`. The pipeline owns the ordering of fetch, clean, optional AI fallback, raw/classification/item upserts, run metadata, and checkpoint commit. `news_pipeline/extractor.py` is only a compatibility entry point and must delegate to `pipeline.py`; it must not contain a separate direct-Supabase implementation.

When changing the shared GitHub repository:

- Work on a `codex/` branch and use a pull request by default; do not write directly to `main` unless the user explicitly requests it.
- Keep news files, news tests, and the news workflow isolated from the protected PDF files.
- Use unique news artifact names and preserve the shared `telegram-user-session` concurrency lock so the two pipelines cannot use the same Telegram `StringSession` concurrently.
- The news workflow may use `TG_API_ID`, `TG_API_HASH`, `TG_STRING_SESSION`, `GROQ_API_KEY`, `SUPABASE_URL`, and server-side `SUPABASE_SERVICE_KEY`. It must run all local tests before any Telegram, Groq, or Supabase network call. The service key is never printed, committed, or exposed to clients.
- Never read, enumerate, print, upload, or commit secret values or Telegram session files. Only reference secret names in workflow configuration.

## Working principles

- Preserve raw Telegram messages and source message IDs for traceability.
- Make ingestion idempotent and keep filtering, normalization, generation, and publishing as separate stages.
- Treat advertisement filtering as a reviewable classification decision; retain confidence and reason rather than silently deleting data.
- Keep video generation and WeChat publishing independent so a failure in one output does not block the other.
- Prefer human review before public publishing until classification and generated content quality are validated.
- Never commit Telegram sessions, API keys, Azure credentials, Supabase secrets, WeChat credentials, or generated private tokens.

## Code-first AI cleaning policy

- Keep deterministic parsing and whitelist filtering as the first decision layer; call Groq only for code-detected ambiguous title/body boundaries.
- AI is an opt-in fallback. Local tests and normal CLI runs must not make network requests unless `--enable-ai` is explicitly supplied.
- The Groq classifier may return only a decision, candidate ID, confidence, and reason code. It must never generate, rewrite, summarize, or complete title/body text.
- Candidate boundaries are generated and validated locally; cleaned text must always be sliced from the immutable raw message.
- Invalid, unavailable, low-confidence, or timed-out AI results fail open to `keep_original` and become diagnostics rather than blocking the pipeline.
- The current production fallback model is `openai/gpt-oss-120b`; `GROQ_API_KEY` is server-side only and must never be printed, committed, or placed in artifacts.
- The current GitHub Actions stage may fetch Telegram data, run the code-first/Groq cleaning flow, and persist the resulting raw/classification/item/run/checkpoint projections to Supabase after the local test suite passes. Artifacts remain the audit output, and the service key is server-side only.
- In the shared repository, this policy applies specifically to `.github/workflows/telegram-news-extract.yml`; the protected PDF workflow is a separate existing system and must not be changed while implementing news work.

## Video production direction

- The target video format is a structured news/information briefing: primarily organized text, key-point cards, source images or screenshots, narration, subtitles, and controlled motion that can be generated consistently in batches.
- `ai_morning_brief/` is the active local video pipeline. It consumes the approved AIHOT source package and renders the reusable template through OpenMontage.
- The supplied reference images are the approved visual direction for the navigation and card intent: a navigation bar fixed at the top, a clear overview section, adaptive information cards, restrained editorial colors, and generous whitespace. The implementation should follow that design intent while keeping the data and copy dynamic rather than copying example content.
- The template identity is fixed as `AI每日早报` / `AI Daily News`. Use one global Chinese-capable UI font (currently Noto Sans SC with a system sans-serif fallback), complete authored subtitle phrases, dynamic navigation highlighting, and the approved fixed intro/outro copy.
- OpenMontage is the active production framework, not a future evaluation item. Keep scene planning, asset copying, narration alignment, caption timing, layout, and rendering deterministic and schema-driven.
- The Telegram pipeline remains the source of truth for raw messages, classification, normalization, deduplication, source traceability, and human review. OpenMontage should consume approved structured news packages and generate video artifacts as an independent downstream stage.
- Keep the video template deterministic and reusable; use AI only for approved editorial assistance and narration where appropriate, while keeping layout, timing constraints, source display, and rendering rules under code or explicit templates.
- Video generation must remain independent from WeChat publishing and website delivery so a failure in one output does not block the others. Keep human approval before public release during the validation phase.

### AI morning-brief production data contract

- A production run must execute `python -m ai_morning_brief.pipeline run --date YYYY-MM-DD` without `--fixture` and must retrieve AIHOT's anonymous selected 24-hour endpoint through the project adapter.
- `--fixture` and files under `ai_morning_brief/fixtures/` are for offline tests and visual template previews only. Fixture runs must be labeled as tests in reports and must not be presented as current news.
- Before reporting a production MP4, verify that `outputs/YYYY-MM-DD/artifacts/source_snapshot.json` is not sourced from `fixture://`, the factual script is grounded in the returned source items, and `quality_report.json` is `pass`.
- Select three to eight eligible items in API order. Fewer than three eligible items is a failed low-volume edition; never fill a missing edition with fabricated, stale, or remembered news.
- Keep source snapshots, source links, fact ledger, narration plan, subtitles, render report, and MP4 together under the dated output directory for auditability.
- The daily 08:00 automation is currently paused during template revision. Re-enable it only after explicit user approval and a successful real-data dry run.

## Local-first testing policy

- Use the local snapshot in `data/supabase_news/` for development, parsing, classification, normalization, deduplication, and regression tests whenever possible.
- Do not access the online Supabase database for routine testing. First make the local tests pass against the project-folder snapshot.
- Only after local tests pass may the task access the online database for final read-only verification or an explicitly requested production operation.
- Treat the local snapshot as a test fixture. Refresh it intentionally when current production data is required, and do not assume it is automatically up to date.
- For shared-repository news changes, run the news test suite before any Telegram, Groq, or Supabase network step. The target workflow must execute `python -m unittest discover -s news_pipeline/tests -v` before `pipeline.py`; a test failure must stop the job before network access.
- Supabase is the long-term source of truth for the checkpoint; artifacts are for audit and recovery visibility, not the authoritative waterline.
- Do not upload local raw snapshots, checkpoints, AI caches, `.session` files, or credentials to the repository. Runtime raw/cleaned/report/checkpoint files may be uploaded as Actions artifacts only.

## Telegram message selection and parsing policy

- For the current channel, use a conservative whitelist: only messages whose trimmed raw text starts with `🗞 今日速读` are target news messages.
- Filter out audio review messages and messages with editorial prefixes such as `您好！作为 Telegram ...`, even if a `🗞 今日速读` block appears later in the text. This policy may change if the channel format changes.
- Preserve the complete raw Telegram text, entities, payload, and message ID during ingestion. Do not silently truncate, rewrite, or discard a target message because its generated body is empty, ends with `…`, or has unstable AI formatting.
- Treat empty, truncated, or malformed generated content as a source-quality or parser warning. Keep it traceable in raw data and avoid fabricating repairs at the ingestion stage.
- When section boundaries are ambiguous or a generated title contains body text, preserve the raw message and record the parser limitation. Do not let uncertain parsing block raw-message capture.

## Supabase table architecture and load policy

The Telegram pipeline intentionally uses five separate tables for raw messages, classifications, structured news items, checkpoints, and run records. The number of tables itself is not a meaningful database burden; storage and query cost are driven mainly by row count, payload size, indexes, and query frequency.

The initial run confirmed the expected scale: 11 raw messages, 11 classifications, 6 included news items, 1 checkpoint, and 1 run record. This is negligible for the current workload. The separation must be preserved because it enables:

- reclassification from immutable raw data without re-fetching Telegram;
- idempotent upserts and checkpoint-based recovery;
- independent deduplication and editorial review states;
- operational diagnosis without mixing pipeline state with content data.

Raw messages should be retained for traceability, while derived tables may be recomputed when parser or classification rules change. The five tables remain the approved minimum architecture; do not add a manual-review table or cross-message story/merge table in this phase, and do not merge the tables merely to reduce table count. The Supabase checkpoint advances only after raw, classification, and cleaned-item writes succeed. If the dataset grows substantially, first measure table sizes and query plans, then consider retention, archiving, partitioning, or targeted index changes. Avoid adding broad indexes or duplicating large raw payloads without evidence.

The five pipeline tables must remain isolated from the existing `articles` table. Service-role credentials are for the server-side GitHub Action only; they must never be exposed to clients.

## Existing infrastructure to consider

- Telegram automation has previously been deployed with GitHub Actions.
- Supabase has previously been used for persistence.
- Telegram login credentials are already configured in GitHub Actions.
- An existing WeChat publishing plugin can serve as the publishing integration reference.

## Expected future stages

1. Telegram incremental ingestion, deterministic cleaning, Groq fallback, and raw/derived persistence — current productionization stage.
2. News, audio-review, editorial, advertisement, unrelated, and unknown classification — conservative whitelist selection is implemented for the current channel.
3. AI morning-brief template refinement and real-data validation — active; daily automation remains paused.
4. Re-enable daily video generation after explicit approval and a passing real-data validation run.
5. Cross-message deduplication and event merging — deferred until continuous message-level runs are stable; no automatic merge is performed now.
6. Shared editorial content model for downstream outputs.
7. WeChat article generation, draft creation, review, and publishing.
