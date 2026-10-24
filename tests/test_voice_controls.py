import base64
import io
import json
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import dashboard
from reelkit import ai, render, voice

def test_ai_key_reads_reel_config_profile(tmp_path, monkeypatch):
    config = tmp_path / "profile.json"
    config.write_text(json.dumps({"gemini_api_key": "profile-test-key"}), encoding="utf-8")
    monkeypatch.setenv("REEL_CONFIG", str(config))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert ai._key() == "profile-test-key"


def test_voice_defaults_and_ranges():
    defaults = voice.normalize_controls()
    assert defaults["voice_engine"] == "auto"
    assert defaults["edge_voice"] == voice.EDGE_DEFAULT
    assert defaults["voice_gain"] == 1.9
    assert defaults["commentary_energy"] == 70
    assert defaults["commentary_words"] == 22
    assert voice.normalize_controls({"commentary_words": 8})["commentary_words"] == 8
    assert voice.normalize_controls({"commentary_words": 80})["commentary_words"] == 80
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
        voice.normalize_controls({"commentary_words": 7})
    with pytest.raises(ValueError):
        voice.normalize_controls({"commentary_words": 81})
    with pytest.raises(ValueError):
        voice.normalize_controls({"commentary_words": True})
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


def test_audio_seconds_uses_ffprobe_and_rejects_invalid_durations(tmp_path, monkeypatch):
    path = tmp_path / "narration.mp3"
    path.write_bytes(b"not-a-wav")
    cases = (("3.1415", 0, 3.14), ("nan", 0, 0.0), ("inf", 0, 0.0),
             ("0", 0, 0.0), ("4.0", 1, 0.0), ("", 0, 0.0))

    for stdout, returncode, expected in cases:
        monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
            stdout=stdout, returncode=returncode))
        assert voice.audio_seconds(path) == expected


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


@pytest.mark.parametrize("model", ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"))
def test_gemini_tts_uses_verbatim_text_and_current_style_metadata(monkeypatch, tmp_path, model):
    with io.BytesIO() as stream:
        with wave.open(stream, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(b"\x00\x00" * 256)
        audio = stream.getvalue()
    body = {"candidates": [{"content": {"parts": [{"inlineData": {
        "mimeType": "audio/wav", "data": base64.b64encode(audio).decode(),
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
    spoken_text = "اقرأ الجملة كما هي"

    result = voice.tts_gemini(spoken_text, str(output), model=model,
                              voice="Kore", style="cinematic", energy=88)

    request_body = json.loads(calls["request"].data)
    part = request_body["contents"][0]["parts"][0]
    voice_config = request_body["generationConfig"]["speechConfig"]["voiceConfig"]
    assert result == str(output)
    assert request_body["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert part["text"] == spoken_text
    assert "سينمائي" in part["speech_metadata"]["style"]
    assert "88 من 100" in part["speech_metadata"]["style"]
    assert voice_config == {"voice": "Kore"}
    assert output.read_bytes() == audio
    assert calls["timeout"] == 60


def test_gemini_tts_stops_after_network_failure_for_fast_auto_fallback(monkeypatch, tmp_path):
    attempts = []

    def fail_urlopen(request, timeout):
        attempts.append((request, timeout))
        raise OSError("offline")

    monkeypatch.setattr(voice, "_key", lambda _key=None: "test-key")
    monkeypatch.setattr(voice.urllib.request, "urlopen", fail_urlopen)
    monkeypatch.setattr(voice.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="Gemini TTS فشل") as error:
        voice.tts_gemini("تعليق تجريبي", str(tmp_path / "voice.wav"))

    assert len(attempts) == 2
    assert "test-key" not in str(error.value)


def test_legacy_gemini_tts_wraps_pcm_and_uses_legacy_voice_config(monkeypatch, tmp_path):
    audio = base64.b64encode(b"\x00\x00" * 256).decode()
    body = {"candidates": [{"content": {"parts": [{"inlineData": {
        "mimeType": "audio/L16;rate=24000", "data": audio,
    }}]}}]}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(body).encode()

    calls = {}

    def fake_urlopen(request, timeout):
        calls["request"] = request
        return FakeResponse()

    monkeypatch.setattr(voice, "_key", lambda _key=None: "test-key")
    monkeypatch.setattr(voice.urllib.request, "urlopen", fake_urlopen)
    output = tmp_path / "legacy-commentary.wav"
    spoken_text = "تعليق تجريبي"

    result = voice.tts_gemini(spoken_text, str(output), model="gemini-3.1-flash-tts-preview",
                              voice="Fenrir", style="broadcast", energy=70)

    request_body = json.loads(calls["request"].data)
    part = request_body["contents"][0]["parts"][0]
    voice_config = request_body["generationConfig"]["speechConfig"]["voiceConfig"]
    assert result == str(output)
    assert "اقرأ النص كما هو دون إضافة معلومات" in part["text"]
    assert spoken_text in part["text"]
    assert voice_config == {"prebuiltVoiceConfig": {"voiceName": "Fenrir"}}
    with wave.open(str(output), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnframes() == 256


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


def test_ai_commentary_enforces_requested_word_limit(monkeypatch):
    captured = {}
    generated = " ".join(f"كلمة{i}" for i in range(1, 35))
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"commentary": generated})}]}}]}
    monkeypatch.setattr(ai, "_key", lambda _key=None: "test-key")
    monkeypatch.setattr(ai, "pick_model", lambda *_args, **_kwargs: "test-model")

    def fake_http(_url, body, **_kwargs):
        captured["body"] = body
        return payload

    monkeypatch.setattr(ai, "_http", fake_http)
    result = ai.commentary(caption="هدف", words=12)
    prompt = captured["body"]["contents"][0]["parts"][0]["text"]
    assert "بحد أقصى 12 كلمة" in prompt
    assert captured["body"]["generationConfig"]["maxOutputTokens"] == 144
    assert result["word_limit"] == 12
    assert result["word_count"] == len(result["commentary"].split())
    assert result["word_count"] <= 12
    assert result["commentary"].endswith("…")


def test_commentary_word_cap_prefers_a_complete_sentence():
    text = " ".join(["هدف"] * 14 + ["مكتمل."] + ["كلمة"] * 10)
    result = ai.limit_commentary_words(text, 22)

    assert len(result.split()) == 15
    assert result.endswith("مكتمل.")


def test_commentary_word_cap_preserves_closing_quotes_after_sentence():
    text = " ".join(["هدف"] * 14 + ['"مكتمل."'] + ["زائد"] * 10)
    result = ai.limit_commentary_words(text, 22)

    assert len(result.split()) == 15
    assert result.endswith('"')
    assert not result.endswith("…")


def test_commentary_word_budget_respects_clip_duration():
    assert ai.commentary_word_budget(40, duration=8) == 12
    assert ai.commentary_word_budget(40, duration=5) == 7
    assert ai.commentary_word_budget(22, duration=60) == 22
    assert ai.commentary_word_budget(22, duration=None) == 22
    assert ai.commentary_word_budget(22, duration=float("nan")) == 22
    assert ai.commentary_word_budget(22, duration=10**400) == 22
    assert ai.commentary_word_budget(22, duration=8, words_per_second=0) == 22


def test_spoken_commentary_fit_reduces_only_when_audio_exceeds_clip():
    assert voice.fit_word_limit(12, clip_seconds=8, speech_seconds=5) == 12
    assert voice.fit_word_limit(22, clip_seconds=8, speech_seconds=7.5) < 22
    assert voice.fit_word_limit(22, clip_seconds=1, speech_seconds=3) == 1
    assert voice.fit_word_limit(12, clip_seconds=float("nan"), speech_seconds=6) == 12


def test_very_short_clip_can_reduce_commentary_below_ui_minimum():
    assert ai.commentary_word_budget(22, duration=3) == 3
    text = "كلمة1 كلمة2 كلمة3 كلمة4 كلمة5"
    assert len(ai.limit_commentary_words(text, 3).split()) == 3


def test_ai_commentary_uses_three_grounding_frames_and_duration_cap(monkeypatch, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"sample")
    captured = {}
    generated = " ".join(f"كلمة{i}" for i in range(1, 24))
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"commentary": generated})}]}}]}
    monkeypatch.setattr(ai, "_key", lambda _key=None: "test-key")
    monkeypatch.setattr(ai, "pick_model", lambda *_args, **_kwargs: "test-model")

    def fake_frames(_video, times, width=900):
        captured["times"] = times
        captured["width"] = width
        return ["frame-1", "frame-2", "frame-3"]

    def fake_http(_url, body, **_kwargs):
        captured["body"] = body
        return payload

    monkeypatch.setattr(ai, "_frames", fake_frames)
    monkeypatch.setattr(ai, "_http", fake_http)
    result = ai.commentary(video=str(video), caption="هدف", words=22, duration=8)

    parts = captured["body"]["contents"][0]["parts"]
    prompt = parts[0]["text"]
    assert captured["times"] == (0.15, 0.5, 0.85)
    assert len(parts) == 4
    assert "ثلاث لقطات ثابتة مرتبة زمنياً" in prompt
    assert "8.0 ثانية" in prompt
    assert "بحد أقصى 12 كلمة" in prompt
    assert "لا تستنتج أسماء اللاعبين أو الفرق" in prompt
    assert captured["body"]["generationConfig"]["temperature"] == 0.35
    assert result["word_limit"] == 12
    assert result["requested_word_limit"] == 22
    assert result["duration_limited"] is True
    assert result["word_count"] == 12


def test_ai_commentary_uses_configured_model(monkeypatch):
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"commentary": "هجمة منظمة نحو المرمى."})}]}}]}
    selected = {}
    monkeypatch.setattr(ai, "_key", lambda _key=None: "test-key")
    monkeypatch.setattr(ai, "_config", lambda: {"gemini_model": " gemini-test-flash "})
    monkeypatch.setattr(ai, "pick_model", lambda _key=None, prefer=None: selected.setdefault("model", prefer))
    monkeypatch.setattr(ai, "_http", lambda *_args, **_kwargs: payload)

    result = ai.commentary(caption="هجمة", words=8)

    assert selected["model"] == "gemini-test-flash"
    assert result["model"] == "gemini-test-flash"


def test_transformative_dashboard_job_requires_commentary_key_before_download(monkeypatch):
    monkeypatch.setattr(dashboard.AI, "_key", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dashboard, "_download_to_local",
                        lambda *_args, **_kwargs: pytest.fail("download must not start"))

    with pytest.raises(Exception) as exc:
        dashboard._create({"input": "https://example.test/source.mp4", "transformative": True})

    assert getattr(exc.value, "status_code", None) == 422
    assert "Gemini" in str(exc.value)


@pytest.mark.parametrize("flag", ["--commentary", "--commentary-text-only", "--transformative"])
def test_cli_fails_fast_when_gemini_commentary_has_no_key(monkeypatch, capsys, flag):
    import reel

    monkeypatch.setattr(reel.AI, "_key", lambda *_args, **_kwargs: None)
    with pytest.raises(SystemExit) as exc:
        reel.main(["-i", "missing.mp4", "-o", "unused.mp4", flag])

    assert exc.value.code == 2
    assert "مفتاح Gemini" in capsys.readouterr().err


def test_dashboard_passes_voice_controls_and_manual_script():
    args = dashboard._make_args({
        "commentary": True,
        "commentary_text": True,
        "commentary_script": "  جملة\n يدوية  ",
        "commentary_style": "cinematic",
        "commentary_energy": 76,
        "commentary_words": 64,
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
    assert value("--commentary-words") == "64"
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


def test_dashboard_rejects_invalid_commentary_word_limit():
    with pytest.raises(dashboard.HTTPException) as error:
        dashboard._voice_payload({"commentary_words": 81})
    assert error.value.status_code == 400


def test_dashboard_rejects_invalid_brand_position_and_scale():
    for options in ({"brand_y": float("nan")}, {"brand_y": 0.9}, {"brand_scale": 1.5}):
        with pytest.raises(dashboard.HTTPException) as error:
            dashboard._make_args(options, "input.mp4", "output.mp4")
        assert error.value.status_code == 400


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


def test_voice_only_mix_never_restores_source_audio_when_tts_is_missing(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    source = tmp_path / "broadcast.wav"
    output = tmp_path / "output.mp4"
    video.write_bytes(b"video-without-audio")
    source.write_bytes(b"copyrighted-broadcast-audio")
    calls = []
    monkeypatch.setattr(render.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    render._mux(str(video), str(output), audio=str(source), voice_mix="voice_only")

    assert output.read_bytes() == b"video-without-audio"
    assert calls == []


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
    commands = {}
    for mode in ("auto", "fixed", "original", "voice_only"):
        temp_video = tmp_path / f"{mode}-video.mp4"
        output = tmp_path / f"{mode}-out.mp4"
        temp_video.write_bytes(b"video")
        render._mux(str(temp_video), str(output), audio=str(source), voice_wav=str(voice_file),
                    duck=0.25, voice_gain=2.0, loudnorm=False, voice_mix=mode)
        command = calls[-1]
        commands[mode] = command
        graphs[mode] = command[command.index("-filter_complex") + 1]
        assert output.read_bytes() == b"muxed"

    assert "sidechaincompress" in graphs["auto"]
    assert "volume=0.25" in graphs["fixed"]
    assert "sidechaincompress" not in graphs["original"]
    assert "volume=0.25" not in graphs["original"]
    assert "[1:a]" in graphs["voice_only"]
    assert "[0:a]" not in graphs["voice_only"]
    assert str(source) not in commands["voice_only"]
    assert "volume=2.0" in graphs["voice_only"]

def test_ai_commentary_falls_back_to_next_model_on_http_error(monkeypatch):
    import urllib.error
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"commentary": "هدف رائع"})}]}}]}
    monkeypatch.setattr(ai, "_key", lambda _key=None: "test-key")
    monkeypatch.setattr(ai, "pick_model", lambda *_args, **_kwargs: "test-model")

    def fake_http(url, body, **_kwargs):
        if "test-model:generateContent" in url:
            raise urllib.error.HTTPError(url, 503, "busy", {}, io.BytesIO(b""))
        return payload

    monkeypatch.setattr(ai, "_http", fake_http)
    monkeypatch.setattr(ai.time, "sleep", lambda _s: None)
    result = ai.commentary(caption="هدف")

    assert result["commentary"] == "هدف رائع"
    assert result["model"] != "test-model"

def test_ai_commentary_tries_three_models_before_failing(monkeypatch):
    import urllib.error
    tried = []
    monkeypatch.setattr(ai, "_key", lambda _key=None: "test-key")
    monkeypatch.setattr(ai, "pick_model", lambda *_args, **_kwargs: "gemini-9.9-flash")

    def fake_http(url, _body=None, **_kwargs):
        tried.append(url.split("/models/")[1].split(":")[0])
        raise urllib.error.HTTPError(url, 503, "busy", {}, io.BytesIO(b""))

    monkeypatch.setattr(ai, "_http", fake_http)
    monkeypatch.setattr(ai.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="فشل توليد التعليق"):
        ai.commentary(caption="هدف")

    assert len(tried) == 3
    assert len(set(tried)) == 3
