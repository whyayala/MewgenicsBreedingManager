import os
import sys
from types import SimpleNamespace

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_proj_root, "src")
sys.path.insert(0, _src_dir)
sys.path.insert(0, _proj_root)

import mewgenics.models.cat_table_model as cat_table_model
from mewgenics.models.cat_table_model import _source_summary
from mewgenics.utils.abilities import _trait_inheritance_probabilities


def _make_cat(*, name="Cat", abilities=None, passive_abilities=None, mutations=None):
    return SimpleNamespace(
        name=name,
        abilities=list(abilities or []),
        passive_abilities=list(passive_abilities or []),
        mutations=list(mutations or []),
    )


def test_trait_inheritance_probabilities_returns_all_categories():
    cat_a = _make_cat(
        name="A",
        abilities=["BasicShortRanged"],
        passive_abilities=["SkillShare+"],
        mutations=["Base Fur"],
    )
    cat_b = _make_cat(
        name="B",
        abilities=["WetHairball"],
        passive_abilities=["Library"],
        mutations=["Base Body"],
    )

    results = _trait_inheritance_probabilities(cat_a, cat_b, 50)

    categories = {category for _, category, _, _ in results}
    assert {"ability", "passive", "mutation"} <= categories
    ability_names = {display for display, category, _, _ in results if category == "ability"}
    # Basic attacks come with the class and are never inherited — they must
    # be excluded from the pool (they'd also dilute real abilities' odds).
    assert "BasicShortRanged" not in ability_names
    assert "WetHairball" in ability_names


def test_source_summary_marks_repaired_pedigree(monkeypatch):
    monkeypatch.setattr(
        cat_table_model,
        "_tr",
        lambda key, default=None, **kwargs: default or key,
    )

    cat = SimpleNamespace(
        name="Chevy",
        parent_a=None,
        parent_b=None,
        pedigree_was_repaired=True,
        status="Gone",
    )

    display, tooltip = _source_summary(cat)

    assert display == "Stray (pedigree repaired)"
    assert "pedigree cycle" in tooltip.lower()
