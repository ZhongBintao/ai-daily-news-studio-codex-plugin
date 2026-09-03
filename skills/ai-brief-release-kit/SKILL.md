---
name: ai-brief-release-kit
description: Prepare source-grounded AI每日早报 publication copy and assemble a private video release package that directly includes schema-5 first-result GPT Image covers. Use after video and cover generation; do not publish to platforms.
metadata:
  author: local-project
  version: "0.4.0"
---

# AI每日早报发布整合包

This skill owns publication copy and private package assembly, not narration,
TTS, video rendering, cover image generation, or platform publishing.

## Workflow

1. Read only `outputs/YYYY-MM-DD/artifacts/editorial_input.json` and use the
   cover ranking helper to choose the first and optional second story.
2. Write `release_plan.json` with source-grounded platform copy, the canonical
   `cover_story_item_id`, and frozen `input_sha256`.
3. Produce two title variants:
   - Bilibili/Douyin: one or two source-grounded clauses joined by `；`, at most
     55 Unicode characters.
   - Xiaohongshu: one concise clause about the first story, at most 20 Unicode
     characters.
   The description is exactly `AI每日早报YYYY-MM-DD`.
4. Pass `cover_story_item_id` to `ai-brief-cover-generator`. Its headline,
   subheadline, and visual brief may be newly authored but must describe the
   same frozen first story.
5. Run `scripts/release_workflow.py finalize` after the final MP4 has
   `run_report.json=status:success`, `artifacts/quality_report.json=status:pass`,
   and a cover manifest is present.
   When an existing cover and publication copy are intentionally frozen while
   a newer passing video is rendered, use the explicit
   `scripts/release_workflow.py update-video` path. It atomically replaces
   only the packaged MP4 and its file/hash records; it never rewrites covers,
   publication copy, or their frozen audit metadata.
6. For cover manifest schema 5, require
   `status=complete_unreviewed`, read each result's `generated_file`, and copy
   it directly into the package. Only a missing or empty cover file blocks this
   path. Do not decode it or inspect text, Logo accuracy, composition, pixel
   dimensions, requested ratio, or family consistency.
7. Preserve read-only compatibility with historical schema 3 and 4 manifests;
   those older schemas continue to use their original approval, family,
   `normalized_file`, and Logo-receipt rules.
8. Present publication copy, cover paths, final video, and the assembled package
   path. Never upload or publish anything.

## Hard validation

- Numeric values, percentages, model names, and ASCII brand tokens in each
  platform title must occur in its matching frozen source item.
- The first title story, Xiaohongshu title, and cover story ID must agree.
- The video success and quality gates remain mandatory. Cover schema 5 removes
  only image-content and image-format validation; it does not weaken video or
  source-copy validation.
- Do not truncate an entity, model name, number, or event to meet a title limit.
  Drop the optional second clause instead.
- The user-facing package contains only publication copy, first-result covers,
  the final MP4, and `package.json`. Prompts and audit artifacts remain outside.

Detailed fields are in
[references/release-contract.md](references/release-contract.md). The helper is
[scripts/release_workflow.py](scripts/release_workflow.py).
