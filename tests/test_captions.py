from pathlib import Path

from backend.captions import parse_vtt, write_ass


def test_parse_vtt_and_generate_highlighted_ass(tmp_path: Path):
    source = tmp_path / "captions.vtt"
    source.write_text(
        """WEBVTT

00:00:10.000 --> 00:00:13.000
Ini adalah rahasia bisnis saya.

00:00:13.000 --> 00:00:15.500
Jangan takut untuk memulai.
""",
        encoding="utf-8",
    )
    cues = parse_vtt(source)
    assert len(cues) == 2
    assert cues[0].start == 10

    output = tmp_path / "clip.ass"
    write_ass(
        output,
        cues,
        9,
        16,
        "Mulai sekarang",
        ["rahasia bisnis"],
        source_channel="Channel Contoh",
    )
    contents = output.read_text(encoding="utf-8")
    assert "Dialogue:" in contents
    assert "rahasia bisnis" in contents
    assert r"{\c&H00D7FF&}" in contents
    assert "source: Channel Contoh" in contents


def test_parse_vtt_supports_timestamp_without_hours(tmp_path: Path):
    source = tmp_path / "short.vtt"
    source.write_text(
        "WEBVTT\n\n00:10.000 --> 00:12.250\nHalo Indonesia.\n",
        encoding="utf-8",
    )
    cues = parse_vtt(source)
    assert cues[0].start == 10
    assert cues[0].end == 12.25


def test_parse_youtube_word_timestamps_into_short_synced_phrases(tmp_path: Path):
    source = tmp_path / "youtube.vtt"
    source.write_text(
        """WEBVTT

00:00:10.000 --> 00:00:12.000 align:start position:0%
teks lama yang sedang bergulir
Halo<00:00:10.400><c> dunia</c><00:00:10.900><c> sekarang.</c>

00:00:12.000 --> 00:00:12.010 align:start position:0%
Halo dunia sekarang.

00:00:12.010 --> 00:00:13.500 align:start position:0%
Halo dunia sekarang.
Ini<00:00:12.300><c> sinkron.</c>
""",
        encoding="utf-8",
    )

    cues = parse_vtt(source)

    assert [cue.text for cue in cues] == ["Halo dunia sekarang.", "Ini sinkron."]
    assert cues[0].start == 10
    assert cues[0].end == 12
    assert cues[1].start == 12.01
    assert cues[1].end == 13.5
    assert all(cue.end - cue.start > 0.1 for cue in cues)
