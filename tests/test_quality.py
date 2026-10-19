import json
from pathlib import Path
from types import SimpleNamespace

from reelkit import quality


def _probe_result(with_audio):
    streams = [{
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1080,
        "height": 1920,
        "avg_frame_rate": "30/1",
        "r_frame_rate": "30/1",
    }]
    if with_audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"streams": streams, "format": {"duration": "5.0"}}),
        stderr="",
    )


def test_quality_fails_when_expected_commentary_audio_is_missing(monkeypatch, tmp_path):
    output = tmp_path / "silent.mp4"
    output.write_bytes(b"x" * 4096)
    monkeypatch.setattr(quality.subprocess, "run", lambda *args, **kwargs: _probe_result(False))

    report = quality.check(output, audio_required=True)

    assert report["video"] is True
    assert report["audio"] is False
    assert report["audio_required"] is True
    assert report["ok"] is False
    assert "اختفى مسار الصوت من المخرج" in report["issues"]


def test_quality_accepts_valid_commentary_audio(monkeypatch, tmp_path):
    output = tmp_path / "with_voice.mp4"
    output.write_bytes(b"x" * 4096)
    monkeypatch.setattr(quality.subprocess, "run", lambda *args, **kwargs: _probe_result(True))

    report = quality.check(output, audio_required=True)

    assert report["ok"] is True
    assert report["audio"] is True
    assert report["audio_codec"] == "aac"


def test_reel_quality_requires_source_or_generated_audio_and_rechecks_replay():
    source = (Path(__file__).resolve().parents[1] / "reel.py").read_text(encoding="utf-8")

    assert "audio_required=bool(audio or voice_wav)" in source
    replay_move = source.index("safe_move(got, a.output)")
    replay_check = source.index('report_quality("بعد الإعادة")')
    assert replay_move < replay_check
