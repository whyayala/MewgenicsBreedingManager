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


class TestRareFurniture:
    """Rare furniture (header_fields[0] == 2 in the save record) has doubled
    stats; room summaries must scale them."""

    @staticmethod
    def _item(name, room="Floor1_Large", rare=False):
        from save_parser import FurnitureItem
        return FurnitureItem(
            key=1, version=1, item_name=name, room=room,
            header_fields=(2 if rare else 0, 0, len(room), 0),
            placement_fields=(0, 0, 0, 1, 1),
        )

    @staticmethod
    def _definition(name, effects):
        from save_parser import FurnitureDefinition
        return FurnitureDefinition(item_name=name, display_name=name,
                                   description="", effects=effects)

    def test_is_rare_flag(self):
        assert self._item("small_bed", rare=True).is_rare
        assert not self._item("small_bed", rare=False).is_rare

    def test_rare_doubles_room_effects(self):
        from save_parser import summarize_furniture_room
        defs = {"couch": self._definition("couch", {"Comfort": 3.0, "Appeal": -1.0})}
        normal = summarize_furniture_room([self._item("couch")], defs)
        rare = summarize_furniture_room([self._item("couch", rare=True)], defs)
        assert normal.raw_effects["Comfort"] == 3.0
        assert rare.raw_effects["Comfort"] == 6.0
        # negatives double too
        assert normal.all_effects["Appeal"] == -1.0
        assert rare.all_effects["Appeal"] == -2.0

    def test_save_rare_flags_correlate_with_can_be_rare(self):
        """In the 1.1 fixture save, every rare-flagged item must be a
        can_be_rare definition (special_* items can never be rare)."""
        from save_parser import parse_save
        save = parse_save(_fixture_save(_FIXTURE_11))
        flagged = [it for it in save.furniture if it.is_rare]
        assert flagged, "fixture save should contain rare furniture"
        assert not any(it.item_name.startswith("special_") for it in flagged)


class TestImgTokenReplacement:
    """[img:token] icon markup must render as readable words, never be
    stripped ("Gain +2 [img:shield]" used to degrade to "Gain +2")."""

    def test_known_tokens(self):
        from save_parser import _replace_img_tokens
        assert _replace_img_tokens("Gain +2 [img:shield].") == "Gain +2 Shield."
        assert _replace_img_tokens("+1 [img:int] and -1 [img:lck]") == "+1 INT and -1 LCK"
        assert _replace_img_tokens("[img:divineshield] 2") == "Divine Shield 2"

    def test_unknown_token_degrades_readably(self):
        from save_parser import _replace_img_tokens
        assert _replace_img_tokens("Gain +1 [img:{str_aux}]") == "Gain +1 Str Aux"

    def test_ability_loader_keeps_stat_words(self, tmp_path):
        from mewgenics.utils.abilities import _ABILITY_NAMES, _load_ability_descriptions
        entries = [
            ('data/text/a.csv', b'KEY,en\nABILITY_BLOCK_DESC,"Gain +2 [img:shield]."\n'),
            ('data/abilities/a.gon', b'Block {\n    desc "ABILITY_BLOCK_DESC"\n}\n'),
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
            descs = _load_ability_descriptions(str(gpak))
            assert descs['block'] == 'Gain +2 Shield.'
        finally:
            _ABILITY_NAMES.clear()
            _ABILITY_NAMES.update(saved)

    def test_conditional_descriptions_do_not_leak_into_stat_totals(self):
        """Now that icon stats survive in description text, the detail-based
        delta fallback must only accept pure stat lists — 'Gain +1 INT at the
        end of each turn' is an in-battle effect, not a sheet stat."""
        from save_parser import _mutation_stat_bonus_from_entries
        entries = [
            {"group_key": "head", "mutation_id": 314, "gon_stats": "",
             "detail": "Gain +1 INT at the end of each turn"},
            {"group_key": "body", "mutation_id": 413, "gon_stats": "",
             "detail": "+2 DEX, -1 STR"},
        ]
        bonus = _mutation_stat_bonus_from_entries(entries)
        assert bonus["INT"] == 0        # conditional sentence ignored
        assert bonus["DEX"] == 2        # pure stat list still counted
        assert bonus["STR"] == -1


class TestDefectIdentity:
    """Defects must keep their specific names ("Cataracts", "Blob Legs") so
    the Detailed Scoring / planner trait lists can rate each one — the old
    unconditional "{part} Birth Defect" label collapsed every distinct defect
    on a body part into one row."""

    def test_defects_keep_specific_names(self):
        from save_parser import parse_save
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        names = {d.casefold() for c in cats for d in (getattr(c, 'defects', []) or [])}
        # Many distinct identities, not ~10 per-part labels
        assert len(names) > 30
        assert 'conjoined body' in names
        assert 'gastroschisis' in names

    def test_unnamed_defect_falls_back_to_part_label(self):
        from save_parser import parse_save
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        names = {d for c in cats for d in (getattr(c, 'defects', []) or [])}
        # eyes.gon block 702 has no name comment anywhere -> part-level label,
        # never a synthetic "Eyes 702".
        assert not any(n.split()[-1].isdigit() for n in names), sorted(names)

    def test_synthetic_name_detector_catches_word_number(self):
        from save_parser import _is_synthetic_visual_mutation_name
        assert _is_synthetic_visual_mutation_name("Eyes 702", "Eye", "Left Eye", 702)
        assert _is_synthetic_visual_mutation_name("Legs 440", "Arm", "Left Arm", 440)
        assert not _is_synthetic_visual_mutation_name("Cataracts", "Eye", "Left Eye", 705)


class TestMutationNameDisambiguation:
    """Same-name mutations with different effects must get stable identity
    suffixes; identical-effect duplicates (shared limb table) stay merged."""

    @staticmethod
    def _install(data):
        from save_parser import set_visual_mut_data
        set_visual_mut_data(data)

    def teardown_method(self, method):
        from save_parser import set_visual_mut_data
        set_visual_mut_data({})

    def test_cross_category_different_effects_get_part_labels(self):
        from save_parser import _build_visual_mut_name_disambiguation
        data = {
            "legs": {325: ("Extra Head", "-2 SPD", "-2 SPD", False)},
            "tail": {321: ("Extra Head", "+1 INT", "+1 INT", False)},
        }
        out = _build_visual_mut_name_disambiguation(data)
        assert out[("legs", 325)] == "Legs"
        assert out[("tail", 321)] == "Tail"

    def test_same_category_different_effects_get_effect_suffix(self):
        from save_parser import _build_visual_mut_name_disambiguation
        data = {"eyes": {302: ("Pop Eyes", "+1 range, +1 reach", "", False),
                         348: ("Pop Eyes", "+1 Thorns", "", False)}}
        out = _build_visual_mut_name_disambiguation(data)
        assert out[("eyes", 302)] == "+1 range, +1 reach"
        assert out[("eyes", 348)] == "+1 Thorns"

    def test_identical_effects_stay_merged(self):
        from save_parser import _build_visual_mut_name_disambiguation
        data = {
            "legs": {301: ("Hooves", "+1 SPD", "+1 SPD", False)},
            "ears": {999: ("Hooves", "+1 SPD", "+1 SPD", False)},
        }
        assert _build_visual_mut_name_disambiguation(data) == {}

    def test_fixture_save_has_no_conflicting_rows(self):
        """With the 1.1 gpak-derived tables installed, no two mutations with
        different effects may share a trait-list row text."""
        from save_parser import parse_save
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        sigs = {}
        for c in cats:
            for e in (c.visual_mutation_entries or []):
                if e.get('is_defect'):
                    continue
                sig = str(e.get('gon_stats') or e.get('detail') or '')
                sigs.setdefault(e['name'], set()).add(sig)
        conflicts = {n: s for n, s in sigs.items() if len(s) > 1}
        assert not conflicts, conflicts


class TestClassExtraction:
    """Class strings are located by pattern, not fixed blob-end offset —
    variant tails (retired cats' equipment records) broke the old scan,
    leaving 50 classed cats "classless" in a real save (and their class stat
    mods unapplied)."""

    def test_class_basics_only_on_classed_cats(self):
        """The definitive invariant from in-game behavior: class basic
        attacks appear only on cats whose class parsed."""
        from save_parser import parse_save
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        class_basics = {
            'BasicMelee_Fighter', 'BasicTankMelee', 'BasicMonkMelee',
            'BasicButcherMelee', 'BasicMedicMelee', 'BasicDruidAbility',
            'BasicNecroRanged', 'BasicPsychicPull', 'BasicRanged_Hunter',
            'BasicStraightShot_Thief', 'BasicMagicShortRanged', 'TinkererCraft',
        }
        offenders = [c.name for c in cats if not c.cat_class
                     and any(t in class_basics for t in (c.abilities or []))]
        assert offenders == [], offenders

    def test_class_recovered_on_variant_tail_blobs(self):
        from save_parser import parse_save
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        classed = sum(1 for c in cats if c.cat_class)
        # 495 classed cats in the fixture (was 445 with the fixed-offset scan)
        assert classed >= 490, classed

    def test_find_class_string_end(self):
        import struct
        from save_parser import _find_class_string_end
        blob = b"\x00" * 40 + struct.pack("<II", 5, 0) + b"Thief" + b"\x00" * 200
        found = _find_class_string_end(blob)
        assert found == (40 + 8 + 5, "Thief")
        assert _find_class_string_end(b"\x00" * 64) is None


class TestBasicAttackExclusion:
    """Basic attacks come with the class and are never inherited — they must
    be excluded from trait rating lists and inheritance odds."""

    def test_tinkerercraft_counts_as_basic(self):
        from mewgenics.scoring.engine import is_basic_trait
        assert is_basic_trait("TinkererCraft")
        assert is_basic_trait("BasicTankMelee")
        assert not is_basic_trait("BearHug")

    def test_inheritance_odds_exclude_basics(self):
        from types import SimpleNamespace
        from mewgenics.utils.abilities import _trait_inheritance_probabilities
        a = SimpleNamespace(name="A", abilities=["BasicTankMelee", "BearHug"],
                            passive_abilities=[], mutations=[], disorders=[])
        b = SimpleNamespace(name="B", abilities=["TinkererCraft"],
                            passive_abilities=[], mutations=[], disorders=[])
        rows = _trait_inheritance_probabilities(a, b, 50.0)
        names = {r[0] for r in rows if r[1] == "ability"}
        assert names == {"BearHug"}
        # BearHug's odds must not be diluted by the basic attack:
        # ability_base(20% + 2.5%*50) * favor_weight / 1 non-basic ability
        (prob,) = [r[2] for r in rows if r[0] == "BearHug"]
        assert prob > 0.5


class TestCrossViewTraitConsistency:
    """Detailed Scoring and the Mutation Planner catalog (which feeds the
    Room Optimizer's trait targets) must agree on what is a trait."""

    def test_sentinel_defect_id_matches(self):
        from types import SimpleNamespace
        from mewgenics.utils.abilities import _cat_has_trait
        cat = SimpleNamespace(visual_mutation_entries=[
            {"mutation_id": 0xFFFF_FFFE, "is_defect": True},
        ], defects=["No Ear"])
        # Catalog keys use the tooltip's "-2" for missing-part sentinels while
        # entries store the raw u32; both must match.
        assert _cat_has_trait(cat, "defect", "no ear|-2")
        assert _cat_has_trait(cat, "defect", "no ear")
        assert not _cat_has_trait(cat, "defect", "no ear|700")


class TestAbilityFamilyCollation:
    """Tiered abilities collate into one trait row — the row's tooltip must
    show BOTH base and upgraded effects, and matching must be tier-blind."""

    def test_family_tip_shows_base_and_upgrade(self):
        from mewgenics.utils.abilities import _ABILITY_DESC, _ability_family_tip
        saved = dict(_ABILITY_DESC)
        _ABILITY_DESC.update({"pierce": "Gain +2 Range.",
                              "pierce2": "Gain +2 Range. Attacks pass through units."})
        try:
            tip = _ability_family_tip("Pierce")
            assert "Gain +2 Range." in tip
            assert "+ Upgraded: Gain +2 Range. Attacks pass through units." in tip
            # same family tip regardless of which tier token asks
            assert _ability_family_tip("Pierce2") == tip
        finally:
            _ABILITY_DESC.clear()
            _ABILITY_DESC.update(saved)

    def test_family_tip_without_upgrade_is_base_only(self):
        from mewgenics.utils.abilities import _ABILITY_DESC, _ability_family_tip
        saved = dict(_ABILITY_DESC)
        _ABILITY_DESC.update({"shriek": "Inflict Fear in a cone."})
        try:
            assert _ability_family_tip("Shriek") == "Inflict Fear in a cone."
        finally:
            _ABILITY_DESC.clear()
            _ABILITY_DESC.update(saved)

    def test_cat_has_trait_matches_across_tiers(self):
        from types import SimpleNamespace
        from mewgenics.utils.abilities import _cat_has_trait
        upgraded = SimpleNamespace(abilities=["Pierce2"])
        base = SimpleNamespace(abilities=["Pierce"])
        # base-keyed catalog entry matches both tiers
        assert _cat_has_trait(upgraded, "ability", "pierce")
        assert _cat_has_trait(base, "ability", "pierce")
        # legacy saved key with tier suffix still matches
        assert _cat_has_trait(upgraded, "ability", "pierce2")
        assert not _cat_has_trait(base, "ability", "bearhug")


class TestTablePerformanceCaching:
    """data() is called once per (row, column, role) — Qt sweeps the whole
    model when sorting/filtering — so the exceptional/donation verdicts must
    be memoized per cat rather than recomputed per cell."""

    def _model(self, monkeypatch, counter):
        from mewgenics.models import cat_table_model as ctm
        real = ctm._is_exceptional_breeder

        def counting(cat):
            counter.append(1)
            return real(cat)

        monkeypatch.setattr(ctm, "_is_exceptional_breeder", counting)
        return ctm.CatTableModel()

    def test_badge_verdicts_computed_once_per_cat(self, monkeypatch):
        from PySide6.QtCore import Qt
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        cats = cats[:50]
        calls: list = []
        model = self._model(monkeypatch, calls)
        model.load(list(cats))
        calls.clear()
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            for role in (Qt.DisplayRole, Qt.ToolTipRole, Qt.BackgroundRole,
                         Qt.ForegroundRole, Qt.UserRole):
                model.data(index, role)
        # One computation per cat, not one per (cat, role).
        assert len(calls) <= len(cats), f"{len(calls)} computations for {len(cats)} cats"

    def test_threshold_change_invalidates_badge_cache(self, monkeypatch):
        from PySide6.QtCore import Qt
        from mewgenics.utils import thresholds as th
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        cats = cats[:20]
        calls: list = []
        model = self._model(monkeypatch, calls)
        model.load(list(cats))
        for row in range(model.rowCount()):
            model.data(model.index(row, 0), Qt.DisplayRole)
        before = len(calls)
        assert before > 0

        th._bump_badge_generation()   # e.g. thresholds edited / Detailed rerun
        for row in range(model.rowCount()):
            model.data(model.index(row, 0), Qt.DisplayRole)
        assert len(calls) > before, "cache must be rebuilt after a generation bump"

    def test_must_breed_suffix_is_not_cached(self):
        """The must-breed suffix is applied live, so toggling it needs no
        cache invalidation."""
        from mewgenics.models.cat_table_model import CatTableModel
        from mewgenics.utils import thresholds as th
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        model = CatTableModel()
        model.load(list(cats))
        # Force a donation candidate by making the floor unreachable.
        th._apply_threshold_preferences({"donation_sum_threshold": 999,
                                         "donation_max_top_stat": 99}, cats)
        try:
            target = next(c for c in cats if model._donation_reason_for(c))
            target.must_breed = False
            assert "Must Breed" not in (model._donation_reason_for(target) or "")
            target.must_breed = True
            assert "Must Breed" in (model._donation_reason_for(target) or "")
        finally:
            target.must_breed = False
            th._apply_threshold_preferences({}, cats)


class TestKinshipMemoSharing:
    """risk_percent with a shared memo must match fresh-memo results — the
    Mutation Planner reuses one memo across its O(n^2) pair search, which
    took ~10s per open without it."""

    def test_shared_memo_matches_fresh_memo(self):
        import math
        from save_parser import risk_percent
        cats, _, _ = parse_save(_fixture_save(_FIXTURE_11))
        alive = [c for c in cats if c.status != "Gone"][:40]
        memo: dict = {}
        for i, a in enumerate(alive):
            for b in alive[i + 1:]:
                shared = risk_percent(a, b, memo)
                fresh = risk_percent(a, b)
                assert math.isclose(shared, fresh, rel_tol=1e-9, abs_tol=1e-9), (a.name, b.name, shared, fresh)
