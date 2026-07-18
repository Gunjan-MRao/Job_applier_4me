"""Regression test for the conda-base detection in launch_app.bat.

Real bug report: a user's Anaconda base was literally
    C:\\Users\\gunja\\anaconda3\\New folder
(note the space and the non-standard "New folder" sub-folder). The old launcher
only checked a fixed list of exact paths (%USERPROFILE%\\anaconda3, etc.) plus
`where conda`, so it missed this install and wrongly claimed conda wasn't present.

The rewritten launcher does a real bounded search: for each common root it checks
the root and every sub-folder up to 2 levels deep for a directory that contains
`condabin\\conda.bat` + `Scripts\\activate.bat` (or `Scripts\\activate.bat` +
`python.exe`). This test encodes that exact algorithm and proves it:

  * finds a base nested one extra level deep and named with a space, and
  * does NOT false-positive on an ordinary virtualenv.

The Python here mirrors the batch :scan_root / :check_dir subroutines 1:1
(Windows "\\" -> os.path.join); it is a documentation + guard of the algorithm,
not an execution of the .bat itself (which needs Windows).
"""
import os


def _check_dir(d: str):
    """Mirror of :check_dir -- return d if it looks like a conda base, else None."""
    if os.path.isfile(os.path.join(d, "condabin", "conda.bat")) and \
       os.path.isfile(os.path.join(d, "Scripts", "activate.bat")):
        return d
    # Minimal installs: activate.bat + a python.exe sitting in the base dir.
    if os.path.isfile(os.path.join(d, "Scripts", "activate.bat")) and \
       os.path.isfile(os.path.join(d, "python.exe")):
        return d
    return None


def _scan_root(root: str):
    """Mirror of :scan_root -- check root, then sub-folders up to 2 levels deep."""
    if not os.path.isdir(root):
        return None
    hit = _check_dir(root)
    if hit:
        return hit
    try:
        level1 = [os.path.join(root, n) for n in os.listdir(root)]
    except OSError:
        return None
    for a in level1:
        if not os.path.isdir(a):
            continue
        hit = _check_dir(a)
        if hit:
            return hit
        try:
            level2 = [os.path.join(a, n) for n in os.listdir(a)]
        except OSError:
            continue
        for b in level2:
            if os.path.isdir(b):
                hit = _check_dir(b)
                if hit:
                    return hit
    return None


def _make_conda_base(path: str):
    os.makedirs(os.path.join(path, "condabin"), exist_ok=True)
    os.makedirs(os.path.join(path, "Scripts"), exist_ok=True)
    open(os.path.join(path, "condabin", "conda.bat"), "w").close()
    open(os.path.join(path, "Scripts", "activate.bat"), "w").close()
    open(os.path.join(path, "python.exe"), "w").close()


def test_finds_base_with_space_at_nonstandard_depth(tmp_path):
    """The exact reported case: base named 'New folder' (space) under anaconda3."""
    home = tmp_path / "fake_home"
    target = home / "anaconda3" / "New folder"   # depth 2 from home, with a space
    _make_conda_base(str(target))

    # Decoys that must be ignored.
    (home / "Documents" / "stuff").mkdir(parents=True)
    (home / "Downloads").mkdir()

    found = _scan_root(str(home))
    assert found is not None, "detection missed the conda base entirely"
    assert os.path.normpath(found) == os.path.normpath(str(target))
    assert "New folder" in found and " " in found  # space handled


def test_virtualenv_is_not_a_false_positive(tmp_path):
    """A plain venv (python.exe lives in Scripts, no condabin) must NOT match."""
    home = tmp_path / "fake_home"
    venv_scripts = home / "project" / "venv" / "Scripts"
    venv_scripts.mkdir(parents=True)
    open(venv_scripts / "activate.bat", "w").close()
    open(venv_scripts / "python.exe", "w").close()   # note: inside Scripts, not base

    assert _scan_root(str(home)) is None


def test_standard_layout_still_found(tmp_path):
    """The ordinary %USERPROFILE%\\anaconda3 layout still works."""
    home = tmp_path / "fake_home"
    target = home / "anaconda3"
    _make_conda_base(str(target))

    found = _scan_root(str(home))
    assert found is not None
    assert os.path.normpath(found) == os.path.normpath(str(target))


def test_launch_bat_has_search_and_override():
    """Guard the .bat itself keeps the robust pieces (search + manual override)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bat = os.path.join(here, "launch_app.bat")
    text = open(bat, encoding="utf-8", errors="replace").read()
    assert ":scan_root" in text and ":check_dir" in text      # real search
    assert ":scan_registry" in text                            # registry fallback
    assert 'set "CONDA_BASE=' in text                          # manual override hook
    assert "conda info --base" in text                         # actionable error
