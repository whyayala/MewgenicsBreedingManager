import os
import sys
from types import SimpleNamespace

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_proj_root, "src")
sys.path.insert(0, _src_dir)
sys.path.insert(0, _proj_root)

from breeding import (
    evaluate_pair,
    pair_projection,
    planner_inbreeding_penalty,
    planner_pair_allows_breeding,
    planner_pair_bias,
    score_pair,
    tracked_offspring,
)
from save_parser import STAT_NAMES


def _make_cat(
    db_key: int,
    *,
    gender: str,
    sexuality: str = "straight",
    parent_a=None,
    parent_b=None,
    generation: int = 0,
    aggression: float = 0.2,
    libido: float = 0.8,
    stat_seed: int = 6,
):
    class _HashableNamespace(SimpleNamespace):
        def __hash__(self):
            return hash(self.db_key)

    return _HashableNamespace(
        db_key=db_key,
        name=f"Cat{db_key}",
        gender=gender,
        sexuality=sexuality,
        gender_display=gender,
        status="In House",
        room="Floor1_Large",
        room_display="1st FL L",
        generation=generation,
        parent_a=parent_a,
        parent_b=parent_b,
        must_breed=False,
        disorders=[],
        defects=[],
        aggression=aggression,
        libido=libido,
        base_stats={stat: stat_seed for stat in STAT_NAMES},
        total_stats={stat: stat_seed for stat in STAT_NAMES},
        haters=[],
        lovers=[],
    )


def test_pair_projection_supports_dict_style_access():
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=4)
    cat_b = _make_cat(2, gender="female", sexuality="straight", stat_seed=8)

    projection = pair_projection(cat_a, cat_b, stimulation=50.0)

    assert projection["avg_expected"] == projection.avg_expected
    assert projection["sum_range"] == projection.sum_range
    assert len(projection["expected_stats"]) == len(STAT_NAMES)


def test_score_pair_rejects_same_sex_pairs_and_blocks_direct_family():
    """Same-sex pairs mate but produce no kitten, so they must never be
    scored as viable breeding pairs."""
    cat_a = _make_cat(1, gender="male", sexuality="bi")
    cat_b = _make_cat(2, gender="male", sexuality="bi")

    factors = score_pair(
        cat_a,
        cat_b,
        hater_key_map={1: set(), 2: set()},
        lover_key_map={1: set(), 2: set()},
        avoid_lovers=False,
    )
    assert not factors.compatible
    assert "no kitten" in factors.reason.lower()

    # Opposite-sex bi pair is still fine.
    cat_c = _make_cat(3, gender="female", sexuality="bi")
    opposite = score_pair(
        cat_a,
        cat_c,
        hater_key_map={1: set(), 3: set()},
        lover_key_map={1: set(), 3: set()},
        avoid_lovers=False,
    )
    assert opposite.compatible
    assert opposite.quality >= 0.0

    direct_family = score_pair(
        cat_a,
        cat_c,
        hater_key_map={1: set(), 3: set()},
        lover_key_map={1: set(), 3: set()},
        avoid_lovers=False,
        parent_key_map={1: set(), 3: {1}},
    )
    assert not direct_family.compatible
    assert "Direct family" in direct_family.reason


def test_evaluate_pair_allows_unrequited_love_when_avoid_lovers_is_on():
    cat_a = _make_cat(1, gender="male", sexuality="bi")
    cat_b = _make_cat(2, gender="female", sexuality="straight")

    ok, reason, risk, _compat = evaluate_pair(
        cat_a,
        cat_b,
        hater_key_map={1: set(), 2: set()},
        lover_key_map={1: {3}, 2: set()},
        avoid_lovers=True,
    )

    assert ok
    assert reason == ""
    assert risk > 0.0


def test_evaluate_pair_allows_mutual_lovers_when_avoid_lovers_is_on():
    cat_a = _make_cat(1, gender="male", sexuality="bi")
    cat_b = _make_cat(2, gender="female", sexuality="straight")

    ok, reason, risk, _compat = evaluate_pair(
        cat_a,
        cat_b,
        hater_key_map={1: set(), 2: set()},
        lover_key_map={1: {2}, 2: {1}},
        avoid_lovers=True,
    )

    assert ok
    assert reason == ""
    assert risk > 0.0


def test_evaluate_pair_uses_cache_accessor_for_risk():
    cat_a = _make_cat(1, gender="male", sexuality="bi")
    cat_b = _make_cat(2, gender="female", sexuality="straight")
    cache = SimpleNamespace(ready=True, get_risk=lambda a, b: 17.25)

    ok, reason, risk, _compat = evaluate_pair(
        cat_a,
        cat_b,
        hater_key_map={1: set(), 2: set()},
        lover_key_map={1: set(), 2: set()},
        avoid_lovers=False,
        cache=cache,
    )

    assert ok
    assert reason == ""
    assert risk == 17.25


def test_planner_pair_bias_prefers_opposite_or_unknown_gender_pairs():
    male = _make_cat(1, gender="male")
    female = _make_cat(2, gender="female")
    unknown = _make_cat(3, gender="?")
    gay_male_a = _make_cat(4, gender="male", sexuality="gay")
    gay_male_b = _make_cat(5, gender="male", sexuality="gay")

    assert planner_pair_allows_breeding(male, female)
    assert planner_pair_allows_breeding(male, unknown)
    # Same-sex pairs mate but produce no kitten — orientation doesn't change that.
    assert not planner_pair_allows_breeding(gay_male_a, gay_male_b)
    assert not planner_pair_allows_breeding(male, male)

    assert planner_pair_bias(male, female) > planner_pair_bias(male, male)
    assert planner_pair_bias(male, unknown) > planner_pair_bias(male, male)


def test_planner_inbreeding_penalty_increases_with_shared_ancestors():
    grandpa = _make_cat(10, gender="male")
    grandma = _make_cat(11, gender="female")
    parent_a = _make_cat(2, gender="female", parent_a=grandpa, parent_b=grandma)
    parent_b = _make_cat(3, gender="male", parent_a=grandpa, parent_b=grandma)
    cousin_a = _make_cat(4, gender="female", parent_a=parent_a, parent_b=_make_cat(5, gender="male"))
    cousin_b = _make_cat(6, gender="male", parent_a=parent_b, parent_b=_make_cat(7, gender="female"))
    unrelated = _make_cat(8, gender="female")
    unrelated_b = _make_cat(9, gender="male")

    assert planner_inbreeding_penalty(cousin_a, cousin_b) > planner_inbreeding_penalty(unrelated, unrelated_b)


def test_tracked_offspring_returns_shared_children_in_stable_order():
    child_one = _make_cat(20, gender="female")
    child_two = _make_cat(21, gender="male")
    child_three = _make_cat(22, gender="female")

    parent_a = _make_cat(1, gender="male")
    parent_b = _make_cat(2, gender="female")
    parent_a.children = [child_two, child_one, child_two, child_three]
    parent_b.children = [child_one, child_two]

    assert [cat.db_key for cat in tracked_offspring(parent_a, parent_b)] == [21, 20]


def test_score_pair_trait_bonus_uses_planner_traits():
    cat_a = _make_cat(1, gender="male", sexuality="bi")
    cat_b = _make_cat(2, gender="female", sexuality="straight")
    cat_a.abilities = ["Fireball"]
    cat_b.abilities = []
    cat_a.passive_abilities = []
    cat_b.passive_abilities = ["Library"]
    cat_a.mutations = ["Spotted"]
    cat_b.mutations = []
    cat_a.disorders = []
    cat_b.disorders = ["Glitch"]

    factors = score_pair(
        cat_a,
        cat_b,
        hater_key_map={1: set(), 2: set()},
        lover_key_map={1: set(), 2: set()},
        avoid_lovers=False,
        planner_traits=[
            {"category": "ability", "key": "fireball", "weight": 10},
            {"category": "passive", "key": "library", "weight": 10},
            {"category": "mutation", "key": "spotted", "weight": 10},
            {"category": "disorder", "key": "glitch", "weight": 10},
        ],
    )

    assert factors.trait_bonus == 20.0
    assert factors.quality > 0.0


def test_score_pair_trait_bonus_includes_birth_defects():
    cat_a = _make_cat(1, gender="male", sexuality="bi")
    cat_b = _make_cat(2, gender="female", sexuality="straight")
    cat_a.defects = ["no eyebrows"]
    cat_b.defects = []

    factors = score_pair(
        cat_a,
        cat_b,
        hater_key_map={1: set(), 2: set()},
        lover_key_map={1: set(), 2: set()},
        avoid_lovers=False,
        planner_traits=[
            {"category": "defect", "key": "no eyebrows", "weight": 10},
        ],
    )

    assert factors.trait_bonus == 5.0


def test_neutral_gender_ignores_both_orientations():
    """Wiki: "If either cat in a breeding pair is Neutral, the multiplier is
    1" — both sides, so a neutral cat breeds at full compatibility with a gay
    cat. That is a gay cat's only productive path, since same-sex pairs mate
    but produce no kitten."""
    from breeding import game_compatibility
    from save_parser import can_breed

    gay_female = _make_cat(1, gender="female", sexuality="gay")
    gay_male = _make_cat(2, gender="male", sexuality="gay")
    neutral = _make_cat(3, gender="?", sexuality="straight")
    straight_male = _make_cat(4, gender="male", sexuality="straight")

    # Neutral pairing is viable for gay cats of either gender.
    assert can_breed(gay_female, neutral)[0]
    assert can_breed(gay_male, neutral)[0]
    assert game_compatibility(gay_female, neutral) > 0.05
    assert game_compatibility(gay_male, neutral) > 0.05

    # A neutral partner must score at least as well as an equivalent
    # same-sex pairing, which produces no kitten at all.
    assert not can_breed(gay_male, straight_male)[0]
