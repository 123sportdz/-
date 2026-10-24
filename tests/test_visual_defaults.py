import ast
from html.parser import HTMLParser
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


class SelectOptions(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.options = {}
        self.selected = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self.current = attrs.get("id")
        elif tag == "option" and self.current:
            value = attrs.get("value")
            if value is not None:
                self.options.setdefault(self.current, []).append(value)
                if "selected" in attrs:
                    self.selected[self.current] = value

    def handle_endtag(self, tag):
        if tag == "select":
            self.current = None


def _dashboard_html():
    # منذ v1.70 تعيش الواجهة في dashboard_ui.html وتُحمَّل إلى dashboard.HTML
    return (ROOT / "dashboard_ui.html").read_text(encoding="utf-8")


def _make_args():
    path = ROOT / "dashboard.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"_brand_args", "_make_args"}
    }
    module = ast.Module(body=[functions["_brand_args"], functions["_make_args"]], type_ignores=[])
    namespace = {"CFG": {}}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["_make_args"]


def _cli_argument(flag):
    path = ROOT / "reel.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == flag
    )


def _function(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_dashboard_quality_options_match_cli_and_have_a_valid_default():
    ui = SelectOptions()
    ui.feed(_dashboard_html())
    cli_call = _cli_argument("--quality")
    cli_choices = ast.literal_eval(next(item.value for item in cli_call.keywords if item.arg == "choices"))

    assert set(ui.options["quality"]) == set(cli_choices)
    assert ui.selected["quality"] == "auto"


def test_dashboard_and_cli_default_to_clean_action_framing_without_tracker_graphics():
    make_args = _make_args()
    args = make_args({}, "source.mp4", "output.mp4")

    assert args[args.index("--subject") + 1] == "action"
    assert args[args.index("--layout") + 1] == "single"
    assert args[args.index("--quality") + 1] == "auto"
    assert "--no-trail" in args

    assert args[args.index("--brand-y") + 1] == "0.13"
    assert args[args.index("--brand-scale") + 1] == "1.0"

    positioned = make_args({"brand_y": 0.18, "brand_scale": 0.8}, "source.mp4", "output.mp4")
    assert positioned[positioned.index("--brand-y") + 1] == "0.18"
    assert positioned[positioned.index("--brand-scale") + 1] == "0.8"

    show_trail = make_args({"show_trail": True}, "source.mp4", "output.mp4")
    assert "--show-trail" in show_trail
    assert "--no-trail" not in show_trail

    cli_subject = _cli_argument("--subject")
    assert next(item.value.value for item in cli_subject.keywords if item.arg == "default") == "action"


def test_renderer_hides_tracking_graphics_by_default():
    path = ROOT / "reelkit" / "render.py"
    function = _function(path, "render")
    names = [arg.arg for arg in function.args.args]
    defaults_start = len(names) - len(function.args.defaults)
    defaults = {
        name: value
        for name, value in zip(names[defaults_start:], function.args.defaults)
    }

    assert ast.literal_eval(defaults["use_trail"]) is False
    assert ast.literal_eval(defaults["brand_y"]) == pytest.approx(0.13)


def test_channel_bug_stays_in_the_top_safe_corner():
    pytest.importorskip("cv2")
    import numpy as np
    from reelkit.graphics import BRAND_Y, draw_brand

    original = np.full((1920, 1080, 3), (45, 120, 50), dtype=np.uint8)
    result = draw_brand(original.copy(), "الجزائر الجديدة TV", "youtube.com/@aljazaer7tv")
    changed = np.any(result != original, axis=2)
    ys, xs = np.where(changed)

    assert BRAND_Y == pytest.approx(0.13)

    assert len(xs) > 0
    assert xs.min() > 540
    assert xs.max() < 1060
    assert ys.min() > 20
    assert ys.max() < 350
    assert changed.sum() < original.shape[0] * original.shape[1] * 0.05


def test_dashboard_can_hide_only_the_channel_name():
    make_args = _make_args()
    assert _cli_argument("--hide-channel-name")
    args = make_args({
        "show_channel_name": False,
        "name": "My channel",
        "url": "youtube.com/@mychannel",
    }, "source.mp4", "output.mp4")

    assert "--hide-channel-name" in args
    assert "--name" not in args
    assert args[args.index("--url") + 1] == "youtube.com/@mychannel"

    visible_args = make_args({"show_channel_name": True, "name": "My channel"}, "source.mp4", "output.mp4")
    assert "--hide-channel-name" not in visible_args
    assert visible_args[visible_args.index("--name") + 1] == "My channel"


def test_commentary_word_limit_cli_and_dashboard_flags_are_wired():
    cli = _cli_argument("--commentary-words")
    keywords = {item.arg: item.value for item in cli.keywords}
    assert ast.literal_eval(keywords["default"]) == 22
    assert isinstance(keywords["type"], ast.Name) and keywords["type"].id == "int"

    tree = ast.parse((ROOT / "reel.py").read_text(encoding="utf-8"))
    call = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commentary"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "AI"
    )
    words = next(item.value for item in call.keywords if item.arg == "words")
    assert isinstance(words, ast.Attribute) and words.attr == "commentary_words"


def test_autopilot_validates_and_forwards_commentary_word_limit():
    path = ROOT / "autopilot.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    argument = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "--commentary-words"
    )
    keywords = {item.arg: item.value for item in argument.keywords}
    assert ast.literal_eval(keywords["default"]) == 22
    assert isinstance(keywords["type"], ast.Name) and keywords["type"].id == "int"

    process = _function(path, "process")
    process_source = ast.get_source_segment(path.read_text(encoding="utf-8"), process)
    assert '"--commentary-words"' in process_source
    assert 'getattr(a, "commentary_words", 22)' in process_source
    assert 'getattr(a, "commentary_pitch", 0)' in process_source
    assert '"--commentary-pitch"' in process_source
    assert '"commentary_pitch": a.commentary_pitch' in ast.get_source_segment(
        path.read_text(encoding="utf-8"), _function(path, "main"))
    main = _function(path, "main")
    main_source = ast.get_source_segment(path.read_text(encoding="utf-8"), main)
    assert "VOICE.normalize_controls" in main_source
    assert "ap.error" in main_source
