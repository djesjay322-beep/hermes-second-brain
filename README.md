# hermes-second-brain

A skill for [Hermes Agent](https://github.com/nousresearch/hermes-agent) that turns it into a
Second Brain inbox: send it an Instagram reel, a YouTube link, or a video file, and it
downloads the media, transcribes speech and on-screen content with Gemini, files the full
record in Supabase, and keeps a compact memory card in Hermes memory.

## Install (run by Hermes itself, as root on the VPS)

Hermes: clone this repo into your skills directory and pick it up — no restart needed
(skills are re-scanned every ~30s):

```bash
git clone https://github.com/<user>/hermes-second-brain /root/.hermes/skills/second-brain
pip3 install -U yt-dlp   # once, for link downloads
```

Then make sure `/root/.hermes/.env` contains:

```
GEMINI_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
```

Verify: send Hermes a reel link with "save this", then ask "what did I save about X?".

## Layout

- `SKILL.md` — the skill (frontmatter + instructions Hermes reads)
- `scripts/ingest.py` — stdlib-only ingest: `--url`, `--file`, `--search`
- `INSTALL.md` — manual install steps (fallback if Hermes can't self-install)
- `STUDY_NOTES.md` — architecture findings from the live Hermes codebase
