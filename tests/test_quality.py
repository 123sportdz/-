from pathlib import Path
from types import SimpleNamespace

from reelkit import quality


def _probe(monkeypatch, duration, with_audio=False):
    streams = [{
        "codec_type": "video", "width": 1080, "height": 1920,
        "avg_frame_rate": "30/1", "codec_name": "h264",
    }]
    if with_audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    payload = {"streams": streams, "format": {"duration": str(duration)}}
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


def test_quality_rejects_output_without_expected_narration(tmp_path, monkeypatch):
    output = tmp_path / "silent.mp4"
    output.write_bytes(b"x" * 2048)
    _probe(monkeypatch, 4.5)

    report = quality.check(output, audio_required=True)

    assert report["audio_required"] is True
    assert report["audio"] is False
    assert report["ok"] is False
    assert "اختفى مسار الصوت من المخرج" in report["issues"]


def test_quality_accepts_output_with_required_audio(tmp_path, monkeypatch):
    output = tmp_path / "with_voice.mp4"
    output.write_bytes(b"x" * 2048)
    _probe(monkeypatch, 4.5, with_audio=True)

    report = quality.check(output, audio_required=True)

    assert report["audio_required"] is True
    assert report["audio"] is True
    assert report["audio_codec"] == "aac"
    assert report["ok"] is True


def test_reel_audio_qa_covers_source_voice_and_replay():
    source = (Path(__file__).resolve().parents[1] / "reel.py").read_text(encoding="utf-8")

    assert "source_audio_available = bool(not a.no_audio and" in source
    assert "(source_info.get(\"acodec\") or info.get(\"acodec\")))" in source
    assert "quality_audio_required = bool(source_audio_available or voice_wav)" in source
    assert "audio_required=quality_audio_required" in source
    replay_move = source.index("safe_move(got, a.output)")
    replay_check = source.index('report_quality("بعد الإعادة")')
    assert replay_move < replay_check
