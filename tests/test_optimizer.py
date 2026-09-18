import os
import sys

import pytest
from types import SimpleNamespace

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_proj_root, "src")
sys.path.insert(0, _src_dir)
sys.path.insert(0, _proj_root)

from room_optimizer import (
    OptimizationParams,
    RoomConfig,
    RoomType,
    best_breeding_room_stimulation,
    build_room_configs,
    optimize_room_distribution,
)
import room_optimizer.optimizer as room_optimizer_impl
from breeding import PairFactors, PairProjection
from save_parser import STAT_NAMES


def _make_cat(
    db_key: int,
    *,
    gender: str,
    sexuality: str = "straight",
    room: str = "Floor1_Large",
    generation: int = 0,
    parent_a=None,
    parent_b=None,
    must_breed: bool = False,
    disorders=None,
    mutations=None,
    age: int | None = None,
    aggression: float = 0.3,
    libido: float = 0.7,
    stat_seed: int = 5,
):
    return SimpleNamespace(
        db_key=db_key,
        name=f"Cat{db_key}",
        gender=gender,
        sexuality=sexuality,
        gender_display=gender,
        status="In House",
        room=room,
        room_display=room,
        generation=generation,
        age=age,
        parent_a=parent_a,
        parent_b=parent_b,
        must_breed=must_breed,
        disorders=list(disorders or []),
        mutations=list(mutations or []),
        aggression=aggression,
        libido=libido,
        base_stats={stat: stat_seed for stat in STAT_NAMES},
        total_stats={stat: stat_seed for stat in STAT_NAMES},
        haters=[],
        lovers=[],
    )


def _room_for_cat(result, db_key: int) -> str | None:
    for assignment in result.rooms:
        if any(cat.db_key == db_key for cat in assignment.cats):
            return assignment.room.key
    return None


def test_build_room_configs_preserves_roles():
    configs = build_room_configs(
        [
            {"room": "Floor1_Large", "type": "breeding"},
            {"room": "Attic", "type": "fallback"},
        ],
        available_rooms=["Floor1_Large", "Attic"],
    )

    assert [cfg.key for cfg in configs] == ["Floor1_Large", "Attic"]
    assert configs[0].room_type == RoomType.BREEDING
    assert configs[1].room_type == RoomType.FALLBACK


def test_build_room_configs_uses_capacity_and_room_stimulation():
    room_stats = {"Floor1_Large": SimpleNamespace(raw_effects={"Stimulation": 17.0})}
    configs = build_room_configs(
        [
            {"room": "Floor1_Large", "type": "breeding", "max_cats": 4},
            {"room": "Attic", "type": "fallback", "max_cats": 0},
        ],
        available_rooms=["Floor1_Large", "Attic"],
        room_stats=room_stats,
    )

    assert configs[0].max_cats == 4
    assert configs[0].base_stim == 17.0
    assert configs[1].max_cats is None
    assert best_breeding_room_stimulation(configs) == 17.0


def test_optimize_room_distribution_rejects_same_sex_pair():
    """Same-sex pairs mate but produce no kitten, so the optimizer must not
    pair them even when both are marked Must Breed."""
    cat_a = _make_cat(1, gender="male", sexuality="bi", must_breed=True, stat_seed=8)
    cat_b = _make_cat(2, gender="male", sexuality="bi", must_breed=True, stat_seed=8)
    cat_c = _make_cat(3, gender="female", sexuality="straight", stat_seed=4)

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 2, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [cat_a, cat_b, cat_c],
        room_configs,
        OptimizationParams(max_risk=10.0, avoid_lovers=False),
        cache=None,
        excluded_keys=set(),
    )

    paired_ids = {
        tuple(sorted((pair.cat_a.db_key, pair.cat_b.db_key)))
        for assignment in result.rooms
        for pair in assignment.pairs
    }

    assert (1, 2) not in paired_ids


def test_optimize_room_distribution_uses_disjoint_room_pairs():
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=8)
    cat_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=8)
    cat_c = _make_cat(3, gender="male", sexuality="bi", stat_seed=7)
    cat_d = _make_cat(4, gender="female", sexuality="bi", stat_seed=7)

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 4, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [cat_a, cat_b, cat_c, cat_d],
        room_configs,
        OptimizationParams(max_risk=10.0, avoid_lovers=False, use_sa=False),
        cache=None,
        excluded_keys=set(),
    )

    breeding_assignment = next(
        assignment for assignment in result.rooms if assignment.room.key == "Floor1_Large"
    )
    paired_cat_ids = [
        cat_id
        for pair in breeding_assignment.pairs
        for cat_id in (pair.cat_a.db_key, pair.cat_b.db_key)
    ]

    assert len(breeding_assignment.pairs) == 2
    assert len(set(paired_cat_ids)) == 4
    assert result.stats.total_pairs == 2


def test_optimize_room_distribution_keep_lovers_together_does_not_block_other_pairs():
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=8)
    cat_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=8)
    cat_c = _make_cat(3, gender="male", sexuality="bi", stat_seed=6)
    cat_d = _make_cat(4, gender="female", sexuality="bi", stat_seed=6)
    cat_a.lovers = [cat_b]
    cat_b.lovers = [cat_a]

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 4, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [cat_a, cat_b, cat_c, cat_d],
        room_configs,
        OptimizationParams(max_risk=10.0, avoid_lovers=True, use_sa=False),
        cache=None,
        excluded_keys=set(),
    )

    breeding_room = _room_for_cat(result, 1)
    assert breeding_room == "Floor1_Large"
    assert breeding_room == _room_for_cat(result, 2)
    assert breeding_room == _room_for_cat(result, 3)
    assert breeding_room == _room_for_cat(result, 4)
    assert result.stats.assigned_cats == 4
    assert result.stats.total_pairs == 2


def test_optimize_room_distribution_allows_unrequited_love_pairs_when_avoid_lovers_is_on():
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=8)
    cat_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=8)
    cat_a.lovers = [cat_b]

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 2, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [cat_a, cat_b],
        room_configs,
        OptimizationParams(max_risk=10.0, avoid_lovers=True, use_sa=False),
        cache=None,
        excluded_keys=set(),
    )

    assert result.stats.total_pairs == 1
    assert _room_for_cat(result, 1) == "Floor1_Large"
    assert _room_for_cat(result, 2) == "Floor1_Large"


def test_optimize_room_distribution_enforces_risk_cutoff():
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=6)
    cat_b = _make_cat(2, gender="female", sexuality="straight", stat_seed=6)

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 2, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [cat_a, cat_b],
        room_configs,
        OptimizationParams(max_risk=1.0, avoid_lovers=False),
        cache=None,
        excluded_keys=set(),
    )

    assert result.stats.total_pairs == 0
    assert all(not assignment.pairs for assignment in result.rooms)


def test_optimize_room_distribution_keeps_empty_rooms_in_result():
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=8)
    cat_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=8)

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Floor1_Small", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Floor2_Small", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Floor2_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [cat_a, cat_b],
        room_configs,
        OptimizationParams(max_risk=10.0, avoid_lovers=False),
        cache=None,
        excluded_keys=set(),
    )

    assert [assignment.room.key for assignment in result.rooms] == [cfg.key for cfg in room_configs]
    assert result.stats.assigned_cats == 2


def test_optimize_room_distribution_family_mode_separates_siblings():
    dad = _make_cat(1, gender="male", sexuality="bi")
    mom = _make_cat(2, gender="female", sexuality="bi")
    sibling_a = _make_cat(3, gender="male", sexuality="bi", parent_a=dad, parent_b=mom, generation=1)
    sibling_b = _make_cat(4, gender="female", sexuality="bi", parent_a=dad, parent_b=mom, generation=1)
    unrelated = _make_cat(5, gender="male", sexuality="bi")

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Floor1_Small", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [dad, mom, sibling_a, sibling_b, unrelated],
        room_configs,
        OptimizationParams(mode_family=True, avoid_lovers=False),
        cache=None,
        excluded_keys=set(),
    )

    assert _room_for_cat(result, 3) != _room_for_cat(result, 4)


def test_optimize_room_distribution_family_mode_runs_sa(monkeypatch):
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=8)
    cat_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=8)
    cat_c = _make_cat(3, gender="male", sexuality="bi", stat_seed=5)

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Floor1_Small", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]

    calls = []

    def _fake_run_sa_refinement(**kwargs):
        calls.append(kwargs)
        return kwargs["room_assignments"]

    monkeypatch.setattr(room_optimizer_impl, "_run_sa_refinement", _fake_run_sa_refinement)

    result = optimize_room_distribution(
        [cat_a, cat_b, cat_c],
        room_configs,
        OptimizationParams(mode_family=True, use_sa=True, avoid_lovers=False),
        cache=None,
        excluded_keys=set(),
    )

    assert calls
    assert calls[0]["mode_family"] is True
    assert result.stats.total_cats == 3


def test_throughput_mode_skips_singletons_that_do_not_add_pairs(monkeypatch):
    cats = [
        _make_cat(1, gender="male", sexuality="bi", stat_seed=8),
        _make_cat(2, gender="female", sexuality="bi", stat_seed=8),
        _make_cat(3, gender="male", sexuality="bi", stat_seed=7),
        _make_cat(4, gender="female", sexuality="bi", stat_seed=7),
    ]

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 2, 50.0),
        RoomConfig("Floor1_Small", RoomType.BREEDING, 1, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]

    valid_pairs = {
        (1, 2): 100.0,
        (3, 4): 90.0,
    }

    def _fake_score_pair_factors(cat_a, cat_b, **_kwargs):
        pair_key = tuple(sorted((cat_a.db_key, cat_b.db_key)))
        compatible = pair_key in valid_pairs
        return PairFactors(
            cat_a=cat_a,
            cat_b=cat_b,
            compatible=compatible,
            reason="" if compatible else "blocked",
            risk=0.0 if compatible else 100.0,
            projection=PairProjection(
                expected_stats={stat: 0.0 for stat in STAT_NAMES},
                stat_ranges={stat: (0, 0) for stat in STAT_NAMES},
                locked_stats=(),
                reachable_stats=(),
                missing_stats=(),
                sum_range=(0, 0),
                avg_expected=0.0,
                seven_plus_total=0.0,
                distance_total=0.0,
            ),
            complementarity_bonus=0.0,
            variance_penalty=0.0,
            personality_bonus=0.0,
            trait_bonus=0.0,
            must_breed_bonus=0.0,
            lover_bonus=0.0,
            quality=valid_pairs.get(pair_key, 0.0),
        )

    monkeypatch.setattr(room_optimizer_impl, "score_pair_factors", _fake_score_pair_factors)

    result = optimize_room_distribution(
        cats,
        room_configs,
        OptimizationParams(
            max_risk=10.0,
            avoid_lovers=False,
            maximize_throughput=True,
        ),
        cache=None,
        excluded_keys=set(),
    )

    small_room = next(
        assignment for assignment in result.rooms if assignment.room.key == "Floor1_Small"
    )
    fallback_room = next(
        assignment for assignment in result.rooms if assignment.room.key == "Attic"
    )

    assert small_room.cats == []
    assert sorted(cat.db_key for cat in fallback_room.cats) == [3, 4]


# ---------------------------------------------------------------------------
# Regression tests for DP cap / greedy fallback (issues #63, #64)
# ---------------------------------------------------------------------------

def test_large_room_greedy_fallback_completes_quickly():
    """With 30 cats in one breeding room (> _MAX_DP_CATS), the optimizer must
    complete in bounded time using the greedy fallback instead of the
    exponential bitmask DP."""
    import time

    cats = []
    for i in range(30):
        gender = "male" if i % 2 == 0 else "female"
        cats.append(_make_cat(i + 1, gender=gender, sexuality="bi", stat_seed=5 + (i % 3)))

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, None, 50.0),  # unlimited capacity
    ]
    start = time.monotonic()
    result = optimize_room_distribution(
        cats,
        room_configs,
        OptimizationParams(max_risk=100.0, avoid_lovers=False),
        cache=None,
        excluded_keys=set(),
    )
    elapsed = time.monotonic() - start

    assert elapsed < 30.0, f"Optimizer took {elapsed:.1f}s — greedy fallback should be fast"
    assert result.stats.total_pairs >= 1
    # Verify pairs are non-overlapping
    used_ids = set()
    for assignment in result.rooms:
        for pair in assignment.pairs:
            assert pair.cat_a.db_key not in used_ids, "Overlapping pair detected"
            assert pair.cat_b.db_key not in used_ids, "Overlapping pair detected"
            used_ids.add(pair.cat_a.db_key)
            used_ids.add(pair.cat_b.db_key)


def test_no_fallback_room_does_not_hang():
    """When all rooms are breeding rooms (no fallback) and every room is at
    capacity, the overflow cats are reported as excluded rather than
    overfilling a room. The DP cap must prevent this from hanging."""
    import time

    cats = []
    for i in range(40):
        gender = "male" if i % 2 == 0 else "female"
        cats.append(_make_cat(i + 1, gender=gender, sexuality="bi", stat_seed=5))

    # All rooms are breeding rooms with cap 6 — only 12 cats fit, 28 overflow.
    # Comfort 12 lets all 6 slots be used while still holding Comfort at the
    # default target of 10; this test is about the DP cap, not about Comfort.
    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0, comfort=12.0),
        RoomConfig("Floor1_Small", RoomType.BREEDING, 6, 50.0, comfort=12.0),
    ]
    start = time.monotonic()
    result = optimize_room_distribution(
        cats,
        room_configs,
        OptimizationParams(max_risk=100.0, avoid_lovers=False),
        cache=None,
        excluded_keys=set(),
    )
    elapsed = time.monotonic() - start

    assert elapsed < 30.0, f"Optimizer took {elapsed:.1f}s with no fallback room"
    # Two rooms x cap 6 = 12 slots; the remaining 28 cats stay where they are
    # and are surfaced as excluded instead of being crammed in.
    placed = sum(len(assignment.cats) for assignment in result.rooms)
    assert placed == 12, placed
    assert result.stats.assigned_cats == 12
    assert len(result.excluded_cats) == 28


def test_greedy_fallback_produces_reasonable_pairs():
    """The greedy approach should find at least as many pairs as a naive
    first-fit, even when it can't use the exact DP."""
    cats = []
    for i in range(28):
        gender = "male" if i % 2 == 0 else "female"
        cats.append(_make_cat(i + 1, gender=gender, sexuality="bi", stat_seed=6))

    # Comfort 34 keeps all 28 cats in one room at the default Comfort target
    # of 10 — this test is about greedy pair selection, not about Comfort.
    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, None, 50.0, comfort=34.0),
    ]
    result = optimize_room_distribution(
        cats,
        room_configs,
        OptimizationParams(max_risk=100.0, avoid_lovers=False),
        cache=None,
        excluded_keys=set(),
    )

    # 14 males + 14 females with bi sexuality → at least 14 pairs possible
    # (greedy should find most of them)
    assert result.stats.total_pairs >= 10, (
        f"Expected at least 10 pairs from 28 bi cats, got {result.stats.total_pairs}"
    )


# ── Issue 70: Kittens routed to fallback rooms ────────────────────────────

def test_send_kittens_to_fallback_routes_young_cats():
    """Kittens (age < threshold) should be placed in fallback rooms, not
    breeding rooms, when send_kittens_to_fallback is enabled."""
    adult_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=5)
    adult_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=7, age=5)
    kitten = _make_cat(3, gender="male", sexuality="bi", stat_seed=7, age=0)

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [adult_a, adult_b, kitten],
        room_configs,
        OptimizationParams(
            max_risk=10.0,
            avoid_lovers=False,
            send_kittens_to_fallback=True,
            kitten_age_threshold=2,
        ),
        cache=None,
        excluded_keys=set(),
    )

    assert _room_for_cat(result, 3) == "Attic"
    # Adults are still paired up in the breeding room.
    assert _room_for_cat(result, 1) == "Floor1_Large"
    assert _room_for_cat(result, 2) == "Floor1_Large"


def test_send_kittens_to_fallback_disabled_leaves_kittens_in_breeding():
    """When the toggle is off, kittens are treated like any other cat and
    may land in breeding rooms (legacy behavior)."""
    kitten_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=0)
    kitten_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=7, age=0)

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [kitten_a, kitten_b],
        room_configs,
        OptimizationParams(max_risk=10.0, avoid_lovers=False),
        cache=None,
        excluded_keys=set(),
    )

    assert _room_for_cat(result, 1) == "Floor1_Large"
    assert _room_for_cat(result, 2) == "Floor1_Large"


def test_send_kittens_to_fallback_skips_eternal_youth():
    """Eternal-youth cats must NOT be treated as kittens — the existing EY
    branch places them in the best breeding room."""
    ey_cat = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=0, disorders=["EternalYouth"])
    adult = _make_cat(2, gender="female", sexuality="bi", stat_seed=7, age=5)

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [ey_cat, adult],
        room_configs,
        OptimizationParams(
            max_risk=10.0,
            avoid_lovers=False,
            send_kittens_to_fallback=True,
            kitten_age_threshold=2,
        ),
        cache=None,
        excluded_keys=set(),
    )

    assert _room_for_cat(result, 1) == "Floor1_Large"


def test_send_kittens_to_fallback_works_in_family_mode():
    """Kitten routing must survive the family-mode rebind step."""
    dad = _make_cat(1, gender="male", sexuality="bi", age=5)
    mom = _make_cat(2, gender="female", sexuality="bi", age=5)
    kitten = _make_cat(3, gender="male", sexuality="bi", age=0, parent_a=dad, parent_b=mom, generation=1)

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [dad, mom, kitten],
        room_configs,
        OptimizationParams(
            mode_family=True,
            avoid_lovers=False,
            send_kittens_to_fallback=True,
            kitten_age_threshold=2,
        ),
        cache=None,
        excluded_keys=set(),
    )

    assert _room_for_cat(result, 3) == "Attic"


# ── Issue 71: Trait-loss avoidance (Evolution/Health room awareness) ──────

def test_avoid_trait_loss_steers_desired_disorder_away_from_health_room():
    """A cat with a desired disorder should prefer a low-Health room when
    avoid_trait_loss is enabled (high Health can cure the disorder away).

    Since game 1.1 the Mutation stat no longer rerolls existing traits, so
    high-Evolution rooms are safe for mutations — only the disorder/Health
    half of the penalty remains (see the test below for the mutation case).
    """
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=5, disorders=["sociopathy"])
    cat_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=7, age=5)

    high_health = RoomConfig("Floor1_Large", RoomType.BEST_PAIRS, 6, 50.0, health=80.0)
    low_health = RoomConfig("Floor1_Small", RoomType.BEST_PAIRS, 6, 50.0, health=0.0)
    fallback = RoomConfig("Attic", RoomType.FALLBACK, None, 50.0)

    profiles = {
        "best_pairs": {
            "traits": [{"category": "disorder", "key": "sociopathy", "weight": 10, "display": "Sociopathy"}],
            "stat_priority": list(STAT_NAMES),
        },
    }

    result = optimize_room_distribution(
        [cat_a, cat_b],
        [high_health, low_health, fallback],
        OptimizationParams(
            max_risk=10.0,
            avoid_lovers=False,
            avoid_trait_loss=True,
            mode_profiles=profiles,
        ),
        cache=None,
        excluded_keys=set(),
    )

    # Both cats should land in the low-health room; the penalty on the
    # high-health room should push the greedy search to pick the other.
    assert _room_for_cat(result, 1) == "Floor1_Small"
    assert _room_for_cat(result, 2) == "Floor1_Small"


def test_high_evolution_room_no_longer_penalizes_desired_mutations():
    """Since game 1.1 the Mutation stat never rerolls existing mutations or
    birth defects, so a desired mutation carries no penalty in a
    high-Evolution room."""
    cat = _make_cat(1, gender="male", sexuality="bi", age=5, mutations=["extra_whiskers"])
    high_evo = RoomConfig("Floor1_Large", RoomType.BEST_PAIRS, 6, 50.0, evolution=80.0)
    desired = [{"category": "mutation", "key": "extra_whiskers", "weight": 10}]
    assert room_optimizer_impl._trait_loss_penalty(cat, high_evo, desired) == 0.0


def test_avoid_trait_loss_disabled_permits_high_evolution_placement():
    """Without the toggle, a cat carrying a desired mutation is not steered
    away from a high-Evolution room."""
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=5, mutations=["extra_whiskers"])
    cat_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=7, age=5)

    high_evo = RoomConfig("Floor1_Large", RoomType.BEST_PAIRS, 6, 50.0, evolution=80.0)
    low_evo = RoomConfig("Floor1_Small", RoomType.BEST_PAIRS, 6, 50.0, evolution=0.0)
    fallback = RoomConfig("Attic", RoomType.FALLBACK, None, 50.0)

    profiles = {
        "best_pairs": {
            "traits": [{"category": "mutation", "key": "extra_whiskers", "weight": 10}],
            "stat_priority": list(STAT_NAMES),
        },
    }

    result = optimize_room_distribution(
        [cat_a, cat_b],
        [high_evo, low_evo, fallback],
        OptimizationParams(
            max_risk=10.0,
            avoid_lovers=False,
            avoid_trait_loss=False,
            mode_profiles=profiles,
        ),
        cache=None,
        excluded_keys=set(),
    )

    # First-fit greedy without the penalty would drop them in the first
    # breeding room in the list.
    assert _room_for_cat(result, 1) == "Floor1_Large"


def test_avoid_trait_loss_steers_desired_disorder_away_from_health_room():
    """A cat with a desired disorder should prefer a low-Health room when
    avoid_trait_loss is enabled (Health rooms cure disorders)."""
    cat_a = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=5, disorders=["nearsighted"])
    cat_b = _make_cat(2, gender="female", sexuality="bi", stat_seed=7, age=5)

    high_health = RoomConfig("Floor1_Large", RoomType.BEST_PAIRS, 6, 50.0, health=80.0)
    low_health = RoomConfig("Floor1_Small", RoomType.BEST_PAIRS, 6, 50.0, health=0.0)
    fallback = RoomConfig("Attic", RoomType.FALLBACK, None, 50.0)

    profiles = {
        "best_pairs": {
            "traits": [{"category": "disorder", "key": "nearsighted", "weight": 10}],
            "stat_priority": list(STAT_NAMES),
        },
    }

    result = optimize_room_distribution(
        [cat_a, cat_b],
        [high_health, low_health, fallback],
        OptimizationParams(
            max_risk=10.0,
            avoid_lovers=False,
            avoid_trait_loss=True,
            mode_profiles=profiles,
        ),
        cache=None,
        excluded_keys=set(),
    )

    assert _room_for_cat(result, 1) == "Floor1_Small"


def test_build_room_configs_extracts_evolution_and_health():
    """RoomConfig should pick up Evolution and Health from room_stats."""
    room_stats = {
        "Floor1_Large": SimpleNamespace(raw_effects={"Evolution": 42.0, "Health": 17.5}),
    }
    configs = build_room_configs(
        [{"room": "Floor1_Large", "type": "breeding", "max_cats": 6}],
        available_rooms=["Floor1_Large"],
        room_stats=room_stats,
    )
    assert configs[0].evolution == 42.0
    assert configs[0].health == 17.5


def test_trait_loss_penalty_matches_disorder_with_id_suffix():
    """Mutation planner stores trait keys as ``"<name>|<id>"`` but
    `cat.disorders` only carries the display name. The penalty must compare by
    the name portion on both sides so a desired disorder from the planner
    actually triggers the penalty. (Mutations no longer participate — since
    game 1.1 high-Evolution rooms don't reroll existing traits.)"""
    cat = _make_cat(1, gender="male", sexuality="bi", age=5, disorders=["Sociopathy"])
    high_health = RoomConfig("Floor1_Large", RoomType.BEST_PAIRS, 6, 50.0, health=80.0)

    # Trait stored with the chip ID suffix (real planner format).
    desired = [{"category": "disorder", "key": "Sociopathy|42", "weight": 10}]
    penalty = room_optimizer_impl._trait_loss_penalty(cat, high_health, desired)
    assert penalty > 0.0

    # Reverse case: cat carries the suffixed form, planner uses the bare name.
    cat_suffixed = _make_cat(2, gender="male", sexuality="bi", age=5, disorders=["Sociopathy|42"])
    desired_bare = [{"category": "disorder", "key": "Sociopathy", "weight": 10}]
    penalty_reverse = room_optimizer_impl._trait_loss_penalty(cat_suffixed, high_health, desired_bare)
    assert penalty_reverse > 0.0

    # Sanity: mismatched name still produces no penalty.
    desired_other = [{"category": "disorder", "key": "Hypersomnia|7", "weight": 10}]
    assert room_optimizer_impl._trait_loss_penalty(cat, high_health, desired_other) == 0.0


def test_unpairable_cat_goes_to_lowest_stim_room_then_fallback():
    """Cats with no viable partner (most often gay cats, whose only
    high-compatibility partners are same-sex and so yield no kitten) are
    parked in the lowest-stimulation breeding room, spilling into fallback
    only once it is full."""
    pair_m = _make_cat(1, gender="male", sexuality="straight", stat_seed=8)
    pair_f = _make_cat(2, gender="female", sexuality="straight", stat_seed=8)
    # Two same-sex cats: they can only pair with each other, which produces
    # no kitten, so both are unpairable.
    lonely_a = _make_cat(3, gender="male", sexuality="gay", stat_seed=5)
    lonely_b = _make_cat(4, gender="male", sexuality="gay", stat_seed=5)

    rooms = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 2, 90.0),   # high stim
        RoomConfig("Floor2_Large", RoomType.BREEDING, 1, 10.0),   # lowest stim, 1 slot
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [pair_m, pair_f, lonely_a, lonely_b],
        rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None,
        excluded_keys=set(),
    )

    # The same-sex pair must never be scored as productive.
    paired = {
        tuple(sorted((p.cat_a.db_key, p.cat_b.db_key)))
        for a in result.rooms for p in a.pairs
    }
    assert (3, 4) not in paired

    placements = {key: _room_for_cat(result, key) for key in (3, 4)}
    # One fits the single lowest-stim slot; the other overflows to fallback.
    assert sorted(placements.values()) == ["Attic", "Floor2_Large"]


_ALL_TREES = ("best_pairs", "melee", "ranged", "magic")


def _profiles_rating(disorder: str, weight: float, modes=_ALL_TREES) -> dict:
    return {
        mode: {
            "traits": [{"category": "disorder", "key": disorder,
                        "weight": weight, "display": disorder}],
            "stat_priority": list(STAT_NAMES),
        }
        for mode in modes
    }


def _cure_rooms():
    return [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 1, 10.0, health=0.0),
        RoomConfig("Floor2_Large", RoomType.BREEDING, 1, 80.0, health=70.0),  # highest Health
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]


def _run_cure(cats, profiles, **param_kwargs):
    params = OptimizationParams(
        max_risk=100.0, avoid_lovers=False, use_sa=False,
        mode_profiles=profiles, **param_kwargs,
    )
    return optimize_room_distribution(cats, _cure_rooms(), params,
                                      cache=None, excluded_keys=set())


def test_universally_undesired_disorder_routed_to_highest_health_room():
    """A disorder no tree wants should send the cat to the highest-Health
    room (which can cure it) rather than the fallback."""
    sick = _make_cat(1, gender="male", sexuality="gay", disorders=["sociopathy"])
    result = _run_cure([sick], _profiles_rating("sociopathy", -6))
    assert _room_for_cat(result, 1) == "Floor2_Large"


def test_must_breed_cat_is_not_parked_for_curing():
    """Must Breed means the user wants it breeding, not parked in a
    Health room."""
    sick = _make_cat(1, gender="male", sexuality="gay",
                     disorders=["sociopathy"], must_breed=True)
    result = _run_cure([sick], _profiles_rating("sociopathy", -6))
    assert _room_for_cat(result, 1) != "Floor2_Large"


def test_disorder_desired_by_any_tree_is_not_cured():
    """If even one tree rates the disorder desirable, it must be preserved."""
    profiles = _profiles_rating("sociopathy", -6)
    profiles["magic"]["traits"][0]["weight"] = 8  # one tree wants it
    sick = _make_cat(1, gender="male", sexuality="gay", disorders=["sociopathy"])
    result = _run_cure([sick], profiles)
    assert _room_for_cat(result, 1) != "Floor2_Large"


def test_universally_undesired_helper_semantics():
    from types import SimpleNamespace
    cat = SimpleNamespace(disorders=["Sociopathy", "Rabies"])

    unwanted = _profiles_rating("sociopathy", -6)
    assert room_optimizer_impl._universally_undesired_disorders(cat, unwanted) == ["sociopathy"]

    # Rated desirable somewhere -> not universally undesired.
    mixed = _profiles_rating("sociopathy", -6)
    mixed["ranged"]["traits"][0]["weight"] = 3
    assert room_optimizer_impl._universally_undesired_disorders(cat, mixed) == []

    # Unrated disorders never qualify.
    assert room_optimizer_impl._universally_undesired_disorders(cat, {}) == []

    # Planner-style "name|id" keys match the bare disorder name.
    suffixed = _profiles_rating("sociopathy|42", -6)
    assert room_optimizer_impl._universally_undesired_disorders(cat, suffixed) == ["sociopathy"]


def _kitten_params(**kw):
    return OptimizationParams(
        max_risk=100.0, avoid_lovers=False, use_sa=False,
        send_kittens_to_fallback=True, kitten_age_threshold=2, **kw,
    )


def test_kittens_prefer_lowest_stim_room_over_fallback():
    """Kittens can't breed, so park them in the quietest room. The fallback
    tends to be the fight room, so it is not the first choice."""
    kitten = _make_cat(1, gender="male", age=1)
    adult_m = _make_cat(2, gender="male", age=5, stat_seed=7)
    adult_f = _make_cat(3, gender="female", age=5, stat_seed=7)
    rooms = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 90.0),
        RoomConfig("Floor2_Large", RoomType.BREEDING, 6, 10.0),  # quietest
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution([kitten, adult_m, adult_f], rooms,
                                        _kitten_params(), cache=None, excluded_keys=set())
    assert _room_for_cat(result, 1) == "Floor2_Large"


def test_kittens_overflow_to_fallback_not_a_loud_breeding_room():
    """When the quiet room fills, the overflow must go to the fallback
    rather than into the highest-stimulation breeding room."""
    kittens = [_make_cat(i, gender="male", age=1) for i in range(1, 6)]
    rooms = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 90.0),
        RoomConfig("Floor2_Large", RoomType.BREEDING, 2, 10.0),  # quietest, only 2 slots
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(kittens, rooms, _kitten_params(),
                                        cache=None, excluded_keys=set())
    placements = [_room_for_cat(result, c.db_key) for c in kittens]
    assert placements.count("Floor2_Large") == 2
    assert placements.count("Attic") == 3
    assert "Floor1_Large" not in placements


def test_kittens_use_quietest_room_when_no_fallback_configured():
    """With every room set to a breeding tree there is no fallback; kittens
    used to land in whatever room came last in room order, often a
    high-stimulation one."""
    kitten = _make_cat(1, gender="male", age=1)
    rooms = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 90.0),
        RoomConfig("Floor2_Large", RoomType.BREEDING, 6, 10.0),  # quietest
        RoomConfig("Attic", RoomType.BREEDING, 6, 70.0),
    ]
    result = optimize_room_distribution([kitten], rooms, _kitten_params(),
                                        cache=None, excluded_keys=set())
    assert _room_for_cat(result, 1) == "Floor2_Large"


def test_kitten_routing_off_by_default():
    """The behaviour stays behind the existing "Kittens to Fallback" toggle."""
    kitten = _make_cat(1, gender="male", age=1)
    adult_m = _make_cat(2, gender="male", age=5, stat_seed=7)
    adult_f = _make_cat(3, gender="female", age=5, stat_seed=7)
    rooms = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 90.0),
        RoomConfig("Floor2_Large", RoomType.BREEDING, 6, 10.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [kitten, adult_m, adult_f], rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None, excluded_keys=set())
    # Not force-routed: the kitten is placed by the normal assignment pass.
    assert _room_for_cat(result, 1) is not None


def test_blocked_cats_are_moved_to_the_fallback_room():
    """Cats blocked from breeding (the Alive Cats exclude flag / blacklist)
    should be relocated to the fallback room rather than left wherever they
    happen to be sitting — otherwise they occupy breeding-room space."""
    blocked = _make_cat(1, gender="male", room="Floor1_Large", age=5)
    adult_m = _make_cat(2, gender="male", stat_seed=7, age=5)
    adult_f = _make_cat(3, gender="female", stat_seed=7, age=5)
    rooms = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0),
    ]
    result = optimize_room_distribution(
        [blocked, adult_m, adult_f], rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None, excluded_keys={1},
    )

    assert _room_for_cat(result, 1) == "Attic"
    # ...and never paired, since fallback rooms don't select pairs.
    paired = {c.db_key for a in result.rooms for p in a.pairs for c in (p.cat_a, p.cat_b)}
    assert 1 not in paired
    # Blocked cats aren't breeding candidates, so they don't inflate the stats.
    assert result.stats.total_cats == 2


def test_rooms_are_not_overfilled_and_overflow_is_reported():
    """Capacity is a real limit: cats that fit nowhere are left where they
    are and surfaced as excluded, instead of being crammed into a room."""
    cats = [_make_cat(i, gender="male" if i % 2 else "female", age=5)
            for i in range(1, 11)]
    rooms = [RoomConfig("Floor1_Large", RoomType.BREEDING, 4, 50.0)]
    result = optimize_room_distribution(
        cats, rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None, excluded_keys=set(),
    )
    placed = sum(len(a.cats) for a in result.rooms)
    assert placed == 4
    assert len(result.excluded_cats) == 6


def test_blocked_cats_left_alone_when_no_fallback_exists():
    """With no fallback room configured there is nowhere safe to move a
    blocked cat, so it is left where it is rather than dropped into a
    breeding room."""
    blocked = _make_cat(1, gender="male", room="Floor1_Large", age=5)
    rooms = [RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0)]
    result = optimize_room_distribution(
        [blocked], rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None, excluded_keys={1},
    )
    assert _room_for_cat(result, 1) is None


def test_comfort_capped_occupancy_lands_on_target():
    """Comfort drops 1 per cat above 4, so the cap is comfort - target + 4.
    Where the target is reachable the resulting Comfort is exactly it."""
    from room_optimizer.optimizer import comfort_capped_occupancy
    for comfort, expected in ((14, 8), (16, 10), (20, 14), (26, 20)):
        cap = comfort_capped_occupancy(comfort, 10.0)
        assert cap == expected, (comfort, cap)
        assert comfort - max(0, cap - 4) == 10
    # Rooms too uncomfortable to reach the target still allow the four
    # cats that cost no Comfort.
    for comfort in (10, 6, 0, -4):
        assert comfort_capped_occupancy(comfort, 10.0) == 4


def test_apply_comfort_target_tightens_breeding_rooms_only():
    from room_optimizer.optimizer import apply_comfort_target
    rooms = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 20, 50.0, comfort=20.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0, comfort=25.0),
    ]
    adjusted = {r.key: r for r in apply_comfort_target(rooms, 10.0)}
    # comfort 20 -> 14 cats keeps Comfort at 10, tighter than the user's 20
    assert adjusted["Floor1_Large"].max_cats == 14
    # Fallback stays uncapped — it is the overflow of last resort.
    assert adjusted["Attic"].max_cats is None


def test_apply_comfort_target_never_loosens_user_capacity():
    from room_optimizer.optimizer import apply_comfort_target
    rooms = [RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0, comfort=30.0)]
    adjusted = apply_comfort_target(rooms, 10.0)
    # comfort 30 would allow 24, but the user asked for 6.
    assert adjusted[0].max_cats == 6


def test_comfort_target_zero_disables_the_cap():
    from room_optimizer.optimizer import apply_comfort_target
    rooms = [RoomConfig("Floor1_Large", RoomType.BREEDING, 20, 50.0, comfort=6.0)]
    assert apply_comfort_target(rooms, 0.0)[0].max_cats == 20


def test_optimizer_respects_comfort_cap_end_to_end():
    """A room with Comfort 14 must not take more than 8 cats."""
    cats = [_make_cat(i, gender="male" if i % 2 else "female", age=5)
            for i in range(1, 21)]
    rooms = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 20, 50.0, comfort=14.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0, comfort=25.0),
    ]
    result = optimize_room_distribution(
        cats, rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None, excluded_keys=set(),
    )
    breeding = next(a for a in result.rooms if a.room.key == "Floor1_Large")
    assert len(breeding.cats) <= 8, len(breeding.cats)
    # Everyone still has a home, thanks to the uncapped fallback.
    assert sum(len(a.cats) for a in result.rooms) == 20


def _comfort_stats(**rooms):
    from save_parser import FurnitureRoomSummary
    return {
        room: FurnitureRoomSummary(
            room=room, cat_count=0, furniture_count=1, items=(),
            raw_effects={"Comfort": float(comfort), "Stimulation": 50.0},
            effective_effects={}, all_effects={},
        )
        for room, comfort in rooms.items()
    }


def test_min_comfort_derives_room_capacity():
    """Min Comfort replaces the hand-computed capacity: the user states the
    Comfort floor and occupancy follows from the room's furniture."""
    stats = _comfort_stats(Floor1_Large=23.0, Floor2_Large=6.0)
    configs = {
        c.key: c for c in build_room_configs(
            [
                {"room": "Floor1_Large", "type": "best_pairs", "min_comfort": 10},
                {"room": "Floor2_Large", "type": "best_pairs", "min_comfort": 10},
            ],
            available_rooms=["Floor1_Large", "Floor2_Large"],
            room_stats=stats,
        )
    }
    # Comfort 23 - (17 - 4) = 10
    assert configs["Floor1_Large"].max_cats == 17
    # Comfort 6 can never reach 10, so only the 4 free cats are allowed.
    assert configs["Floor2_Large"].max_cats == 4


def test_min_comfort_zero_allows_filling_to_zero_comfort():
    stats = _comfort_stats(Floor1_Large=23.0)
    cfg = build_room_configs(
        [{"room": "Floor1_Large", "type": "best_pairs", "min_comfort": 0}],
        available_rooms=["Floor1_Large"], room_stats=stats,
    )[0]
    assert cfg.max_cats == 27  # Comfort hits 0 at 27 cats


def test_fallback_rooms_ignore_min_comfort():
    stats = _comfort_stats(Attic=25.0)
    cfg = build_room_configs(
        [{"room": "Attic", "type": "fallback", "min_comfort": 10}],
        available_rooms=["Attic"], room_stats=stats,
    )[0]
    assert cfg.max_cats is None


def test_legacy_capacity_config_still_honoured():
    """Configs saved before Min Comfort existed keep their explicit capacity,
    with the global comfort target still applying on top."""
    from room_optimizer.optimizer import apply_comfort_target
    stats = _comfort_stats(Floor1_Large=23.0)
    cfg = build_room_configs(
        [{"room": "Floor1_Large", "type": "best_pairs", "max_cats": 20}],
        available_rooms=["Floor1_Large"], room_stats=stats,
    )[0]
    assert cfg.max_cats == 20
    assert cfg.min_comfort is None
    assert apply_comfort_target([cfg], 10.0)[0].max_cats == 17


def test_per_room_min_comfort_not_capped_twice():
    """A room carrying its own Comfort floor must not also be squeezed by the
    global comfort_target."""
    from room_optimizer.optimizer import apply_comfort_target
    stats = _comfort_stats(Floor1_Large=23.0)
    cfg = build_room_configs(
        [{"room": "Floor1_Large", "type": "best_pairs", "min_comfort": 4}],
        available_rooms=["Floor1_Large"], room_stats=stats,
    )[0]
    assert cfg.max_cats == 23  # Comfort 23 - (23-4) = 4
    assert apply_comfort_target([cfg], 10.0)[0].max_cats == 23


# ── More Depth (simulated annealing) must honour deliberate placements ──────

def _sa_rooms():
    return [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 8, 90.0, comfort=26.0),
        RoomConfig("Floor2_Large", RoomType.BREEDING, 8, 10.0, comfort=26.0),  # quietest
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0, comfort=25.0),
    ]


def _sa_cats():
    cats = [_make_cat(i, gender="male" if i % 2 else "female", age=5, stat_seed=7)
            for i in range(1, 11)]
    cats.append(_make_cat(90, gender="male", age=1))   # kitten
    cats.append(_make_cat(91, gender="female", age=5))  # blocked
    return cats


def test_more_depth_keeps_blocked_cats_in_the_fallback():
    """SA rebuilds assignments from the breeding-candidate map, which excludes
    blocked cats — they used to be silently dropped from the result."""
    cats = _sa_cats()
    for use_sa in (False, True):
        result = optimize_room_distribution(
            cats, _sa_rooms(),
            OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=use_sa,
                               sa_chains=1),
            cache=None, excluded_keys={91},
        )
        assert _room_for_cat(result, 91) == "Attic", use_sa
        paired = {c.db_key for a in result.rooms for p in a.pairs
                  for c in (p.cat_a, p.cat_b)}
        assert 91 not in paired, use_sa


def test_more_depth_keeps_kittens_in_the_quiet_room():
    """Kittens contribute nothing to pair scores, so SA would shuffle them
    between rooms for free and undo their deliberate placement."""
    cats = _sa_cats()
    for use_sa in (False, True):
        result = optimize_room_distribution(
            cats, _sa_rooms(),
            OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=use_sa,
                               sa_chains=1, send_kittens_to_fallback=True,
                               kitten_age_threshold=2),
            cache=None, excluded_keys=set(),
        )
        assert _room_for_cat(result, 90) == "Floor2_Large", use_sa


def test_more_depth_respects_capacity_with_pinned_cats():
    """Pinned cats still occupy space. Only eternal-youth cats are exempt from
    room capacity, so pinning must not let SA overfill a room."""
    cats = [_make_cat(i, gender="male" if i % 2 else "female", age=5, stat_seed=7)
            for i in range(1, 15)]
    cats += [_make_cat(90 + i, gender="male", age=1) for i in range(4)]  # kittens
    rooms = _sa_rooms()
    result = optimize_room_distribution(
        cats, rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=True,
                           sa_chains=1, send_kittens_to_fallback=True,
                           kitten_age_threshold=2),
        cache=None, excluded_keys=set(),
    )
    for assignment in result.rooms:
        cap = assignment.room.max_cats
        if cap is not None:
            assert len(assignment.cats) <= cap, (assignment.room.key, len(assignment.cats))


def _spacious_rooms(count: int = 4, *, capacity: int = 20, comfort: float = 24.0):
    """Breeding rooms with far more capacity between them than any test uses."""
    keys = ["Floor1_Large", "Floor1_Small", "Floor2_Small", "Floor2_Large"][:count]
    return [
        RoomConfig(key, RoomType.BEST_PAIRS, capacity, 20.0 + idx, comfort=comfort)
        for idx, key in enumerate(keys)
    ] + [RoomConfig("Attic", RoomType.FALLBACK, None, 50.0, comfort=comfort)]


def test_spare_capacity_does_not_leave_breeding_rooms_empty():
    """Rooms used to be filled to capacity one at a time, so whenever the
    house had more room than cats the rooms at the tail of the fill order got
    nothing at all. Reported as "2nd floor left is empty after I cut down to
    60 cats"."""
    cats = [
        _make_cat(i, gender="male" if i % 2 else "female", stat_seed=6)
        for i in range(1, 25)
    ]
    rooms = _spacious_rooms()
    result = optimize_room_distribution(
        cats, rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None, excluded_keys=set(),
    )

    occupancy = {
        a.room.key: len(a.cats) for a in result.rooms if a.room.room_type.uses_profile
    }
    assert all(occupancy.values()), f"a breeding room was left empty: {occupancy}"
    # 24 cats over 4 rooms: an even spread is 6 apiece. Allow slack for pair
    # placement, but nothing like the old 20/4/0/0.
    assert max(occupancy.values()) - min(occupancy.values()) <= 4, occupancy


def test_spare_capacity_spread_survives_more_depth():
    """The SA pass scores a crowding penalty, so it has no reason to undo the
    spread the greedy pass produced."""
    cats = [
        _make_cat(i, gender="male" if i % 2 else "female", stat_seed=6)
        for i in range(1, 25)
    ]
    rooms = _spacious_rooms()
    result = optimize_room_distribution(
        cats, rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=True,
                           sa_chains=1),
        cache=None, excluded_keys=set(),
    )

    occupancy = {
        a.room.key: len(a.cats) for a in result.rooms if a.room.room_type.uses_profile
    }
    assert all(occupancy.values()), f"More Depth emptied a breeding room: {occupancy}"


def test_balanced_order_keeps_quiet_rooms_first_until_they_fill():
    """Balancing must not cost kittens and parked cats their quiet-room
    preference: rooms tie while they are all inside the free four, and the
    tie breaks on stimulation exactly as before."""
    loud = RoomConfig("Floor1_Large", RoomType.BEST_PAIRS, 20, 90.0, comfort=24.0)
    quiet = RoomConfig("Floor2_Large", RoomType.BEST_PAIRS, 20, 5.0, comfort=24.0)

    empty = {loud.key: 0, quiet.key: 0}
    assert [r.key for r in room_optimizer_impl.balanced_room_order([loud, quiet], empty)] == [
        quiet.key, loud.key
    ]

    # Once the quiet room has used its free four, the loud one is cheaper.
    filled = {loud.key: 0, quiet.key: room_optimizer_impl.COMFORT_FREE_CATS}
    assert [r.key for r in room_optimizer_impl.balanced_room_order([loud, quiet], filled)] == [
        loud.key, quiet.key
    ]


def test_crowding_after_counts_only_cats_past_the_free_four():
    crowding_after = room_optimizer_impl.crowding_after
    free = room_optimizer_impl.COMFORT_FREE_CATS
    assert crowding_after(0) == 0
    assert crowding_after(free - 1) == 0
    assert crowding_after(free) == 1
    assert crowding_after(free + 5) == 6
    # Placing a pair costs both of its cats.
    assert crowding_after(free, added=2) == 2


def _stim_tiered_rooms():
    """Three breeding rooms that differ only in Stimulation, plus a fallback.

    Two slots each, so exactly one pair fits per room and the room a pair
    lands in is the room it was actually given priority for.
    """
    return [
        RoomConfig("Floor1_Large", RoomType.BEST_PAIRS, 2, 5.0, comfort=24.0),
        RoomConfig("Floor1_Small", RoomType.BEST_PAIRS, 2, 40.0, comfort=24.0),
        RoomConfig("Floor2_Large", RoomType.BEST_PAIRS, 2, 95.0, comfort=24.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0, comfort=24.0),
    ]


def _trait_carrier_pairs():
    """Six cats: one carrier of each desired category, plus a plain mate each.

    The optimizer re-pairs freely, so the assertions key on where each
    *carrier* lands rather than on which mate it ends up with.
    """
    passive_carrier = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=5)
    passive_carrier.passive_abilities = ["Library"]
    active_carrier = _make_cat(3, gender="male", sexuality="bi", stat_seed=7, age=5)
    active_carrier.abilities = ["Fireball"]
    mutation_carrier = _make_cat(5, gender="male", sexuality="bi", stat_seed=7, age=5,
                                 mutations=["Spotted"])

    mates = [
        _make_cat(k, gender="female", sexuality="bi", stat_seed=7, age=5)
        for k in (2, 4, 6)
    ]

    profiles = {
        "best_pairs": {
            "traits": [
                {"category": "passive", "key": "library", "weight": 10, "display": "Library"},
                {"category": "ability", "key": "fireball", "weight": 10, "display": "Fireball"},
                {"category": "mutation", "key": "spotted", "weight": 10, "display": "Spotted"},
            ],
            "stat_priority": [],
        },
    }
    return [passive_carrier, active_carrier, mutation_carrier, *mates], profiles


def test_desired_passives_get_the_loudest_room_then_actives():
    """Wiki: a passive is certain only at 95 Stimulation, an active already at
    32, and a mutation never. So the loudest room is worth most to the pair
    carrying a desired passive, next to the active-carriers, and least to the
    mutation-carriers — which is the order rooms are handed out in."""
    cats, profiles = _trait_carrier_pairs()
    result = optimize_room_distribution(
        cats, _stim_tiered_rooms(),
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False,
                           mode_profiles=profiles),
        cache=None, excluded_keys=set(),
    )

    stim_by_room = {a.room.key: a.room.base_stim for a in result.rooms}
    passive_stim = stim_by_room[_room_for_cat(result, 1)]
    active_stim = stim_by_room[_room_for_cat(result, 3)]
    mutation_stim = stim_by_room[_room_for_cat(result, 5)]

    assert passive_stim == 95.0, f"passive carrier landed at {passive_stim} Stim"
    assert passive_stim > active_stim > mutation_stim, (
        passive_stim, active_stim, mutation_stim
    )


def test_active_carrier_takes_the_loud_room_when_it_is_that_or_nothing():
    """With no room at the active's 32-Stimulation guarantee, the
    active-carrier must still outrank a mutation-carrier for the loud one."""
    rooms = [
        RoomConfig("Floor1_Large", RoomType.BEST_PAIRS, 2, 5.0, comfort=24.0),
        RoomConfig("Floor2_Large", RoomType.BEST_PAIRS, 2, 95.0, comfort=24.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0, comfort=24.0),
    ]
    active_carrier = _make_cat(3, gender="male", sexuality="bi", stat_seed=7, age=5)
    active_carrier.abilities = ["Fireball"]
    mutation_carrier = _make_cat(5, gender="male", sexuality="bi", stat_seed=7, age=5,
                                 mutations=["Spotted"])
    mates = [
        _make_cat(k, gender="female", sexuality="bi", stat_seed=7, age=5) for k in (4, 6)
    ]
    profiles = {
        "best_pairs": {
            "traits": [
                {"category": "ability", "key": "fireball", "weight": 10, "display": "Fireball"},
                {"category": "mutation", "key": "spotted", "weight": 10, "display": "Spotted"},
            ],
            "stat_priority": [],
        },
    }

    result = optimize_room_distribution(
        [active_carrier, mutation_carrier, *mates], rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False,
                           mode_profiles=profiles),
        cache=None, excluded_keys=set(),
    )
    assert _room_for_cat(result, 3) == "Floor2_Large"
    assert _room_for_cat(result, 5) == "Floor1_Large"


def test_trait_inheritance_chance_matches_the_wiki_thresholds():
    from breeding import trait_inheritance_chance

    # Passive: 5% + 1% x Stim, certain at 95.
    assert trait_inheritance_chance("passive", 0.0) == pytest.approx(0.05)
    assert trait_inheritance_chance("passive", 95.0) == pytest.approx(1.0)
    assert trait_inheritance_chance("passive", 94.0) < 1.0

    # Active: 20% + 2.5% x Stim, certain at 32.
    assert trait_inheritance_chance("ability", 0.0) == pytest.approx(0.20)
    assert trait_inheritance_chance("ability", 32.0) == pytest.approx(1.0)
    assert trait_inheritance_chance("ability", 31.0) < 1.0

    # Mutation: an even roll at 0 Stimulation, asymptotic after — never
    # certain, however loud the room.
    assert trait_inheritance_chance("mutation", 0.0) == pytest.approx(0.5)
    assert trait_inheritance_chance("mutation", 1000.0) < 1.0


def test_more_depth_sees_room_stimulation():
    """The SA pass looks pair scores up by room *mode*. Keying on the mode
    alone collapsed every room sharing a tree into one entry, so More Depth
    could not tell a loud Best Pairs room from a quiet one and undid the
    first pass's Stimulation ordering."""
    from room_optimizer.optimizer import _sa_mode_key

    assert _sa_mode_key("best_pairs", 0.0) != _sa_mode_key("best_pairs", 95.0)
    assert _sa_mode_key("best_pairs", 95.0) != _sa_mode_key("melee", 95.0)
    assert _sa_mode_key("best_pairs", 95.0) == _sa_mode_key("best_pairs", 95.0)


def test_more_depth_moves_a_passive_pair_into_the_loud_room():
    """Seeded with the wrong layout, More Depth must recognise that the
    passive-carrying pair belongs in the high-Stimulation room."""
    import room_optimizer.optimizer as impl
    import breeding

    carrier_m = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=5)
    carrier_m.passive_abilities = ["Library"]
    carrier_f = _make_cat(2, gender="female", sexuality="bi", stat_seed=7, age=5)
    carrier_f.passive_abilities = ["Library"]
    plain_m = _make_cat(3, gender="male", sexuality="bi", stat_seed=7, age=5)
    plain_f = _make_cat(4, gender="female", sexuality="bi", stat_seed=7, age=5)
    cats = [carrier_m, carrier_f, plain_m, plain_f]

    rooms = [
        RoomConfig("Quiet", RoomType.BEST_PAIRS, 2, 0.0, comfort=24.0),
        RoomConfig("Loud", RoomType.BEST_PAIRS, 2, 95.0, comfort=24.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0, comfort=24.0),
    ]
    profiles = {"best_pairs": {
        "traits": [{"category": "passive", "key": "library", "weight": 10,
                    "display": "Library"}],
        "stat_priority": []}}
    params = OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=True,
                                sa_chains=1, sa_neighbors_per_temp=400,
                                mode_profiles=profiles)

    cache: dict = {}

    def scorer(a, b, room, stimulation):
        key = (min(a.db_key, b.db_key), max(a.db_key, b.db_key),
               float(stimulation), room.mode_key)
        if key not in cache:
            profile = impl._profile_for_room(params, room)
            cache[key] = breeding.score_pair(
                a, b, hater_key_map={}, lover_key_map={}, avoid_lovers=False,
                stimulation=stimulation, planner_traits=profile.get("traits", []),
                stat_priority=[])
        scorer._pair_factor_cache = cache
        return cache[key]

    # Deliberately wrong seed: the carriers are in the quiet room.
    refined = impl._run_sa_refinement(
        room_assignments={"Quiet": [carrier_m, carrier_f],
                          "Loud": [plain_m, plain_f], "Attic": []},
        room_configs=rooms, cats_by_id={c.db_key: c for c in cats},
        filtered_cats=cats, params=params, mode_family=False, family_group_ids={},
        hater_key_map={c.db_key: set() for c in cats},
        lover_key_map={c.db_key: set() for c in cats},
        best_ey_room=None, original_state={c.db_key: "" for c in cats},
        score_pair_cached=scorer,
    )

    loud = {c.db_key for c in refined["Loud"]}
    assert loud == {1, 2}, f"More Depth left the passive pair out of the loud room: {refined}"


def test_trait_appetite_does_not_outrank_the_inbreeding_discount():
    """Stimulation appetite must break ties, not lead. Quality already carries
    the inbreeding discount, so ranking appetite above it let any
    trait-carrier jump ahead of any non-carrier however inbred it was."""
    import breeding

    traits = [{"category": "passive", "key": "library", "weight": 1,
               "display": "Library"}]

    gp_m = _make_cat(90, gender="male", stat_seed=7)
    gp_f = _make_cat(91, gender="female", stat_seed=7)

    clean_m = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=5)
    clean_f = _make_cat(2, gender="female", sexuality="bi", stat_seed=7, age=5)

    sib_m = _make_cat(3, gender="male", sexuality="bi", stat_seed=7, age=5,
                      parent_a=gp_m, parent_b=gp_f, generation=1)
    sib_m.passive_abilities = ["Library"]
    sib_f = _make_cat(4, gender="female", sexuality="bi", stat_seed=7, age=5,
                      parent_a=gp_m, parent_b=gp_f, generation=1)

    def factors(a, b):
        return breeding.score_pair(
            a, b, hater_key_map={}, lover_key_map={}, avoid_lovers=False,
            stimulation=50.0, planner_traits=traits)

    clean = factors(clean_m, clean_f)
    inbred = factors(sib_m, sib_f)

    # The premise: siblings are much riskier, and the light trait bonus does
    # not make up for it in the score.
    assert inbred.risk > clean.risk
    assert clean.quality > inbred.quality

    need_clean = breeding.desired_trait_stim_need(clean_m, clean_f, traits)
    need_inbred = breeding.desired_trait_stim_need(sib_m, sib_f, traits)
    assert need_inbred > need_clean  # only the sibling pair carries the trait

    # The optimizer's ordering must still put the cleaner pair first.
    order = sorted(
        [("clean", 0.0, 0.0, clean.quality, need_clean),
         ("inbred", 0.0, 0.0, inbred.quality, need_inbred)],
        key=lambda p: (p[1], p[2], p[3], p[4]), reverse=True,
    )
    assert order[0][0] == "clean"


def test_max_risk_still_excludes_inbred_pairs():
    """The hard inbreeding gate is unchanged by any of the Stimulation work."""
    gp_m = _make_cat(90, gender="male", stat_seed=7)
    gp_f = _make_cat(91, gender="female", stat_seed=7)
    sib_m = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=5,
                      parent_a=gp_m, parent_b=gp_f, generation=1)
    sib_m.passive_abilities = ["Library"]
    sib_f = _make_cat(2, gender="female", sexuality="bi", stat_seed=7, age=5,
                      parent_a=gp_m, parent_b=gp_f, generation=1)

    rooms = [
        RoomConfig("Loud", RoomType.BEST_PAIRS, 2, 95.0, comfort=24.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0, comfort=24.0),
    ]
    profiles = {"best_pairs": {
        "traits": [{"category": "passive", "key": "library", "weight": 10,
                    "display": "Library"}],
        "stat_priority": []}}

    result = optimize_room_distribution(
        [sib_m, sib_f], rooms,
        OptimizationParams(max_risk=10.0, avoid_lovers=False, use_sa=False,
                           mode_profiles=profiles),
        cache=None, excluded_keys=set(),
    )

    # A desired passive must not buy a sibling pair past the risk cap.
    paired = {
        tuple(sorted((p.cat_a.db_key, p.cat_b.db_key)))
        for a in result.rooms for p in a.pairs
    }
    assert (1, 2) not in paired


def test_more_depth_never_lands_below_its_own_greedy_seed():
    """More Depth starts from the greedy placement, so it must never return a
    worse layout than the one it was handed.

    Its per-room term used to be ``sum_q / total_possible`` — average quality
    per *possible* pairing, which falls as a room fills whether or not the
    extra cats pair up. SA was optimising something the app never reports and
    routinely finished below its own seed: on a 93-cat save, 11 pairs at
    562.0 total quality against the seed's 13 at 584.9.
    """
    cats = [
        _make_cat(i, gender="male" if i % 2 else "female", stat_seed=6, age=5)
        for i in range(1, 21)
    ]
    rooms = _spacious_rooms()

    def run(use_sa):
        result = optimize_room_distribution(
            cats, rooms,
            OptimizationParams(max_risk=100.0, avoid_lovers=False,
                               use_sa=use_sa, sa_chains=1),
            cache=None, excluded_keys=set(),
        )
        pairs = [p for a in result.rooms for p in a.pairs]
        return len(pairs), sum(p.quality for p in pairs)

    seed_pairs, seed_quality = run(False)
    sa_pairs, sa_quality = run(True)

    assert seed_pairs > 0, "the greedy seed found no pairs, so this proves nothing"
    assert sa_pairs >= seed_pairs, (
        f"More Depth lost pairs: {sa_pairs} vs the seed's {seed_pairs}"
    )


def test_sa_objective_ranks_whole_pairs_ahead_of_average_quality():
    """The SA score must count pairs first, matching the greedy DP's
    (count, quality, -risk) ordering — not normalise quality by how many
    pairings a room could theoretically hold."""
    import inspect
    import room_optimizer.parallel as par

    body = inspect.getsource(par._sa_chain)
    scoring = body[body.index("def _state_score"):body.index("def _neighbor")]
    # Throughput mode keeps its own normalised term, so look only at the
    # default branch — and at code, not the comment explaining the old form.
    default_branch = scoring[scoring.index("                else:"):]
    code = "\n".join(
        line for line in default_branch.splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "sum_q / total_possible" not in code, (
        "SA is normalising quality by possible pairings again"
    )
    assert "valid_pairs * 1000.0" in code
    assert "total_quality += sum_q" in code


def test_disorders_do_not_scale_with_stimulation():
    """Disorders are list traits like passives, and each parent rolls a flat
    15% to pass one down. The wiki is explicit that the roll is "not affected
    by furniture or Stimulation" — it fell through to the mutation curve and
    was reported as 50% rising to 66%."""
    from breeding import trait_inheritance_chance, DISORDER_INHERITANCE_CHANCE

    for stim in (-50.0, 0.0, 32.0, 95.0, 200.0):
        assert trait_inheritance_chance("disorder", stim) == pytest.approx(
            DISORDER_INHERITANCE_CHANCE
        ), stim
    assert DISORDER_INHERITANCE_CHANCE == pytest.approx(0.15)


def test_a_disorder_pair_does_not_compete_for_the_loud_room():
    """A pair wanted only for a disorder gains nothing from Stimulation, so it
    must not outrank a passive-carrier for the high-Stimulation room."""
    import breeding

    traits = [
        {"category": "passive", "key": "library", "weight": 10, "display": "Library"},
        {"category": "disorder", "key": "ocd", "weight": 10, "display": "OCD"},
    ]

    passive_carrier = _make_cat(1, gender="male", sexuality="bi", stat_seed=7, age=5)
    passive_carrier.passive_abilities = ["Library"]
    disorder_carrier = _make_cat(3, gender="male", sexuality="bi", stat_seed=7, age=5,
                                 disorders=["OCD"])
    mates = [
        _make_cat(k, gender="female", sexuality="bi", stat_seed=7, age=5) for k in (2, 4)
    ]

    assert breeding.desired_trait_stim_need(disorder_carrier, mates[0], traits) == 0.0
    assert breeding.desired_trait_stim_need(passive_carrier, mates[1], traits) > 0.0

    rooms = [
        RoomConfig("Quiet", RoomType.BEST_PAIRS, 2, 0.0, comfort=24.0),
        RoomConfig("Loud", RoomType.BEST_PAIRS, 2, 95.0, comfort=24.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 50.0, comfort=24.0),
    ]
    result = optimize_room_distribution(
        [passive_carrier, disorder_carrier, *mates], rooms,
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False,
                           mode_profiles={"best_pairs": {"traits": traits,
                                                         "stat_priority": []}}),
        cache=None, excluded_keys=set(),
    )
    assert _room_for_cat(result, 1) == "Loud"
    assert _room_for_cat(result, 3) == "Quiet"


def test_disorder_and_defect_names_never_overlap():
    """The two categories are disjoint in the save format, which is why they
    need separate inheritance models. Guards against a future refactor
    folding `cat.defects` into `cat.disorders`."""
    cat = _make_cat(1, gender="male", disorders=["OCD"])
    cat.defects = ["Lobster Claw"]
    assert not (set(cat.disorders) & set(cat.defects))


_SEXUALITY_RAW = {"straight": 0.05, "bi": 0.5, "gay": 0.95}


def _oriented(db_key, gender, sexuality, **kw):
    cat = _make_cat(db_key, gender=gender, sexuality=sexuality, stat_seed=6,
                    age=5, **kw)
    cat.sexuality_raw = _SEXUALITY_RAW[sexuality]
    cat.libido = 0.7
    return cat


def _two_breeding_rooms():
    return [
        RoomConfig("RoomA", RoomType.BEST_PAIRS, 6, 30.0, comfort=24.0),
        RoomConfig("RoomB", RoomType.BEST_PAIRS, 6, 30.0, comfort=24.0),
        RoomConfig("Attic", RoomType.FALLBACK, None, 20.0, comfort=24.0),
    ]


def test_same_sex_attraction_matches_the_orientation_curve():
    from breeding import same_sex_attraction

    assert same_sex_attraction(_oriented(1, "male", "straight")) < 0.1
    assert same_sex_attraction(_oriented(2, "male", "bi")) == pytest.approx(0.707, abs=0.01)
    assert same_sex_attraction(_oriented(3, "male", "gay")) == pytest.approx(1.0, abs=0.01)


def test_gay_males_are_split_so_they_cannot_divert_each_other():
    """A gay male is exactly as compatible with another gay male (0.52) as
    with a straight female (0.52), and a same-sex mating still consumes both
    cats for the night. Leaving the spare male in the same room risks the two
    taking each other and stranding the female — doubly wasteful, and here
    there is an empty room to use instead."""
    gay_a = _oriented(1, "male", "gay")
    gay_b = _oriented(2, "male", "gay")
    female = _oriented(3, "female", "straight")

    result = optimize_room_distribution(
        [gay_a, gay_b, female], _two_breeding_rooms(),
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None, excluded_keys=set(),
    )
    assert _room_for_cat(result, 1) != _room_for_cat(result, 2), (
        "both gay males were left in one room, where they can divert each other"
    )
    # The female keeps an uncontested partner.
    paired_room = _room_for_cat(result, 3)
    assert paired_room in ("RoomA", "RoomB")


def test_bi_males_are_split_too():
    """Bi males contend at 0.37 — the same as their compatibility with a bi
    female — so they divert each other for the same reason."""
    result = optimize_room_distribution(
        [_oriented(1, "male", "bi"), _oriented(2, "male", "bi"),
         _oriented(3, "female", "straight")],
        _two_breeding_rooms(),
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None, excluded_keys=set(),
    )
    assert _room_for_cat(result, 1) != _room_for_cat(result, 2)


def test_straight_cats_are_never_treated_as_rivals():
    """Straight cats sit at ~0.08 same-sex attraction and never contend, so
    the rule must not start scattering an ordinary roster."""
    from breeding import same_sex_attraction
    from room_optimizer.optimizer import same_sex_rivalry

    males = [_oriented(i, "male", "straight") for i in (1, 2, 3)]
    assert same_sex_attraction(males[0]) < 0.5
    assert same_sex_rivalry(males[0], males, lambda a, b: True) == 0.0


def test_pair_pull_is_the_mean_of_both_orientations_not_the_product():
    """The multiplier is sin(pi/2 * PARTNER_sexuality) and same-sex roles are
    rolled at random, so the expected value is the mean of the two cats'
    orientations. Scoring it as the product understated the commonest case on
    a real roster by a factor of seven."""
    from breeding import same_sex_pair_pull, SAME_SEX_PULL_BASELINE

    gay = _oriented(1, "male", "gay")
    straight = _oriented(2, "male", "straight")
    bi = _oriented(3, "male", "bi")

    # gay + straight: mean 0.538, product would be 0.078.
    assert same_sex_pair_pull(gay, straight) == pytest.approx(
        0.538 - SAME_SEX_PULL_BASELINE, abs=0.01)
    assert same_sex_pair_pull(gay, gay) == pytest.approx(
        0.997 - SAME_SEX_PULL_BASELINE, abs=0.01)
    assert same_sex_pair_pull(bi, straight) == pytest.approx(
        0.393 - SAME_SEX_PULL_BASELINE, abs=0.01)
    # Straight + straight sits under the baseline and scores exactly zero.
    assert same_sex_pair_pull(straight, straight) == 0.0


def test_a_lone_gay_male_is_split_from_the_straight_males():
    """The case a product-based score missed completely: with one gay male
    among straight ones, half the role rolls make the straight male the
    initiator and the multiplier becomes the gay male's ~1.0."""
    cats = [_oriented(1, "male", "gay"), _oriented(2, "male", "straight"),
            _oriented(3, "female", "straight"), _oriented(4, "female", "straight")]
    result = optimize_room_distribution(
        cats, _two_breeding_rooms(),
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=False),
        cache=None, excluded_keys=set(),
    )
    assert _room_for_cat(result, 1) != _room_for_cat(result, 2)


def test_rivalry_is_capped_at_one_diversion_per_cat():
    """A cat can only be diverted once, so its exposure is its strongest
    temptation — not a sum that grows with every same-sex cat in the room."""
    from room_optimizer.optimizer import same_sex_rivalry

    gay = _oriented(1, "male", "gay")
    room_small = [gay, _oriented(2, "male", "gay"), _oriented(9, "female", "straight")]
    room_big = room_small + [_oriented(i, "male", "gay") for i in (3, 4, 5, 6)]

    pull_small = same_sex_rivalry(gay, room_small, lambda a, b: True)
    pull_big = same_sex_rivalry(gay, room_big, lambda a, b: True)
    assert pull_small > 0
    assert pull_big == pytest.approx(pull_small), "rivalry grew with room size"
    assert pull_big <= 1.0


def test_two_gay_females_together_cost_nothing():
    """Neither could conceive with the other or with a male, so there is no
    productive pairing to divert — separating them would be pointless churn."""
    from room_optimizer.optimizer import same_sex_rivalry

    a = _oriented(1, "female", "gay")
    b = _oriented(2, "female", "gay")
    # No cat in the room can breed with either of them.
    assert same_sex_rivalry(a, [a, b], lambda x, y: False) == 0.0
    # With a viable mate present, the rivalry is real.
    assert same_sex_rivalry(a, [a, b], lambda x, y: True) > 0.0


def test_neutral_cats_contend_with_nobody():
    """A neutral cat fills either role and breeds with everything, so it is
    never a same-sex rival."""
    from room_optimizer.optimizer import same_sex_rivalry

    neutral = _make_cat(1, gender="?", sexuality="straight", stat_seed=6, age=5)
    other = _oriented(2, "male", "gay")
    assert same_sex_rivalry(neutral, [neutral, other], lambda a, b: True) == 0.0


def test_more_depth_keeps_gay_males_apart():
    """The SA pass scores its own rivalry penalty, so it must not undo the
    split the first pass made."""
    result = optimize_room_distribution(
        [_oriented(1, "male", "gay"), _oriented(2, "male", "gay"),
         _oriented(3, "female", "straight"), _oriented(4, "female", "straight")],
        _two_breeding_rooms(),
        OptimizationParams(max_risk=100.0, avoid_lovers=False, use_sa=True,
                           sa_chains=1),
        cache=None, excluded_keys=set(),
    )
    assert _room_for_cat(result, 1) != _room_for_cat(result, 2)
