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
