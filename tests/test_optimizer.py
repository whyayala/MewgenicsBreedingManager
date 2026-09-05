import os
import sys
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
    """When all rooms are breeding rooms (no fallback), overflow cats end up
    in the last breeding room.  The DP cap must prevent this from hanging."""
    import time

    cats = []
    for i in range(40):
        gender = "male" if i % 2 == 0 else "female"
        cats.append(_make_cat(i + 1, gender=gender, sexuality="bi", stat_seed=5))

    # All rooms are breeding rooms with cap 6 — only 12 cats fit, 28 overflow
    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, 6, 50.0),
        RoomConfig("Floor1_Small", RoomType.BREEDING, 6, 50.0),
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
    assert result.stats.assigned_cats == 40


def test_greedy_fallback_produces_reasonable_pairs():
    """The greedy approach should find at least as many pairs as a naive
    first-fit, even when it can't use the exact DP."""
    cats = []
    for i in range(28):
        gender = "male" if i % 2 == 0 else "female"
        cats.append(_make_cat(i + 1, gender=gender, sexuality="bi", stat_seed=6))

    room_configs = [
        RoomConfig("Floor1_Large", RoomType.BREEDING, None, 50.0),
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
