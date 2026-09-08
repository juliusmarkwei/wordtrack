# wordtrack — Build Requirements

This document is a build spec, not existing code. It describes a CLI tool
to be implemented from scratch and should be handed to a coding agent
(e.g. Claude Code) as its instructions for building the project and
producing the repository's real `README.md` (end-user documentation)
alongside the code.

## 1. Purpose

Build **wordtrack**: a local, offline command-line tool that generates
`.srt` subtitle files from any English video or audio file, using a
speech-to-text model that runs entirely on the user's own machine. No
cloud upload, no account, no usage limits, no watermark.

### Motivation

Consumer apps like CapCut gate automatic captioning behind a paid plan
(a small number of free caption generations per rolling 30-day window,
then none). This tool exists so the same underlying job — turning spoken
audio into a timed, editable transcript — has a version that never runs
out and never requires a subscription.

### Non-goals

- It does **not** burn captions onto the video itself. Output is a
  standard `.srt` file, meant to be imported into a video editor (e.g.
  CapCut, VN) where the user applies their own bold/animated caption
  style.
- It does not support languages other than English in this version
  (the underlying model can, but validating and documenting other
  languages is out of scope for v1).
- It is not a GUI app. Command line only.

## 2. Functional Requirements

### 2.1 Input

- Accepts a path to a single video file (e.g. `.mp4`, `.mov`, `.mkv`,
  `.avi`, `.webm`) or a single audio file (e.g. `.mp3`, `.wav`, `.m4a`,
  `.flac`) — anything the system's `ffmpeg` can decode.
- Must give a clear, non-crashing error message if the given path
  doesn't exist.
- Must give a clear message (not a stack trace) if no speech is detected
  in the file.

### 2.2 Processing

- Transcribes the file's speech locally using an OpenAI Whisper model,
  run through a local inference library (no network calls per
  transcription — network is only needed the first time a given model
  size is used, to download its weights).
- Requests word-level timestamps from the model, not just per-segment
  timestamps — the caption grouping described below depends on knowing
  the start/end time of every individual word.
- Filters out silence rather than letting the model hallucinate words
  into gaps with no speech.

### 2.3 Caption grouping

Given the flat list of timestamped words, group them into subtitle cues
using two rules, applied together:

1. A cue accumulates words until it reaches a configurable maximum word
   count (default: 1 word per cue — i.e. word-by-word, matching the
   bold "one word at a time" caption style common on TikTok/YouTube
   Shorts).
2. Independently of the word count, a cue ends early if the gap between
   the previous word's end time and the next word's start time exceeds
   a configurable threshold (default: 0.6 seconds) — so a single caption
   never silently spans an unrelated pause in speech.

### 2.4 Output

- Writes a standards-compliant `.srt` file: sequential integer index,
  `HH:MM:SS,mmm --> HH:MM:SS,mmm` timing line, then the cue's text, each
  entry separated by a blank line.
- Default output path: same directory and base name as the input file,
  with a `.srt` extension.
- Must support an explicit output path override.

### 2.5 CLI interface

Command name: `wordtrack`

```
wordtrack <input-file> [options]
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `<input-file>` | positional, required | — | Path to the video or audio file to caption |
| `--model` | choice: `tiny`, `base`, `small`, `medium`, `large-v3` | `small` | Whisper model size — trade-off between speed and accuracy |
| `--words-per-line` | integer | `1` | Max words per caption cue (see §2.3) |
| `--max-gap` | float (seconds) | `0.6` | Max silence allowed inside one cue before it splits (see §2.3) |
| `--out` | path | `<input file>.srt` | Output file path |
| `--language` | string | `en` | Spoken language code passed to the model |
| `-h` / `--help` | flag | — | Show usage and exit immediately, without loading the speech model (help must be fast even before dependencies are downloaded/loaded) |

On completion, print: the detected language and the model's confidence in
that detection, the number of caption cues written, and the output path.

## 3. Non-Functional Requirements

- **Fully offline after setup.** Only the one-time model weight download
  (per model size, on first use) needs network access.
- **No usage limits.** No caps of any kind on how many files or how
  often the tool is run.
- **No telemetry, no accounts, no API keys.**
- **Isolated dependencies.** Installing this tool must not modify the
  user's system Python or any other project's environment — dependencies
  live in a dedicated virtual environment created for this tool alone.
- **Cross-platform.** Must work on macOS and Linux. (Windows support is
  out of scope for v1.)

## 4. Distribution & Installation Requirements

The project must be distributable from a public GitHub repository and
installable by a stranger with a single terminal command:

```bash
curl -fsSL https://raw.githubusercontent.com/<GITHUB_USER>/<REPO_NAME>/main/install.sh | bash
```

Implement this as a **POSIX-friendly Bash shell script**, `install.sh`
(shell was chosen deliberately over Perl or any other scripting language,
since it needs zero additional interpreter on macOS/Linux and is the
standard convention for this style of installer — e.g. Homebrew, rustup,
nvm all ship this way).

### 4.1 `install.sh` must

1. Detect the OS (macOS vs. Linux) and, on Linux, detect an available
   package manager (apt, dnf, or pacman, in that order of preference).
2. Check for `python3` and `ffmpeg`. If either is missing:
   - On macOS, offer to install Homebrew (if absent) and then the
     missing dependency via `brew`.
   - On Linux, offer to install the missing dependency via the detected
     package manager.
   - Always ask for explicit confirmation before running anything that
     requires `sudo`. Never install silently.
   - If nothing can be auto-installed, fail with a clear message telling
     the user what to install manually.
3. Download the application's source files (not `git clone` — plain
   `curl` of the raw files is preferred so the installer doesn't
   require `git`) into an install directory, default `~/.wordtrack`,
   overridable via an environment variable.
4. Create a Python virtual environment inside the install directory and
   install the tool's Python dependencies into it — never into the
   system Python.
5. Generate a small wrapper script that invokes the tool via that
   venv's Python interpreter, name it `wordtrack`, and make it
   executable.
6. Make `wordtrack` available on the user's `PATH` without requiring
   `sudo` — symlink it into `~/.local/bin` (creating that directory if
   needed). If `~/.local/bin` is not already on the user's `PATH`,
   print the exact line to add to their shell profile rather than
   silently failing.
7. Support these environment variable overrides: which GitHub
   user/repo/branch to pull from, and the install directory path.
8. Be safe to run when piped directly from `curl` (i.e. must not assume
   an interactive stdin is available for any confirmation prompts — read
   from `/dev/tty` when stdin isn't a terminal).
9. Print a clear success message and a ready-to-copy example command at
   the end.

### 4.2 `uninstall.sh` must

- Remove the install directory and the `~/.local/bin/wordtrack`
  symlink, and confirm what was removed.
- Also be runnable as a `curl | bash` one-liner.

## 5. Repository Structure

```
wordtrack/
├── wordtrack.py     # the CLI implementation
├── requirements.txt    # Python dependencies
├── install.sh          # one-line installer (see §4.1)
├── uninstall.sh         # one-line uninstaller (see §4.2)
├── README.md            # end-user documentation (see §6)
└── LICENSE
```

## 6. Documentation Requirements

Produce a separate, end-user-facing `README.md` (distinct from this
requirements document) that includes at minimum:

- What the tool does and why it exists (1–2 short paragraphs, no
  marketing tone).
- Requirements (OS, Python, ffmpeg) and a note that the installer
  handles them automatically.
- The install one-liner, and a short explanation of what it does step by
  step.
- Full usage documentation: the base command, every flag in a table
  with defaults, and a model-size comparison table (speed vs. accuracy
  trade-off across `tiny`/`base`/`small`/`medium`/`large-v3`).
- At least one example each for a video input and an audio-only input.
- A short section on how to take the resulting `.srt` and get bold,
  animated captions onto a video (import into an editor and apply a
  caption style there — this tool does not do that step itself).
- Uninstall instructions.
- A "build from source" section for anyone who wants to clone the repo
  and run it locally instead of using the installer.
- A troubleshooting section covering at least: file-not-found errors,
  poor transcript accuracy, slow performance, and `wordtrack: command
  not found` after install (PATH issue).
- License section.

## 7. Acceptance Criteria

The implementation is complete when:

- [ ] Running the installer one-liner on a clean macOS machine with no
      prior Python/ffmpeg installed results in a working `wordtrack`
      command, with the user only having to answer y/n prompts for
      installing missing dependencies.
- [ ] Running the installer a second time (already installed) does not
      error and leaves a working install.
- [ ] `wordtrack --help` works instantly, without downloading or
      loading the speech model.
- [ ] `wordtrack <video file>` produces a valid `.srt` file with
      correct, sequential numbering and well-formed timestamps.
- [ ] `wordtrack <audio-only file>` works identically to the video
      case.
- [ ] `--words-per-line` and `--max-gap` visibly change how cues are
      grouped, and a long silence always forces a new cue regardless of
      word count.
- [ ] `--out` correctly overrides the default output path.
- [ ] Running against a file that doesn't exist prints a clear error and
      exits non-zero, without a stack trace.
- [ ] Running against a file with no speech prints a clear message and
      exits non-zero, without a stack trace.
- [ ] `uninstall.sh` removes the install directory and the command from
      `PATH`, verified by `wordtrack` no longer being found afterward.
- [ ] All shell scripts pass `bash -n` (syntax check) and are safe to
      run via `curl ... | bash` (no assumption of an interactive stdin).

## 8. Open Items for Whoever Publishes This Repo

- Choose the actual GitHub username/org and repository name, and update
  every placeholder (`<GITHUB_USER>`, `<REPO_NAME>`) in `install.sh`,
  `uninstall.sh`, and the end-user `README.md` accordingly.
- Confirm the license (this spec assumes MIT unless told otherwise).
