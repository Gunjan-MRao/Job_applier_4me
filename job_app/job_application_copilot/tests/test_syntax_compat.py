"""Project-wide syntax guards so code that only compiles on a newer interpreter
can never silently ship again.

Real bug these catch: an f-string whose {expression} part contained a backslash
escape (e.g. `f"{x or '\\u2014'}"`). PEP 701 made that legal on Python 3.12+, but
it is a SyntaxError on 3.9-3.11. The project docs ask for `conda create ... python=3.12`,
but the user's actual `jobcopilot` env was older, so the app booted and then the
Streamlit page crashed with "f-string expression part cannot include a backslash".

Two guards, because they have different reach:

  * test_no_backslash_inside_fstring_expressions -- the AUTHORITATIVE check for
    this specific regression. It walks the AST and inspects the source text of
    every f-string {expression}, so it flags a stray backslash on ANY host,
    including Python 3.12+ (where the code parses fine and a plain parse would
    not notice).
  * test_parses_under_min_supported_python -- a general "does every file even
    parse" guard, pinned to the oldest supported grammar via feature_version.
    Note: feature_version does NOT re-impose the pre-3.12 f-string tokenizer
    rule on a 3.12+ host, so on new hosts it will not catch the backslash bug on
    its own -- that is exactly why the dedicated AST check above exists. It still
    catches ordinary syntax errors and adds real f-string coverage on <3.12 CI.
"""
import ast
import os

import pytest

MIN_VERSION = (3, 9)  # oldest Python this project promises to run on
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _all_py_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
        dirnames[:] = [d for d in dirnames if d not in
                       ("__pycache__", ".git", "node_modules", ".venv", "venv")]
        for name in filenames:
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


@pytest.mark.parametrize("path", _all_py_files(), ids=lambda p: os.path.relpath(p, PROJECT_ROOT))
def test_parses_under_min_supported_python(path):
    src = open(path, encoding="utf-8").read()
    try:
        ast.parse(src, filename=path, feature_version=MIN_VERSION)
    except SyntaxError as e:
        pytest.fail(
            f"{os.path.relpath(path, PROJECT_ROOT)} does not parse under Python "
            f"{MIN_VERSION[0]}.{MIN_VERSION[1]}: {e.msg} (line {e.lineno}).\n"
            "This ships broken on older interpreters. If it's a backslash inside an "
            "f-string {expression}, move the escaped value into a module constant."
        )


def test_no_backslash_inside_fstring_expressions():
    """Directly assert the specific regression: no backslash in any f-string {expr}."""
    offenders = []
    for path in _all_py_files():
        src = open(path, encoding="utf-8").read()
        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError:
            continue  # covered by the parametrized test above
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for value in node.values:
                    if isinstance(value, ast.FormattedValue):
                        seg = ast.get_source_segment(src, value.value)
                        if seg and "\\" in seg:
                            offenders.append(
                                f"{os.path.relpath(path, PROJECT_ROOT)}:{value.lineno} -> {seg}"
                            )
    assert not offenders, (
        "Backslash inside f-string expression(s) (breaks on Python < 3.12):\n"
        + "\n".join(offenders)
    )
