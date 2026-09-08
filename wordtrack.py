#!/usr/bin/env python3
"""wordtrack: local, offline subtitle generator built on Whisper."""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

MODEL_CHOICES = ["tiny", "base", "small", "medium", "large-v3"]
FORMAT_CHOICES = ["srt", "vtt", "sbv", "ssa", "ass", "lrc"]
LRC_DEFAULT_TAIL_SECONDS = 2.0

ParsedWord = namedtuple("ParsedWord", ["start", "end", "word"])


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"


def color_enabled(stream):
    return (
        hasattr(stream, "isatty")
        and stream.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM") != "dumb"
    )


def style(text, *codes, stream=sys.stderr):
    if not codes or not color_enabled(stream):
        return text
    return "".join(codes) + text + Colors.RESET


def build_parser():
    parser = argparse.ArgumentParser(
        prog="wordtrack",
        description="Generate a subtitle file from a video or audio file, "
        "using a Whisper speech-to-text model that runs entirely on this machine.",
        epilog="To convert an existing caption file to another format without "
        "re-running speech recognition, use: wordtrack convert <input-file> --format <format>",
    )
    parser.add_argument(
        "input", metavar="<input-file>", help="Path to the video or audio file to caption"
    )
    parser.add_argument(
        "--model",
        choices=MODEL_CHOICES,
        default="small",
        help="Whisper model size: trade-off between speed and accuracy (default: small)",
    )
    parser.add_argument(
        "--words-per-line",
        type=int,
        default=1,
        metavar="N",
        help="Max words per caption cue (default: 1)",
    )
    parser.add_argument(
        "--max-gap",
        type=float,
        default=0.6,
        metavar="SECONDS",
        help="Max silence gap inside one cue before it splits (default: 0.6)",
    )
    parser.add_argument(
        "--format",
        choices=FORMAT_CHOICES,
        default="srt",
        help="Subtitle output format (default: srt)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        metavar="PATH",
        help="Output subtitle path (default: <input file>.<format>)",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="en",
        help="Spoken language code passed to the model (default: en)",
    )
    return parser


def build_convert_parser():
    parser = argparse.ArgumentParser(
        prog="wordtrack convert",
        description="Convert an existing caption file to another subtitle format, "
        "without re-running speech recognition.",
    )
    parser.add_argument(
        "input", metavar="<input-file>", help="Path to the existing caption file to convert"
    )
    parser.add_argument(
        "--format",
        choices=FORMAT_CHOICES,
        required=True,
        help="Target subtitle format",
    )
    parser.add_argument(
        "--from-format",
        choices=FORMAT_CHOICES,
        default=None,
        help="Source format, if it can't be inferred from the input file's extension",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        metavar="PATH",
        help="Output path (default: <input file>.<format>)",
    )
    return parser


def format_srt_timestamp(seconds):
    total_ms = round(seconds * 1000)
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, ms = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_vtt_timestamp(seconds):
    total_ms = round(seconds * 1000)
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, ms = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def format_sbv_timestamp(seconds):
    total_ms = round(seconds * 1000)
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, ms = divmod(total_ms, 1000)
    return f"{hours}:{minutes:02d}:{secs:02d}.{ms:03d}"


def format_ass_timestamp(seconds):
    total_cs = round(seconds * 100)
    hours, total_cs = divmod(total_cs, 360_000)
    minutes, total_cs = divmod(total_cs, 6_000)
    secs, cs = divmod(total_cs, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def format_lrc_timestamp(seconds):
    total_cs = round(seconds * 100)
    minutes, total_cs = divmod(total_cs, 6_000)
    secs, cs = divmod(total_cs, 100)
    return f"{minutes:02d}:{secs:02d}.{cs:02d}"


def group_words(words, words_per_line, max_gap):
    """Group a flat list of timestamped words into caption cues.

    A cue closes (and a new one starts) when it already holds
    words_per_line words, or when the gap since the previous word
    exceeds max_gap - whichever happens first.
    """
    cues = []
    current = []
    for word in words:
        if current:
            gap = word.start - current[-1].end
            if len(current) >= words_per_line or gap > max_gap:
                cues.append(current)
                current = []
        current.append(word)
    if current:
        cues.append(current)
    return cues


def cue_text(cue):
    return "".join(word.word for word in cue).strip()


def write_srt(cues, out_path):
    entries = []
    for index, cue in enumerate(cues, start=1):
        start = format_srt_timestamp(cue[0].start)
        end = format_srt_timestamp(cue[-1].end)
        entries.append(f"{index}\n{start} --> {end}\n{cue_text(cue)}\n")
    out_path.write_text("\n".join(entries), encoding="utf-8")


def write_vtt(cues, out_path):
    entries = ["WEBVTT\n"]
    for index, cue in enumerate(cues, start=1):
        start = format_vtt_timestamp(cue[0].start)
        end = format_vtt_timestamp(cue[-1].end)
        entries.append(f"{index}\n{start} --> {end}\n{cue_text(cue)}\n")
    out_path.write_text("\n".join(entries), encoding="utf-8")


def write_sbv(cues, out_path):
    entries = []
    for cue in cues:
        start = format_sbv_timestamp(cue[0].start)
        end = format_sbv_timestamp(cue[-1].end)
        entries.append(f"{start},{end}\n{cue_text(cue)}\n")
    out_path.write_text("\n".join(entries), encoding="utf-8")


SSA_HEADER = """[Script Info]
Title: wordtrack captions
ScriptType: v4.00

[V4 Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding
Style: Default,Arial,20,16777215,65535,0,0,0,0,1,2,2,2,10,10,10,0,1

[Events]
Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ssa(cues, out_path):
    lines = [SSA_HEADER]
    for cue in cues:
        start = format_ass_timestamp(cue[0].start)
        end = format_ass_timestamp(cue[-1].end)
        lines.append(f"Dialogue: Marked=0,{start},{end},Default,,0000,0000,0000,,{cue_text(cue)}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


ASS_HEADER = """[Script Info]
Title: wordtrack captions
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(cues, out_path):
    lines = [ASS_HEADER]
    for cue in cues:
        start = format_ass_timestamp(cue[0].start)
        end = format_ass_timestamp(cue[-1].end)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0000,0000,0000,,{cue_text(cue)}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_lrc(cues, out_path):
    entries = []
    for cue in cues:
        start = format_lrc_timestamp(cue[0].start)
        entries.append(f"[{start}]{cue_text(cue)}")
    out_path.write_text("\n".join(entries) + "\n", encoding="utf-8")


WRITERS = {
    "srt": write_srt,
    "vtt": write_vtt,
    "sbv": write_sbv,
    "ssa": write_ssa,
    "ass": write_ass,
    "lrc": write_lrc,
}


TIMESTAMP_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d+)$")


def parse_timestamp(text):
    """Parse a "[H:]MM:SS[.,]frac" timestamp, as used by every supported format."""
    match = TIMESTAMP_RE.match(text.strip())
    if not match:
        raise ValueError(f"unrecognized timestamp: {text!r}")
    hours_str, minutes_str, secs_str, frac_str = match.groups()
    hours = int(hours_str) if hours_str else 0
    minutes = int(minutes_str)
    secs = int(secs_str)
    frac = int(frac_str) / (10 ** len(frac_str))
    return hours * 3600 + minutes * 60 + secs + frac


def parse_srt(content):
    """Shared reader for SRT and VTT: index/header lines are ignored, only
    blocks containing a "-->" timing line are treated as cues."""
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", content.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        timing_idx = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_idx is None:
            continue
        start_str, _, end_str = lines[timing_idx].partition("-->")
        try:
            start = parse_timestamp(start_str.strip())
            end = parse_timestamp(end_str.strip().split()[0])
        except (ValueError, IndexError):
            continue
        text = " ".join(lines[timing_idx + 1:]).strip()
        if text:
            cues.append((start, end, text))
    return cues


def parse_sbv(content):
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", content.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines or "," not in lines[0]:
            continue
        start_str, _, end_str = lines[0].partition(",")
        try:
            start = parse_timestamp(start_str.strip())
            end = parse_timestamp(end_str.strip())
        except ValueError:
            continue
        text = " ".join(lines[1:]).strip()
        if text:
            cues.append((start, end, text))
    return cues


def parse_ssa_ass(content):
    cues = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("Dialogue:"):
            continue
        fields = line[len("Dialogue:"):].strip().split(",", 9)
        if len(fields) < 10:
            continue
        try:
            start = parse_timestamp(fields[1].strip())
            end = parse_timestamp(fields[2].strip())
        except ValueError:
            continue
        text = fields[9].strip().replace("\\N", " ").replace("\\n", " ")
        if text:
            cues.append((start, end, text))
    return cues


def parse_lrc(content):
    tag_re = re.compile(r"^\[([^\]]+)\](.*)$")
    timed = []
    for line in content.splitlines():
        match = tag_re.match(line.strip())
        if not match:
            continue
        try:
            start = parse_timestamp(match.group(1))
        except ValueError:
            continue  # metadata tag, e.g. [ar:Artist Name]
        text = match.group(2).strip()
        if text:
            timed.append((start, text))
    cues = []
    for i, (start, text) in enumerate(timed):
        end = timed[i + 1][0] if i + 1 < len(timed) else start + LRC_DEFAULT_TAIL_SECONDS
        cues.append((start, end, text))
    return cues


READERS = {
    "srt": parse_srt,
    "vtt": parse_srt,
    "sbv": parse_sbv,
    "ssa": parse_ssa_ass,
    "ass": parse_ssa_ass,
    "lrc": parse_lrc,
}


class ProgressBar:
    """A simple carriage-return progress bar for stderr.

    Falls back to no output at all when stderr isn't a terminal, so
    piped/logged runs don't fill up with escape-code noise.
    """

    def __init__(self, total, label="Transcribing", width=30):
        self.total = total or 0
        self.label = label
        self.width = width
        self.enabled = self.total > 0 and sys.stderr.isatty()
        self.color = color_enabled(sys.stderr)
        self._last_pct = -1

    def update(self, current):
        if not self.enabled:
            return
        fraction = max(0.0, min(1.0, current / self.total))
        pct = int(fraction * 100)
        if pct == self._last_pct:
            return
        self._last_pct = pct
        filled = int(self.width * fraction)
        empty = self.width - filled
        if self.color:
            label = f"{Colors.CYAN}{self.label}{Colors.RESET}"
            bar = f"{Colors.GREEN}{'#' * filled}{Colors.RESET}{Colors.DIM}{'-' * empty}{Colors.RESET}"
            pct_text = f"{Colors.BOLD}{pct:3d}%{Colors.RESET}"
        else:
            label = self.label
            bar = "#" * filled + "-" * empty
            pct_text = f"{pct:3d}%"
        print(f"\r{label} [{bar}] {pct_text}", end="", file=sys.stderr, flush=True)

    def finish(self):
        if not self.enabled:
            return
        self.update(self.total)
        print(file=sys.stderr)


def extract_audio(input_path, workdir):
    """Use system ffmpeg to decode input_path to a 16kHz mono wav file."""
    wav_path = Path(workdir) / "audio.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        str(wav_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg could not decode '{input_path}':\n{stderr}")
    return wav_path


def run_convert(argv):
    parser = build_convert_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(style(f"wordtrack: error: file not found: {input_path}", Colors.RED), file=sys.stderr)
        return 1
    if not input_path.is_file():
        print(style(f"wordtrack: error: not a file: {input_path}", Colors.RED), file=sys.stderr)
        return 1

    source_format = args.from_format or input_path.suffix.lstrip(".").lower()
    if source_format not in READERS:
        print(
            style(
                f"wordtrack: error: unrecognized source format '{source_format}' "
                f"(expected one of: {', '.join(FORMAT_CHOICES)}; pass --from-format to override)",
                Colors.RED,
            ),
            file=sys.stderr,
        )
        return 1

    if source_format == args.format:
        print(
            style(
                f"wordtrack: error: source and target are both '{args.format}' — nothing to convert",
                Colors.RED,
            ),
            file=sys.stderr,
        )
        return 1

    try:
        content = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        print(style(f"wordtrack: error: could not read '{input_path}' as UTF-8: {exc}", Colors.RED), file=sys.stderr)
        return 1

    parsed = READERS[source_format](content)
    if not parsed:
        print(
            style(f"wordtrack: error: no caption cues found in '{input_path}'", Colors.RED),
            file=sys.stderr,
        )
        return 1

    out_path = Path(args.out) if args.out else input_path.with_suffix(f".{args.format}")
    cues = [[ParsedWord(start, end, f" {text}")] for start, end, text in parsed]
    WRITERS[args.format](cues, out_path)

    print(
        style(
            f"Converted {len(cues)} caption cue{'s' if len(cues) != 1 else ''} "
            f"from {source_format} to {args.format}: {out_path}",
            Colors.GREEN,
            stream=sys.stdout,
        )
    )
    return 0


def run_transcribe(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(style(f"wordtrack: error: file not found: {input_path}", Colors.RED), file=sys.stderr)
        return 1
    if not input_path.is_file():
        print(style(f"wordtrack: error: not a file: {input_path}", Colors.RED), file=sys.stderr)
        return 1

    if args.words_per_line < 1:
        print(style("wordtrack: error: --words-per-line must be at least 1", Colors.RED), file=sys.stderr)
        return 1
    if args.max_gap <= 0:
        print(style("wordtrack: error: --max-gap must be greater than 0", Colors.RED), file=sys.stderr)
        return 1

    if shutil.which("ffmpeg") is None:
        print(
            style(
                "wordtrack: error: ffmpeg was not found on your PATH. "
                "Install ffmpeg and try again.",
                Colors.RED,
            ),
            file=sys.stderr,
        )
        return 1

    out_path = Path(args.out) if args.out else input_path.with_suffix(f".{args.format}")

    # Deferred so `--help` and argument errors stay instant, without
    # loading the (large, slow-to-import) speech model.
    from faster_whisper import WhisperModel

    try:
        with tempfile.TemporaryDirectory(prefix="wordtrack-") as workdir:
            print(style(f"Decoding audio from '{input_path}'...", Colors.CYAN), file=sys.stderr)
            try:
                wav_path = extract_audio(input_path, workdir)
            except RuntimeError as exc:
                print(style(f"wordtrack: error: {exc}", Colors.RED), file=sys.stderr)
                return 1

            print(style(f"Loading '{args.model}' model...", Colors.CYAN), file=sys.stderr)
            model = WhisperModel(args.model, device="cpu", compute_type="int8")

            segments, info = model.transcribe(
                str(wav_path),
                language=args.language,
                word_timestamps=True,
                vad_filter=True,
            )

            progress = ProgressBar(total=info.duration)
            if progress.enabled:
                progress.update(0)  # show the bar immediately, before the first segment lands
            else:
                print(style("Transcribing...", Colors.CYAN), file=sys.stderr)

            words = []
            for segment in segments:
                if segment.words:
                    words.extend(segment.words)
                progress.update(segment.end)
            progress.finish()
    except Exception as exc:  # model/runtime failures: no raw traceback for the user
        print(style(f"wordtrack: error: {exc}", Colors.RED), file=sys.stderr)
        return 1

    if not words:
        print(style("wordtrack: no speech detected in this file.", Colors.YELLOW), file=sys.stderr)
        return 1

    cues = group_words(words, args.words_per_line, args.max_gap)
    WRITERS[args.format](cues, out_path)

    print(
        style(
            f"Detected language: {info.language} ({info.language_probability * 100:.1f}% confidence)",
            Colors.GREEN,
            stream=sys.stdout,
        )
    )
    print(
        style(
            f"Wrote {len(cues)} caption cue{'s' if len(cues) != 1 else ''} to {out_path}",
            Colors.GREEN,
            stream=sys.stdout,
        )
    )
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["convert"]:
        return run_convert(argv[1:])
    return run_transcribe(argv)


if __name__ == "__main__":
    sys.exit(main())
