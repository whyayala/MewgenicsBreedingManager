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
