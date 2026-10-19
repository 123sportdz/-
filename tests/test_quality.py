from pathlib import Path
from types import SimpleNamespace

from reelkit import quality


def _probe(monkeypatch, duration):
    payload = {
        "streams": [{
            "codec_type": "video", "width": 1080, "height": 1920,
            "avg_frame_rate": "30/1", "codec_name": "h264",
        }],
        "format": {"duration": str(duration)},
    }
    monkeypatch.setattr(
        quality.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=__import__("json").dumps(payload)),
    )


def test_quality_rejects_zero_duration_output(tmp_path, monkeypatch):
    output = tmp_path / "zero.mp4"
    output.write_bytes(b"x" * 2048)
    _probe(monkeypatch, 0)

    report = quality.check(output)

    assert report["ok"] is False
    assert any("مدة الفيديو" in issue for issue in report["issues"])


def test_quality_accepts_valid_video_without_required_audio(tmp_path, monkeypatch):
    output = tmp_path / "valid.mp4"
    output.write_bytes(b"x" * 2048)
    _probe(monkeypatch, 4.5)

    report = quality.check(output)

    assert report["ok"] is True
    assert report["duration"] == 4.5
