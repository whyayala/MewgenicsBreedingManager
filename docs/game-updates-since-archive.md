# Mewgenics updates since repo archive (v5.8.4, 2026-04-24)

Research date: 2026-08-21. Sources: [Mewgenics Wiki Version History](https://mewgenics.wiki.gg/wiki/Version_History),
[Wiki Breeding page](https://mewgenics.wiki.gg/wiki/Breeding), Steam news, PC Gamer coverage.

## Timeline

| Version | Date | Branch | Relevance |
|---|---|---|---|
| 1.1.21016 beta | 2026-04-28 | beta | **The big one** — breeding/genetics overhaul (details below) |
| 1.1.21020 beta | 2026-04-29 | beta | Hotfix (mutation tooltips) |
| 1.1.21025 beta | 2026-04-30 | beta | Bugfixes; Cyclops "Missing"-defect counting fix; voice inheritance 98%→75% |
| 1.1.21035 beta | 2026-05-17 | beta | Bugfixes (Forbidden Famine disorders, random negative-stat events) |
| 1.1.21038/21039 | 2026-05-22/23 | **stable** | **"Mewgenics 1.1" ships to default branch** |
| *(none)* | Jun–Jul 2026 | — | No public builds documented |
| 1.1.21198 beta | 2026-08-12 | beta | JA/KO/zh-CN/RU localizations, new fonts/charsets; event/item fixes |
| 1.1.21215 beta | 2026-08-18 | beta | Localization fixes |
| 1.1.21220 beta | 2026-08-20 | beta | Localization/animation fixes |

**Current stable target: 1.1.21039 (May 23).** Everything after is beta-branch and mostly localization.

## Confirmed UNCHANGED (verified against wiki, matches our code)

- **Breeding compatibility**: `0.15 × initiator_CHA × partner_libido × lover_mult × sexuality_mult`,
  success threshold 5%, `cos/sin(π/2 × sexuality)` — matches `save_parser.py::can_breed` docstring
  and `breeding.py::estimate_breeding_compatibility`.
- **Inbreeding-triggered disorder chance**: `max(2%, 0.4 × COI − 6%)` — matches
  `save_parser.py::_malady_breakdown` (`0.02 + 0.4 × max(coi − 0.20, 0)`).
- **New birth-defect chance**: `1.5 × COI` if COI > 5%, guaranteed at 66.6% — matches `_malady_breakdown`.
- **Inherited disorders**: 15% per parent.
- **Ability inheritance vs stimulation**: first active `20% + 2.5%×Stim`, second `2% + 0.5%×Stim` —
  matches `breeding.py::ability_inheritance_chances`.

## CHANGED in 1.1 — needs code updates

### Tier 2: formula changes

1. **Birth-defect inheritance now depends on stimulation AND inbreeding** (the headline change).
   Per wiki: for the defect-vs-ordinary-part roll, the stimulation weight uses `Stim − 2 × Inbreed%`
   in place of `Stim`. Stimulation must offset *double* the inbreeding percentage to suppress
   inheriting a parent's defect.
   - ✅ DONE: `save_parser.py::_defect_inheritance_weight(stim, coi)`; used by the mutation
     planner's pair outcome table (defect rows) with an explanatory note, plus a defect
     help blurb in the single-trait view.

2. **Negative stimulation fix**: probabilities no longer flip past 100% below −200 Stim.
   - ✅ DONE: `_stimulation_inheritance_weight` now uses `abs()` in the denominator and
     clamps to [0, 1].

3. **Mutation stat behavior rework**:
   - No longer rerolls existing mutations or birth defects.
   - Rolls only simple (+2/−1 stat) mutations until Mutation stat > 10.
   - ✅ DONE (reroll half): the room optimizer's avoid-trait-loss penalty no longer
     steers mutation carriers away from high-Evolution rooms (only the Health/disorder
     half remains); tooltips updated. The app does not model *new*-mutation rolls, so
     the simple-until-10 rule has no further code impact.

4. **Voice inheritance**: 98% → 75% — not modeled anywhere; N/A.

5. **"Missing" defect counting**: heads with 1 eye/eyebrow/ear (Cyclops etc.) no longer count as
   an additional "Missing" defect for the absent counterpart. Check defect counting in
   `visual_mutation_catalog.py` and scoring.

### Tier 3: content/trait effect changes (revisit default trait ratings)

- Malaria: now reduces only CON.
- Sociopathy: CHA +10 → +5, adds INT.
- Schrödinger's Syndrome: All Stats Up +1 → +2, extra bonus turn.
- Naegleria Fowleri: cat becomes AI-controlled at 0 INT instead of dying.
- Psychosis moved to the "crippling" Forbidden Spell consequence pool (90% basic / 10% crippling split).
- Descriptions self-update from `resources.gpak`; hardcoded rating defaults in scoring views do not.

### Tier 1: save format

- Nothing in the notes suggests a save-layout change, but 1.1 was a large build — verify with the
  field-by-field check against a current save (header `version` field: `save_parser.py` ~line 2411).
- Aug beta builds added JA/KO/zh-CN/RU to the gpak — if parsing gpak from a beta install, expect
  new locale content; stable gpak unchanged since May.

## Open questions

- Exact magnitude of "chances of inheriting parent birth defects significantly increased the more
  inbred the kitten is" — wiki formula above is the best available; confirm in-game or via
  `tools/field_mapper/` experiments if precision matters.
- Whether 1.1 changed the save header `version` int (check a post-1.1 save vs `tools/saves/`).
