#!/usr/bin/env python3
"""Fetch YouTube subtitles into timestamped markdown chunks, then merge translated chunks.

Usage:
  yt_subs.py fetch <url> [--out DIR] [--chunk-chars N] [--track KEY] [--transcribe]
                         [--whisper-model NAME] [--cookies-from-browser BROWSER]
  yt_subs.py merge <workdir>

`fetch` writes <workdir>/meta.json, <workdir>/source/NN.md and creates <workdir>/translated/.
`merge` checks every translated chunk keeps every timestamp of its source chunk, then writes
<workdir>/<title>.zh-TW.md. Any missing chunk or timestamp aborts with a non-zero exit.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PARA_MIN_MS = 20_000   # a paragraph may close after this long at a sentence end or pause
PARA_MAX_MS = 45_000   # a paragraph always closes after this long
PAUSE_MS = 2_000       # silence between cues counted as a pause
MIN_CJK_RATIO = 0.5    # merge rejects a translated chunk below this share of CJK characters
TS_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\(https://youtu\.be/[^)]+\)", re.M)
SENTENCE_END = tuple(".?!。？！…\"”'")
TRAD_ZH = ("zh-Hant", "zh-TW", "zh-HK")
SIMP_ZH = ("zh-Hans", "zh-CN", "zh-SG", "zh")
WHISPER_MODEL = "large-v3-turbo"
WHISPER_MODEL_DIR = Path.home() / ".cache" / "whisper-cpp"
KIND_LABEL = {"manual": "人工字幕", "auto": "自動產生字幕", "transcribed": "語音轉錄"}


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def yt_dlp(args, cookies):
    cmd = ["yt-dlp", "--no-update", "--no-warnings", *args]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"yt-dlp failed:\n{r.stderr.strip()}")
    return r.stdout


def base_lang(key):
    """'en-eEY6OEpapPo' -> 'en', 'zh-Hant' -> 'zh-Hant', 'en-orig' -> 'en'."""
    key = key.removesuffix("-orig")
    if key.startswith("zh-"):
        return key.split("-")[0] + "-" + key.split("-")[1]
    return key.split("-")[0]


def pick_track(info):
    """Return (lang_key, kind, mode). kind: manual|auto. mode: copy|to-trad|translate."""
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}
    orig = info.get("language") or ""

    def find(tracks, langs):
        for lang in langs:
            for k in tracks:
                if base_lang(k) == lang:
                    return k
        return None

    if k := find(manual, TRAD_ZH):
        return k, "manual", "copy"
    if k := find(manual, SIMP_ZH):
        return k, "manual", "to-trad"
    if orig and (k := find(manual, [orig.split("-")[0]])):
        return k, "manual", "translate"
    # Videos with AI-dubbed audio carry one *-orig track per dub language; only the one
    # matching the video's own language is the real transcript.
    orig_auto = [k for k in auto if k.endswith("-orig")]
    if orig and (same := [k for k in orig_auto if k.split("-")[0] == orig.split("-")[0]]):
        orig_auto = same[:1]
    elif len(orig_auto) > 1:
        print(f"WARNING: video language unknown, guessing {orig_auto[0]!r} among {orig_auto}; "
              "override with --track", file=sys.stderr)
    if orig_auto:
        k = orig_auto[0]
        lang = base_lang(k)
        mode = "copy" if lang in TRAD_ZH else "to-trad" if lang in SIMP_ZH else "translate"
        return k, "auto", mode
    if k := find(manual, ["en"]):
        return k, "manual", "translate"
    if manual:
        return next(iter(manual)), "manual", "translate"
    return None


def whisper_model_path(name):
    """Return the ggml model file for `name`, downloading it into WHISPER_MODEL_DIR on first use."""
    if "/" in name or name.endswith(".bin"):
        path = Path(name).expanduser()
        if not path.exists():
            die(f"whisper model not found: {path}")
        return path
    path = WHISPER_MODEL_DIR / f"ggml-{name}.bin"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
        print(f"Downloading whisper model {name} -> {path} (one-time, may take minutes)", file=sys.stderr)
        tmp = path.with_suffix(".part")
        r = subprocess.run(["curl", "-fsSL", "-o", str(tmp), url])
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            die(f"failed to download whisper model from {url}")
        tmp.rename(path)
    return path


def transcribe(info, work, model, cookies):
    """Download the original-language audio and run whisper.cpp on it.

    Returns (cues, lang) where cues match parse_json3's [(start_ms, end_ms, text)].
    """
    if not shutil.which("whisper-cli"):
        die("no subtitles on this video, and whisper-cli is missing for the audio fallback.\n"
            "Install it with: brew install whisper-cpp")
    model_path = whisper_model_path(model)
    lang = (info.get("language") or "").split("-")[0]
    # Dubbed videos carry several audio tracks; take the one in the video's own language.
    fmt = f"ba[language^={lang}]/ba" if lang else "ba"
    args = ["-f", fmt, "-x", "--audio-format", "wav",
            "--postprocessor-args", "ExtractAudio:-ar 16000 -ac 1",
            "-o", str(work / "audio.%(ext)s"), f"https://www.youtube.com/watch?v={info['id']}"]
    yt_dlp(args, cookies)
    audio = work / "audio.wav"
    if not audio.exists():
        die(f"audio not downloaded: {audio}")

    out = work / "raw.whisper"
    print(f"Transcribing with whisper.cpp ({model_path.name}), this can take a while...", file=sys.stderr)
    r = subprocess.run(["whisper-cli", "-m", str(model_path), "-f", str(audio), "-l", lang or "auto",
                        "-oj", "-of", str(out), "-np"], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"whisper-cli failed:\n{r.stderr.strip()[-2000:]}")
    result = json.loads((work / "raw.whisper.json").read_text(encoding="utf-8", errors="replace"))
    cues = []
    for seg in result.get("transcription", []):
        text = re.sub(r"\s+", " ", seg.get("text", "")).strip()
        if text:
            cues.append((seg["offsets"]["from"], seg["offsets"]["to"], text))
    audio.unlink()
    return cues, lang or result.get("result", {}).get("language", "")


def parse_json3(path):
    """Return [(start_ms, end_ms, text)] with newline-only append events dropped."""
    cues = []
    for ev in json.loads(Path(path).read_text(encoding="utf-8")).get("events", []):
        if "segs" not in ev or ev.get("aAppend"):
            continue
        text = "".join(s.get("utf8", "") for s in ev["segs"])
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            t = ev.get("tStartMs", 0)
            cues.append((t, t + ev.get("dDurationMs", 0), text))
    return cues


def join_text(parts):
    out = ""
    for p in parts:
        cjk_edge = out and (ord(out[-1]) > 0x2E80 or ord(p[0]) > 0x2E80)
        out += p if (not out or cjk_edge) else " " + p
    return out


def paragraphs(cues):
    paras, cur, start, last = [], [], 0, 0
    for t, end, text in cues:
        if cur:
            span = t - start
            at_break = cur[-1].endswith(SENTENCE_END) or t - last >= PAUSE_MS
            if span >= PARA_MAX_MS or (span >= PARA_MIN_MS and at_break):
                paras.append((start, join_text(cur)))
                cur = []
        if not cur:
            start = t
        cur.append(text)
        last = end
    if cur:
        paras.append((start, join_text(cur)))
    return paras


def hms(ms):
    s = ms // 1000
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def ts_line(video_id, ms):
    return f"[{hms(ms)}](https://youtu.be/{video_id}?t={ms // 1000})"


def safe_name(title):
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", title).strip()
    return re.sub(r"\s+", " ", name)[:80] or "subtitles"


def cmd_fetch(a):
    info = json.loads(yt_dlp(["-J", "--skip-download", "--no-playlist", a.url], a.cookies_from_browser))
    vid = info["id"]
    picked = None if a.transcribe else pick_track(info)
    if a.track:
        auto = info.get("automatic_captions") or {}
        if a.track not in auto and a.track not in (info.get("subtitles") or {}):
            die(f"track {a.track!r} not available")
        kind = "manual" if a.track in (info.get("subtitles") or {}) else "auto"
        lang = base_lang(a.track)
        picked = a.track, kind, "copy" if lang in TRAD_ZH else "to-trad" if lang in SIMP_ZH else "translate"
    work = Path(a.out or f"yt-{vid}").resolve()
    (work / "source").mkdir(parents=True, exist_ok=True)
    (work / "translated").mkdir(exist_ok=True)

    if picked:
        key, kind, mode = picked
        flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
        yt_dlp(["--skip-download", flag, "--sub-langs", key, "--sub-format", "json3",
                "-o", str(work / "raw.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"],
               a.cookies_from_browser)
        raw = work / f"raw.{key}.json3"
        if not raw.exists():
            die(f"subtitle file not downloaded: {raw}")
        cues = parse_json3(raw)
    else:
        if not a.transcribe:
            print("No subtitles or auto captions; falling back to whisper.cpp transcription.", file=sys.stderr)
        cues, lang = transcribe(info, work, a.whisper_model, a.cookies_from_browser)
        # Whisper writes Chinese as Simplified or a mix, so never copy it as-is.
        key, kind = f"whisper:{Path(a.whisper_model).name.removeprefix('ggml-').removesuffix('.bin')}", "transcribed"
        mode = "to-trad" if lang == "zh" else "translate"

    paras = paragraphs(cues)
    if not paras:
        die("subtitle track is empty")

    chunks, cur, size = [], [], 0
    for p in paras:
        if cur and size + len(p[1]) > a.chunk_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += len(p[1])
    chunks.append(cur)

    for old in (work / "source").glob("*.md"):
        old.unlink()
    for i, chunk in enumerate(chunks, 1):
        body = "\n\n".join(f"{ts_line(vid, ms)}\n{text}" for ms, text in chunk)
        (work / "source" / f"{i:02d}.md").write_text(body + "\n", encoding="utf-8")
        if mode == "copy":
            (work / "translated" / f"{i:02d}.md").write_text(body + "\n", encoding="utf-8")

    meta = {
        "id": vid, "title": info.get("title", ""), "channel": info.get("channel") or info.get("uploader", ""),
        "url": f"https://www.youtube.com/watch?v={vid}", "duration": info.get("duration") or 0,
        "upload_date": info.get("upload_date", ""), "track": key, "kind": kind, "mode": mode,
        "chunks": len(chunks), "paragraphs": len(paras),
    }
    (work / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"workdir": str(work), **meta}, ensure_ascii=False, indent=2))
    print(f"\nNext: translate each source/NN.md into translated/NN.md (mode={mode}), "
          f"then run: merge {work}")


def cmd_merge(a):
    work = Path(a.workdir).resolve()
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    sources = sorted((work / "source").glob("*.md"))
    problems, bodies = [], []
    for src in sources:
        dst = work / "translated" / src.name
        if not dst.exists():
            problems.append(f"{src.name}: translated file missing")
            continue
        want = TS_RE.findall(src.read_text(encoding="utf-8"))
        text = dst.read_text(encoding="utf-8").strip()
        got = TS_RE.findall(text)
        missing = sorted(set(want) - set(got))
        extra = sorted(set(got) - set(want))
        if missing:
            problems.append(f"{src.name}: {len(missing)} timestamp(s) missing: {', '.join(missing)}")
        if extra:
            problems.append(f"{src.name}: unexpected timestamp(s): {', '.join(extra)}")
        if not missing and not extra and want != got:
            problems.append(f"{src.name}: timestamps out of order or duplicated")
        paras = TS_RE.split(text)[2::2]
        empty = [ts for ts, body in zip(got, paras) if not body.strip()]
        if empty:
            problems.append(f"{src.name}: empty paragraph after: {', '.join(empty)}")
        if meta["mode"] != "copy":
            chars = re.sub(r"\s|\[\d{2}:\d{2}:\d{2}\]\([^)]*\)", "", text)
            ratio = sum(0x4E00 <= ord(c) <= 0x9FFF for c in chars) / max(len(chars), 1)
            if ratio < MIN_CJK_RATIO:
                problems.append(f"{src.name}: only {ratio:.0%} Chinese characters — not translated?")
        bodies.append(text)
    if problems:
        print("MERGE FAILED — fix these and rerun merge:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    kind = KIND_LABEL[meta["kind"]]
    d = meta["upload_date"]
    header = [
        f"# {meta['title']}", "",
        f"- 頻道：{meta['channel']}",
        f"- 網址：{meta['url']}",
        f"- 長度：{hms(meta['duration'] * 1000)}",
        *( [f"- 上傳日期：{d[:4]}-{d[4:6]}-{d[6:]}"] if len(d) == 8 else [] ),
        f"- 字幕來源：{meta['track']}（{kind}）",
        "", "---", "", "",
    ]
    out = work / f"{safe_name(meta['title'])}.zh-TW.md"
    out.write_text("\n".join(header) + "\n\n".join(bodies) + "\n", encoding="utf-8")
    print(f"OK: {len(sources)} chunk(s), {meta['paragraphs']} paragraph(s), 0 missing -> {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("url")
    f.add_argument("--out", help="work directory (default: ./yt-<video id>)")
    f.add_argument("--chunk-chars", type=int, default=8000, help="max source characters per chunk")
    f.add_argument("--track", help="force a subtitle track key, e.g. en-orig (see yt-dlp --list-subs)")
    f.add_argument("--transcribe", action="store_true",
                   help="ignore subtitles and transcribe the audio with whisper.cpp (automatic when none exist)")
    f.add_argument("--whisper-model", default=WHISPER_MODEL,
                   help=f"whisper.cpp model name or .bin path (default: {WHISPER_MODEL}, "
                        f"downloaded to {WHISPER_MODEL_DIR})")
    f.add_argument("--cookies-from-browser", help="e.g. chrome, when YouTube asks for sign-in")
    m = sub.add_parser("merge")
    m.add_argument("workdir")
    a = ap.parse_args()
    cmd_fetch(a) if a.cmd == "fetch" else cmd_merge(a)


if __name__ == "__main__":
    main()
