---
name: second-brain
description: "Save reels, videos and links into the Second Brain: downloads the media, transcribes speech and on-screen content with Gemini, files the full record in Supabase, and keeps a compact memory card in Hermes memory."
version: 1.0.0
author: ESJAY
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Second Brain, Memory, Video, Instagram, YouTube, Ingest]
    related_skills: []
---

# Second Brain Ingest

## When to use

Use when the user sends an Instagram reel/post link, a YouTube link, or a video file in chat and wants it **saved / remembered / filed** — phrases like "save this", "remember this", "add this to my brain", "file this away". Also use when the user asks "what did I save about X?" (search mode).

Do NOT use for casual chat about a video. If the user just wants to discuss it, discuss it — only ingest when they ask to keep it.

## How it works

`scripts/ingest.py` (Python stdlib only — no pip packages needed) does the heavy lifting:

1. Downloads the media (`yt-dlp` for links; direct file for chat uploads).
2. Sends video+audio to Gemini, which returns structured JSON: title, summary, key points, tags, full transcript, plus tools shown on screen, techniques used, and steps performed.
3. Saves the FULL record to Supabase table `public.second_brain_items` (same table the old n8n workflow used).
4. Prints a compact memory card as JSON for you to file in Hermes memory.

`SKILL_DIR` = the directory containing this SKILL.md file.

## Save flow

1. Identify the input:
   - A **URL** in the message → `--url "<url>"`
   - A **video the user sent in chat** → the turn shows `[User sent a video: /path/to/file.mp4]` → `--file "/path/to/file.mp4"`. If the message also contained the original share URL, pass it as `--source-url "<url>"` so the saved record links back to the source.
   - A **photo / carousel / screenshot** → NOT supported by the script yet. Say so honestly, save nothing, do not invent a summary.
2. Run it (needs `yt-dlp` on PATH for links — installed once via INSTALL.md — and env vars `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, which the script also reads from `/root/.hermes/.env` as a fallback):

   ```bash
   python3 "$SKILL_DIR/scripts/ingest.py" --url "<url>"
   # or
   python3 "$SKILL_DIR/scripts/ingest.py" --file "/path/to/video.mp4" --source-url "<original url, if any>"
   ```

3. Read the JSON it prints:
   - `{"ok": true, "saved": true, ...}` → new record filed. Continue to step 4.
   - `{"ok": true, "already_saved": true, "title": "..."}` → tell the user it's already in the brain (mention the title). Stop.
   - `{"ok": false, "error": "..."}` → tell the user plainly what failed (e.g. "Instagram blocked the download for this reel"). Save nothing. Do NOT invent a summary from the URL alone.
4. File the memory card: call the `memory` tool with `action: "add"`, `target: "memory"`, and content built from `memory_card` — one tight paragraph: the core idea, the tools/techniques/steps, and the single action. **Personalize "why it matters"** using what you know about the user (their goals, work, DJing, content creation) — the script's `why_it_matters` is a generic draft; rewrite it as THEIR reason in one line.
5. Reply to the user: one short confirmation — the title and the core idea in a single line. **Never paste the full transcript into chat.**

## Search flow

When the user asks what they saved about something:

```bash
python3 "$SKILL_DIR/scripts/ingest.py" --search "<keywords>"
```

Present the matches (title + one-line summary + original URL). If nothing matches, say so — do not hallucinate saved items.

## Rules

- Never claim something was saved unless the script printed `"saved": true`.
- Never put the full transcript in chat or in Hermes memory — memory gets the compact card only; the transcript lives in Supabase.
- Instagram downloads are flaky per-reel (Instagram rate-limits and blocks). A failed download is an honest failure, not a bug to work around by guessing.
- The Supabase table is shared with the old n8n ingest workflow. The `url` column is unique — re-saving the same URL returns `already_saved`, never a duplicate.
