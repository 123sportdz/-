import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _dashboard_make_args():
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


def test_render_preserves_source_marks_by_default():
    path = ROOT / "reelkit" / "render.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render")
    names = [arg.arg for arg in function.args.args]
    index = names.index("remove_watermarks")
    default_start = len(names) - len(function.args.defaults)
    default = function.args.defaults[index - default_start]

    assert isinstance(default, ast.Constant)
    assert default.value is False


def test_dashboard_preserves_marks_unless_removal_is_explicit():
    make_args = _dashboard_make_args()

    default_args = make_args({}, "source.mp4", "output.mp4")
    assert "--keep-watermarks" in default_args
    assert "--remove-watermarks" not in default_args

    removal_args = make_args({"keep_watermarks": False}, "source.mp4", "output.mp4")
    assert "--remove-watermarks" in removal_args
    assert "--keep-watermarks" not in removal_args
