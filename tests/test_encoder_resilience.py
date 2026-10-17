from pathlib import Path

import numpy as np

from reelkit.detect import precision_kwargs
from reelkit.encode import should_retry_x264
from reelkit import render as render_module
from reelkit import detect as detect_module
from reelkit import replay as replay_module
from reelkit import encode as ENC


def test_precision_uses_quantize_on_ultralytics_84_and_later():
    assert precision_kwargs(True, "8.4.174") == {"quantize": 16}
    assert precision_kwargs(True, "8.5.0") == {"quantize": 16}
    assert precision_kwargs(True, "8.4.0rc1") == {"quantize": 16}


def test_precision_keeps_legacy_half_for_older_ultralytics():
    assert precision_kwargs(True, "8.3.301") == {"half": True}
    assert precision_kwargs(False, "8.4.174") == {}


def test_nvenc_resource_failures_are_retried_in_software():
    assert should_retry_x264("nvenc", "CUDA_ERROR_OUT_OF_MEMORY: out of memory")
    assert should_retry_x264("nvenc", "No capable devices found")
    assert not should_retry_x264("x264", "CUDA_ERROR_OUT_OF_MEMORY")
    assert not should_retry_x264("nvenc", "disk is full")


def test_render_retries_nvenc_broken_pipe_with_x264(monkeypatch, tmp_path):
    frame = np.zeros((9, 16, 3), dtype=np.uint8)
    calls = []
    messages = []

    class Capture:
        def __init__(self):
            self.read_count = 0

        def read(self):
            self.read_count += 1
            return (True, frame.copy()) if self.read_count == 1 else (False, None)

        def release(self):
            pass

    class Pipe:
        def __init__(self, broken):
            self.broken = broken

        def write(self, data):
            if self.broken:
                raise BrokenPipeError
            return len(data)

        def close(self):
            pass

    class Process:
        def __init__(self, broken):
            self.stdin = Pipe(broken)
            self.returncode = 1 if broken else 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    def popen(command, stdin=None, stderr=None):
        calls.append(command)
        broken = len(calls) == 1
        if broken:
            stderr.write("CUDA_ERROR_OUT_OF_MEMORY: No capable devices found\n")
            stderr.flush()
        return Process(broken)

    def video_args(prefer="auto", crf=20, preset="medium"):
        if str(prefer).lower() in {"cpu", "x264", "libx264", "software"}:
            return "x264", ["-c:v", "libx264", "-crf", str(crf)]
        return "nvenc", ["-c:v", "h264_nvenc"]

    def fake_run(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "video\naudio\n"
            stderr = ""
        return Result()

    def fake_mux(_tmp_video, output, **kwargs):
        Path(output).write_bytes(b"muxed")

    monkeypatch.setattr(render_module.ENC, "video_args", video_args)
    monkeypatch.setattr(render_module.ENC, "should_retry_x264", should_retry_x264)
    monkeypatch.setattr(render_module.subprocess, "Popen", popen)
    monkeypatch.setattr(render_module.subprocess, "run", fake_run)
    monkeypatch.setattr(render_module.cv2, "VideoCapture", lambda _: Capture())
    monkeypatch.setattr(render_module, "_mux", fake_mux)
    monkeypatch.setattr(detect_module, "release_gpu_memory", lambda: False)
    monkeypatch.setitem(render_module.ENC._PROBE, "nvenc", True)

    output = tmp_path / "fallback.mp4"
    frames = render_module.render(
        "source.mp4", None, str(output), {"fps": 30.0, "W": 16, "H": 9},
        np.asarray([8.0]), np.asarray([0]), np.asarray([np.nan]),
        np.empty((0, 6), dtype=np.float32), out_w=16, out_h=28,
        progress=messages.append,
    )

    assert frames == 1
    assert len(calls) == 2
    assert "h264_nvenc" in calls[0]
    assert "libx264" in calls[1]
    assert output.read_bytes() == b"muxed"
    assert any("NVENC" in message for message in messages)
    assert any("NVENC" in message for message in messages)


def test_replay_retries_nvenc_failure_with_x264(monkeypatch, tmp_path):
    reel = tmp_path / "reel.mp4"
    reel.write_bytes(b"x" * 1024)
    out = tmp_path / "reel_replay.mp4"
    calls = []

    class Result:
        def __init__(self, code, err):
            self.returncode = code
            self.stdout = ""
            self.stderr = err

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        calls.append(cmd)
        if cmd[0] == "ffmpeg" and len(calls) == 3:
            return Result(1, "[h264_nvenc] CUDA_ERROR_OUT_OF_MEMORY: out of memory\n")
        if cmd[0] == "ffmpeg":
            out.write_bytes(b"v" * 30000)
        return Result(0, "")

    monkeypatch.setattr(replay_module, "_dur", lambda _p: 10.0)
    monkeypatch.setattr(replay_module, "_has_audio", lambda _p: False)
    monkeypatch.setattr(replay_module, "badge_png", lambda *_a, **_k: None)
    monkeypatch.setattr(replay_module.subprocess, "run", fake_run)
    monkeypatch.setitem(ENC._PROBE, "nvenc", True)

    got = replay_module.add_replay(str(reel), str(out), 5.0, workdir=str(tmp_path))

    ffmpeg_calls = [c for c in calls if c[0] == "ffmpeg"]
    assert got == str(out)
    assert len(ffmpeg_calls) == 2
    assert "h264_nvenc" in ffmpeg_calls[0]
    assert "libx264" in ffmpeg_calls[1]


def test_replay_keeps_single_attempt_for_non_nvenc_errors(monkeypatch, tmp_path):
    reel = tmp_path / "reel.mp4"
    reel.write_bytes(b"x" * 1024)
    out = tmp_path / "reel_replay.mp4"
    calls = []

    class Result:
        def __init__(self, code, err):
            self.returncode = code
            self.stdout = ""
            self.stderr = err

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        calls.append(cmd)
        return Result(1, "No space left on device\n")

    monkeypatch.setattr(replay_module, "_dur", lambda _p: 10.0)
    monkeypatch.setattr(replay_module, "_has_audio", lambda _p: False)
    monkeypatch.setattr(replay_module, "badge_png", lambda *_a, **_k: None)
    monkeypatch.setattr(replay_module.subprocess, "run", fake_run)
    monkeypatch.setitem(ENC._PROBE, "nvenc", True)

    assert replay_module.add_replay(str(reel), str(out), 5.0, workdir=str(tmp_path)) is None
    assert len([c for c in calls if c[0] == "ffmpeg"]) == 1
