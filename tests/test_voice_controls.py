import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import dashboard
from reelkit import ai, render, voice


def test_voice_defaults_and_ranges():
    defaults = voice.normalize_controls()
    assert defaults["voice_engine"] == "auto"
    assert defaults["edge_voice"] == voice.EDGE_DEFAULT
    assert defaults["voice_gain"] == 1.9
    assert defaults["commentary_energy"] == 70
    assert defaults["voice_mix"] == "auto"
    assert voice.normalize_controls({"voice_rate": -20, "voice_pitch": 12})["voice_rate"] == -20
    with pytest.raises(ValueError):
        voice.normalize_controls([])
    with pytest.raises(ValueError):
        voice.normalize_controls({"voice_rate": 51})
    with pytest.raises(ValueError):
        voice.normalize_controls({"voice_gain": True})
    with pytest.raises(ValueError):
        voice.normalize_controls({"voice_engine": "unknown"})
    with pytest.raises(ValueError):
        voice.normalize_controls({"commentary_energy": 101})
    with pytest.raises(ValueError):
        voice.normalize_controls({"voice_mix": "not-a-mode"})


def test_voice_script_normalization_and_limit():
    assert voice.normalize_script("  هدف\tرائع!\n  ") == "هدف رائع!"
    with pytest.raises(ValueError):
        voice.normalize_script("x" * 501)
    with pytest.raises(ValueError):
        voice.normalize_script(["not", "text"])


def test_edge_rate_pitch_format_and_limits():
    assert voice.edge_rate(10) == "+10%"
    assert voice.edge_rate("-20%") == "-20%"
    assert voice.edge_pitch(4) == "+4Hz"
    assert voice.edge_pitch("-12Hz") == "-12Hz"
    with pytest.raises(ValueError):
        voice.edge_rate(101)
    with pytest.raises(ValueError):
        voice.edge_pitch(21)


def test_say_routes_edge_voice_style_rate_and_pitch(monkeypatch):
    calls = {}

    def fake_edge(text, out_wav, **kwargs):
        calls.update(kwargs)
        return out_wav

    monkeypatch.setattr(voice, "tts_edge", fake_edge)
    monkeypatch.setattr(voice, "audio_seconds", lambda _path: 1.4)

    result = voice.say(
        "هدف رائع", "preview.audio", engine="edge", style="algerian",
        edge_voice="ar-DZ-AminaNeural", rate=16, pitch=-3,
    )

    assert result == {"path": "preview.audio", "engine": "edge", "seconds": 1.4}
    assert calls == {"voice": "ar-DZ-AminaNeural", "rate": "+16%", "pitch": "-3Hz"}


def test_auto_voice_falls_back_to_edge_when_gemini_fails(monkeypatch):
    calls = []

    def fail_gemini(*_args, **_kwargs):
        calls.append("gemini")
        raise RuntimeError("unavailable")

    def fake_edge(_text, out_wav, **kwargs):
        calls.append(("edge", kwargs))
        return out_wav

    monkeypatch.setattr(voice, "tts_gemini", fail_gemini)
    monkeypatch.setattr(voice, "tts_edge", fake_edge)
    monkeypatch.setattr(voice, "audio_seconds", lambda _path: 1.0)

    result = voice.say("هدف رائع", "fallback.mp3", engine="auto", energy=92,
                       edge_voice="ar-DZ-IsmaelNeural", rate=10, pitch=1)

    assert result["engine"] == "edge"
    assert calls[0] == "gemini"
    assert calls[1] == ("edge", {"voice": "ar-DZ-IsmaelNeural", "rate": "+10%", "pitch": "+1Hz"})


def test_auto_engine_falls_back_from_gemini_to_edge(monkeypatch):
    calls = []

    def fail_gemini(*_args, **_kwargs):
        calls.append("gemini")
        raise RuntimeError("provider unavailable")

    def fake_edge(text, out_wav, **kwargs):
        calls.append(("edge", kwargs))
        return out_wav

    monkeypatch.setattr(voice, "tts_gemini", fail_gemini)
    monkeypatch.setattr(voice, "tts_edge", fake_edge)
    monkeypatch.setattr(voice, "audio_seconds", lambda _path: 1.0)

    result = voice.say("هدف", "fallback.audio", engine="auto", rate=12, energy=80)

    assert result["engine"] == "edge"
    assert calls[0] == "gemini"
    assert calls[1] == ("edge", {"voice": voice.EDGE_DEFAULT, "rate": "+12%", "pitch": "+0Hz"})


def test_gemini_tts_receives_voice_and_style_without_network(monkeypatch, tmp_path):
    audio = base64.b64encode(b"\x00\x00" * 256).decode()
    body = {"candidates": [{"content": {"parts": [{"inlineData": {
        "mimeType": "audio/L16;rate=24000", "data": audio,
    }}]}}]}
    calls = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(body).encode()

    def fake_urlopen(request, timeout):
        calls["request"] = request
        calls["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(voice, "_key", lambda _key=None: "test-key")
    monkeypatch.setattr(voice.urllib.request, "urlopen", fake_urlopen)
    output = tmp_path / "commentary.wav"

    result = voice.tts_gemini("اقرأ الجملة كما هي", str(output), model="test-model",
                              voice="Kore", style="cinematic", energy=88)

    request_body = json.loads(calls["request"].data)
    prompt = request_body["contents"][0]["parts"][0]["text"]
    voice_name = request_body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"]
    assert result == str(output)
    assert voice_name == "Kore"
    assert "سينمائي" in prompt
    assert "درجة الحماسة 88 من 100" in prompt
    assert "اقرأ النص كما هو دون إضافة معلومات" in prompt
    assert output.is_file()


def test_ai_commentary_uses_selected_style_in_prompt(monkeypatch):
    captured = {}
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"commentary": "هدف رائع"})}]}}]}

    monkeypatch.setattr(ai, "_key", lambda _key=None: "test-key")
    monkeypatch.setattr(ai, "pick_model", lambda *_args, **_kwargs: "test-model")

    def fake_http(_url, body, **_kwargs):
        captured["body"] = body
        return payload

    monkeypatch.setattr(ai, "_http", fake_http)
    result = ai.commentary(caption="هدف", style="algerian", energy=15)

    prompt = captured["body"]["contents"][0]["parts"][0]["text"]
    assert result["commentary"] == "هدف رائع"
    assert voice.COMMENTARY_STYLES["algerian"]["text"] in prompt
    assert "15/100" in prompt


def test_dashboard_passes_voice_controls_and_manual_script():
    args = dashboard._make_args({
        "commentary": True,
        "commentary_text": True,
        "commentary_script": "  جملة\n يدوية  ",
        "commentary_style": "cinematic",
        "commentary_energy": 76,
        "voice_engine": "edge",
        "edge_voice": "ar-DZ-AminaNeural",
        "gemini_voice": "Charon",
        "voice_rate": 14,
        "voice_pitch": -2,
        "voice_gain": 2.2,
        "voice_duck": 0.18,
        "voice_mix": "fixed",
    }, "input.mp4", "output.mp4")

    def value(flag):
        return args[args.index(flag) + 1]

    assert "--commentary" in args
    assert value("--commentary-script") == "جملة يدوية"
    assert value("--commentary-style") == "cinematic"
    assert value("--commentary-energy") == "76"
    assert value("--voice-engine") == "edge"
    assert value("--edge-voice") == "ar-DZ-AminaNeural"
    assert value("--gemini-voice") == "Charon"
    assert value("--voice-rate") == "14"
    assert value("--voice-pitch") == "-2"
    assert value("--voice-gain") == "2.2"
    assert value("--voice-duck") == "0.18"
    assert value("--voice-mix") == "fixed"
    hidden_text_args = dashboard._make_args({"commentary": True, "commentary_text": False}, "input.mp4", "output.mp4")
    assert "--no-commentary-text" in hidden_text_args
    assert "--commentary-text-only" not in hidden_text_args


def test_voice_preview_api_returns_audio_and_cleans_temp(monkeypatch):
    captured = {}

    def fake_say(text, out_path, **kwargs):
        captured.update(text=text, path=out_path, **kwargs)
        Path(out_path).write_bytes(b"audio" * 100)
        return {"path": out_path, "engine": "edge", "seconds": 1.0}

    monkeypatch.setattr(dashboard.VOICE, "say", fake_say)
    client = TestClient(dashboard.app)
    response = client.post("/api/voice/preview", json={
        "text": "جملة معاينة", "voice_engine": "edge", "edge_voice": "ar-DZ-IsmaelNeural",
        "commentary_energy": 93,
    })

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["x-voice-engine"] == "edge"
    assert response.content == b"audio" * 100
    assert captured["text"] == "جملة معاينة"
    assert captured["rate"] == 10
    assert captured["energy"] == 93
    assert not Path(captured["path"]).exists()


def test_voice_preview_api_rejects_invalid_controls_without_synthesis(monkeypatch):
    monkeypatch.setattr(dashboard.VOICE, "say", lambda *_args, **_kwargs: pytest.fail("must not synthesize"))
    response = TestClient(dashboard.app).post("/api/voice/preview", json={
        "text": "معاينة", "voice_engine": "unknown",
    })
    assert response.status_code == 400


def test_voice_preview_rejects_nonboolean_visibility(monkeypatch):
    monkeypatch.setattr(dashboard.VOICE, "say", lambda *_args, **_kwargs: pytest.fail("must not synthesize"))
    response = TestClient(dashboard.app).post("/api/voice/preview", json={
        "text": "معاينة", "voice_engine": "edge", "commentary_show": "false",
    })
    assert response.status_code == 400


def test_gemini_voice_preview_requires_saved_key(monkeypatch):
    monkeypatch.setattr(dashboard.VOICE, "_key", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dashboard.VOICE, "say", lambda *_args, **_kwargs: pytest.fail("must not synthesize"))
    response = TestClient(dashboard.app).post("/api/voice/preview", json={
        "text": "معاينة", "voice_engine": "gemini",
    })
    assert response.status_code == 503


def test_duck_control_maps_to_sidechain_ratio():
    assert render._duck_ratio(0.0) == pytest.approx(15.0)
    assert render._duck_ratio(0.22) == pytest.approx(11.92)
    assert render._duck_ratio(1.0) == pytest.approx(1.0)
    assert render._duck_ratio(float("nan")) == pytest.approx(11.92)


def test_voice_only_mix_applies_gain_without_match_audio(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    voice_wav = tmp_path / "commentary.wav"
    output = tmp_path / "output.mp4"
    video.write_bytes(b"video")
    voice_wav.write_bytes(b"voice")
    commands = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, **_kwargs):
        if command[0] == "ffprobe":
            return Result(stdout="3.0")
        commands.append(command)
        Path(command[-1]).write_bytes(b"rendered")
        return Result()

    monkeypatch.setattr(render.subprocess, "run", fake_run)
    render._mux(str(video), str(output), voice_wav=str(voice_wav), voice_gain=2.4,
                loudnorm=False, voice_mix="voice_only")
    filter_graph = commands[0][commands[0].index("-filter_complex") + 1]
    assert "volume=2.4" in filter_graph
    assert "apad[a]" in filter_graph


def test_voice_mix_modes_build_the_expected_filtergraph(tmp_path, monkeypatch):
    source = tmp_path / "source-audio.wav"
    voice_file = tmp_path / "voice.wav"
    source.write_bytes(b"source")
    voice_file.write_bytes(b"voice")
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="4.0", returncode=0, stderr="")
        Path(command[-1]).write_bytes(b"muxed")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(render.subprocess, "run", fake_run)
    graphs = {}
    for mode in ("auto", "fixed", "original", "voice_only"):
        temp_video = tmp_path / f"{mode}-video.mp4"
        output = tmp_path / f"{mode}-out.mp4"
        temp_video.write_bytes(b"video")
        render._mux(str(temp_video), str(output), audio=str(source), voice_wav=str(voice_file),
                    duck=0.25, voice_gain=2.0, loudnorm=False, voice_mix=mode)
        command = calls[-1]
        graphs[mode] = command[command.index("-filter_complex") + 1]
        assert output.read_bytes() == b"muxed"

    assert "sidechaincompress" in graphs["auto"]
    assert "volume=0.25" in graphs["fixed"]
    assert "sidechaincompress" not in graphs["original"]
    assert "volume=0.25" not in graphs["original"]
    assert "[1:a]" not in graphs["voice_only"]
    assert "volume=2.0" in graphs["voice_only"]
