#!/usr/bin/env python3
"""
Second Brain ingest script for the Hermes Agent skill.

Usage:
    python3 ingest.py --url "https://www.instagram.com/reel/XXXX/"
    python3 ingest.py --file "/path/to/video.mp4" [--source-url "https://..."]
    python3 ingest.py --search "dj pricing"

What it does:
  1. Gets the media bytes (yt-dlp download for --url, direct read for --file).
  2. Sends video+audio to Gemini (gemini-flash-lite-latest, inline base64, <=19MB).
  3. Saves the FULL record to Supabase public.second_brain_items.
  4. Prints a JSON result with a compact memory_card for the agent.

Stdlib only. Exit 0 on success (even for already_saved / honest failures —
check the "ok" field); exit 1 on unexpected crashes.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

GEMINI_MODEL = "gemini-flash-lite-latest"  # verified working 2026-10-06
MAX_INLINE_BYTES = 19 * 1024 * 1024

ANALYZE_PROMPT = """You are filing a video into a personal knowledge base. Study BOTH the audio and the visuals carefully.

1. Transcribe ALL speech (condensed but faithful — keep every substantive point).
2. Describe what is VISUALLY shown: tools/products/brands/apps on screen, techniques demonstrated, steps performed in order.

Reply ONLY as valid JSON (no markdown fences) with these keys:
{
  "title": "short descriptive title",
  "summary": "2-3 sentences capturing what this is and why it's useful",
  "key_points": ["3-6 strings: the concrete takeaways, including tools and techniques"],
  "tags": ["3-6 short lowercase tags"],
  "transcript": "full speech transcript, then a 'VISUAL NOTES:' section describing on-screen tools, products, and steps",
  "core_idea": "the single core idea in one sentence",
  "tools": ["tools, products, apps or brands shown or mentioned"],
  "techniques": ["techniques or methods demonstrated"],
  "steps": ["steps performed, in order shown"],
  "why_it_matters": "one generic sentence on why someone would care about this",
  "action": "one concrete next step a person could take with this knowledge"
}"""


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(0)


def load_env():
    """os.environ first, then /root/.hermes/.env as fallback (gateway runs as root)."""
    env = dict(os.environ)
    if not (env.get("GEMINI_API_KEY") and env.get("SUPABASE_URL") and env.get("SUPABASE_KEY")):
        hermes_home = env.get("HERMES_HOME", "/root/.hermes")
        dotenv = os.path.join(hermes_home, ".env")
        try:
            with open(dotenv, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.removeprefix("export ").partition("=")
                        env.setdefault(k.strip(), v.strip().strip("\"'"))
        except OSError:
            pass
    return env


def detect_platform(url):
    u = url.lower()
    if "instagram.com" in u:
        return "instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return "other"


def download_url(url, tmpdir):
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        fail("yt-dlp is not installed on this machine (needed to download links). "
             "Install it once: pip3 install -U yt-dlp")
    out_tmpl = os.path.join(tmpdir, "dl.%(ext)s")
    cmd = [ytdlp, "--no-playlist", "--max-filesize", "19M",
           "-f", "mp4/best/best", "-o", out_tmpl, url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        fail("Download timed out after 5 minutes.")
    files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
             if f.startswith("dl.") and os.path.getsize(os.path.join(tmpdir, f)) > 0]
    if p.returncode != 0 or not files:
        tail = (p.stderr or p.stdout or "")[-600:]
        fail(f"Could not download this link (site blocked it or format unavailable). "
             f"Details: {tail.strip() or 'no output'}")
    return files[0]


def guess_mime(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        ".mp4": "video/mp4", ".mov": "video/mp4", ".webm": "video/webm",
        ".mkv": "video/x-matroska", ".mp3": "audio/mp3", ".m4a": "audio/mp4",
        ".ogg": "audio/ogg", ".oga": "audio/ogg", ".wav": "audio/wav",
    }.get(ext, "video/mp4")


def gemini_analyze(media_bytes, mime, api_key):
    b64 = base64.b64encode(media_bytes).decode()
    body = {
        "contents": [{"parts": [
            {"text": ANALYZE_PROMPT},
            {"inline_data": {"mime_type": mime, "data": b64}},
        ]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.loads(r.read().decode())
    except Exception as e:
        fail(f"Gemini request failed: {e}")
    try:
        text = resp["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        fail(f"Gemini returned an unexpected response: {str(resp)[:400]}")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fail(f"Gemini did not return valid JSON: {text[:400]}")


def supabase_req(env, method, path, query="", payload=None):
    url = env["SUPABASE_URL"].rstrip("/") + "/rest/v1" + path + query
    headers = {
        "apikey": env["SUPABASE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_KEY']}",
        "Content-Type": "application/json",
    }
    if method == "POST":
        headers["Prefer"] = "return=representation"
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else []
    except urllib.error.HTTPError as e:
        fail(f"Supabase {method} failed ({e.code}): {e.read().decode()[:400]}")
    except Exception as e:
        fail(f"Supabase request failed: {e}")


def cmd_save(args, env):
    for k in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
        if not env.get(k):
            fail(f"Missing {k}. Add it to /root/.hermes/.env (see INSTALL.md).")

    tmpdir = tempfile.mkdtemp(prefix="sb-ingest-")
    try:
        if args.url:
            stored_url = args.url.strip()
            platform = detect_platform(stored_url)
            media_path = download_url(stored_url, tmpdir)
        else:
            media_path = args.file
            if not os.path.isfile(media_path):
                fail(f"File not found: {media_path}")
            stored_url = args.source_url or ("tgfile:sha1:" + hashlib.sha1(
                open(media_path, "rb").read()).hexdigest()[:16])
            platform = detect_platform(args.source_url) if args.source_url else "other"

        size = os.path.getsize(media_path)
        if size > MAX_INLINE_BYTES:
            fail(f"File is {size/1048576:.1f}MB — over the 19MB inline limit. "
                 "Ask the user for a shorter clip.")

        with open(media_path, "rb") as f:
            media_bytes = f.read()
        mime = guess_mime(media_path)

        # Dedupe on the unique url column before spending a Gemini call.
        q = "?url=eq." + urllib.parse.quote(stored_url, safe="") + "&select=id,title"
        existing = supabase_req(env, "GET", "/second_brain_items", q)
        if existing:
            print(json.dumps({
                "ok": True, "saved": False, "already_saved": True,
                "id": existing[0]["id"], "title": existing[0]["title"],
                "url": stored_url,
            }, ensure_ascii=False))
            return

        g = gemini_analyze(media_bytes, mime, env["GEMINI_API_KEY"])

        row = {
            "url": stored_url,
            "platform": platform,
            "title": str(g.get("title") or "Untitled")[:300],
            "summary": str(g.get("summary") or ""),
            "key_points": [str(x) for x in (g.get("key_points") or [])][:10],
            "tags": [str(x) for x in (g.get("tags") or [])][:10],
            "transcript": str(g.get("transcript") or ""),
        }
        saved = supabase_req(env, "POST", "/second_brain_items", payload=row)
        rec_id = saved[0]["id"] if saved else None

        memory_card = {
            "core_idea": str(g.get("core_idea") or row["summary"]),
            "tools": [str(x) for x in (g.get("tools") or [])],
            "techniques": [str(x) for x in (g.get("techniques") or [])],
            "steps": [str(x) for x in (g.get("steps") or [])],
            "why_it_matters": str(g.get("why_it_matters") or ""),
            "action": str(g.get("action") or ""),
        }
        print(json.dumps({
            "ok": True, "saved": True, "already_saved": False,
            "id": rec_id, "platform": platform, "url": stored_url,
            "title": row["title"], "memory_card": memory_card,
        }, ensure_ascii=False))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def cmd_search(args, env):
    for k in ("SUPABASE_URL", "SUPABASE_KEY"):
        if not env.get(k):
            fail(f"Missing {k}. Add it to /root/.hermes/.env (see INSTALL.md).")
    q = urllib.parse.quote(args.search, safe="")
    query = (f"?select=id,title,summary,url,platform,created_at"
             f"&or=(title.ilike.*{q}*,summary.ilike.*{q}*)"
             f"&order=created_at.desc&limit=10")
    rows = supabase_req(env, "GET", "/second_brain_items", query)
    print(json.dumps({"ok": True, "count": len(rows), "items": rows}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Second Brain ingest for Hermes")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="Reel/YouTube/video URL to download and file")
    g.add_argument("--file", help="Local video/audio file path (e.g. from a Telegram message)")
    g.add_argument("--search", help="Search saved items by keyword")
    ap.add_argument("--source-url", help="Original share URL when --file came from chat")
    args = ap.parse_args()
    env = load_env()
    if args.search:
        cmd_search(args, env)
    else:
        cmd_save(args, env)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # never die with a traceback the agent can't use
        fail(f"Unexpected error: {e}")
