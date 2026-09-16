"""Detailed Scoring ratings must survive a save that happens before cats load.

Reported as "I keep losing my chosen ratings on the detailed scoring page when
I start using a new version of the app". The version is incidental: the view
saves its ratings filtered against the currently-loaded roster, and on startup
that roster is empty, so any early save wrote both trait sections out blank.
"""
import json
import os
import sys

import pytest

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_proj_root, "src")
sys.path.insert(0, _src_dir)
sys.path.insert(0, _proj_root)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _view(ratings_path):
    from breed_priority import BreedPriorityView
    from save_parser import STAT_NAMES, ROOM_DISPLAY

    return BreedPriorityView(
        str(ratings_path), list(STAT_NAMES), dict(ROOM_DISPLAY),
        lambda x: x, lambda x: "",
    )


def _write(path, abilities=None, mutations=None):
    path.write_text(json.dumps({
        "abilities": abilities or {},
        "mutations": mutations or {},
    }), encoding="utf-8")


def _read(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    merged = {}
    merged.update(data.get("abilities", {}))
    merged.update(data.get("mutations", {}))
    return merged


def test_saving_with_no_cats_loaded_keeps_existing_ratings(qt_app, tmp_path):
    """The exact startup race: ratings load, something triggers a save before
    any cats arrive, and the file must still hold them afterwards."""
    ratings = tmp_path / "breed_priority.json"
    _write(ratings, abilities={"Fireball": 2, "Library": 1},
           mutations={"Spotted": -1})

    view = _view(ratings)
    assert view._cats == [], "precondition: no save is loaded yet"
    assert view._ma_ratings.get("Fireball") == 2, "ratings should load from disk"

    view._save_ratings()

    survived = _read(ratings)
    assert survived.get("Fireball") == 2
    assert survived.get("Library") == 1
    assert survived.get("Spotted") == -1


def test_ratings_for_traits_absent_from_this_save_are_not_dropped(qt_app, tmp_path):
    """The ratings file is shared by every save in APPDATA_CONFIG_DIR, so a
    trait missing from the open save belongs to another one — not to nobody."""
    from types import SimpleNamespace

    ratings = tmp_path / "breed_priority.json"
    _write(ratings, abilities={"Fireball": 2, "FromAnotherSave": -1})

    view = _view(ratings)
    view._cats = [SimpleNamespace(
        abilities=["Fireball"], passive_abilities=[], disorders=[],
        mutations=[], defects=[],
    )]
    view._save_ratings()

    survived = _read(ratings)
    assert survived.get("Fireball") == 2
    assert survived.get("FromAnotherSave") == -1, (
        "a rating for a trait outside the open save was deleted"
    )


def test_a_neutral_rating_still_persists(qt_app, tmp_path):
    """0 is an explicit 'no opinion', not an absence — clearing a rating must
    stick rather than reverting to whatever was there before."""
    ratings = tmp_path / "breed_priority.json"
    _write(ratings, abilities={"Fireball": 2})

    view = _view(ratings)
    view._ma_ratings["Fireball"] = 0
    view._save_ratings()

    assert _read(ratings).get("Fireball") == 0
