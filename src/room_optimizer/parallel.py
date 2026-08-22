"""Parallel simulated annealing for room optimization.

All functions in this module work with serializable primitives only (ints,
floats, strings, dicts, sets, tuples) so they can run in ProcessPoolExecutor
workers without needing to pickle Cat or BreedingCache objects.
"""

from __future__ import annotations

import math
import multiprocessing
import os
import random
from concurrent.futures import ProcessPoolExecutor, as_completed, wait as _futures_wait
from functools import lru_cache
from typing import Optional


# ---------------------------------------------------------------------------
# Pure-function reimplementation of room pair selection (bitmask DP)
# ---------------------------------------------------------------------------

def _select_room_pairs_pure(
    cat_ids: list[int],
    room_mode: str,
    pair_scores: dict[tuple[int, int, str], tuple[bool, float, float]],
    hater_key_map: dict[int, frozenset[int]],
    lover_key_map: dict[int, frozenset[int]],
    avoid_lovers: bool,
    max_risk: float,
    mode_family: bool,
    family_group_ids: dict[int, tuple[int, ...] | None],
) -> tuple[float, int] | None:
    """Score a room's best non-overlapping pair set using only primitives.

    Returns ``(total_quality, pair_count)`` or ``None`` if the room contains
    an incompatible pair in family mode.
    """
    n = len(cat_ids)
    if n < 2:
        return (0.0, 0)

    # Family-mode hard constraint: every pair in the room must be compatible
    if mode_family:
        for i in range(n):
            for j in range(i + 1, n):
                a, b = cat_ids[i], cat_ids[j]
                pk = (min(a, b), max(a, b), room_mode)
                ga = family_group_ids.get(a)
                if ga is not None and ga == family_group_ids.get(b):
                    return None
                compat, risk, _ = pair_scores.get(pk, (False, 999.0, 0.0))
                if not compat or risk > max_risk:
                    return None

    # Build mutual-lover targets for exclusivity filtering
    room_set = set(cat_ids)
    mutual_lover_targets: dict[int, set[int]] = {}
    if avoid_lovers:
        for cid in cat_ids:
            mutuals = {
                o for o in lover_key_map.get(cid, frozenset())
                if o in room_set and cid in lover_key_map.get(o, frozenset())
            }
            if mutuals:
                mutual_lover_targets[cid] = mutuals

    # Enumerate candidate pairs
    candidate_pairs: dict[tuple[int, int], tuple[float, float]] = {}  # (i, j) -> (quality, risk)
    for i in range(n):
        a = cat_ids[i]
        for j in range(i + 1, n):
            b = cat_ids[j]
            # Hater exclusion
            if b in hater_key_map.get(a, frozenset()):
                continue
            if a in hater_key_map.get(b, frozenset()):
                continue
            # Lover exclusivity
            lt_a = mutual_lover_targets.get(a)
            if lt_a and b not in lt_a:
                continue
            lt_b = mutual_lover_targets.get(b)
            if lt_b and a not in lt_b:
                continue

            pk = (min(a, b), max(a, b), room_mode)
            compat, risk, quality = pair_scores.get(pk, (False, 999.0, 0.0))
            if not compat or risk > max_risk:
                continue
            candidate_pairs[(i, j)] = (quality, risk)

    if not candidate_pairs:
        return (0.0, 0)

    # Maximum cats in a room before falling back to greedy pair selection.
    # Must match the value in optimizer.py — duplicated here because this
    # module runs in ProcessPoolExecutor workers without importing optimizer.
    _MAX_DP_CATS = 22

    if n <= _MAX_DP_CATS:
        # Exact bitmask DP — optimal but exponential in room size. Tracks only
        # (count, quality, risk); the concrete pair list is never returned, so
        # building it per state would just burn allocations in the SA hot loop.
        @lru_cache(maxsize=None)
        def _best(mask: int) -> tuple[int, float, float]:
            if mask.bit_count() < 2:
                return (0, 0.0, 0.0)
            first_bit = mask & -mask
            first_idx = first_bit.bit_length() - 1
            best = _best(mask ^ first_bit)
            for second_idx in range(first_idx + 1, n):
                if not (mask & (1 << second_idx)):
                    continue
                cp = candidate_pairs.get((first_idx, second_idx))
                if cp is None:
                    continue
                q, r = cp
                remainder = _best(mask ^ first_bit ^ (1 << second_idx))
                cand = (remainder[0] + 1, remainder[1] + q, remainder[2] + r)
                if (cand[0], cand[1], -cand[2]) > (best[0], best[1], -best[2]):
                    best = cand
            return best

        count, total_q, _ = _best((1 << n) - 1)
    else:
        # Greedy fallback for large rooms — O(P log P) instead of O(2^N).
        sorted_candidates = sorted(
            candidate_pairs.items(),
            key=lambda item: (-item[1][0], item[1][1]),  # -quality, +risk
        )
        used_indices: set[int] = set()
        total_q = 0.0
        count = 0
        for (i, j), (q, r) in sorted_candidates:
            if i not in used_indices and j not in used_indices:
                total_q += q
                count += 1
                used_indices.add(i)
                used_indices.add(j)

    return (total_q, count)


def _throughput_density_bonus(valid_pairs: int, total_possible: float, enabled: bool) -> float:
    if not enabled or valid_pairs <= 0 or total_possible <= 0:
        return 0.0
    density = max(0.0, min(1.0, valid_pairs / total_possible))
    return math.expm1((density ** 1.5) * valid_pairs)


# ---------------------------------------------------------------------------
# Pure SA chain
# ---------------------------------------------------------------------------

def _sa_chain(
    *,
    initial_state: dict[int, str],
    original_state: dict[int, str],
    pair_scores: dict[tuple[int, int, str], tuple[bool, float, float]],
    breeding_room_keys: list[str],
    all_room_keys: list[str],
    room_max_cats: dict[str, int | None],
    room_stim: dict[str, float],
    room_modes: dict[str, str],
    fixed_ids: frozenset[int],
    hater_key_map: dict[int, frozenset[int]],
    lover_key_map: dict[int, frozenset[int]],
    avoid_lovers: bool,
    max_risk: float,
    maximize_throughput: bool,
    move_penalty_weight: float,
    mode_family: bool,
    family_group_ids: dict[int, tuple[int, ...] | None],
    sa_temperature: float,
    sa_cooling_rate: float,
    sa_neighbors_per_temp: int,
    seed: int,
    cancel_event=None,
    cancel_check=None,
) -> tuple[dict[int, str], float]:
    """Run one SA chain and return (best_state, best_score).

    *cancel_event* is an optional ``multiprocessing.Manager().Event()`` proxy
    (picklable, so it works in ProcessPoolExecutor workers); *cancel_check* is
    an optional callable for the in-process (n_chains=1) path. When either
    signals, the chain returns its best-so-far result early.
    """
    rng = random.Random(seed)

    def _chain_cancelled() -> bool:
        if cancel_event is not None and cancel_event.is_set():
            return True
        return bool(cancel_check and cancel_check())
    breeding_set = set(breeding_room_keys)

    mutable_ids = [cid for cid in initial_state if cid not in fixed_ids]
    if len(mutable_ids) < 2:
        return initial_state, float("-inf")

    neighbor_count = max(1, int(sa_neighbors_per_temp))

    def _room_cats(room_key: str, state: dict[int, str]) -> list[int]:
        return [cid for cid, r in state.items() if r == room_key]

    def _room_effective_count(room_key: str, state: dict[int, str]) -> int:
        return sum(0 if cid in fixed_ids else 1 for cid in _room_cats(room_key, state))

    # Room scores depend only on (room_mode, membership) — pair_scores is
    # frozen for the whole chain. An SA move changes at most two rooms, yet
    # _state_score visits every room, so without this memo the exponential
    # bitmask DP re-solves identical memberships thousands of times per chain
    # (the "More Depth" slowdown on rooms holding 15+ cats).
    _NO_SCORE = object()
    room_score_cache: dict[tuple[str, tuple[int, ...]], tuple[float, int] | None] = {}

    def _room_score(room_key: str, cat_ids: list[int], stim: float) -> tuple[float, int] | None:
        mode = room_modes.get(room_key, "fallback")
        key = (mode, tuple(sorted(cat_ids)))
        cached = room_score_cache.get(key, _NO_SCORE)
        if cached is _NO_SCORE:
            cached = _select_room_pairs_pure(
                cat_ids, mode, pair_scores, hater_key_map, lover_key_map,
                avoid_lovers, max_risk, mode_family, family_group_ids,
            )
            room_score_cache[key] = cached
        return cached

    def _room_accepts_cat(room_key: str, cat_id: int, state: dict[int, str]) -> bool:
        cats_in = _room_cats(room_key, state)
        if cat_id in cats_in:
            return True

        max_c = room_max_cats.get(room_key)
        if max_c is not None and _room_effective_count(room_key, state) >= max_c:
            return False

        if mode_family:
            for other in cats_in:
                if other == cat_id:
                    continue
                ga = family_group_ids.get(cat_id)
                if ga is not None and ga == family_group_ids.get(other):
                    return False
                pk = (min(cat_id, other), max(cat_id, other), room_modes.get(room_key, "fallback"))
                compat, risk, _ = pair_scores.get(pk, (False, 999.0, 0.0))
                if not compat or risk > max_risk:
                    return False
            return True
        # Outside family mode _select_room_pairs_pure never returns None, so
        # the old `_room_score(...) is not None` here was an exponential DP
        # evaluated to produce a constant True — capacity (checked above) is
        # the only remaining constraint.
        return True

    def _state_score(state: dict[int, str]) -> float:
        # Group cats by room in one pass instead of scanning the full state
        # once per room.
        by_room: dict[str, list[int]] = {rk: [] for rk in breeding_room_keys}
        for cid, rk in state.items():
            if rk in by_room:
                by_room[rk].append(cid)
        total_quality = 0.0
        for rk in breeding_room_keys:
            cats_in = by_room[rk]
            effective_count = sum(0 if cid in fixed_ids else 1 for cid in cats_in)
            max_c = room_max_cats.get(rk)
            if max_c is not None and effective_count > max_c:
                excess = effective_count - max_c
                total_quality -= 1000.0 * (excess ** 2)

            rs = _room_score(rk, cats_in, room_stim.get(rk, 50.0))
            if rs is None:
                return float("-inf")
            sum_q, valid_pairs = rs
            if valid_pairs:
                n_cats = len(cats_in)
                total_possible = (n_cats * (n_cats - 1)) / 2.0
                if maximize_throughput:
                    total_quality += valid_pairs * 1000.0
                    total_quality += sum_q / total_possible
                    total_quality += _throughput_density_bonus(valid_pairs, total_possible, True)
                else:
                    total_quality += sum_q / total_possible
                    total_quality += _throughput_density_bonus(valid_pairs, total_possible, False)

        moved = sum(1 for cid, r in state.items() if r != original_state.get(cid) and r)
        total_quality -= moved * move_penalty_weight
        return total_quality

    def _neighbor(state: dict[int, str]) -> dict[int, str]:
        new_state = state.copy()
        keys = [cid for cid in new_state if cid not in fixed_ids]
        if not keys:
            return new_state

        if rng.random() < 0.55 or len(keys) < 2:
            cat_to_move = rng.choice(keys)
            room_counts: dict[str, int] = {rk: 0 for rk in breeding_room_keys}
            for cid, r_key in new_state.items():
                if cid in fixed_ids:
                    continue
                if r_key in room_counts:
                    room_counts[r_key] += 1

            valid_rooms = [
                rk for rk in breeding_room_keys
                if rk != new_state[cat_to_move]
                and _room_accepts_cat(rk, cat_to_move, new_state)
            ]
            if not valid_rooms:
                return new_state

            weights: list[float] = []
            for rk in valid_rooms:
                max_c = room_max_cats.get(rk)
                if max_c is None:
                    weights.append(1.0)
                else:
                    remaining = max(0.1, max_c - room_counts[rk])
                    weights.append(remaining)
            new_state[cat_to_move] = rng.choices(valid_rooms, weights=weights, k=1)[0]
        else:
            c1, c2 = rng.sample(keys, 2)
            room1 = new_state[c1]
            room2 = new_state[c2]
            new_state[c1], new_state[c2] = room2, room1
            if mode_family and (
                not _room_accepts_cat(room2, c1, new_state)
                or not _room_accepts_cat(room1, c2, new_state)
            ):
                return state
        return new_state

    # --- SA main loop ---
    state = dict(initial_state)
    current_score = _state_score(state)
    best_state = state.copy()
    best_score = current_score

    # Probe phase
    positive_deltas: list[float] = []
    test_state = state.copy()
    test_score = current_score
    probe_steps = max(8, min(240, neighbor_count // 2))
    for _ in range(probe_steps):
        nb = _neighbor(test_state)
        ns = _state_score(nb)
        if ns > test_score:
            positive_deltas.append(ns - test_score)
        test_state = nb
        test_score = ns

    avg_delta = sum(positive_deltas) / len(positive_deltas) if positive_deltas else 1.0
    if sa_temperature > 0:
        temperature = float(sa_temperature)
    else:
        temperature = max(1.0, -avg_delta / math.log(0.8))

    while temperature > 0.1:
        # Poll once per temperature step: cheap relative to the neighbor
        # evaluations, and keeps Cancel responsive even mid-anneal.
        if _chain_cancelled():
            return best_state, best_score
        for _ in range(neighbor_count):
            nb = _neighbor(state)
            nb_score = _state_score(nb)
            delta = nb_score - current_score
            if delta > 0 or math.exp(delta / temperature) > rng.random():
                state = nb
                current_score = nb_score
                if current_score > best_score:
                    best_state = state.copy()
                    best_score = current_score
        temperature *= sa_cooling_rate

    return best_state, best_score


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_DEFAULT_SA_CHAINS = min(os.cpu_count() or 1, 4)


def run_parallel_sa(
    *,
    initial_state: dict[int, str],
    original_state: dict[int, str],
    pair_scores: dict[tuple[int, int, str], tuple[bool, float, float]],
    breeding_room_keys: list[str],
    all_room_keys: list[str],
    room_max_cats: dict[str, int | None],
    room_stim: dict[str, float],
    room_modes: dict[str, str],
    fixed_ids: frozenset[int],
    hater_key_map: dict[int, frozenset[int]],
    lover_key_map: dict[int, frozenset[int]],
    avoid_lovers: bool,
    max_risk: float,
    maximize_throughput: bool,
    move_penalty_weight: float,
    mode_family: bool,
    family_group_ids: dict[int, tuple[int, ...] | None],
    sa_temperature: float,
    sa_cooling_rate: float,
    sa_neighbors_per_temp: int,
    n_chains: int = 0,
    cancel_check=None,
) -> dict[int, str]:
    """Run multiple SA chains in parallel and return the best result.

    ``n_chains=0`` (default) auto-detects ``min(cpu_count, 4)``.
    ``n_chains=1`` runs a single chain in-process (no subprocess overhead).
    *cancel_check* is an optional callable; when it returns True the solver
    returns the best result found so far.
    """
    _cancelled = cancel_check or (lambda: False)
    if n_chains <= 0:
        n_chains = _DEFAULT_SA_CHAINS

    kwargs = dict(
        initial_state=initial_state,
        original_state=original_state,
        pair_scores=pair_scores,
        breeding_room_keys=breeding_room_keys,
        all_room_keys=all_room_keys,
        room_max_cats=room_max_cats,
        room_stim=room_stim,
        room_modes=room_modes,
        fixed_ids=fixed_ids,
        hater_key_map=hater_key_map,
        lover_key_map=lover_key_map,
        avoid_lovers=avoid_lovers,
        max_risk=max_risk,
        maximize_throughput=maximize_throughput,
        move_penalty_weight=move_penalty_weight,
        mode_family=mode_family,
        family_group_ids=family_group_ids,
        sa_temperature=sa_temperature,
        sa_cooling_rate=sa_cooling_rate,
        sa_neighbors_per_temp=sa_neighbors_per_temp,
    )

    if _cancelled():
        return dict(initial_state)

    if n_chains == 1:
        best_state, _ = _sa_chain(**kwargs, seed=0, cancel_check=cancel_check)
        return best_state

    best_state: dict[int, str] = dict(initial_state)
    best_score = float("-inf")

    # A Manager Event proxy is picklable, so worker chains can poll it and
    # exit early. (future.cancel() only stops chains that haven't started;
    # without the event, cancelling used to block on the pool join until
    # every running chain annealed to completion.)
    manager = multiprocessing.Manager()
    cancel_event = manager.Event()
    try:
        with ProcessPoolExecutor(max_workers=n_chains) as pool:
            pending = {
                pool.submit(_sa_chain, **kwargs, seed=i, cancel_event=cancel_event)
                for i in range(n_chains)
            }
            while pending:
                if not cancel_event.is_set() and _cancelled():
                    # Signal chains to stop; keep collecting — each returns
                    # its best-so-far state at the next temperature step.
                    cancel_event.set()
                done, pending = _futures_wait(pending, timeout=0.25)
                for future in done:
                    try:
                        state, score = future.result()
                        if score > best_score:
                            best_score = score
                            best_state = state
                    except Exception:
                        pass
    finally:
        manager.shutdown()

    return best_state


# ---------------------------------------------------------------------------
# P7P SA pure chain
# ---------------------------------------------------------------------------

def _p7p_sa_chain(
    *,
    pair_data: list[dict],
    initial_ids: list[int],
    starter_pairs: int,
    sa_temperature: float,
    sa_neighbors: int,
    seed: int,
) -> tuple[list[int], float]:
    """Run one P7P SA chain with pre-serialized pair data.

    ``pair_data`` is a list of dicts with keys:
    ``pair_index``, ``cat_a_key``, ``cat_b_key``, ``score``.
    """
    rng = random.Random(seed)

    pair_by_id: dict[int, dict] = {p["pair_index"]: p for p in pair_data}
    if len(pair_by_id) < 2 or len(initial_ids) < 2:
        return initial_ids, float("-inf")

    neighbors_per_temp = max(1, int(sa_neighbors))

    # Pre-build index: cat_key -> set of pair_indices that involve that cat.
    # _candidate_pool previously did an O(P) linear scan per call; with this
    # index it becomes O(|used_cats| * avg_pairs_per_cat) — critical for large
    # rosters where P can be in the tens of thousands.
    _cat_to_pairs: dict[int, set[int]] = {}
    for p in pair_data:
        pid = p["pair_index"]
        _cat_to_pairs.setdefault(p["cat_a_key"], set()).add(pid)
        _cat_to_pairs.setdefault(p["cat_b_key"], set()).add(pid)
    _all_pair_ids: set[int] = set(pair_by_id.keys())

    def _state_key(ids: list[int]) -> list[int]:
        return sorted(ids)

    def _state_score(ids: list[int]) -> float:
        if not ids:
            return float("-inf")
        return sum(pair_by_id[pid]["score"] for pid in ids if pid in pair_by_id) + len(ids) * 1000.0

    def _cats_for_state(ids: list[int], skip_index: int | None = None) -> set[int]:
        used: set[int] = set()
        for idx, pid in enumerate(ids):
            if skip_index is not None and idx == skip_index:
                continue
            p = pair_by_id.get(pid)
            if p:
                used.add(p["cat_a_key"])
                used.add(p["cat_b_key"])
        return used

    def _candidate_pool(blocked: set[int], used_cats: set[int]) -> list[int]:
        excluded = set(blocked)
        for cat_key in used_cats:
            excluded.update(_cat_to_pairs.get(cat_key, set()))
        return list(_all_pair_ids - excluded)

    def _neighbor(ids: list[int]) -> list[int] | None:
        if not ids:
            return None
        if len(ids) < starter_pairs and rng.random() < 0.35:
            used = _cats_for_state(ids)
            cands = _candidate_pool(set(ids), used)
            if cands:
                return _state_key(ids + [rng.choice(cands)])
        if len(ids) > 1 and rng.random() < 0.15:
            drop = rng.randrange(len(ids))
            return _state_key(ids[:drop] + ids[drop + 1:])
        replace = rng.randrange(len(ids))
        used = _cats_for_state(ids, skip_index=replace)
        blocked = set(ids)
        blocked.discard(ids[replace])
        cands = _candidate_pool(blocked, used)
        if not cands:
            return None
        new_ids = ids[:]
        new_ids[replace] = rng.choice(cands)
        return _state_key(new_ids)

    current_ids = _state_key(list(initial_ids))
    current_score = _state_score(current_ids)
    best_ids = current_ids[:]
    best_score = current_score

    # Probe
    positive_deltas: list[float] = []
    probe_ids = current_ids[:]
    probe_score = current_score
    for _ in range(neighbors_per_temp):
        nb = _neighbor(probe_ids)
        if nb is None:
            break
        ns = _state_score(nb)
        if ns > probe_score:
            positive_deltas.append(ns - probe_score)
        probe_ids = nb
        probe_score = ns

    avg_delta = sum(positive_deltas) / len(positive_deltas) if positive_deltas else 1.0
    temperature = float(sa_temperature) if sa_temperature > 0 else max(1.0, -avg_delta / math.log(0.8))

    while temperature > 0.1:
        for _ in range(neighbors_per_temp):
            nb = _neighbor(current_ids)
            if nb is None:
                continue
            ns = _state_score(nb)
            delta = ns - current_score
            if delta > 0 or math.exp(delta / temperature) > rng.random():
                current_ids = nb
                current_score = ns
                if current_score > best_score:
                    best_ids = current_ids[:]
                    best_score = current_score
        temperature *= 0.9

    return best_ids, best_score


def run_parallel_p7p_sa(
    *,
    pair_data: list[dict],
    initial_ids: list[int],
    starter_pairs: int,
    sa_temperature: float,
    sa_neighbors: int,
    n_chains: int = 0,
) -> list[int]:
    """Run multiple P7P SA chains in parallel and return the best pair IDs."""
    if n_chains <= 0:
        n_chains = _DEFAULT_SA_CHAINS

    kwargs = dict(
        pair_data=pair_data,
        initial_ids=initial_ids,
        starter_pairs=starter_pairs,
        sa_temperature=sa_temperature,
        sa_neighbors=sa_neighbors,
    )

    if n_chains == 1:
        best_ids, _ = _p7p_sa_chain(**kwargs, seed=0)
        return best_ids

    best_ids = list(initial_ids)
    best_score = float("-inf")

    with ProcessPoolExecutor(max_workers=n_chains) as pool:
        futures = {
            pool.submit(_p7p_sa_chain, **kwargs, seed=i): i
            for i in range(n_chains)
        }
        for future in as_completed(futures):
            try:
                ids, score = future.result()
                if score > best_score:
                    best_score = score
                    best_ids = ids
            except Exception:
                pass

    return best_ids
