import json

from backend import downloader
from backend.process import ToolError


def test_subtitle_failure_does_not_cancel_video(monkeypatch, tmp_path):
    commands: list[list[str]] = []

    monkeypatch.setattr(downloader, "require_tool", lambda name: f"/{name}")
    monkeypatch.setattr(downloader.shutil, "which", lambda name: "/usr/bin/node")

    def fake_run(command, cwd=None):
        commands.append(command)
        if "--dump-single-json" in command:
            return type("Result", (), {"stdout": json.dumps({"title": "Tes"})})()
        if "--skip-download" in command:
            raise ToolError("HTTP Error 429: Too Many Requests")
        (tmp_path / "source.mp4").touch()
        return type("Result", (), {"stdout": ""})()

    monkeypatch.setattr(downloader, "run", fake_run)

    metadata, source, subtitle = downloader.download_youtube(
        "https://youtube.com/watch?v=test", tmp_path, 1080, lambda *_: None
    )

    assert metadata["title"] == "Tes"
    assert source == tmp_path / "source.mp4"
    assert subtitle is None

    subtitle_command = next(command for command in commands if "--write-subs" in command)
    assert subtitle_command[subtitle_command.index("--sub-langs") + 1] == "id,id.*"
    assert "node:/usr/bin/node" in subtitle_command
