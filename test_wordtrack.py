#!/usr/bin/env python3
"""Unit tests for wordtrack's pure functions.

Uses synthetic word/cue data only - no real audio/video or model calls,
so these run instantly and without any dependencies beyond the stdlib.
"""

import io
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wordtrack as wt

Word = namedtuple("Word", ["start", "end", "word", "probability"])


class GroupWordsTests(unittest.TestCase):
    def test_words_per_line_caps_cue_size(self):
        words = [Word(i * 0.2, i * 0.2 + 0.1, f" w{i}", 0.9) for i in range(6)]
        cues = wt.group_words(words, words_per_line=3, max_gap=0.6)
        self.assertEqual([len(c) for c in cues], [3, 3])

    def test_gap_splits_cue_early_regardless_of_word_cap(self):
        words = [
            Word(0.0, 0.2, " Hello", 0.9),
            Word(2.0, 2.2, " world", 0.9),  # gap of 1.8s >> max_gap
        ]
        cues = wt.group_words(words, words_per_line=5, max_gap=0.6)
        self.assertEqual(len(cues), 2)


class MinDurationTests(unittest.TestCase):
    def test_zero_duration_word_is_extended_to_the_floor(self):
        words = [
            Word(0.0, 0.2, " Hello", 0.9),
            Word(0.2, 0.2, " world", 0.9),  # start == end: zero-duration word
            Word(1.0, 1.2, " again", 0.9),
        ]
        cues = wt.group_words(words, words_per_line=1, max_gap=0.6)
        fixed = wt.enforce_min_duration(wt.cue_entries(cues), min_duration=0.12)

        for i, (start, end, _) in enumerate(fixed):
            self.assertGreaterEqual(end - start, 0.12 - 1e-9)
            if i + 1 < len(fixed):
                self.assertLessEqual(end, fixed[i + 1][0])

    def test_extension_never_overlaps_the_next_cue(self):
        # The next cue starts only 50ms later - too tight to reach the
        # 0.12s floor without overlapping, so the fix must clip instead.
        words = [
            Word(0.0, 0.0, " a", 0.9),
            Word(0.05, 0.20, " b", 0.9),
        ]
        cues = wt.group_words(words, words_per_line=1, max_gap=0.6)
        fixed = wt.enforce_min_duration(wt.cue_entries(cues), min_duration=0.12)
        self.assertLessEqual(fixed[0][1], fixed[1][0])

    def test_already_long_enough_cues_are_left_untouched(self):
        entries = [(0.0, 1.0, "a"), (2.0, 3.0, "b")]
        fixed = wt.enforce_min_duration(entries, min_duration=0.12)
        self.assertEqual(fixed, entries)

    def test_zero_min_duration_disables_the_floor(self):
        entries = [(0.0, 0.0, "a")]
        fixed = wt.enforce_min_duration(entries, min_duration=0.0)
        self.assertEqual(fixed, entries)


class CueCountWarningTests(unittest.TestCase):
    def test_no_warning_under_threshold(self):
        self.assertIsNone(wt.cue_count_warning(500, threshold=1000))

    def test_no_warning_exactly_at_threshold(self):
        self.assertIsNone(wt.cue_count_warning(1000, threshold=1000))

    def test_warning_over_threshold_mentions_count_and_fix(self):
        message = wt.cue_count_warning(5841, threshold=1000)
        self.assertIsNotNone(message)
        self.assertIn("5841", message)
        self.assertIn("--words-per-line", message)

    def test_warning_is_actually_printed_for_large_cue_count(self):
        buf = io.StringIO()
        message = wt.cue_count_warning(5841, threshold=1000)
        print(wt.style(message, wt.Colors.YELLOW, stream=buf), file=buf)
        self.assertIn("5841", buf.getvalue())


class LargeTranscriptWriteTests(unittest.TestCase):
    def test_large_word_by_word_transcript_writes_well_formed_srt(self):
        # 1200 words, one per cue at --words-per-line 1 (the default) -
        # comfortably over the 1000-cue warning threshold.
        words = [Word(i * 0.3, i * 0.3 + 0.2, f" word{i}", 0.9) for i in range(1200)]

        cues = wt.group_words(words, words_per_line=1, max_gap=0.6)
        entries = wt.enforce_min_duration(wt.cue_entries(cues), min_duration=0.12)
        self.assertEqual(len(entries), 1200)
        self.assertIsNotNone(wt.cue_count_warning(len(entries), threshold=1000))

        pseudo_cues = [[wt.ParsedWord(s, e, f" {t}")] for s, e, t in entries]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.srt"
            wt.write_srt(pseudo_cues, out_path)
            content = out_path.read_text(encoding="utf-8")

        parsed_back = wt.parse_srt(content)
        self.assertEqual(len(parsed_back), 1200)
        for start, end, _ in parsed_back:
            self.assertGreaterEqual(end - start, 0.12 - 1e-9)

    def test_small_transcript_produces_no_warning(self):
        words = [Word(i * 0.3, i * 0.3 + 0.2, f" word{i}", 0.9) for i in range(50)]
        cues = wt.group_words(words, words_per_line=1, max_gap=0.6)
        entries = wt.enforce_min_duration(wt.cue_entries(cues), min_duration=0.12)
        self.assertIsNone(wt.cue_count_warning(len(entries), threshold=1000))


if __name__ == "__main__":
    unittest.main()
