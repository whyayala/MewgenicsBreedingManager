import sys
from pathlib import Path
from types import SimpleNamespace

_proj_root = Path(__file__).resolve().parents[1]
_src_dir = _proj_root / "src"
sys.path.insert(0, str(_src_dir))

from mewgenics.scoring.cat_stats import get_cat_stats, get_mutation_stat_bonuses


def _make_cat(**kwargs):
    defaults = {
        "base_stats": {"STR": 5, "DEX": 4, "CON": 6, "INT": 3, "SPD": 7, "CHA": 5, "LCK": 4},
        "total_stats": {"STR": 5, "DEX": 3, "CON": 6, "INT": 3, "SPD": 7, "CHA": 5, "LCK": 4},
        "visual_mutation_entries": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_get_cat_stats_base():
    cat = _make_cat()
    result = get_cat_stats(cat, use_current=False, add_mutation_stats=False)
    assert result == cat.base_stats


def test_get_cat_stats_current():
    cat = _make_cat()
    result = get_cat_stats(cat, use_current=True, add_mutation_stats=False)
    assert result == cat.total_stats


def test_get_cat_stats_current_fallback_to_base():
    cat = _make_cat(total_stats=None)
    result = get_cat_stats(cat, use_current=True, add_mutation_stats=False)
    assert result == cat.base_stats


def test_get_mutation_stat_bonuses_parses_detail():
    cat = _make_cat(visual_mutation_entries=[
        {"detail": "+2 CON, -1 DEX"},
        {"detail": "+1 LCK"},
        {"detail": ""},
        {"detail": "+1 Range"},  # non-stat, ignored
    ])
    bonuses = get_mutation_stat_bonuses(cat)
    assert bonuses == {"CON": 2, "DEX": -1, "LCK": 1}


def test_get_cat_stats_with_mutation_stats():
    cat = _make_cat(visual_mutation_entries=[
        {"detail": "+2 CON, -1 DEX"},
    ])
    result = get_cat_stats(cat, use_current=False, add_mutation_stats=True)
    assert result["CON"] == 8  # 6 + 2
    assert result["DEX"] == 3  # 4 - 1
    assert result["STR"] == 5  # unchanged


def test_get_mutation_stat_bonuses_empty():
    cat = _make_cat()
    bonuses = get_mutation_stat_bonuses(cat)
    assert bonuses == {}


# ── engine.py tests ──────────────────────────────────────────────────────────

from mewgenics.scoring.engine import (
    compute_breed_priority_score, ScoreResult, priority_tier,
    BREED_PRIORITY_WEIGHTS, ability_base, is_basic_trait,
)


def test_priority_tier_boundaries():
    assert priority_tier(10.0) == ("Keep", "#f0c060")
    assert priority_tier(4.0) == ("Good", "#1ec8a0")
    assert priority_tier(0.0) == ("Neutral", "#777777")
    assert priority_tier(-1.0) == ("Consider", "#e08030")
    assert priority_tier(-5.0) == ("Consider", "#e08030")
    assert priority_tier(-6.0) == ("Cull", "#e04040")


def test_ability_base_strips_tier2():
    assert ability_base("Vurp2") == "Vurp"
    assert ability_base("Vurp") == "Vurp"
    assert ability_base("A2") == "A"
    assert ability_base("2") == "2"  # single char, no strip


def test_is_basic_trait():
    assert is_basic_trait("BasicAttack") is True
    assert is_basic_trait("basicmove") is True
    assert is_basic_trait("Vurp") is False


def _scope_cat(name, stats=None, gender="M", room="Floor1_Large",
               abilities=None, passive_abilities=None, mutations=None,
               defects=None, disorders=None, aggression=0.5, libido=0.5,
               sexuality="straight", age=5, lovers=None, haters=None,
               children=None, status="In House"):
    s = stats or {"STR": 5, "DEX": 5, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5}
    return SimpleNamespace(
        name=name, base_stats=dict(s), total_stats=dict(s),
        gender=gender, room=room, status=status, age=age,
        abilities=abilities or [], passive_abilities=passive_abilities or [],
        mutations=mutations or [], defects=defects or [], disorders=disorders or [],
        aggression=aggression, libido=libido, sexuality=sexuality,
        lovers=lovers or [], haters=haters or [], children=children or [],
        visual_mutation_entries=[], db_key=id(name),
    )


def test_score_basic_cat_no_scope():
    """With empty scope, cat is sole owner of its 7-stats (not in scope set)."""
    cat = _scope_cat("Solo", stats={"STR": 7, "DEX": 7, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5})
    result = compute_breed_priority_score(
        cat, scope_cats=[], ma_ratings={},
        stat_names=["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"],
    )
    assert isinstance(result, ScoreResult)
    # Sole owner of 2 stats at 7: 2 * (5.0*2) = 20.0, plus 7-count: 2*2.0 = 4.0
    assert result.subtotals["stat_7"] == 20.0
    assert result.subtotals["stat_7_count"] == 4.0
    assert result.total == 24.0
    assert result.tier == "Keep"


def test_score_7_rarity_sole_owner():
    """Sole owner of a 7 in a stat gets 2x weight."""
    stat_names = ["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"]
    cat_a = _scope_cat("A", stats={"STR": 7, "DEX": 5, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5})
    cat_b = _scope_cat("B", stats={"STR": 5, "DEX": 5, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5})
    scope = [cat_a, cat_b]
    result = compute_breed_priority_score(
        cat_a, scope_cats=scope, ma_ratings={}, stat_names=stat_names,
    )
    # Sole owner: stat_7 * 2 = 5.0 * 2 = 10.0, plus 7-count: 2.0 * 1 = 2.0
    assert result.subtotals["stat_7"] == 10.0
    assert result.subtotals["stat_7_count"] == 2.0


def test_score_7_rarity_shared():
    """When two cats share a 7 in STR, the bonus is the base weight (not 2x)."""
    stat_names = ["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"]
    cat_a = _scope_cat("A", stats={"STR": 7, "DEX": 5, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5})
    cat_b = _scope_cat("B", stats={"STR": 7, "DEX": 5, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5})
    scope = [cat_a, cat_b]
    result = compute_breed_priority_score(
        cat_a, scope_cats=scope, ma_ratings={}, stat_names=stat_names,
    )
    assert result.subtotals["stat_7"] == 5.0  # base weight, 2 cats < threshold 7


def test_score_trait_rating_desirable():
    """A desirable trait on a sole owner gets 2x weight."""
    stat_names = ["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"]
    cat = _scope_cat("A", abilities=["Vurp"])
    scope = [cat]
    result = compute_breed_priority_score(
        cat, scope_cats=scope, ma_ratings={"Vurp": 1},
        stat_names=stat_names,
    )
    # Sole owner of desirable: 2 * trait_desirable(2.0) = 4.0
    assert result.subtotals["trait_desirable"] == 4.0


def test_score_gene_risk_safe():
    """Cat with zero risk against all scope partners gets zero_risk_bonus."""
    stat_names = ["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"]
    cat_a = _scope_cat("A", gender="M")
    cat_b = _scope_cat("B", gender="F")
    scope = [cat_a, cat_b]

    def fake_risk(a, b, memo=None):
        return 0.0

    def fake_can_breed(a, b):
        return (True, [])

    result = compute_breed_priority_score(
        cat_a, scope_cats=scope, ma_ratings={}, stat_names=stat_names,
        gene_risk_lookup=fake_risk, can_breed_fn=fake_can_breed,
    )
    assert result.subtotals["zero_risk_bonus"] == 2.0


def test_score_aggression_low():
    stat_names = ["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"]
    cat = _scope_cat("Calm", aggression=0.1)
    result = compute_breed_priority_score(cat, [], {}, stat_names)
    assert result.subtotals["low_aggression"] == 1.0


def test_score_age_penalty():
    stat_names = ["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"]
    cat = _scope_cat("Old", age=14)
    result = compute_breed_priority_score(cat, [], {}, stat_names)
    # age 14, threshold 10, over=4, mult=1+(4-1)//3=2, pts=2*-2.0=-4.0
    assert result.subtotals["age_penalty"] == -4.0


# ── helpers.py tests ─────────────────────────────────────────────────────────

from mewgenics.scoring.helpers import (
    build_relationship_maps, compute_seven_sets,
    compute_all_scores, compute_heatmap_norms,
)


def test_build_relationship_maps():
    cat_a = _scope_cat("A")
    cat_b = _scope_cat("B", haters=[cat_a])
    cat_c = _scope_cat("C", lovers=[cat_a])
    hated_by, loved_by = build_relationship_maps([cat_a, cat_b, cat_c])
    assert cat_b in hated_by.get(id(cat_a), [])  # cat_b hates cat_a → cat_a is in hated_by
    assert cat_c in loved_by.get(id(cat_a), [])   # cat_c loves cat_a


def test_compute_seven_sets():
    stat_names = ["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"]
    cat_a = _scope_cat("A", stats={"STR": 7, "DEX": 7, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5})
    cat_b = _scope_cat("B", stats={"STR": 7, "DEX": 5, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5})
    scope_set = {id(cat_a), id(cat_b)}
    seven_sets, scope_7_sets = compute_seven_sets(
        [cat_a, cat_b], scope_set, stat_names=stat_names,
    )
    assert seven_sets[id(cat_a)] == frozenset({"STR", "DEX"})
    assert seven_sets[id(cat_b)] == frozenset({"STR"})
    assert len(scope_7_sets) == 2


def test_compute_heatmap_norms_disabled():
    col_max, row_max, score_max = compute_heatmap_norms({}, [], False, "column")
    assert col_max == {}
    assert row_max == {}
    assert score_max == 1.0


# ── filters.py tests ─────────────────────────────────────────────────────────

from mewgenics.scoring.filters import FilterState, cat_passes_filter
from mewgenics.scoring.engine import ScoreResult


def _dummy_score(total=5.0, gene_risk=None):
    return ScoreResult(
        total=total, tier="Good", tier_color="#1ec8a0",
        breakdown=[], subtotals={}, scope_gene_risk=gene_risk,
    )


def test_filter_state_roundtrip():
    fs = FilterState()
    fs.age_active = True
    fs.age_value = 8
    fs.age_op = "Greater Than"
    d = fs.to_dict()
    fs2 = FilterState.from_dict(d)
    assert fs2.age_active is True
    assert fs2.age_value == 8
    assert fs2.age_op == "Greater Than"


def test_filter_passes_all_disabled():
    cat = _scope_cat("A", age=5)
    fs = FilterState()  # all disabled
    assert cat_passes_filter(cat, fs, _dummy_score(), set()) is True


def test_filter_age_less_than():
    fs = FilterState()
    fs.age_active = True
    fs.age_value = 10
    fs.age_op = "Less Than"
    assert cat_passes_filter(_scope_cat("Young", age=5), fs, _dummy_score(), set()) is True
    assert cat_passes_filter(_scope_cat("Old", age=15), fs, _dummy_score(), set()) is False


def test_filter_gender():
    fs = FilterState()
    fs.gender_active = True
    fs.gender_male = True
    fs.gender_female = False
    fs.gender_unknown = False
    assert cat_passes_filter(_scope_cat("M", gender="M"), fs, _dummy_score(), set()) is True
    assert cat_passes_filter(_scope_cat("F", gender="F"), fs, _dummy_score(), set()) is False


def test_filter_stat():
    fs = FilterState()
    fs.stat_filters["STR"]["active"] = True
    fs.stat_filters["STR"]["value"] = 7
    fs.stat_filters["STR"]["op"] = "Equals"
    cat7 = _scope_cat("Strong", stats={"STR": 7, "DEX": 5, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5})
    cat5 = _scope_cat("Weak", stats={"STR": 5, "DEX": 5, "CON": 5, "INT": 5, "SPD": 5, "CHA": 5, "LCK": 5})
    assert cat_passes_filter(cat7, fs, _dummy_score(), set()) is True
    assert cat_passes_filter(cat5, fs, _dummy_score(), set()) is False


def test_filter_score():
    fs = FilterState()
    fs.score_active = True
    fs.score_value = 5.0
    fs.score_op = "Greater Than"
    assert cat_passes_filter(_scope_cat("A"), fs, _dummy_score(total=8.0), set()) is True
    assert cat_passes_filter(_scope_cat("B"), fs, _dummy_score(total=3.0), set()) is False


def test_gay_male_and_female_weighted_separately():
    """Gay males father kittens with straight females normally, while gay
    females can only breed with a neutral cat — so penalising restricted
    breeders must not also demote gay males."""
    from mewgenics.scoring.engine import compute_breed_priority_score, BREED_PRIORITY_WEIGHTS

    weights = dict(BREED_PRIORITY_WEIGHTS)
    weights["gay_female_pref"] = -8.0
    weights["gay_pref"] = 0.0

    _scope_fields = dict(
        abilities=[], passive_abilities=[], disorders=[], mutations=[], defects=[],
        aggression=0.5, libido=0.5, age=3, lovers=[], haters=[],
        parent_a=None, parent_b=None, is_blacklisted=False, must_breed=False,
    )
    gay_male = _make_cat(db_key=1, gender="male", sexuality="gay", **_scope_fields)
    gay_female = _make_cat(db_key=2, gender="female", sexuality="gay", **_scope_fields)
    scope = [gay_male, gay_female]

    male_res = compute_breed_priority_score(
        gay_male, scope_cats=scope, ma_ratings={},
        stat_names=["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"], weights=weights)
    female_res = compute_breed_priority_score(
        gay_female, scope_cats=scope, ma_ratings={},
        stat_names=["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"], weights=weights)

    assert male_res.subtotals.get("gay_female_pref", 0.0) == 0.0
    assert female_res.subtotals.get("gay_female_pref") == -8.0
    assert female_res.total < male_res.total


def test_gay_pref_only_applies_to_males():
    from mewgenics.scoring.engine import compute_breed_priority_score, BREED_PRIORITY_WEIGHTS

    weights = dict(BREED_PRIORITY_WEIGHTS)
    weights["gay_pref"] = -5.0
    weights["gay_female_pref"] = 0.0

    _scope_fields = dict(
        abilities=[], passive_abilities=[], disorders=[], mutations=[], defects=[],
        aggression=0.5, libido=0.5, age=3, lovers=[], haters=[],
        parent_a=None, parent_b=None, is_blacklisted=False, must_breed=False,
    )
    gay_male = _make_cat(db_key=1, gender="male", sexuality="gay", **_scope_fields)
    gay_female = _make_cat(db_key=2, gender="female", sexuality="gay", **_scope_fields)
    scope = [gay_male, gay_female]

    male_res = compute_breed_priority_score(
        gay_male, scope_cats=scope, ma_ratings={},
        stat_names=["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"], weights=weights)
    female_res = compute_breed_priority_score(
        gay_female, scope_cats=scope, ma_ratings={},
        stat_names=["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"], weights=weights)

    assert male_res.subtotals.get("gay_pref") == -5.0
    assert female_res.subtotals.get("gay_pref", 0.0) == 0.0
    assert male_res.total < female_res.total
