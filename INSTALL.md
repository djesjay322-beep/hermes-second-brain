# Installing the Second Brain skill into Hermes

All steps run **as root on the VPS** (`2.29.35.207.sslip.io`). The live Hermes
gateway runs as root (`hermes-gateway.service` under root's user systemd), and
`/root/.hermes/` is root-only — there is no way to install this without root.

## 0. Get the files onto the VPS

The skill lives in `~/workspace/second-brain/hermes-skill/` on the assistant's
machine (files: `SKILL.md`, `scripts/ingest.py`, this file). Copy the whole
directory to the VPS however you like (scp, paste, etc.), e.g. to
`/home/botadmin/second-brain-skill/`. The assistant cannot write to the VPS,
so this copy step is yours.

## 1. Install yt-dlp (one time, as root)

```bash
pip3 install -U yt-dlp
yt-dlp --version   # should print a version, not "command not found"
```

The skill needs it to download Instagram reels / YouTube videos. Without it,
`--url` ingests fail with a clear error (nothing is saved, nothing is invented).

## 2. Add secrets to /root/.hermes/.env (as root)

Do NOT paste these in chat. Edit the file directly on the VPS:

```bash
nano /root/.hermes/.env
```

Add (append if the file already has other keys — never delete existing lines):

```
GEMINI_API_KEY=<your Gemini AI Studio key — the same one the n8n workflow used>
SUPABASE_URL=https://lqoozvdlproniluqnaur.supabase.co
SUPABASE_KEY=<the Supabase API key the n8n Second Brain workflow used>
```

The script reads these from the environment first, then falls back to parsing
`/root/.hermes/.env` itself.

## 3. Install the skill (as root)

```bash
mkdir -p /root/.hermes/skills/second-brain
cp -r /home/botadmin/second-brain-skill/* /root/.hermes/skills/second-brain/
chown -R root:root /root/.hermes/skills/second-brain
chmod 700 /root/.hermes/skills/second-brain
ls /root/.hermes/skills/second-brain/
# expect: SKILL.md  scripts/
```

Hermes discovers skills by scanning for `SKILL.md` — no registration step.
The discovery cache refreshes within ~30 seconds, so **no restart is normally
needed**. If Hermes doesn't see it after a minute:

```bash
systemctl --user restart hermes-gateway.service
```

## 4. Verify (do this before deleting anything)

1. In Telegram, ask Hermes: "list your skills" — `second-brain` should appear.
2. Send Hermes a YouTube link and say "save this". Expected: a one-line
   confirmation with the title + core idea, and a new row in Supabase
   `public.second_brain_items`.
3. Send the same link again — expected: "already in your brain", no duplicate.
4. Ask: "what did I save about <topic>?" — expected: matches from the brain.
5. Direct check (as root, optional):
   ```bash
   python3 /root/.hermes/skills/second-brain/scripts/ingest.py --search "test"
   ```

## 5. Decommission the old workflow

Only after steps 1–4 pass on real inputs: delete the n8n workflow
**"Second Brain Ingest"** (`g73GPH0fI9f5Z80F`). It shares the same Supabase
table, so the saved library carries over untouched.

## Known limits (honest)

- **Instagram is flaky per-reel.** Instagram rate-limits and blocks downloads;
  some reels fail inside yt-dlp ("Requested format is not available"). The
  script reports this as an honest failure and saves nothing. The durable fix
  is Instagram login cookies for yt-dlp (needs the user's IG session).
- **19MB cap.** Telegram only hands the gateway files ≤20MB, and Gemini
  inline upload caps around the same. Longer videos need a shorter clip.
- **Photos/carousels/screenshots** are not handled by the script yet
  (video/audio + URLs only).
- **Search is keyword-based** (`ilike` on title/summary) — same as the old
  workflow. True vector/semantic search needs an embeddings column + pgvector,
  not built yet.
