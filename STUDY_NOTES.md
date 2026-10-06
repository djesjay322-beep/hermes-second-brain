# Hermes Agent — skill study notes (2026-10-06, read-only inspection)

Target: `/usr/local/lib/hermes-agent` on the VPS (2.29.35.207.sslip.io),
Hermes Agent v0.21.1, running as root since 2026-10-02
(`hermes-gateway.service` under root's user systemd, PID found via
`pgrep -f "hermes_cli.main gateway run"`; cgroup confirms
`.../user@0.service/app.slice/hermes-gateway.service`).
Inspection done as `botadmin` via n8n SSH — code is world-readable,
`/root/.hermes/` is root-only, botadmin has no sudo.

## 1. Skill discovery & invocation (VERIFIED in code)

- Skills = directories containing `SKILL.md` (YAML frontmatter + markdown
  instructions). The agent-visible set lives in `$HERMES_HOME/skills/`
  = `/root/.hermes/skills/` (gateway runs as root).
  `agent/skill_utils.py::get_all_skills_dirs()` → `[get_skills_dir()]`
  (+ optional create_dir + `skills.external_dirs` from config).
- Discovery: `gateway/run.py` does `skills_dir.rglob("SKILL.md")`, skipping
  excluded dirs and support dirs (`references/`, `templates/`, `assets/`,
  `scripts/` are never scanned as standalone skills).
- The agent gets a `skills_list` tool (name + description only) and a
  `skill_view(name)` tool (full SKILL.md + linked files); the system prompt
  includes a skills index (`agent/prompt_builder.py`). **SKILL.md alone is
  sufficient — no registration step.** Discovery cache TTL is 30s, so a newly
  dropped skill dir is picked up without a restart (restart is a fallback).
- Frontmatter format (from `skills/media/youtube-content/SKILL.md`):
  `name, description, version, author, license, platforms: [linux, macos,
  windows], metadata.hermes.tags[], metadata.hermes.related_skills[]`.
  `skill_matches_platform` filters by platform — use `[linux]` for the VPS.
- Skills can also be auto-loaded per session (`_hmwa_auto_load_skills` in
  `gateway/run_turn.py`), but normal on-demand `skill_view` is enough.

## 2. Telegram media delivery to the agent (VERIFIED in code)

- `plugins/platforms/telegram/adapter.py::_download_observed_media`:
  incoming photo/video/voice/audio/document is downloaded (bounded by
  `_max_doc_bytes`, default **20MB**) into a server-side media cache via
  `cache_media_bytes_async`.
- `gateway/run.py::_media_placeholder_text` renders it into the agent's prompt
  literally as:
  - `[User sent a video: /path/to/cached/file.mp4]`
  - `[User sent an image: /path]` (images also get vision enrichment)
  - `[User sent audio: /path]`, `[User sent a file: /path]`
- So a skill CAN act on a chat-sent video: the local path is right there in
  the turn text. Oversized/failed downloads are annotated in the text too
  (never silent).

## 3. How skills run code & reach the network (VERIFIED in code)

- Agent tools include `terminal` (shell) and `execute_code` (Python kernel).
  The bundled `youtube-content` skill pattern is: `uv run python
  $SKILL_DIR/scripts/fetch_transcript.py "<url>"` — i.e. the agent runs the
  skill's helper script via shell. Our draft uses plain `python3` + stdlib
  (`urllib`) so no venv/pip setup is needed.
- **yt-dlp is NOT installed** on the VPS (`which yt-dlp` empty; `uv` also not
  on PATH). INSTALL.md covers `pip3 install -U yt-dlp` as root.
- Secrets: `tools/skills_tool.py::load_env()` parses `HERMES_HOME/.env`
  (`/root/.hermes/.env`). The draft script ALSO falls back to reading that
  file directly (it runs as root, the file is root-readable) in case the
  exec environment doesn't inherit the vars. **Not live-verified** which of
  the two paths actually delivers the vars — the fallback covers both.

## 4. Memory (VERIFIED in code)

- Built-in `memory` tool (`tools/memory_tool.py`): `action` ∈
  {add, remove, replace, batch}, `target` ∈ {memory, user}. The skill instructs
  the agent to `memory(action=add, target=memory, content=<compact card>)`
  after a successful ingest. The full transcript/record lives in Supabase;
  only the compact card enters Hermes memory — by skill instruction, not by
  code, which is the correct layer for this policy.
- Memory provider plugins exist (`plugins/memory/`: mem0, supermemory,
  honcho, …) but the active provider wasn't readable (root-only config);
  irrelevant to the skill — it uses the `memory` tool abstraction.

## 5. Supabase table (from local ddl.sql)

`public.second_brain_items`: `id` uuid PK, `url` text UNIQUE NOT NULL,
`platform` text CHECK IN ('youtube','instagram','other'),
`title`, `summary`, `key_points` text[], `tags` text[], `transcript` text,
`created_at` timestamptz. The draft upserts on `url` (pre-check GET, then
POST) to honor the unique constraint and report `already_saved`.

## 6. Gemini (parity with proven n8n flow)

Model `gemini-flash-lite-latest` via
`POST https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent`
(model name + "verified working 2026-10-06" from `build_ingest.py`).
Inline `inline_data` base64, `responseMimeType: application/json`, prompt
asks for transcript + visual analysis (tools/techniques/steps) + memory-card
fields. 19MB inline cap matches Telegram's 20MB handoff.

## Honest gaps (not verifiable without root / live install)

1. Skill auto-discovery of a NEW dir under `/root/.hermes/skills/` — verified
   in code (rglob + 30s cache), not live-tested. INSTALL.md step 4 covers it.
2. Whether the agent's shell inherits `/root/.hermes/.env` vars — covered by
   the script's direct-file fallback; both paths need the keys present.
3. End-to-end: Gemini key validity, Supabase key permissions, yt-dlp on a real
   reel — all need the live install + a real test (INSTALL.md step 4).
4. The `memory` tool's write gate (`_apply_write_gate`) may stage writes for
   approval depending on config — the agent handles this conversationally;
   the skill doesn't bypass it.
