"""
Regression tests for the Mewgenics 1.1 compatibility fixes:

- class stat modifiers folded into Cat.total_stats (parse time)
- ability display names resolved from GPAK GON name keys / variant_of chains
- room optimizer cancellation actually stops the SA solver

Uses the 1.1-era fixture save (steamcampaign02.sav inside tools/saves/saves.zip,
auto-extracted on first run).
"""

import os
import struct
import sys
import zipfile

import pytest

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_proj_root, 'src')
sys.path.insert(0, _src_dir)
sys.path.insert(0, _proj_root)

from save_parser import (  # noqa: E402
    STAT_NAMES, parse_save, set_class_stat_mods,
)
from mewgenics.utils.abilities import (  # noqa: E402
    _ABILITY_NAMES, _ability_display_name, _load_ability_descriptions,
    _mutation_display_name,
)

_SAVES_DIR = os.path.join(_proj_root, 'tools', 'saves')
_FIXTURE_11 = 'steamcampaign02.sav'

_THIEF_MODS = {'SPD': 4, 'LCK': 1, 'STR': -1, 'CON': -1}
_TANK_MODS = {'CON': 4, 'INT': -1, 'DEX': -1}


def _fixture_save(name: str) -> str:
    """Return the path to a fixture save, extracting from saves.zip if needed."""
    path = os.path.join(_SAVES_DIR, name)
    if not os.path.exists(path):
        with zipfile.ZipFile(os.path.join(_SAVES_DIR, 'saves.zip')) as z:
            z.extract(name, _SAVES_DIR)
    return path


@pytest.fixture
def class_mods_11():
    """Install 1.1 class stat mods (as loaded from classes.gon) and clean up."""
    set_class_stat_mods({'Thief': dict(_THIEF_MODS), 'Tank': dict(_TANK_MODS)})
    yield
    set_class_stat_mods({})


@pytest.fixture
def ability_names():
    """Install a small ability-name map (as built from the 1.1 GPAK) and clean up."""
    saved = dict(_ABILITY_NAMES)
    _ABILITY_NAMES.clear()
    _ABILITY_NAMES.update({
        'bearhug': 'Grab',
        'tankswap': 'Swap',
        'basictankmelee': 'Push Attack',
        'basicstraightshotthief': 'Nail Throw',
    })
    yield
    _ABILITY_NAMES.clear()
    _ABILITY_NAMES.update(saved)


class TestClassStatMods:
    def test_class_mods_folded_into_totals(self, class_mods_11):
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        by_name = {c.name: c for c in cats}
        tizzy = by_name['Tizzy']

        assert tizzy.cat_class == 'Thief'
        assert tizzy.class_stat_mods == _THIEF_MODS
        for i, stat in enumerate(STAT_NAMES):
            expected = (tizzy.stat_base[i] + tizzy.stat_mod[i] + tizzy.stat_sec[i]
                        + tizzy.mutation_stat_bonus.get(stat, 0)
                        + _THIEF_MODS.get(stat, 0))
            assert tizzy.total_stats[stat] == expected, stat

    def test_unclassed_cat_totals_unchanged(self, class_mods_11):
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        unclassed = next(c for c in cats if not c.cat_class)
        assert unclassed.class_stat_mods == {}
        for i, stat in enumerate(STAT_NAMES):
            expected = (unclassed.stat_base[i] + unclassed.stat_mod[i]
                        + unclassed.stat_sec[i]
                        + unclassed.mutation_stat_bonus.get(stat, 0))
            assert unclassed.total_stats[stat] == expected, stat

    def test_scoring_current_stats_not_double_counted(self, class_mods_11):
        from mewgenics.scoring.cat_stats import get_cat_stats
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        tizzy = next(c for c in cats if c.name == 'Tizzy')
        # get_cat_stats(use_current=True) must return total_stats as-is;
        # it used to add class mods a second time on top.
        assert get_cat_stats(tizzy, True) == tizzy.total_stats


class TestAbilityDisplayNames:
    def test_renamed_token_resolves(self, ability_names):
        assert _ability_display_name('BearHug') == 'Grab'
        assert _ability_display_name('BasicTankMelee') == 'Push Attack'
        assert _ability_display_name('BasicStraightShot_Thief') == 'Nail Throw'

    def test_tier_token_resolves_via_base(self, ability_names):
        assert _ability_display_name('TankSwap2') == 'Swap'

    def test_fallback_without_gpak(self):
        saved = dict(_ABILITY_NAMES)
        _ABILITY_NAMES.clear()
        try:
            assert _ability_display_name('BearHug') == 'Bear Hug'
            assert _ability_display_name('TankSwap2') == 'Tank Swap'
        finally:
            _ABILITY_NAMES.update(saved)

    def test_mutation_display_name_uses_map(self, ability_names):
        assert _mutation_display_name('BearHug') == 'Grab'

    def test_loader_harvests_names_and_variants(self, tmp_path):
        entries = [
            ('data/text/abilities.csv',
             b'KEY,en\nABILITY_BEARHUG_NAME,Grab\nABILITY_SWAP_NAME,Swap\n'),
            ('data/abilities/tank.gon',
             b'BearHug {\n    name "ABILITY_BEARHUG_NAME"\n    desc "d"\n}\n'
             b'TankSwap {\n    name "ABILITY_SWAP_NAME"\n}\n'
             b'TankSwap2 {\n    variant_of TankSwap\n}\n'),
        ]
        gpak = tmp_path / 'mini.gpak'
        with open(gpak, 'wb') as f:
            f.write(struct.pack('<I', len(entries)))
            for name, blob in entries:
                enc = name.encode()
                f.write(struct.pack('<H', len(enc)))
                f.write(enc)
                f.write(struct.pack('<I', len(blob)))
            for _, blob in entries:
                f.write(blob)

        saved = dict(_ABILITY_NAMES)
        try:
            _load_ability_descriptions(str(gpak))
            assert _ABILITY_NAMES['bearhug'] == 'Grab'
            assert _ABILITY_NAMES['tankswap'] == 'Swap'
            # variant_of chain: TankSwap2 inherits TankSwap's display name
            assert _ABILITY_NAMES['tankswap2'] == 'Swap'
        finally:
            _ABILITY_NAMES.clear()
            _ABILITY_NAMES.update(saved)


class TestOptimizerCancellation:
    def test_run_parallel_sa_returns_initial_state_on_immediate_cancel(self):
        from room_optimizer.parallel import run_parallel_sa
        initial = {1: 'roomA', 2: 'roomA', 3: 'roomB', 4: 'roomB'}
        result = run_parallel_sa(
            initial_state=initial,
            original_state=dict(initial),
            pair_scores={},
            breeding_room_keys=['roomA'],
            all_room_keys=['roomA', 'roomB'],
            room_max_cats={'roomA': 6, 'roomB': 6},
            room_stim={'roomA': 50.0, 'roomB': 50.0},
            room_modes={'roomA': 'breeding', 'roomB': 'fallback'},
            fixed_ids=frozenset(),
            hater_key_map={},
            lover_key_map={},
            avoid_lovers=False,
            max_risk=10.0,
            maximize_throughput=False,
            move_penalty_weight=0.5,
            mode_family=False,
            family_group_ids={},
            sa_temperature=8.0,
            sa_cooling_rate=0.95,
            sa_neighbors_per_temp=50,
            n_chains=1,
            cancel_check=lambda: True,
        )
        assert result == initial

    def test_single_chain_polls_cancel_mid_run(self):
        from room_optimizer.parallel import run_parallel_sa
        calls = {'n': 0}

        def cancel_after_first_poll():
            calls['n'] += 1
            return calls['n'] > 1

        initial = {i: 'roomA' if i % 2 else 'roomB' for i in range(1, 9)}
        result = run_parallel_sa(
            initial_state=initial,
            original_state=dict(initial),
            pair_scores={},
            breeding_room_keys=['roomA'],
            all_room_keys=['roomA', 'roomB'],
            room_max_cats={'roomA': 8, 'roomB': 8},
            room_stim={'roomA': 50.0, 'roomB': 50.0},
            room_modes={'roomA': 'breeding', 'roomB': 'fallback'},
            fixed_ids=frozenset(),
            hater_key_map={},
            lover_key_map={},
            avoid_lovers=False,
            max_risk=10.0,
            maximize_throughput=False,
            move_penalty_weight=0.5,
            mode_family=False,
            family_group_ids={},
            sa_temperature=8.0,
            sa_cooling_rate=0.95,
            sa_neighbors_per_temp=100000,  # would take a long time uncancelled
            n_chains=1,
            cancel_check=cancel_after_first_poll,
        )
        assert isinstance(result, dict)
        assert set(result) == set(initial)


class TestInheritanceWeights:
    """1.1 breeding-model changes: negative-stim guard + defect-specific weight."""

    def test_weight_baseline_and_monotonic(self):
        from save_parser import _stimulation_inheritance_weight as w
        assert w(0) == 0.5
        assert w(50) == pytest.approx(1.5 / 2.5)
        assert w(50) > w(0) > w(-50)

    def test_negative_stim_no_longer_flips_past_bounds(self):
        from save_parser import _stimulation_inheritance_weight as w
        # Pre-fix, stim in (-200, -100) went negative and stim < -200 exceeded 1.0
        # (the game's 1.1.21016 bug). All values must now stay within [0, 1].
        for stim in (-50, -150, -200, -250, -300, -1000):
            assert 0.0 <= w(stim) <= 1.0, stim
        assert w(-300) == 0.0

    def test_defect_weight_penalized_by_inbreeding(self):
        from save_parser import (
            _defect_inheritance_weight as dw,
            _stimulation_inheritance_weight as w,
        )
        # No inbreeding: identical to the normal weight.
        assert dw(50, 0.0) == w(50)
        # Effective stim = stim - 2 * inbreeding%: 50 - 2*25 = 0 -> 50/50.
        assert dw(50, 0.25) == w(0) == 0.5
        # Heavy inbreeding drives defect inheritance up (weight favors the
        # defective parent's part more than stimulation alone would suppress).
        assert dw(50, 0.50) < dw(50, 0.25) < dw(50, 0.0)


class TestTraitLossPenalty:
    """1.1: the Mutation stat no longer rerolls existing traits — only the
    Health/disorder half of the avoid-trait-loss penalty remains."""

    @staticmethod
    def _room(evolution=0.0, health=0.0):
        from room_optimizer.types import RoomConfig, RoomType
        return RoomConfig("r1", RoomType.BREEDING, 6, 50.0,
                          evolution=evolution, health=health)

    @staticmethod
    def _cat(mutations=(), disorders=()):
        from types import SimpleNamespace
        return SimpleNamespace(mutations=list(mutations), disorders=list(disorders))

    def test_high_evolution_no_longer_penalizes_mutations(self):
        from room_optimizer.optimizer import _trait_loss_penalty
        cat = self._cat(mutations=["Gem Eyes"])
        room = self._room(evolution=80.0)
        traits = [{"category": "mutation", "key": "Gem Eyes", "weight": 5}]
        assert _trait_loss_penalty(cat, room, traits) == 0.0

    def test_high_health_still_penalizes_disorders(self):
        from room_optimizer.optimizer import _trait_loss_penalty
        cat = self._cat(disorders=["Sociopathy"])
        room = self._room(health=60.0)
        traits = [{"category": "disorder", "key": "Sociopathy", "weight": 5}]
        assert _trait_loss_penalty(cat, room, traits) == pytest.approx(5 * 0.6)


class TestUnresolvedKeyGuard:
    """Descriptions/names whose string key is missing from the text tables
    must not leak raw ALL_CAPS keys into the UI."""

    def test_loader_skips_unresolved_desc_and_name(self, tmp_path):
        from mewgenics.utils.abilities import (
            _ABILITY_DESC, _ABILITY_NAMES, _load_ability_descriptions,
        )
        entries = [
            ('data/text/abilities.csv', b'KEY,en\nABILITY_GOOD_DESC,Does a thing.\n'),
            ('data/passives/p.gon',
             b'GoodOne {\n    desc "ABILITY_GOOD_DESC"\n}\n'
             b'Lucky {\n    name "PASSIVE_LUCKY_NAME"\n    desc "PASSIVE_LUCKY_DESC"\n}\n'),
        ]
        gpak = tmp_path / 'mini.gpak'
        with open(gpak, 'wb') as f:
            f.write(struct.pack('<I', len(entries)))
            for name, blob in entries:
                enc = name.encode()
                f.write(struct.pack('<H', len(enc)))
                f.write(enc)
                f.write(struct.pack('<I', len(blob)))
            for _, blob in entries:
                f.write(blob)

        saved_names = dict(_ABILITY_NAMES)
        try:
            descs = _load_ability_descriptions(str(gpak))
            assert descs.get('goodone') == 'Does a thing.'
            # PASSIVE_LUCKY_DESC / _NAME have no text-table entry: neither the
            # raw key nor a name derived from it may be stored.
            assert 'lucky' not in descs
            assert 'lucky' not in _ABILITY_NAMES
        finally:
            _ABILITY_NAMES.clear()
            _ABILITY_NAMES.update(saved_names)
