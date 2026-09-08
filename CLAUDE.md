# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**wordtrack**: a local, offline CLI that generates `.srt` subtitle files
from video/audio using a Whisper model, with no cloud calls, accounts, or
usage limits. `SPEC.md` is the original build spec (functional/non-functional
requirements, acceptance criteria) — consult it for the "why" behind any
design decision that isn't obvious from the code. `README.md` is the
end-user-facing docs (install, usage, troubleshooting).

## Commands

```bash
# syntax-check the shell scripts
bash -n install.sh
bash -n uninstall.sh

# compile-check the CLI
python3 -m py_compile wordtrack.py

# dev loop: run against a local venv without installing
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 wordtrack.py --help                 # must be instant, no model load
python3 wordtrack.py some_video.mp4 --model tiny   # use `tiny` for fast local iteration
```

There is no automated test suite. Verify changes manually against the
acceptance criteria in `SPEC.md` §7 — in particular: `--help` must stay
instant (no heavy imports before arg parsing), missing-file and no-speech
cases must print a clean one-line error and exit non-zero (no traceback),
and grouping behavior (`--words-per-line`, `--max-gap`) must be checked
against real transcribed output, not just unit-level word lists.

## Architecture

Pipeline in `wordtrack.py`: **decode with ffmpeg → transcribe with
faster-whisper (word timestamps + VAD) → group words into cues → write
.srt**.

- **`extract_audio()`**: shells out to the system `ffmpeg` binary (not a
  Python decoding library) to convert the input to 16kHz mono wav in a
  temp dir. This is deliberate — it's what makes the tool support
  "anything system ffmpeg can decode" per spec, and matches the
  installer's explicit ffmpeg dependency check.
- **`faster_whisper.WhisperModel`** is imported lazily, inside `main()`,
  after argument parsing/validation — this is why `--help` and bad-input
  errors return instantly without loading a multi-hundred-MB model.
  Model weights download from Hugging Face on first use per model size,
  then run fully offline.
- **`vad_filter=True`** on `model.transcribe()` is what satisfies the
  "filter silence instead of hallucinating words into gaps" requirement.
  A silence-only input yields zero words, which is how the "no speech
  detected" path is triggered — not a separate energy-based check.
- **`group_words()`** is the core cue-grouping algorithm: walks the flat
  word list, closing the current cue (and starting a new one) as soon as
  it already has `words_per_line` words *or* the gap since the previous
  word's end exceeds `max_gap` — whichever comes first. Both conditions
  are checked together, not as separate passes.
- **Output format** is format-agnostic downstream of `group_words()`: the
  same `cues` list feeds any of the `write_*` functions dispatched via
  `WRITERS[args.format]` (srt/vtt/sbv/ssa/ass/lrc). Only the per-format
  timestamp precision (ms vs. centiseconds) and file structure differ —
  adding a new format means adding a timestamp formatter + writer + a
  `WRITERS`/`FORMAT_CHOICES` entry, not touching the transcription path.
  LRC only carries a start time per line (no cue end time, no hours
  component) since that's the line-timestamp lyrics format, not a
  start/end subtitle format.
- **`language=args.language`** is always passed explicitly to
  `transcribe()` (default `"en"`), so `info.language_probability` will
  read 1.0 in normal use — faster-whisper only runs real language
  auto-detection when `language=None`. This is expected, not a bug.
- **`ProgressBar`** renders a `\r`-updating bar on stderr during
  transcription, driven by `segment.end / info.duration` as segments
  stream out of the (lazy) `model.transcribe()` generator. It's gated on
  `sys.stderr.isatty()` and a known duration — piped/logged/backgrounded
  runs get none of the escape-code noise, by design, not by omission.
- Any failure inside the decode/load/transcribe path is caught in
  `main()` and printed as `wordtrack: error: ...` — no bare tracebacks
  reach the user, per spec's non-crashing-error requirement.

## install.sh / uninstall.sh

Both are POSIX-friendly Bash, safe under `curl | bash` (no assumption of
an interactive stdin — confirmation prompts read from `/dev/tty`, and
`confirm()` defaults to "no" when no tty is available rather than
hanging). Dependencies (`python3`, `ffmpeg`) are installed via Homebrew on
macOS or apt/dnf/pacman on Linux, always with an explicit y/N prompt
before anything requiring `sudo`. All Python deps install into a venv
inside `WORDTRACK_INSTALL_DIR` (default `~/.wordtrack`) — never into
system Python. `install.sh` downloads `wordtrack.py`/`requirements.txt` by
plain `curl` from `raw.githubusercontent.com` (no `git` dependency),
templated by `WORDTRACK_REPO_OWNER`/`WORDTRACK_REPO_NAME`/`WORDTRACK_REPO_BRANCH`.

## Known placeholder before publishing

`install.sh`, `uninstall.sh`, and `README.md` all contain the literal
placeholders `<GITHUB_USER>` and `<REPO_NAME>` in the install one-liner
and `git clone` example — these must be swapped for the real GitHub
owner/repo before the curl-based installer will work (see `SPEC.md` §8).
