import cv2
import numpy as np
import pytest

from reelkit import detect, ffio


class _FakeCap:
    """بديل cv2.VideoCapture: فريمات ثم خطأ OOM في القراءة (كما في تقرير ويندوز)."""

    def __init__(self, frames=2, error=None):
        self._remaining = frames
        self._error = error

    def get(self, _prop):
        return 30.0

    def read(self):
        if self._error is not None and self._remaining <= 0:
            raise self._error
        if self._remaining <= 0:
            return False, None
        self._remaining -= 1
        return True, np.zeros((72, 128, 3), np.uint8)

    def release(self):
        pass


class _EmptyResult:
    boxes = []


class _BoxResult:
    """نتيجة YOLO مزيفة بصندوق واحد للكرة."""

    def __init__(self):
        self.boxes = [type("B", (), {"xyxy": [np.array([10.0, 10.0, 50.0, 50.0])],
                                     "conf": [0.9]})()]


def _stub_detector(cls, batch=2):
    obj = object.__new__(cls)
    obj.batch = batch
    obj.precision = {}
    obj.model = None
    obj.conf = 0.2
    obj.iou = 0.5
    obj._warmed = True
    obj.tile = 1
    obj.overlap = 0.2
    obj._predict_batch = lambda frames: [_EmptyResult() for _ in frames]
    return obj


def test_read_frame_lenient_returns_eof_on_memory_error():
    cap = _FakeCap(frames=0, error=cv2.error("error: (-4:Insufficient memory) Failed to allocate"))
    assert ffio.read_frame_lenient(cap) == (False, None)


def test_read_frame_lenient_reraises_other_cv2_errors():
    cap = _FakeCap(frames=0, error=cv2.error("some other cv2 failure"))
    with pytest.raises(cv2.error):
        ffio.read_frame_lenient(cap)


def test_person_scan_survives_oom_and_returns_partial(monkeypatch):
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: _FakeCap(frames=4))
    pd = _stub_detector(detect.PersonDetector)
    out = pd.scan("video.mp4", rate=15.0, fps=30.0)
    assert out.shape == (2, 3)


def test_ball_scan_survives_oom_and_returns_partial(monkeypatch):
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: _FakeCap(frames=4))
    bd = _stub_detector(detect.BallDetector)
    bd._predict_batch = lambda frames: [_BoxResult() for _ in frames]
    out = bd.scan("video.mp4", rate=15.0, fps=30.0)
    assert out.ndim == 2 and out.shape[0] >= 1


def test_person_scan_oom_on_first_frame_returns_empty_not_crash(monkeypatch):
    monkeypatch.setattr(
        cv2, "VideoCapture",
        lambda _path: _FakeCap(frames=0, error=cv2.error("Insufficient memory")))
    pd = _stub_detector(detect.PersonDetector)
    out = pd.scan("video.mp4", rate=15.0, fps=30.0)
    assert out.shape == (0, 3)
