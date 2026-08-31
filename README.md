# Mewgenics Breeding Manager

> This is a maintained fork of [frankieg33/MewgenicsBreedingManager](https://github.com/frankieg33/MewgenicsBreedingManager), which was archived at `v5.8.4`. This fork picks up from there, updated for the Mewgenics 1.1 balance overhaul and beyond.

A Python desktop tool for managing your Mewgenics cats. Reads your save file directly, scores every cat for breeding priority, optimizes room layouts, and helps plan multi-generation lines — all while tracking lineage, inbreeding risk, and trait inheritance.

Current release: `v5.9.3`

If you'd like to support the original author, you can [here](https://ko-fi.com/frankieg33).

## Screenshots

### Main Page

![Main Page](Sceenshots/Home%20Screen.png)

### Breeding Optimizer

![Breeding Optimizer](Sceenshots/Room%20Optimizer.png)

### Perfect 7 Planner

![Perfect 7 Planner](Sceenshots/Perfect%207%20Planner.png)

## Features

### Cat Scoring

Two views for evaluating which cats to keep, breed, or cull:

- **Detailed Scoring** — assigns a breed priority score to every cat based on configurable weights: stat rarity, genetic safety, trait ratings, personality, age, and relationships. Includes heatmap mode, scope filtering by room, complex weight rules, and 5 independent profiles for different strategies.
- **Simple Scoring** — assign point values to individual stats, mutations, and traits, then sort by total. Great for targeted goals like "high STR melee cats" or "collect all rare mutations."
- Each view has its own trait-rating profiles (5 slots) stored per save.

### Breeding & Genetics

- Compare any pair with inheritance odds, expected offspring stats, and inbreeding risk
- Full ancestry tracking — generation depth, shared ancestors, coefficient of inbreeding
- Mating Pair Search finds safe breeding partners with compatibility scoring
- Breeding Partners grid shows all pair combinations at a glance

### Room Optimizer

- Assigns cats to rooms to maximize breeding outcomes
- Movement-aware scoring accounts for relocation cost
- Configurable room capacity, type (breeding/fallback/general), and stimulation
- Avoids trait loss from high-Evolution or high-Health rooms
- Routes kittens to fallback rooms until they're old enough to breed

### Perfect 7 Planner

- Plans multi-generation lines toward all-7 stat cats
- Simulated annealing solver finds optimal breeding chains
- Foundation pair selection with depth control

### Other Tools

- Family Tree browser with in-game cat sprite rendering
- Mutation & Disorder Planner for targeting specific traits
- Furniture Viewer showing per-room stat effects
- Live save file watching — auto-refreshes when the game saves
- Ability and mutation descriptions from `resources.gpak`

## Install

```bash
git clone https://github.com/whyayala/MewgenicsBreedingManager
cd MewgenicsBreedingManager
pip install -r requirements.txt
python src/mewgenics_manager.py
```

On Windows you can also run `run.bat` which auto-installs dependencies on first run.

The app looks for `resources.gpak` in common Steam paths, the configured save root, and the working directory. If it can't find it, you'll be prompted to browse for it.

## Build

```bash
# Windows
build.bat

# Linux
build.sh
```

Produces a standalone executable via PyInstaller.

## Requirements

- Python 3.14+
- PySide6
- lz4
- openpyxl

## Credits

- Save parsing research based on [pzx521521/mewgenics-save-editor](https://github.com/pzx521521/mewgenics-save-editor)
- Community reverse-engineering help from players and mod users
- **Detailed Scoring view** — concept and implementation by [Byron Altice](https://github.com/byronaltice) (ported from his fork)
- PR contributors: [0demongamer0](https://github.com/0demongamer0), [An-on-im](https://github.com/An-on-im), [byronaltice](https://github.com/byronaltice), [heartskingu](https://github.com/heartskingu), [ICaxapl](https://github.com/ICaxapl), [luisMolina95](https://github.com/luisMolina95), [TheMegax](https://github.com/TheMegax)
- Simulated annealing (SA) idea from [PurpleMyst](https://github.com/PurpleMyst/mewgenics_breeding_helper)
- Original idea and reference from frankieg33

## Release Notes

### v5.9.3

**Mutation Planner per-tree trait weights.** Two bugs corrupted saved trait selections; update is recommended.

- **Removing a trait reset the surviving traits' weights to +5 (desired)**, silently flipping undesired (negative) selections. The trait table's remove button emptied the active tree's trait list before the rebuild read the survivors' weights out of that same list, so each fell back to the default. Reproduced against a live view: traits at −8 and +7 both became +5 after removing an unrelated third trait. The per-row × button was unaffected.
- **Traits selected in one tree leaked into Best Pairs.** Whenever Best Pairs was empty, the active tree's selections were copied into it and persisted to the save sidecar — so working in Melee or Ranged silently populated Best Pairs. The code path exists to migrate pre-multi-tree saves and was being handed live data; it is now restricted to genuinely legacy payloads (old flat trait lists still migrate correctly).

Already-overwritten weights cannot be recovered: after updating, check each tree for traits sitting at +5 that you intended as undesired, and Best Pairs for entries you never added.

### v5.9.2

**Trait identity & cross-view consistency.** Distinct traits no longer collapse into shared rows (or fragment into duplicates), and Detailed Scoring, Simple Scoring, the Mutation Planner, and the Room Optimizer now agree on what a trait is.

- **Birth defects keep their real names** ("Cataracts", "Blob Legs", "Lobster Claw") instead of collapsing into generic "{part} Birth Defect" labels — 56 distinct defects in a real save were shown as 10 unratable rows. Each is now individually ratable; existing defect ratings reset to Undesirable (re-rate as needed).
- **Same-name mutations with different effects are disambiguated** with stable identity suffixes: "Slender (Eyes)" (eleven different mutations shared the name), "Pop Eyes (+1 Thorns)" vs "Pop Eyes (+1 range, +1 reach)", "Extra Head (Legs)" vs "(Tail)". Identical-effect arm/leg duplicates stay merged as one trait.
- **Class detection fixed for ~50 cats** whose save blobs carry extra trailing data (mostly retired cats' equipment records): the class field is now located by pattern rather than a fixed offset. Affected cats regained their class — and the class stat modifiers that were missing from their totals. Jesters keeping their original class's basic attack are now parsed correctly.
- **Basic attacks excluded everywhere** from rating lists, breeding targets, and inheritance odds (including TinkererCraft, which dodged the old name-prefix filter). Verified against a real save: class basics appear only on classed cats — they come with the class and are never inherited, and counting them diluted every real ability's computed inheritance odds.
- **Ability tiers collate into one row with a full tooltip**: base and upgraded effects both shown ("+ Upgraded: ..."), matching is tier-blind, and the planner catalog now collates the same way as the scoring views.
- **Missing-part defects ("No Ear") are targetable again** in the Mutation Planner / Room Optimizer — an ID-format mismatch made them silently match no cats.

### v5.9.1

**1.1 breeding model, rare furniture, and "More Depth" performance.**

- **Rare furniture stats**: rare items have doubled effects in-game; room summaries counted every item at base values, under-reporting Comfort/Stimulation/Health/Evolution in any room with rares (which also skewed the Room Optimizer's stimulation inputs). The save's rarity flag is now read; rares display as "Rare {name}" with doubled values.
- **"More Depth" ~6× faster**: the simulated-annealing search re-solved an exponential room-pair problem for every room on every step, though a move touches at most two rooms. Room scores are now cached per membership — 49s → 8s on a real 93-cat save (greedy baseline 0.1s).
- **1.1 breeding model**: birth-defect inheritance uses the game's new rule (effective stimulation = `stim − 2 × inbreeding%`, surfaced in the Mutation Planner); negative-stimulation probabilities are clamped, matching the game's 1.1.21016 fix; high-Mutation rooms are no longer treated as a trait-loss risk (1.1 removed trait rerolling), leaving only the Health-cures-disorders penalty.
- **Tooltip fix**: unresolved localization keys (`PASSIVE_LUCKY_DESC` …) no longer leak into trait tooltips.

### v5.9.0

**First release of the maintained fork — updated for Mewgenics 1.1.** The 1.1 balance overhaul (May 2026) reworked classes, breeding, and mutations; this release brings the app back in line with the live game. Verified field-by-field against a current 1.1 save.

- **Class stat modifiers now applied to total stats**: the game applies class mods (e.g. Thief `SPD +4, LCK +1, STR −1, CON −1`) on top of the save's stat arrays. The parser loaded them but never folded them into totals, so every classed cat's stats were wrong in the main table and detail panel (445 of 1,992 cats in the test save). Scoring paths that compensated separately no longer double-count.
- **Ability names match the game again**: the 1.1 class rework renamed many abilities while save files kept the old internal tokens (`BearHug` → "Grab", `AnimateDead` → "Eternal Servitude" — 168 of 1,018 tokens in a current save). Display names are now resolved from the GPAK's GON `name` keys, following `variant_of` chains, with a clean fallback when no game data is available.
- **Room Optimizer: major speedup + working Cancel**: pair risk is now computed once per pair (not once per pair × room) with a shared kinship memo — 40.4s → 4.7s on the 4,000-cat fixture, with bigger gains on deep lineages. Cancel is polled inside the hot loops and the simulated-annealing worker processes now stop on request (previously Cancel could hang for the full solve).
- **New dev tooling**: `tools/diagnose_cat.py` (per-cat stat/mutation/ability diagnostics against a save + gpak) and `tools/extract_gpak_subset.py` (extracts only the entries the app reads from `resources.gpak` into a small drop-in file). `docs/game-updates-since-archive.md` maps the 1.1 patch notes to code impact.
- **Regression tests** covering the class-mod fold, ability-name resolution, and optimizer cancellation, plus a 1.1-era fixture save in `tools/saves/saves.zip`.

### v5.8.4

**Final upstream release.** The original project was archived at this version; this fork continues from here (see the note at the top of this file).

- **Mating Pair Search — filter + indicator fixes** (#102, #103): "Hide in-love" now treats *any* lover (not just mutual) as disqualifying, with separate toggles for the left list and the matches table. Cats with a lover now show a ♥ next to their name in both panels, and the list entries now include age.
- **Donation/Exceptional thresholds driven by Detailed Scoring** (#104): new "Score source" combo in the Thresholds dialog — keep the default Base stat sum, or switch to the Detailed Scoring total with float thresholds. The sidebar counts and tooltips adapt to the active source. Falls back to base-sum silently when the Detailed cache hasn't been populated yet.
- **CSV/XLSX export**: added Class, Passive Abilities, Disorders, Defects, Tags, Lovers, and Haters columns.
- **Getting Started guide**: a new 9-page walkthrough under Help > Getting Started, with a startup prompt on first launch (Open Guide / Skip Once / Always Skip). Preference is persisted.
- **Startup flow**: the splash screen now waits for the save to finish loading before showing the startup prompt or What's New dialog, so the splash doesn't sit parked behind modal windows.
- **Breeding math**: `can_breed` and the new `game_compatibility` helper now cite the wiki's formula verbatim (`0.15 × CHA × libido × lover_mult × sexuality_mult` with the `> 0.05` gate) and feed compat-aware scoring throughout the app.
- **Issue #101** closed as working-as-intended — same-sex P7P pairs where at least one cat is bi/gay can produce kittens per the game's sexuality math, and the planner surfaces them correctly.

### v5.8.3

Bug fix.

- **Restored human-readable mutation names and descriptions** (issue #99): names like "Aura Ears", "Slenderman Tail", "Human Head Body", "Exposed Brain", and "Wing Hoof Legs" are back in the UI, along with their effect details (e.g. "adds bruise", "jump movement"). The v5.8.1 defect-trust refactor had accidentally stranded the display-name assignment inside an unreachable branch of `_read_visual_mutation_entries`, so every GPAK-known mutation fell through to the generic `"{slot} {id}"` fallback.

### v5.8.2

Crash fix and new Mating Pair Search filters.

- **Fixed Alive Cats sort crash after a quick refresh** (issue #94): the table now uses proper Qt layout-change signals instead of a malformed `layoutChanged` emission, so clicking a sort header right after the game auto-saves no longer aborts the app. As a bonus, your selection and scroll position now survive the refresh.
- **Mating Pair Search filters** (issue #96): a new filter pane on the top of the left bar — "Hide cats already in love" toggle, max risk %, min quality (Best Pair mode), and a searchable trait checklist that unions mutations + passives + disorders + defects + abilities. The selected cat's existing traits are bolded and marked with a checkmark in the list.
- **Mating Pair Search room visibility**: each candidate's room is now shown in a new column, and rooms also appear next to each name in the cat selection list.

### v5.8.1

Bug fixes.

- **Fixed phantom eyebrow birth defect** (issue #93): GPAK's own `tag birth_defect` marker is now authoritative when present, so mutations like "no eyebrows" are no longer mislabeled as defects on stray cats.
- **Reduced game crashes when Mewgenics and the manager are open at the same time** (issue #94): both save readers now copy the `.sav` (and any `-wal`/`-shm`/`-journal` sidecars) to a temp file before opening, eliminating file-handle contention with the running game.
- **More diagnostic logs**: every save load records snapshot size, copy duration, parse time, and each detected birth defect's source — uploaded logs are now actionable when a report does come in.

### v5.8.0

Detailed Scoring view — ported and consolidated from the [byronaltice fork](https://github.com/byronaltice/MewgenicsBreedingManager).

- **New Detailed Scoring view** (concept and implementation by [Byron Altice](https://github.com/byronaltice)): weighted breed-priority ranker with 5-slot profiles, per-cat custom Complex Weights rules, a filter dialog, heatmap column coloring, and a current-stats overview popup.
- **Cat Scoring section** in the sidebar: **Simple Scoring** (was Manual Scoring) and **Detailed Scoring**. The previous Automatic Scoring view has been retired — Detailed Scoring supersedes it.
- **Consolidated scoring engine**: Detailed Scoring and Simple Scoring now share `src/mewgenics/scoring/engine.py`. Ports forward the `(group_key, mutation_id)` mutation-bonus dedupe fix and folds class stat modifiers into current-stat readouts.
- **Session persistence**: auto-loads your most recently used save on startup; restores window geometry, splitter sizes, table column widths, and all Detailed Scoring preferences (active profile, weights, Complex Weights, filters, scope, toggles, sort).
- **Fork back-ports**: defect detection via GON block data, distinct mutation stat variants surfaced as separate traits, and a latent nav bug fix so back/forward now correctly returns to Simple/Detailed Scoring.
- **Performance**: Detailed Scoring runs computation on a background thread and defers recompute while hidden.

### v5.7.9

- Guarded `auto_scoring` worker retirement disconnect against already-disconnected or destroyed C++ object state

### v5.7.8

Thread safety hardening and code quality fixes.

- **Data race eliminated**: `BreedingCacheWorker` now snapshots the alive cat list at construction time instead of reading live `cat.status` from the background thread while the main thread may mutate it
- **Worker interruption**: `SaveLoadWorker` and `QuickRoomRefreshWorker` now check `isInterruptionRequested()` so retired workers exit early instead of running to completion
- **Double-retirement guard**: `_retire_worker()` tracks whether a worker was already retired, preventing duplicate `deleteLater` connections
- **API cleanup**: Replaced direct `_cats_by_key` access across class boundaries with public `BreedingCache.refresh_cat_index()` method

### v5.7.6

Crash fix, icon rendering improvements, and UI polish.

- **Crash fix**: Proper QThread worker lifecycle management — superseded workers are now retired with `requestInterruption()` + `deleteLater()` instead of being leaked as zombies, preventing the ~1-minute crash cycle when the game autosaves while MBM is open
- **#90**: Gradient icon colors no longer washed out in table view (reduced Screen composition from 2 passes to 1); detail panel icons fixed at 72px with camelCase word-wrapping labels
- **Profile sprites**: Cat face thumbnails now scale-to-fit instead of fill-and-crop, so ears and chin are no longer cut off
- **UI**: Column header borders now show subtle resize grip indicators

### v5.7.5

Dead cat detection, gradient icon rendering, and adventure heuristic improvements.

- **#89**: Dead cats are now detected via the `death_day` field in the save binary — cats that died but remain in a room are marked "Dead" in the status column and excluded from alive filters
- **#90**: Ability/mutation/passive icons now render with proper gradient fills instead of flat single-color approximations
- **#81**: Improved `has_adventured` heuristic — now requires 4+ abilities in addition to positive stat gains, eliminating nearly all false positives from nightly cat fights

### v5.7.4

Not-adventured override for issue #81.

- **#81**: Added "Toggle Not Adventured" context menu action — right-click cats whose `has_adventured` flag is a false positive (e.g. from nightly fights, not actual adventures) and mark them as not-adventured. The override persists in a `.not_adventured` sidecar file and survives save reloads.

### v5.7.3

Bug fix and mutation planner UX improvements.

- **#85**: Newly unlocked rooms (e.g. Attic) now appear immediately after the game writes the save, without requiring a game restart — `house_unlocks` is now merged with `house_state`/furniture instead of used as a fallback
- **Mutation Planner**: Added "Add Desired" (weight +5) and "Add Undesired" (weight -5) buttons for quick trait targeting; buttons override each other when re-adding an existing trait
- **Mutation Planner**: Added "Remove Trait" button to remove traits highlighted in the left table from the selected list
- **Mutation Planner**: Added sortable "Sel" column to the trait table so selected traits can be grouped together
- **Reset UI to Defaults** no longer destroys user-curated data (selected traits, foundation pairs, offspring selections, room priority config) — only resets layout and search state

### v5.7.2

Bug-fix release addressing issues #81–#84.

- **#81**: `has_adventured` heuristic now only counts positive `stat_mod` values, avoiding false exclusions from Fight Club / Adv Ready caused by negative debuffs or status effects
- **#82**: Main window is now vertically resizable — sidebar wrapped in a scroll area so it adapts to smaller screens
- **#83**: Mutation planner selected traits list now expands properly with the splitter instead of capping at 200px
- **#84**: Manual Scoring no longer loses selected mutations/disorders on restart — fixed initialization order where `set_trait_ratings()` overwrote saved checked lists before `set_cats()` could rebuild them

### v5.7.1

Stability release. Fixes the ~10% crash reported against v5.4.8 that also affected v5.7.0, in which the application would crash when the game wrote to its save while the manager was open (a day passing, a new cat being added, breeding, etc.).

- Closed four independent race / exception gaps in the auto-refresh path:
  - `SaveLoadWorker.run()` now catches every exception and emits a `failed` signal instead of letting the QThread die silently (which had stranded the loading overlay and the `_save_load_worker` reference forever)
  - `QuickRoomRefreshWorker` carries a *generation token*; `MainWindow._on_room_patch` drops stale signals from superseded workers and wraps the body in a try/except that falls back to a reload instead of aborting the event loop
  - `load_save` / cache cleanup no longer call `QThread.terminate()` on in-flight workers (the textbook crash recipe while the thread was mid-SQLite / mid-parse) — superseded workers are discarded by identity check in their finished slots and allowed to finish naturally
  - `QFileSystemWatcher` bursts are debounced with a 250 ms single-shot timer so simultaneous writes from the game collapse into one refresh
- New `retry_transient` helper retries only genuinely transient I/O errors (`sqlite3.OperationalError`, `sqlite3.DatabaseError`, `OSError`, `EOFError`) from the partial-write window; real bugs propagate immediately instead of wasting ~350 ms re-running a doomed parse
- `_on_save_load_failed` only schedules a self-heal retry for transient errors, capped at 3 consecutive attempts so a permanently-broken save cannot spin a busy loop
- **Atomic file writes** — config and sidecar files (blacklist, must-breed, pinned, tags) now use write-then-rename to prevent corruption on crash or power loss
- Consolidated `_active_cat_fingerprint()` helper shared between Perfect Planner and Room Optimizer caches
- Logging for sidecar I/O failures instead of silent `pass`

16 regression tests cover each fix in isolation.

### v5.7.0

- New **Automatic Scoring** view — ranks every cat with a breed priority score based on stat rarity (7rare), genetic safety risk, trait ratings, personality (libido, aggression, sexuality), age, love/hate relationships, and stat sum percentile. Configurable weights, heatmap mode, scope filtering by room, and 5 independent profiles
- New **Trait Ratings** system — rate abilities and mutations as Top Priority, Desirable, Neutral, or Undesirable. Ratings are shared between Automatic and Manual Scoring views via 5-slot profiles with JSON persistence
- Manual Scoring profile dropdown — switch between trait rating profiles directly from the Manual Scoring config panel
- Stats Overview dialog — popup showing stat distribution across all cats
- Background scoring thread — heavy computation runs off the main thread so the UI stays responsive
- Pre-computed scope data — eliminates redundant O(N*S) per-cat work for stat counts, trait counts, and scope stats
- Lazy view computation — Automatic Scoring only computes when the view is visible; scores are cached until cat data changes
- Startup splash screen with progress indicator during shape extraction and save loading
- Comprehensive tooltips for all Automatic Scoring weights, options, display modes, and score columns
- Updated onboarding tutorial with Cat Sorting walkthrough (Automatic and Manual Scoring)

### v5.6.2

- Tier-2 ability support — upgraded passive abilities parsed from save, shown with "+" suffix and green-tinted chips (cherry-picked from byronaltice fork)
- GPAK ability descriptions preferred over hardcoded lookup; multi-language text extraction with BOM-aware decoding
- Generic mutation disambiguation — mutations with identical names now append their stat description
- Tooltip detail deduplication when detail already appears in display name
- Eager view loading — all views build at startup and receive cat data immediately, eliminating tab-switch freezes

### v5.6.0

- Game-accurate compatibility formula (`0.15 * CHA * libido * lover_mult * sexuality_mult`) displayed as a color-coded chip with per-attempt success % in the pair detail panel
- Ability inheritance chances (stimulation-based: first active, second active, passive) shown inline with candidate labels
- Disorder inheritance (15% per parent + inbred disorder roll based on COI) shown as chips in the risk row
- Compatibility integrated into optimizer pipeline — pairs below 5% are rejected early (performance win), quality scores scale with compatibility factor
- Stimulation inheritance weight unclamped to allow negative values per wiki mechanics
- Soft warnings instead of hard blocks for edge-case sexuality pairings; only hard-blocks when both cats have near-zero compatibility
- ? gender cats bypass sexuality scoring entirely (issue #75)
- Manual Scoring: added disorder selectors, cross-cat mutation disambiguation, QCheckBox state fix, filter buttons, undesired mutation persistence fix

### v5.5.0

- New Manual Scoring view — assign configurable point weights to stats, desired/undesirable mutations, inbredness, libido, aggression, passives, spells, and sexuality, then sort and filter cats by total score
- Instant view switching when cat data hasn't changed — generation counter skips redundant rebuilds
- Lazy data propagation — only the visible view receives cat data updates

### v5.4.9

- Lowered optimizer bitmask DP threshold from 24 to 22 cats per room
- Rewrote `_kinship()` from recursive to iterative stack-based evaluation
- Replaced O(V * Depth) generation depth computation with O(V) memoized DFS
- Fixed room button rebuild, quick room refresh re-filtering, and broken test imports

### v5.4.8

- Fixed room config bleeding between save files
- Room Optimizer routes kittens to fallback rooms
- Room Optimizer avoids placing cats with desired mutations into trait-loss rooms
