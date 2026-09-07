from __future__ import annotations

import html
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path


TIMESTAMP = re.compile(
    r"(?:(?P<sh>\d{2}):)?(?P<sm>\d{2}):(?P<ss>\d{2})[.,](?P<sms>\d{3})\s+-->\s+"
    r"(?:(?P<eh>\d{2}):)?(?P<em>\d{2}):(?P<es>\d{2})[.,](?P<ems>\d{3})"
)
TAG = re.compile(r"<[^>]+>")
INLINE_TIMESTAMP = re.compile(
    r"<(?:(?P<h>\d{2}):)?(?P<m>\d{2}):(?P<s>\d{2})[.,](?P<ms>\d{3})>"
)


@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: list["WordCue"] = field(default_factory=list)


@dataclass
class WordCue:
    start: float
    end: float
    text: str


def parse_vtt(path: Path | None) -> list[Cue]:
    if not path or not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    cues: list[Cue] = []
    timed_words: list[Cue] = []
    index = 0
    while index < len(lines):
        match = TIMESTAMP.search(lines[index])
        if not match:
            index += 1
            continue
        start = _seconds(match, "s")
        end = _seconds(match, "e")
        index += 1
        content: list[str] = []
        while index < len(lines) and lines[index].strip():
            content.append(lines[index].strip())
            index += 1
        for line in content:
            if INLINE_TIMESTAMP.search(line):
                timed_words.extend(_parse_timed_line(line, start, end))
        text = html.unescape(TAG.sub("", " ".join(content)))
        text = re.sub(r"\s+", " ", text).strip()
        if text and (not cues or text != cues[-1].text or start >= cues[-1].end - 0.1):
            cues.append(Cue(start=start, end=end, text=text))
        index += 1
    return _group_timed_words(timed_words) if timed_words else cues


def _parse_timed_line(line: str, cue_start: float, cue_end: float) -> list[WordCue]:
    words: list[WordCue] = []
    cursor = 0
    start = cue_start
    for match in INLINE_TIMESTAMP.finditer(line):
        end = _inline_seconds(match)
        text = _clean_vtt_text(line[cursor : match.start()])
        if text and end > start:
            words.append(WordCue(start=start, end=end, text=text))
        start = end
        cursor = match.end()
    text = _clean_vtt_text(line[cursor:])
    if text and cue_end > start:
        words.append(WordCue(start=start, end=cue_end, text=text))
    return words


def _group_timed_words(words: list[WordCue]) -> list[Cue]:
    if not words:
        return []
    groups: list[Cue] = []
    current: list[WordCue] = []
    for word in sorted(words, key=lambda item: (item.start, item.end)):
        if current and word.start < current[-1].start:
            continue
        word_count = sum(len(item.text.split()) for item in current)
        should_split = bool(
            current
            and (
                word.start - current[-1].end > 0.45
                or word.start - current[0].start > 1.65
                or word_count + len(word.text.split()) > 5
                or re.search(r"[.!?…]$", current[-1].text)
            )
        )
        if should_split:
            groups.append(_word_group(current))
            current = []
        current.append(word)
    if current:
        groups.append(_word_group(current))
    return groups


def _word_group(words: list[WordCue]) -> Cue:
    return Cue(
        start=words[0].start,
        end=words[-1].end,
        text=re.sub(r"\s+", " ", " ".join(word.text for word in words)).strip(),
        words=list(words),
    )


def _clean_vtt_text(value: str) -> str:
    value = html.unescape(TAG.sub("", value))
    return re.sub(r"\s+", " ", value).strip()


def _inline_seconds(match: re.Match) -> float:
    return (
        int(match["h"] or 0) * 3600
        + int(match["m"]) * 60
        + int(match["s"])
        + int(match["ms"]) / 1000
    )


def write_ass(
    path: Path,
    cues: list[Cue],
    clip_start: float,
    clip_end: float,
    title: str,
    keywords: list[str],
    source_channel: str | None = None,
) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Subtitle,DejaVu Sans,60,&H0000E7FF,&H0000E7FF,&H00120B20,&H00000000,-1,-1,0,0,100,100,0,0,1,5,1,5,70,70,0,1
Style: ActiveBox,DejaVu Sans,60,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,-1,-1,0,0,100,100,0,0,3,7,0,5,0,0,0,1
Style: ActiveText,DejaVu Sans,60,&H0000E7FF,&H0000E7FF,&H00120B20,&H00000000,-1,-1,0,0,100,100,0,0,1,5,0,5,0,0,0,1
Style: Attribution,DejaVu Sans,27,&H00FFFFFF,&H00FFFFFF,&H00100B20,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,8,70,70,78,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    duration = max(0, clip_end - clip_start)
    lines = [header]
    if source_channel:
        attribution = textwrap.shorten(
            f"TONTON SELENGKAPNYA DI {source_channel}", width=58, placeholder="…"
        )
        lines.append(
            f"Dialogue: 3,{_ass_time(0)},{_ass_time(duration)},Attribution,,0,0,0,,"
            f"{_ass_escape(attribution)}\n"
        )
    for cue in cues:
        start = max(cue.start, clip_start)
        end = min(cue.end, clip_end)
        if end <= start:
            continue
        display_words = cue.text.upper().split()
        rows = _subtitle_rows(display_words)
        text = r"\N".join(_ass_escape(" ".join(row)) for row in rows)
        lines.append(
            f"Dialogue: 2,{_ass_time(start - clip_start)},{_ass_time(end - clip_start)},"
            f"Subtitle,,0,0,0,,{{\\an5\\pos(540,1080)}}{text}\n"
        )
        word_timings = cue.words or _estimate_word_timings(cue, display_words)
        positions = _word_positions(rows)
        for timing, (word, x, y) in zip(word_timings, positions):
            word_start = max(timing.start, clip_start, start)
            word_end = min(timing.end, clip_end, end)
            if word_end <= word_start:
                continue
            lines.append(
                f"Dialogue: 4,{_ass_time(word_start - clip_start)},"
                f"{_ass_time(word_end - clip_start)},ActiveBox,,0,0,0,,"
                f"{{\\an5\\pos({x},{y})}}{_ass_escape(word.upper())}\n"
            )
            lines.append(
                f"Dialogue: 5,{_ass_time(word_start - clip_start)},"
                f"{_ass_time(word_end - clip_start)},ActiveText,,0,0,0,,"
                f"{{\\an5\\pos({x},{y})}}{_ass_escape(word.upper())}\n"
            )
    path.write_text("".join(lines), encoding="utf-8")


def _subtitle_rows(words: list[str]) -> list[list[str]]:
    if len(words) <= 3:
        return [words]
    split = (len(words) + 1) // 2
    return [words[:split], words[split:]]


def _word_positions(rows: list[list[str]]) -> list[tuple[str, int, int]]:
    # DejaVu Sans 60 di PlayResX 1080 rata-rata ~35 px per karakter.
    # Posisi ini sengaja stabil di tengah, seperti caption podcast referensi.
    positions: list[tuple[str, int, int]] = []
    line_gap = 74
    first_y = 1080 - (len(rows) - 1) * line_gap // 2
    for row_index, row in enumerate(rows):
        widths = [max(34, round(len(word) * 35.5)) for word in row]
        spaces = 22 * max(0, len(row) - 1)
        cursor = 540 - (sum(widths) + spaces) / 2
        for word, width in zip(row, widths):
            positions.append((word, round(cursor + width / 2), first_y + row_index * line_gap))
            cursor += width + 22
    return positions


def _estimate_word_timings(cue: Cue, words: list[str]) -> list[WordCue]:
    if not words:
        return []
    weights = [max(1, len(re.sub(r"\W", "", word))) for word in words]
    total = sum(weights)
    cursor = cue.start
    timings: list[WordCue] = []
    for index, (word, weight) in enumerate(zip(words, weights)):
        end = cue.end if index == len(words) - 1 else cursor + (cue.end - cue.start) * weight / total
        timings.append(WordCue(cursor, end, word))
        cursor = end
    return timings


def _seconds(match: re.Match, prefix: str) -> float:
    return (
        int(match[f"{prefix}h"] or 0) * 3600
        + int(match[f"{prefix}m"]) * 60
        + int(match[f"{prefix}s"])
        + int(match[f"{prefix}ms"]) / 1000
    )


def _ass_time(seconds: float) -> str:
    seconds = max(0, seconds)
    hours = int(seconds // 3600)
    minutes = int(seconds % 3600 // 60)
    whole = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    if centiseconds == 100:
        whole += 1
        centiseconds = 0
    return f"{hours}:{minutes:02d}:{whole:02d}.{centiseconds:02d}"


def _ass_escape(value: str) -> str:
    return value.replace("{", "(").replace("}", ")")


def _highlight(value: str, keywords: list[str]) -> str:
    result = value
    color_on = r"{\c&H00D7FF&}"
    color_off = r"{\c&HFFFFFF&}"
    for keyword in sorted(keywords, key=len, reverse=True):
        if len(keyword.strip()) < 3:
            continue
        pattern = re.compile(re.escape(keyword.strip()), re.IGNORECASE)
        result = pattern.sub(lambda match: f"{color_on}{match.group(0)}{color_off}", result)
    return result
