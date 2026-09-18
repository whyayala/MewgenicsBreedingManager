# CLAUDE.md

## Project Overview

PySide6 desktop app that reads Mewgenics save files and provides breeding management tools. Parses binary `.sav` files (LZ4-compressed SQLite) to extract cat data (stats, abilities, mutations, relationships, lineage) and displays it across 12+ specialized views.

## Build & Run

```bash
pip install -r requirements.txt
python src/mewgenics_manager.py

# Build standalone Windows exe
build.bat
```

Tests: `pytest tests/ --basetemp=tmp/pytest` (use basetemp on WSL/Windows to avoid permission issues).

## Module Structure

Entry point is `src/mewgenics_manager.py` (thin wrapper that calls `mewgenics.app.main()`). All application code lives in the `src/mewgenics/` package.

```
src/
  mewgenics_manager.py              # Backwards-compatible entry point (thin wrapper)
  save_parser.py                    # Binary parser, Cat model, genetics/kinship logic
  breeding.py                       # Breeding compatibility, scoring, offspring tracking
  room_optimizer/
    types.py                        # Dataclasses: RoomConfig, OptimizationParams, ScoredPair, etc.
    optimizer.py                    # Room assignment: greedy placement + SA refinement
    parallel.py                     # Simulated-annealing chains (ProcessPoolExecutor)
  visual_mutation_catalog.py        # Lookup tables: (slot, mutation_id) -> display name
  breed_priority/                   # Detailed Scoring view (standalone UI package)
    __init__.py                     # BreedPriorityView — main widget
    scoring.py                      # compute_breed_priority_score, ScoreResult, weights
    filters.py                      # FilterState + FilterDialog
    profiles.py                     # 5-slot profile UI + load/save/delete handlers
    complex_weights/                # ComplexWeight rule system (model, dialog, evaluator)
    columns.py, column_values.py    # Score table column layout + per-mode values
    recompute_helpers.py            # Relationship maps, compute_all_scores, heatmap norms
    stats_overview.py               # Current Stats Overview popup
    weight_popup.py                 # Weight editor popup
    tooltips.py                     # HTML tooltip builders
    delegates.py                    # Custom item delegates + header overlays
    theme.py, styles.py             # Colors + stylesheets
    collapsible_splitter.py         # Left-panel collapsible splitter
    color_utils.py, chip_colors.py  # Color math + chip color pairs
    stat_text_formatter.py          # Stat-cell text formatter
    constants.py                    # Backwards-compat re-exports
  mewgenics/
    __init__.py                     # Package init + module-level setup (locale, tags, thresholds)
    app.py                          # main() — QApplication, palette, save selector
    main_window.py                  # MainWindow (~3000 lines)
    constants.py                    # Colors, column indices, widths, stylesheets
    dialogs.py                      # TagManagerDialog, ThresholdPreferencesDialog,
                                    #   SharedOptimizerSearchSettingsDialog, SaveSelectorDialog
    panels/
      cat_detail.py                 # CatDetailPanel, LineageDialog, chip helpers
      room_priority.py              # RoomPriorityPanel
    models/
      breeding_cache.py             # BreedingCache + BreedingCacheWorker
      cat_table_model.py            # CatTableModel, NameTagDelegate, sort helpers
      room_filter_model.py          # RoomFilterModel
    workers/
      save_loader.py                # SaveLoadWorker
      room_refresh.py               # QuickRoomRefreshWorker
      optimizer_worker.py           # RoomOptimizerWorker
    views/
      family_tree.py                # FamilyTreeBrowserView
      safe_breeding.py              # SafeBreedingView
      breeding_partners.py          # BreedingPartnersView
      room_optimizer.py             # RoomOptimizerView, RoomOptimizerCatLocator, RoomOptimizerDetailPanel
      perfect_planner.py            # PerfectCatPlannerView + 4 sub-panels
      calibration.py                # CalibrationView
      mutation_planner.py           # MutationDisorderPlannerView + planner trait helpers
      manual_scoring.py             # ManualScoringView (Simple Scoring)
      furniture.py                  # FurnitureView
    utils/
      paths.py                      # Bundle dir, save dir, gpak paths, file finders
      config.py                     # App config load/save, UI state, splitter persistence
      localization.py               # _tr(), locale catalog, language management
      styling.py                    # Font enforcement, widget styling, _chip(), _sec()
      tags.py                       # Tag definitions, icons, pixmaps
      thresholds.py                 # Breeding threshold preferences
      optimizer_settings.py         # Optimizer flags, search settings, room priority config
      planner_state.py              # Planner blob persistence, foundation pairs
      game_data.py                  # GPAK loading, game data reload
      calibration.py                # Calibration data load/save, trait overrides
      cat_persistence.py            # Blacklist, must-breed, pinned, tags load/save
      cat_analysis.py               # _cat_base_sum, exceptional/donation checks
      abilities.py                  # Ability/mutation descriptions, tooltips, effect lines
      ability_icons.py              # SWF shape parser, ability icon rendering from GPAK
      shape_extractor.py            # DefinedShape PNG extraction from ZIP or GPAK catparts.swf
      table_state.py                # Table view header/sort state persistence
```

### `save_parser.py` — Core Data Layer

Everything that touches the binary save format or genetic math lives here. No Qt dependencies.

- **`BinaryReader`**: Stateful binary reader (u32, u64, f64, utf16str, etc.)
- **`Cat`**: Core data model. Holds stats, abilities, mutations, relationships, room assignment, generation depth.
- **`SaveData`**: Container for a fully-parsed save (cats list + metadata).
- **`GameData`**: Lookup tables for visual mutations and furniture definitions. Populated at startup from `.gpak` files.
- **`FurnitureItem / FurnitureDefinition / FurnitureRoomSummary`**: Furniture parsing and room stat aggregation.
- **`parse_save(path) -> SaveData`**: Top-level entry point. Constructs Cat objects, resolves parent/child links, computes generation depths. `SaveData` unpacks as `(cats, errors, unlocked_house_rooms)` for backwards compatibility — it is a 3-tuple, not the 2-tuple older call sites assumed — and also carries `furniture`, `furniture_data`, `pedigree_map` and `accessible_cats`.
- `can_breed`, `risk_percent`, `kinship_coi`, `raw_coi`, `shared_ancestor_counts`: Breeding eligibility and kinship math.

Key constants:
- `STAT_NAMES = ["STR", "DEX", "CON", "INT", "SPD", "CHA", "LCK"]` — 7 stats, max value 7
- `EXCEPTIONAL_SUM_THRESHOLD = 40`, `DONATION_SUM_THRESHOLD = 34`, `DONATION_MAX_TOP_STAT = 6`
- Generation: `0` = stray (no parents in save), `1+` = bred kitten

### `breeding.py` — Breeding Logic

No Qt dependencies.

- **`PairProjection`**: Expected offspring stat ranges for a pair.
- **`PairFactors`**: Full score breakdown (risk, complementarity, personality bonus, etc.).
- **`pair_projection(cat_a, cat_b) -> PairProjection`**: Offspring stat projections.
- **`score_pair(cat_a, cat_b) -> PairFactors`**: Scores a pair on all axes.
- `is_mutual_lover_pair`, `planner_pair_allows_breeding`, `planner_inbreeding_penalty`, `planner_pair_bias`: Planner compatibility checks.
- `tracked_offspring`: Offspring tracked for a pair in the planner.

### `room_optimizer/` — Room Assignment

Assigns cats to rooms to maximize breeding outcomes. Two stages, always both:
a greedy placement pass, then a simulated-annealing refinement that starts
from it. The greedy pass is the SA pass's **seed**, not an alternative to it —
there is no greedy-only mode in the UI.

- **`RoomType`** (enum): `BEST_PAIRS`, `MELEE`, `RANGED`, `MAGIC`, `FALLBACK`, plus
  `NONE`. `BREEDING` and `GENERAL` are legacy aliases of `BEST_PAIRS`/`FALLBACK`
  kept for old configs. `uses_profile` is the test for "is a pairing room".
- **`RoomConfig`**: Per-room settings — `key`, `room_type`, `max_cats`, `base_stim`,
  `evolution`, `health`, `comfort` (signed; rooms can be negative) and
  `min_comfort` (the per-room Comfort floor set in the Room Priority panel,
  which is what actually derives `max_cats`).
- **`OptimizationParams`**: Solver config — `min_stats`, `max_risk`,
  `comfort_target`, the SA knobs (`sa_temperature`, `sa_neighbors_per_temp`,
  `sa_chains`, `move_penalty_weight`), and the behaviour flags
  (`mode_profiles`, `send_kittens_to_fallback`, `avoid_trait_loss`,
  `maximize_throughput`, `mode_family`). `use_sa` defaults to `True` and exists
  only so tests can exercise the greedy seed without paying for annealing.
- **`optimize_room_distribution(cats, rooms, params) -> OptimizationResult`**: Main solver entry point.

**Both stages score independently.** The greedy pass calls `breeding.score_pair`;
the SA pass works from a frozen `pair_scores` table keyed by
`(cat_a, cat_b, room_identity)` built in `_run_sa_refinement`. A change to pair
scoring or placement that only lands in one of them is the single most common
bug in this package — it has happened repeatedly. When you touch either, check
the other, and prefer an end-to-end test that runs with `use_sa=True`.

### `mewgenics/` — Qt UI Package

All PySide6 code lives here. `mewgenics/__init__.py` runs one-time initialization (locale, tags, thresholds, game data).

**Key modules:**
- **`main_window.py`** — `MainWindow` (QMainWindow hub, owns all views via QTabWidget)
- **`app.py`** — `main()` entry point (QApplication setup, palette, save selector)
- **`dialogs.py`** — All dialog windows (tag manager, threshold prefs, optimizer settings, save selector)
- **`panels/cat_detail.py`** — `CatDetailPanel` (stat/trait detail for selected cat) + `LineageDialog`
- **`panels/room_priority.py`** — `RoomPriorityPanel` (room priority configuration)

**Views** (each is a self-contained tab):
- `views/family_tree.py` — `FamilyTreeBrowserView` (visual ancestry tree)
- `views/safe_breeding.py` — `SafeBreedingView` (safe breeding partners)
- `views/breeding_partners.py` — `BreedingPartnersView` (pair compatibility grid)
- `views/room_optimizer.py` — `RoomOptimizerView` + detail panel + cat locator
- `views/perfect_planner.py` — `PerfectCatPlannerView` + 4 sub-panels
- `views/calibration.py` — `CalibrationView` (parser field calibration, dev use)
- `views/mutation_planner.py` — `MutationDisorderPlannerView` (mutation/disorder targeting)
- `views/furniture.py` — `FurnitureView` (furniture stat viewer per room)
- `views/manual_scoring.py` — `ManualScoringView` (Simple Scoring — point-value editor)
- `../breed_priority/` — `BreedPriorityView` (Detailed Scoring — weighted breed-priority ranker with profiles, complex weights, filters, heatmap)

**Models & Workers:**
- `models/cat_table_model.py` — `CatTableModel`, `NameTagDelegate`
- `models/room_filter_model.py` — `RoomFilterModel`
- `models/breeding_cache.py` — `BreedingCache`, `BreedingCacheWorker`
- `workers/save_loader.py` — `SaveLoadWorker`
- `workers/room_refresh.py` — `QuickRoomRefreshWorker`
- `workers/optimizer_worker.py` — `RoomOptimizerWorker`

## Data Flow

1. User selects a `.sav` file -> `SaveLoadWorker` calls `parse_save()` -> `Cat` objects created
2. Parent/child links resolved by UID matching + blob scanning fallback
3. Generation depth computed iteratively (gen 0 = no parents)
4. `BreedingCache` pre-computes all pair outcomes in a background thread
5. `QFileSystemWatcher` triggers auto-refresh when the save file changes on disk

## Cat Sprite Rendering

Cat sprites are composited from DefinedShape PNGs in `src/CatAssets/DefinedShapes/`. These are rasterized SWF vector shapes extracted from `catparts.swf` in the game's GPAK archive.

**Extraction chain** (in `app.py` at startup via `ensure_defined_shapes()`):
1. If `DefinedShapes/` has >= 5000 PNGs, skip (already cached)
2. Try extracting from `CatAssets/DefinedShapes.zip` (~3 s, bundled in git)
3. Fall back to parsing `catparts.swf` from the GPAK (~25 s, requires game)

**Key files:**
- `utils/shape_extractor.py` — ZIP extraction + GPAK SWF parsing + Qt QPainter rendering
- `utils/ability_icons.py` — Shared SWF parsing primitives (`_BitReader`, `_parse_shape`, `_gpak_entry_bytes`)
- `swf_cat_renderer.py` — Reads PNGs from `DefinedShapes/`, composites layered sprites with palette texturing
- `swf_database.py` — `SWFDatabaseAccessor` for precomputed sprite frame data + shape bounds
- `CatAssets/swf_database/shapes.db` — Shape bounds metadata (10K+ entries)
- `CatAssets/DefinedShapes.zip` — Pre-rendered shape PNGs (6,894 files, 16.5 MB)

## Game Mechanics Reference

The app models the game's own formulas. When changing scoring, inheritance or
room sizing, check the source rather than the existing code — several
hardcoded constants predate the 1.1 balance overhaul.

**Primary sources** ([The Mewgenics Wiki](https://mewgenics.wiki.gg/)):

- [Breeding](https://mewgenics.wiki.gg/wiki/Breeding) — inheritance formulas for stats, abilities, passives, mutations and birth defects
- [Stimulation](https://mewgenics.wiki.gg/wiki/Stimulation) — what the Stimulation room stat does
- [Stats/House Stats](https://mewgenics.wiki.gg/wiki/Stats/House_Stats) — Comfort, Stimulation, Health, Mutation, Appeal
- [Fighting](https://mewgenics.wiki.gg/wiki/Fighting) — how Comfort and Charisma drive the overnight fight roll
- [Mutations](https://mewgenics.wiki.gg/wiki/Mutations) — the visual mutation and birth defect catalog

### Inheritance, and why Stimulation is not worth the same to every pair

| Trait | Chance | Certain at | Implemented in |
|---|---|---|---|
| Passive ability | `5% + 1% × Stim` | **95 Stim** | `breeding.trait_inheritance_chance` |
| Active ability (first) | `20% + 2.5% × Stim` | **32 Stim** | same |
| Active ability (second) | `2% + 0.5% × Stim` | 196 Stim | `utils/abilities.py` display only |
| Visual mutation / stat | `50% + 50% × Stim/(200 + \|Stim\|)` | never | `save_parser._stimulation_inheritance_weight` |
| **Disorder** | **flat 15% per parent** | **n/a — Stimulation does nothing** | `breeding.DISORDER_INHERITANCE_CHANCE` |
| Visual birth defect | part roll at `Stim − 2 × inbreeding%` | — | `save_parser._defect_inheritance_weight` (see caveat) |

The differing thresholds are the whole reason the optimizer ranks rooms per
pair: a desired passive keeps gaining right up to 95 Stimulation, an active
stops caring past 32, and a mutation is already past halfway at 0. A flat
trait bonus makes every room look identical and the ordering collapses.

**Disorders are not birth defects, whatever the wiki calls them.** `cat.disorders`
(OCD, Anemia, Dwarfism, Schizophrenia) are list traits like passives: each
parent rolls a flat 15% to pass one random disorder from their own list, and
the roll ignores furniture and Stimulation entirely. `cat.defects` are visual
birth defects occupying a body-part slot (Lobster Claw, Cleft Pallet, Forked
Tail) and inherit through the part comparison. The two never overlap — on a
real save the 72 disorder names and 56 defect names share not one entry. The
wiki muddles the terminology (it calls some disorders "Birth Defect
Disorders"); the mechanics are distinct.

> **Caveat on `_defect_inheritance_weight`.** It returns a value that *falls*
> as inbreeding rises, which matches the wiki's "Ordinary vs. Birth Defect"
> formula — that is the chance the **ordinary** part wins, i.e. of *avoiding*
> the defect. But its docstring and `views/mutation_planner.py` both present
> it as the chance of *inheriting* one. One of the two is inverted and it has
> not been settled, so `trait_inheritance_chance` deliberately leaves defects
> on the plain curve rather than build on it.

**Body parts hold one mutation each.** One carrier against a plain part is the
Stimulation-biased roll above; two carriers of *different* mutations on the
same part is a 50/50 pick between them that Stimulation cannot shift; both
carrying the same one is certain. `breeding._mutation_slot_conflict` detects
the contested case from `Cat.visual_mutation_entries[*]["slot_key"]`.

**Same-sex pairs mate but produce no kitten** (Gay Strays). A neutral/ditto
cat's compatibility multiplier is 1 on both sides, which is a gay cat's only
productive pairing. See `save_parser.can_breed` and `breeding.game_compatibility`.

**An opposite-sex attempt is gated by the MOTHER's sexuality**, so the two
orientations are not symmetric: a gay male fathers kittens with a straight
female at full compatibility (his own multiplier is never consulted), while a
gay female cannot conceive with any male — 0.04, below the game's 0.05 floor.
Her only productive partner is a neutral cat. This is why `gay_pref` and
`gay_female_pref` are separate weights in Detailed Scoring.

**Same-sex-attracted cats are rivals, not passengers.** `can_breed` rejects a
same-sex pair, which kept it out of the optimizer's *selected* pairs and made
such cats look inert. They are not: a gay male is exactly as compatible with
another gay male (0.52) as with a straight female (0.52), and mating still
consumes both cats for the night. Two of them in one breeding room can take
each other and strand a female who had a viable partner — two males wasted
and a pairing lost. The multiplier is `sin(pi/2 * PARTNER_sexuality)` — the **partner's**
orientation, not the cat's own — and for a same-sex pair "the roles are chosen
randomly", so the expected pull is the **mean** of the two cats' values, not
the product. That distinction decides everything: a gay male beside a straight
male averages **0.538**, because half the role rolls make the straight male the
initiator and the multiplier becomes the gay male's ~1.00. The product would
score that 0.078 and dismiss it — and on a real roster, where a few gay cats
sit among dozens of straight ones, gay-straight is almost every rivalry there
is (on the fixture save: 3 pairs flagged by the product, 75 by the mean).

`breeding.same_sex_pair_pull` computes it; `optimizer.same_sex_rivalry` takes
each cat's **strongest** temptation rather than a sum, since a cat can only be
diverted once. Applied at room-assignment time in both passes, the same way
lover exclusivity is.

### Comfort and fight risk

Comfort **drops 1 for each cat in a room above 4** — the first four are free.
Fight avoidance is `1 − 0.1 × Comfort`, so a room at Comfort 0 (its nominal
"full" capacity) carries roughly a 16% overnight fight chance against about 1%
at Comfort 10. That is why `COMFORT_FREE_CATS = 4` and why rooms are sized by
a Comfort floor rather than a headcount.

## Conventions

- Windows-targeted: save paths use `%LOCALAPPDATA%`, build produces `.exe`
- Qt signals/slots for all UI reactivity; `blockSignals(True)` prevents cascading updates during programmatic changes
- Views persist user choices to a JSON sidecar file alongside the save (load on `__init__`, save on every change)
- Utility modules use `_` prefix convention — functions are module-private but importable across the package
- Mutable module-level state (dicts, lists) must use in-place mutation (`.clear()` + `.update()`, slice assignment) when shared across modules, not rebinding

## Known Design Decisions

- **Lover conflicts at room level, not pair level**: `breeding.py::is_lover_conflict()` intentionally returns `False`. Lover exclusivity is enforced at room assignment time by `room_optimizer/optimizer.py::_filter_lover_exclusivity()`.
- **Generation depth fallback**: Cats with unresolvable ancestry default to generation 0 (stray). The iterative algorithm in `parse_save()` converges; the fallback is intentional.
- **Inbredness/sexuality dual field**: During `Cat.__init__`, `inbredness` temporarily holds the raw sexuality float. It is overwritten with true COI in `MainWindow._on_save_loaded()`. `parsed_inbredness` preserves the original for calibration override detection.
- **Cross-class access**: Views expose public properties/methods (`room_priority_panel`, `cat_locator`, `offspring_tracker`, `set_navigate_to_cat_callback()`, `save_session_state()`) for MainWindow to use. Avoid accessing `_private` attributes across class boundaries.
- **Module-level initialization**: `mewgenics/__init__.py` runs setup (game data, locale, tags, thresholds) once when the package is first imported. Modules that need initialized state import it after this runs.
- **DefinedShape extraction**: Shapes are extracted once and cached as PNGs. The ZIP is the primary source (fast, no game dependency). GPAK is the fallback (requires game). Individual PNGs are gitignored; only the ZIP is tracked.
- **Room capacity comes from Comfort, not a headcount**: the Room Priority panel takes a per-room **Min Comfort**; `_room_capacity_from_entry()` turns that into `max_cats`. Filling a room to Comfort 0 is its nominal capacity and also its worst fight risk, so the default floor is 10.
- **Placement spreads, it does not pack**: `balanced_room_order()` ranks rooms by `crowding_after()` — Comfort already given up — so rooms tie while they are all inside their free four and the stimulation tiebreak still sends kittens and parked cats to the quietest one. Filling rooms one at a time left later rooms empty whenever the house had more capacity than cats.
- **One trait matcher**: `save_parser.cat_has_visual_trait()` is canonical, and `breeding.py` and `mewgenics/utils/abilities.py` both delegate to it. It cannot live in the UI package — importing anything from `mewgenics` runs its `__init__.py`, and `breeding.py` is Qt-free. Two copies drifted apart once already; don't add a third.
- **Trait keys are `"<name>|<id>"`**: visual mutation ids are reused across body parts (defect 700 is five different traits), so both halves must match. Name-only or id-only comparison is always a bug.
- **SA ranks whole pairs before quality**: `_state_score` uses `valid_pairs * 1000 + sum_q`, matching the greedy DP's `(count, quality, -risk)`. Normalizing by possible pairings instead made SA optimize something the app never displays and finish below its own seed.

## Release Checklist

Before pushing a release commit:

1. Update `VERSION` file with the new version number. It feeds `APP_VERSION`
   (via `mewgenics/utils/paths.py`) and the CI zip names.
2. Update `WhatsNewDialog` default highlights and body text in `src/mewgenics/dialogs.py` to reflect the new release.
3. Update `README.md` current release and add release notes.
4. Commit and merge, then tag `vX.Y.Z` on `main`.

`.github/workflows/build.yml` triggers on `v*` tags: it builds the Windows and
Linux zips and then **publishes the GitHub release itself**. Creating the
release first (`gh release create vX.Y.Z --notes-file …`) keeps your own notes
— CI sees it already exists and just uploads the assets. Pushing the tag alone
gets a release with auto-generated notes.

## tools/field_mapper/

Reverse-engineering pipeline for discovering binary field offsets. Dev-only — not part of the main app.
