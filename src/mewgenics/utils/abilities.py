"""Ability/mutation descriptions, tooltips, display names, and effect lines."""
import html
import re
import struct
from typing import Sequence

from save_parser import (
    Cat, _load_gpak_text_strings, _resolve_game_string,
    _stimulation_inheritance_weight, _extract_primary_language_text,
)


# ── Ability tooltip lookup ───────────────────────────────────────────────────
# Keys: display name lowercased with all non-alphanumeric chars removed.

_ABILITY_LOOKUP: dict[str, str] = {
    # Birth defects
    "twoedarm":           "-2 Strength",
    "twotoedarm":         "-2 Strength",
    "bentarm":            "-2 Speed",
    "conjoinedbody":      "+2 Constitution, -3 Speed",
    "lumpybody":          "Start each battle with 1 Bruise",
    "malnourishedbody":   "-1 Constitution",
    "turnersyndrome":     "-2 Intelligence",
    "williamssyndrome":   "+10 Charisma, -5 Intelligence",
    "birdbeakears":       "Start each battle with Confusion 2",
    "floppyears":         "Start each battle with Immobile 1",
    "inwardeyes":         "Start each battle with Confusion 2",
    "redeyes":            "Gain 5% miss chance every turn",
    "blind":              "Start every battle with Blind 1",
    "bushyeyebrow":       "-1 Luck",
    "noeyebrows":         "-2 Charisma",
    "sloth":              "-3 Charisma, Brace 1",
    "conjoinedtwin":      "+2 Intelligence, -3 Charisma",
    "bentleg":            "Trample — units moved through take damage",
    "duckleg":            "-2 Speed, water does not slow movement",
    "twoedleg":           "-2 Strength",
    "twotoedleg":         "-2 Strength",
    "nomouth":            "Can't use consumables, eat, or musical abilities",
    "cleftlip":           "-2 Charisma",
    "lumpytail":          "+1 Constitution, start with 1 Immobile",
    "notail":             "-1 Dexterity",
    "tailsack":           "-1 Speed, -1 Constitution",
    # Collarless passives
    "180":                "When you use your basic attack, turn around and use it again.",
    "amped":              "Gain +1 Speed at the end of your turn.",
    "amplify":            "+1 Magic Damage.",
    "animalhandler":      "Start each battle with a random vermin familiar.",
    "bareminimum":        "Your stats can't go below 5.",
    "charming":           "25% chance to inflict Charm on units that damage you.",
    "daunt":              "Small enemies won't attack you.",
    "dealer":             "You can use consumables on other units.",
    "deathboon":          "When downed, all allies gain All Stats Up.",
    "deathsdoor":         "While at 1 HP, spells cost 1 mana but can only be cast once per turn.",
    "deathproof":         "While downed, 25% chance to revive with 1 HP at end of each round.",
    "dirtyclaws":         "Attacks on Poisoned/Bleeding enemies inflict +1 Poison/Bleed.",
    "etank":              "Start each battle with +20 unfilled max health.",
    "fastfootsies":       "Immune to negative tile effects.",
    "firstimpression":    "Start each battle with +1 Bonus Attack.",
    "furious":            "Gain +1 Damage per critical hit. +5% critical hit chance.",
    "gassy":              "When you take damage, knock back all adjacent units.",
    "hotblooded":         "Burn you inflict is increased by 1.",
    "infested":           "50% chance to spawn a flea familiar when you end your turn.",
    "latebloomer":        "On your 5th turn, gain All Stats Up 3.",
    "leader":             "Adjacent allies have +1 Damage and +1 Range.",
    "longshot":           "+1 Range.",
    "luckdrain":          "Steal luck from enemies you damage.",
    "lucky":              "+4 Luck.",
    "mange":              "Inflict Poison 1 on units that contact you.",
    "mania":              "10% chance to restore all mana at the start of your turn.",
    "metaldetector":      "5% chance to spawn a coin when you move over a tile.",
    "mightofthemeek":     "Damage of 2 or less is always critical.",
    "minime":             "Start each battle with a tiny duplicate cat at half your stats.",
    "naturalhealing":     "+1 Health Regeneration.",
    "overconfident":      "While at full HP, spells cost 2 less but you take double damage.",
    "patience":           "If you end your turn without actions, gain an extra turn at end of round.",
    "protection":         "Gain +1 Holy Shield.",
    "pulp":               "When you kill a unit, it becomes meat.",
    "rockin":             "Spawn 4 small rocks at the start of each battle.",
    "santasangre":        "When downed, allies heal 12 HP. Excess healing becomes Shield.",
    "scavenger":          "If trinket slot is empty, equip a small food item at battle start.",
    "selfassured":        "Gain a random stat up whenever you down a unit.",
    "serialkiller":       "After 3 kills, gain +6 Speed and backstabs have 100% crit.",
    "skillshare":         "Your other passive is shared with all party cats at battle start.",
    "slugger":            "+1 Damage.",
    "study":              "Gain +1 Intelligence whenever you hit a new unit type.",
    "unrestricted":       "Once-per-battle abilities can be cast once per turn instead.",
    "unscarred":          "While at full HP, 100% critical hit chance.",
    "wiggly":             "+25% Dodge Chance.",
    "worms":              "50% chance to spawn a maggot familiar when you end your turn.",
    "zenkaiboost":        "End battle at 1 HP → +1 random stat permanently, next battle starts with All Stats Up 3.",
    # Fighter passives
    "avenger":            "When an allied cat is downed, gain All Stats Up 2 and heal 8.",
    "boned":              "When you kill a unit without a weapon, gain a Bone Club.",
    "dualwield":          "When you use your weapon, automatically use it again for free.",
    "fervor":             "When you down a unit, heal 5 HP.",
    "frenzy":             "When you down a unit, gain +2 Strength.",
    "hamsterstyle":       "+1 INT, -1 STR, +1 CON, +1 Health Regen, start with 2 Bonus Moves.",
    "hulkup":             "When you take damage, gain +2 Speed.",
    "math":               "Spells cost 3 mana but can only be cast once per turn.",
    "merciless":          "10+ damage in a single hit: +2 Shield and refresh movement action.",
    "overpowered":        "Excess damage causes enemies to explode, dealing overflow to nearby units.",
    "patellarreflex":     "When damaged, counter-attack for 1 damage + Bruise.",
    "punchface":          "Basic attacks hitting the front of a unit are always critical.",
    "ratstyle":           "+2 Speed, +10% Dodge Chance.",
    "scars":              "Start with +1 Brace.",
    "skullcrack":         "Your basic attack inflicts Bruise.",
    "smash":              "Weapons deal triple damage but always break when used.",
    "thickskull":         "All injuries are Concussions. +3 Shield per concussion (max 30).",
    "turtlestyle":        "+4 Armor, +2 Vitality, -1 Speed.",
    "underdog":           "+2 STR and +1 Brace for each adjacent enemy.",
    "vengeful":           "Basic attack is always critical against enemies that have damaged you.",
    "weaponmaster":       "Weapon/item abilities deal +2 Damage and +25% critical chance.",
    # Tank passives
    "bouncer":            "When an ally takes damage, move toward the source and attack if possible.",
    "chainknockback":     "Basic attack gains +1 Knockback; knocked-back units knock back others.",
    "hardhead":           "You block attacks from the front.",
    "hardy":              "Heal to full HP at the start of each battle.",
    "heavyhanded":        "+2 Knockback Damage.",
    "homerun":            "Increases all Knockback by 10.",
    "mountainform":       "Knockback immunity. Tiles walked over become dirt and may spawn rocks.",
    "petrocks":           "Each rock you spawn becomes a Pet Rock. One Pet Rock spawns per combat.",
    "plow":               "When you knock back a unit, leave a rock where it was.",
    "prioritytarget":     "Enemies attack you instead of allies if they can.",
    "protective":         "Your allies have Brace 1.",
    "scabs":              "Gain +2 Shield when you take damage from an ability.",
    "slackoff":           "If you end your turn with unused movement, gain 8 HP.",
    "slowandsteady":      "At speed 0 or below, attack an extra time per turn. -2 SPD, +1 Range/turn.",
    "stoic":              "If you end your turn with unused movement, gain +2 Bonus Moves.",
    "thorns":             "Start with Thorns 2. Gain +1 Thorns when you take damage.",
    "thunderthighs":      "Trample. Contact effects from abilities/items apply when trampling.",
    "toadstyle":          "Movement action is a jump; landing on a unit deals damage and displaces it.",
    "wrestlemaniac":      "Basic attack becomes Suplex when adjacent to enemies. Gain Toss ability.",
    # Psychic passives
    "antigravity":        "Flying Movement. +1 SPD when using Gravity ability. Gravity costs -1 mana.",
    "beckon":             "Your basic attack has +4 Knockback.",
    "blink":              "33% chance to teleport to a random tile when targeted.",
    "eldritchvisage":     "Start of your turn: inflict Magic Weakness 1 on all enemies in line of sight.",
    "enlightened":        "While at full mana, the first spell you cast each turn is free.",
    "fullpower":          "While at full mana, basic attack deals triple damage and has +3 Knockback.",
    "glow":               "Your basic attack inflicts Blind.",
    "omniscience":        "All line-of-sight restrictions ignored. Hidden enemies are always highlighted.",
    "overflow":           "While at full mana, gain +2 Brace and Flying Movement. Mana is uncapped.",
    "psionicrepel":       "Units that attack or contact you get knocked back 10 tiles.",
    "psysmack":           "Knockback damage you and allies deal is doubled.",
    "soulshatter":        "When you kill a unit, deal 1 damage to all enemies.",
    "truesight":          "You and your allies can't miss enemies within your line of sight.",
    "wither":             "Gravity abilities inflict a random negative status on enemies.",
    # Necromancer passives
    "bedbugs":            "Start battles with 2 beefy leech familiars.",
    "cambionconception":  "When downed, spawn a demon kitten familiar.",
    "eternalhealth":      "Suffer only Jinxed when downed; heal to full when your party wins.",
    "infected":           "When you down a unit, reanimate it with 50% HP.",
    "lastgrasp":          "When downed, each enemy takes 6 damage and each ally heals 6 HP.",
    "leechmother":        "Your basic attack spawns a leech familiar.",
    "onewithnothing":     "If you end your turn with 0 mana, Mana Regeneration is doubled.",
    "parasitic":          "When you gain health, spawn a leech familiar.",
    "relentlessdead":     "At end of each round, spawn a Zombie kitten familiar onto a random tile.",
    "sacrificiallamb":    "When downed, allies gain All Stats Up and take an extra turn.",
    "soulbond":           "Your basic attack inflicts Soul Link.",
    "spreadsorrow":       "When you inflict a debuff, also inflict it on another random enemy.",
    "superstition":       "Basic attack inflicts -1 Luck. Units that damage you also lose 1 Luck.",
    "torpor":             "While downed, basic attack is Haunt. Your body gains +6 corpse HP.",
    "undeath":            "When downed, reanimate each ally to 33% HP. (Once per battle.)",
    "vampirism":          "Your basic attack has Lifesteal.",
    # Thief passives
    "afterimage":         "When you move, spawn a shadow that mimics your basic action.",
    "agile":              "+2 Movement Range. Move a 2nd time if not using full range.",
    "backstabber":        "Your backstabs are always critical.",
    "bountyhunter":       "During your turn, one random enemy has a Bounty.",
    "burgle":             "Your basic attack gains you 1 coin when it deals damage.",
    "cripple":            "Your critical hits inflict Immobilize and Weakness 2.",
    "critical":           "Critical hits deal +100% more damage. Gain +1 Luck per critical hit.",
    "doublethrow":        "Your basic attack hits twice for half damage.",
    "firststrike":        "Gain an extra turn at the start of battle.",
    "goldenclaws":        "+1 Damage for each coin you collect.",
    "more":               "When you kill a unit, refresh your movement action.",
    "penetrate":          "Basic attack passes through units and ignores shield. +1 Range.",
    "pinpoint":           "Your critical hits inflict Marked.",
    "poisontips":         "Your basic attack inflicts Poison 1.",
    "razorclaws":         "Your basic attack inflicts Bleed 1.",
    "shank":              "When behind an enemy, basic attack hits 2 times using Strength.",
    "shiv":               "Basic attack: +2 damage, +25% crit, inflicts Bleed 1 in melee range.",
    "stealthed":          "Start each battle with Stealth.",
    "sweetspot":          "+1 Range. Basic attack deals more damage the farther away you are.",
    "weakspot":           "Basic attack ignores shield and inflicts Weakness 1.",
    # Hunter passives
    "animalcontrol":      "Your basic attack causes units to immediately attack an enemy in range.",
    "broodmother":        "Familiars and Charmed units gain +2 Damage and +5 HP.",
    "bullseye":           "Your ranged attacks never miss. +25% critical hit chance.",
    "fleabag":            "Spawn Flea familiars equal to kills this battle when your turn ends.",
    "gravityfalls":       "+1 damage per tile beyond range 3.",
    "hazardous":          "Tile damage and effects are doubled.",
    "huntersboon":        "When you kill an enemy, gain 5 mana.",
    "luckswing":          "+50% critical hit chance but +25% miss chance.",
    "rubberarrows":       "Your projectiles bounce to another enemy within 3 tiles.",
    "sniper":             "Critical hits deal +100% damage and have 25% chance to inflict Stun.",
    "splitshot":          "Basic attack shoots multiple projectiles in a 5-tile cross (half damage each).",
    "survivalist":        "4 healing consumables and a water bottle added. +2 food stored after each battle.",
    "taintedmother":      "Familiars and Charmed units gain +4 Speed and inflict Poison and Bleed.",
    # Cleric passives
    "angelic":            "When you heal an ally, they also gain mana.",
    "blessed":            "Gain +1 to 2 random stats at the start of each turn.",
    "devoted":            "Healing you provide is doubled.",
    "holyaura":           "Allies adjacent to you gain +1 Brace.",
    "inspiration":        "When you heal an ally, they gain +1 Damage.",
    "martyrdom":          "When you take damage, all allies heal 1 HP.",
    "pacifist":           "Your basic attack heals instead of dealing damage.",
    "radiant":            "Your healing abilities also deal damage to nearby enemies.",
    "sanctuary":          "Allies in your line of sight are immune to debuffs.",
    "smite":              "Holy damage you deal is doubled.",
    # Mage passives
    "arcanemastery":      "Your spells cost 1 less mana.",
    "blastzone":          "Your AOE spells affect a larger area.",
    "crystalclear":       "While at full mana, your spells deal +2 damage.",
    "focused":            "+2 Intelligence. Your spells deal +1 damage.",
    "magicshield":        "Gain +1 Shield when you cast a spell.",
    "manaburn":           "Your spells inflict Mana Drain.",
    "overload":           "When you run out of mana, deal damage equal to mana spent to all nearby enemies.",
    "sorcerersoul":       "Access to Sorcerer class abilities when leveling up.",
    "spellweaver":        "Casting the same spell twice in a row doubles its damage.",
    "unstable":           "Your spells have 20% chance to be empowered for double damage.",
    # Monk passives
    "acrobatics":         "+2 Movement Range. You can move through enemies.",
    "concentration":      "If you don't move during your turn, your next attack is always critical.",
    "counterattack":      "When damaged in melee, automatically counter-attack.",
    "discipline":         "+2 to all stats at the start of each battle.",
    "flowstate":          "After using an ability, gain +1 Speed for the rest of your turn.",
    "harmonize":          "Your abilities heal allies they pass through.",
    "innerpeace":         "+1 Health Regeneration and +1 Mana Regeneration per turn.",
    "ironbody":           "+4 Constitution. You are immune to Stun and Immobilize.",
    "reflexes":           "+10% Dodge Chance. Dodging an attack gives you +1 Speed.",
    "zenmaster":          "While at full HP, all your abilities cost 0 mana.",
    # Druid passives
    "barkaspect":         "Gain +1 Brace when you take damage.",
    "earthbound":         "Immunity to knockback. Gain +2 Constitution.",
    "floral":             "Spawn flowers that heal adjacent allies each turn.",
    "growth":             "Gain +1 to a random stat at the end of each battle.",
    "naturecall":         "Spawn a random nature familiar at the start of each battle.",
    "photosynthesis":     "Regenerate 1 HP and 1 mana each turn when standing on grass/dirt.",
    "pollinate":          "Your familiars spread healing pollen to adjacent allies.",
    "primalrage":         "When you take damage, gain +1 Strength and +1 Speed (stacks).",
    "regrowth":           "When downed, revive with 25% HP once per battle.",
    "thornedbody":        "Units that attack you in melee take 2 damage.",
    # Jester passives
    "allofthem":          "Gain a copy of the last ability used by any unit this battle.",
    "alsorandom":         "At the start of your turn, gain a random status effect.",
    "chaosmagic":         "Your abilities have random additional effects.",
    "clumsy":             "50% chance to hit adjacent allies when attacking.",
    "copycat":            "Your basic attack copies the last ability used by an ally.",
    "gambler":            "At battle start, randomly gain or lose 1-3 of each stat.",
    "jackofalltrades":    "Gain one random ability from each class at the start of each battle.",
    "jinx":               "Units adjacent to you have -2 Luck.",
    "pandemonium":        "At the start of each round, swap positions with a random unit.",
    "pratfall":           "When you miss, all allies gain +1 Damage for the next attack.",
    # Soul passives
    "butcherssoul":       "Access to Butcher class abilities when leveling up.",
    "clericsoul":         "Access to Cleric class abilities when leveling up.",
    "druidsoul":          "Access to Druid class abilities when leveling up.",
    "fighterssoul":       "Access to Fighter class abilities when leveling up.",
    "hunterssoul":        "Access to Hunter class abilities when leveling up.",
    "jesterssoul":        "Access to Jester class abilities when leveling up.",
    "magessoul":          "Access to Mage class abilities when leveling up.",
    "monkssoul":          "Access to Monk class abilities when leveling up.",
    "necromancerssoul":   "Access to Necromancer class abilities when leveling up.",
    "psychicssoul":       "Access to Psychic class abilities when leveling up.",
    "tankssoul":          "Access to Tank class abilities when leveling up.",
    "thiefsoul":          "Access to Thief class abilities when leveling up.",
    "tinkerersoul":       "Access to Tinkerer class abilities when leveling up.",
    "voidsoul":           "Only upgraded Collarless abilities offered on level up. Collarless spells cost 1 less mana.",
}

_MUTATION_DISPLAY_NAMES: dict[str, str] = {
    "twoedarm": "Two-Toed Arm",
    "twotoedarm": "Two-Toed Arm",
    "twoedleg": "Two-Toed Leg",
    "twotoedleg": "Two-Toed Leg",
    "conjoinedbody": "Conjoined Body",
    "lumpybody": "Lumpy Body",
    "malnourishedbody": "Malnourished Body",
    "turnersyndrome": "Turner Syndrome",
    "williamssyndrome": "Williams Syndrome",
    "birdbeakears": "Bird Beak Ears",
    "floppyears": "Floppy Ears",
    "inwardeyes": "Inward Eyes",
    "redeyes": "Red Eyes",
    "bushyeyebrow": "Bushy Eyebrow",
    "noeyebrows": "No Eyebrows",
    "conjoinedtwin": "Conjoined Twin",
    "bentleg": "Bent Leg",
    "duckleg": "Duck Leg",
    "bentarm": "Bent Arm",
    "nomouth": "No Mouth",
    "cleftlip": "Cleft Lip",
    "lumpytail": "Lumpy Tail",
    "notail": "No Tail",
    "tailsack": "Tail Sack",
    "etank": "E-Tank",
    "deathsdoor": "Death's Door",
    "mightofthemeek": "Might of the Meek",
    "minime": "Mini-Me",
    "jackofalltrades": "Jack of All Trades",
    "slowandsteady": "Slow and Steady",
    "huntersboon": "Hunter's Boon",
    "holymantle": "Holy Mantle",
    "pawmissile": "Paw Missile",
    "pawmissle": "Paw Missile",
    "butcherssoul": "Butcher's Soul",
    "clericsoul": "Cleric Soul",
    "druidsoul": "Druid Soul",
    "fighterssoul": "Fighter's Soul",
    "hunterssoul": "Hunter's Soul",
    "jesterssoul": "Jester's Soul",
    "magessoul": "Mage's Soul",
    "monkssoul": "Monk's Soul",
    "necromancerssoul": "Necromancer's Soul",
    "psychicssoul": "Psychic's Soul",
    "sorcerersoul": "Sorcerer Soul",
    "tankssoul": "Tank's Soul",
    "thiefsoul": "Thief Soul",
    "tinkerersoul": "Tinkerer Soul",
    "voidsoul": "Void Soul",
}

_ABILITY_KEY_ALIASES: dict[str, str] = {
    "holymantle": "holymantel",
    "pawmissle": "pawmissile",
}

# Populated at runtime by _load_ability_descriptions()
_ABILITY_DESC: dict[str, str] = {}

# {stripped_token: localized display name}, rebuilt by _load_ability_descriptions.
# Save files store internal tokens (BearHug, AnimateDead); since the 1.1 class
# rework many in-game display names diverge from the token (Grab, Eternal
# Servitude), so display must go through this map when the GPAK is loaded.
_ABILITY_NAMES: dict[str, str] = {}


def _strip_tier(name: str) -> tuple[str, int]:
    """Return (base_name, tier). 'TankSwap2' -> ('TankSwap', 2), 'TankSwap' -> ('TankSwap', 1)."""
    if len(name) > 1 and name[-1] == "2":
        return name[:-1], 2
    return name, 1


def _ability_display_name(name: str) -> str:
    """Return the in-game display name for an ability/passive token.

    Looks up the GPAK-derived name map (full token first, then the
    tier-stripped base so 'TankSwap2' resolves via 'TankSwap'); falls back to
    camel-case spacing of the raw token when the GPAK is not loaded.
    """
    key = re.sub(r'[^a-z0-9]', '', name.lower())
    display = _ABILITY_NAMES.get(key)
    if display:
        return display
    base, _tier = _strip_tier(name)
    base_key = re.sub(r'[^a-z0-9]', '', base.lower())
    display = _ABILITY_NAMES.get(base_key)
    if display:
        return display
    return _mutation_display_name(base)


def _mutation_display_name(name: str) -> str:
    """Return a human-readable display name for a mutation/ability identifier."""
    key = re.sub(r'[^a-z0-9]', '', name.lower())
    if key in _MUTATION_DISPLAY_NAMES:
        return _MUTATION_DISPLAY_NAMES[key]
    if key in _ABILITY_NAMES:
        return _ABILITY_NAMES[key]
    spaced = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
    spaced = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', spaced)
    if spaced == spaced.lower():
        return spaced.title()
    return spaced


def _trait_selector_summary(tip: str) -> str:
    """Condense a tooltip/detail string for use in the trait selector."""
    text = _extract_primary_language_text(str(tip or "").replace("\u00a0", " ").strip())
    if not text:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    if "(ID " in lines[0] and len(lines) >= 3:
        lines = lines[2:]
    if lines and lines[-1].startswith("Affects:"):
        lines = lines[:-1]

    text = " ".join(lines).strip()
    if not text:
        return ""

    effects = _mutation_stat_effects(text)
    if not effects:
        return ""

    return ", ".join(f"{amount} {label}" for label, amount in effects)


def _trait_selector_label(category: str, name: str, tip: str = "") -> str:
    """Build a clean dropdown label for a trait."""
    prefix_map = {
        "mutation": "[Mutation]",
        "defect": "[Birth Defect]",
        "passive": "[Passive/Disorder]",
        "disorder": "[Passive/Disorder]",
        "ability": "[Ability]",
    }
    prefix = prefix_map.get(category, f"[{category.title()}]")
    summary = _trait_selector_summary(tip)
    return f"{prefix} {name}{' — ' + summary if summary else ''}"


def _trait_display_kind(category: str) -> str:
    """Return a short human-readable category label for a trait."""
    return {
        "mutation": "Mutation",
        "defect": "Birth Defect",
        "passive": "Passive / Disorder",
        "disorder": "Passive / Disorder",
        "ability": "Ability",
    }.get(category, category.title())


def _trait_description_preview(tip: str) -> str:
    """Return a compact one-line preview of a trait's description."""
    text = _extract_primary_language_text(str(tip or "").replace("\u00a0", " ").strip())
    if not text:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    if "(ID " in lines[0] and len(lines) >= 3:
        lines = lines[2:]
    if lines and lines[-1].startswith("Affects:"):
        lines = lines[:-1]
    text = " ".join(lines).strip()
    if not text:
        return ""
    if _is_redundant_trait_metadata(text):
        return ""

    if re.fullmatch(r"[A-Z0-9_]+(?:_DESC)?", text):
        return ""

    return text


def _trait_visible_detail(tip: str) -> str:
    """Return the compact text we want to show for a trait in the browser."""
    summary = _trait_selector_summary(tip)
    if summary:
        return summary
    return _trait_description_preview(tip)


def _is_redundant_trait_metadata(text: str) -> bool:
    cleaned = " ".join(str(text or "").replace("\u00a0", " ").split()).strip()
    if "(ID " not in cleaned:
        return False
    if re.search(r"[+-]\s*\d", cleaned):
        return False
    if re.search(r"\b(gain|start|when|your|allies|enemies|chance|immune|battle|turn|damage|heal)\b", cleaned, re.IGNORECASE):
        return False
    return bool(
        re.fullmatch(r"(?:[A-Za-z]+(?: [A-Za-z]+)*) Mutation \(ID \d+\) [A-Za-z]+ \d+", cleaned)
        or re.fullmatch(r"(?:[A-Za-z]+(?: [A-Za-z]+)*) \(ID \d+\) [A-Za-z]+ \d+", cleaned)
    )


def _ability_tip(name: str) -> str:
    """Return a tooltip description for an ability/mutation name, or '' if unknown.

    Strips any trailing tier suffix ('2') before lookup so that 'TankSwap2'
    resolves the same as 'TankSwap' for the base description.

    Prefers the GPAK description when available (authoritative and complete);
    falls back to the hardcoded _ABILITY_LOOKUP when GPAK is not loaded.
    """
    base, _tier = _strip_tier(name)
    key = re.sub(r'[^a-z0-9]', '', base.lower())
    key = _ABILITY_KEY_ALIASES.get(key, key)
    return _ABILITY_DESC.get(key) or _ABILITY_LOOKUP.get(key, "")


def _ability_upgraded_tip(name: str, passive_tier: int = 1) -> str:
    """Return tooltip for an ability, appending the tier-2 description when upgraded.

    For active abilities the tier is auto-detected from a trailing '2' suffix.
    For passives, pass ``passive_tier`` from ``cat.passive_tiers``.
    The upgrade line is prefixed with '+' to distinguish it from the base description.
    """
    base, active_tier = _strip_tier(name)
    tier = active_tier if active_tier > 1 else passive_tier
    base_tip = _ability_tip(base)
    if tier < 2:
        return base_tip
    tier2_key = re.sub(r'[^a-z0-9]', '', base.lower()) + "2"
    upgrade_text = _ABILITY_DESC.get(tier2_key, "")
    if not upgrade_text:
        return base_tip
    if base_tip:
        return f"{base_tip}\n+ Upgraded: {upgrade_text}"
    return f"+ Upgraded: {upgrade_text}"


def _abilities_tooltip(cat: "Cat") -> str:
    passive_tiers = getattr(cat, "passive_tiers", {})
    lines: list[str] = []
    for ability in cat.abilities:
        base, tier = _strip_tier(ability)
        display = _ability_display_name(base)
        label = f"{display}+" if tier > 1 else display
        tip = _ability_upgraded_tip(ability)
        lines.append(label if not tip else f"{label}\n{tip}")
    for passive in cat.passive_abilities:
        tier = passive_tiers.get(passive, 1)
        name = _mutation_display_name(passive)
        label = f"● {name}+" if tier > 1 else f"● {name}"
        tip = _ability_upgraded_tip(passive, passive_tier=tier)
        lines.append(label if not tip else f"{label}\n{tip}")
    for disorder in cat.disorders:
        name = _mutation_display_name(disorder)
        tip = _ability_tip(disorder)
        lines.append(f"⚠ {name}" if not tip else f"⚠ {name}\n{tip}")
    return "\n\n".join(lines)


def _mutations_tooltip(cat: "Cat") -> str:
    parts: list[str] = []
    for text, tip in cat.mutation_chip_items:
        parts.append(tip or text)
    for text, tip in getattr(cat, "defect_chip_items", []):
        parts.append(f"⚠ {tip or text}")
    return "\n\n".join(parts)


_MUTATION_EFFECT_LABELS = {
    "strength": "STR",
    "str": "STR",
    "dexterity": "DEX",
    "dex": "DEX",
    "constitution": "CON",
    "con": "CON",
    "intelligence": "INT",
    "int": "INT",
    "speed": "SPD",
    "spd": "SPD",
    "charisma": "CHA",
    "cha": "CHA",
    "luck": "LCK",
    "lck": "LCK",
    "all stats": "All Stats",
    "crit chance": "Crit Chance",
    "critical chance": "Crit Chance",
    "critical hit chance": "Crit Chance",
    "dodge chance": "Dodge Chance",
    "movement range": "Move Range",
    "range": "Range",
    "damage": "Damage",
    "knockback damage": "Knockback Dmg",
    "knockback": "Knockback",
    "shield": "Shield",
    "brace": "Brace",
    "armor": "Armor",
    "vitality": "Vitality",
    "health regeneration": "HP Regen",
    "health regen": "HP Regen",
    "mana regeneration": "Mana Regen",
    "mana regen": "Mana Regen",
    "health": "HP",
    "mana": "Mana",
    "magic damage": "Magic Dmg",
    "bonus moves": "Bonus Moves",
    "corpse hp": "Corpse HP",
    "poison": "Poison",
    "bleed": "Bleed",
    "stun": "Stun",
    "weakness": "Weakness",
}

_MUTATION_EFFECT_LABEL_RE = "|".join(sorted((re.escape(k) for k in _MUTATION_EFFECT_LABELS), key=len, reverse=True))
_MUTATION_EFFECT_RE = re.compile(
    rf"(?P<sign>[+-])\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<pct>%?)\s*(?:to\s+)?(?P<label>{_MUTATION_EFFECT_LABEL_RE})\b",
    re.IGNORECASE,
)


def _ability_effect_lines(cat: "Cat") -> list[str]:
    passive_tiers = getattr(cat, "passive_tiers", {})
    lines: list[str] = []
    for ability in cat.abilities:
        base, tier = _strip_tier(ability)
        label = f"{base}+" if tier > 1 else base
        tip = _ability_upgraded_tip(ability).strip()
        if tip:
            lines.append(f"{label}: {tip}")
    for passive in cat.passive_abilities:
        tier = passive_tiers.get(passive, 1)
        name = _mutation_display_name(passive)
        label = f"{name}+" if tier > 1 else name
        tip = _ability_upgraded_tip(passive, passive_tier=tier).strip()
        if tip:
            lines.append(f"{label}: {tip}")
    return lines


def _mutation_stat_effects(text: str) -> list[tuple[str, str]]:
    """Extract compact numeric effect badges from mutation/defect text."""
    if not text:
        return []
    effects: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _MUTATION_EFFECT_RE.finditer(text):
        label = _MUTATION_EFFECT_LABELS.get(match.group("label").strip().casefold(), match.group("label").strip())
        amount = f"{match.group('sign')}{match.group('value')}{match.group('pct')}"
        key = (label, amount)
        if key in seen:
            continue
        seen.add(key)
        effects.append((label, amount))
    return effects


def _mutation_effect_components(tip: str) -> tuple[str, list[tuple[str, str]], list[str]]:
    """
    Return a compact summary, numeric effect badges, and affected slots for a
    mutation/defect tooltip.
    """
    lines = [line.strip() for line in str(tip or "").splitlines() if line.strip()]
    detail = "\n".join(lines[2:]) if len(lines) > 2 else ""
    summary = _trait_description_preview(detail)
    effects = _mutation_stat_effects(detail)
    if effects and summary.startswith(("+", "-")):
        summary = ""
    affects = []
    match = re.search(r"\bAffects:\s*(.+)$", str(tip or ""), re.IGNORECASE | re.MULTILINE)
    if match:
        affects = [part.strip() for part in re.split(r"\s*,\s*", match.group(1).strip()) if part.strip()]
    return summary, effects, affects


def _mutation_effect_lines(cat: "Cat") -> list[str]:
    lines: list[str] = []
    for text, tip in cat.mutation_chip_items:
        cleaned = tip.strip()
        if not cleaned:
            continue
        if cleaned == text:
            lines.append(text)
        else:
            lines.append(cleaned.replace("\n", " | "))
    return lines


def _read_db_key_candidates(raw: bytes, self_key: int, offsets: tuple[int, ...], base_offset: int = 0) -> list[int]:
    keys: list[int] = []
    for off in offsets:
        pos = base_offset + off
        if pos < 0 or pos + 4 > len(raw):
            continue
        try:
            value = struct.unpack_from('<I', raw, pos)[0]
        except Exception:
            continue
        if value in (0, 0xFFFF_FFFF) or value == self_key:
            continue
        if value not in keys:
            keys.append(value)
    return keys


def _trait_inheritance_probabilities(
    a: "Cat", b: "Cat", stimulation: float,
) -> list[tuple[str, str, float, str]]:
    """
    Calculate per-trait inheritance probabilities using game formulas.
    Returns (display_name, category, probability, source_detail) tuples.
    """
    stim = max(0.0, min(100.0, float(stimulation)))
    favor_weight = _stimulation_inheritance_weight(stim)
    results: list[tuple[str, str, float, str]] = []

    a_has_skillshare = any(
        p.lower() in ("skillshare", "skillshare+", "skillshareplus")
        for p in (a.passive_abilities or [])
    )
    b_has_skillshare = any(
        p.lower() in ("skillshare", "skillshare+", "skillshareplus")
        for p in (b.passive_abilities or [])
    )

    # Active abilities
    ability_base = 0.2 + 0.025 * stim
    a_abilities = list(a.abilities or [])
    b_abilities = list(b.abilities or [])
    seen: dict[str, tuple[float, str]] = {}
    b_keys = {x.lower() for x in b_abilities}

    for ab in a_abilities:
        key = ab.lower()
        prob_a = ability_base * favor_weight / len(a_abilities)
        if key in b_keys:
            prob_b = ability_base * (1.0 - favor_weight) / len(b_abilities)
            prob = min(1.0, prob_a + prob_b)
            seen[key] = (prob, f"Both parents ({prob * 100:.0f}%)")
        else:
            seen[key] = (prob_a, f"From {a.name} ({prob_a * 100:.0f}%)")

    for ab in b_abilities:
        key = ab.lower()
        if key not in seen:
            prob_b = ability_base * (1.0 - favor_weight) / len(b_abilities)
            seen[key] = (prob_b, f"From {b.name} ({prob_b * 100:.0f}%)")

    for key, (prob, detail) in seen.items():
        display = key
        for ab in a_abilities + b_abilities:
            if ab.lower() == key:
                display = ab
                break
        results.append((display, "ability", prob, detail))

    # Passive abilities
    passive_base = 0.05 + 0.01 * stim
    a_passives = list(a.passive_abilities or [])
    b_passives = list(b.passive_abilities or [])
    seen_p: dict[str, tuple[float, str]] = {}
    b_pkeys = {x.lower() for x in b_passives}

    for pa in a_passives:
        key = pa.lower()
        if a_has_skillshare:
            seen_p[key] = (1.0, f"SkillShare+ from {a.name} (100%)")
        else:
            prob_a = passive_base * favor_weight / len(a_passives)
            if key in b_pkeys:
                prob_b = 1.0 if b_has_skillshare else passive_base * (1.0 - favor_weight) / len(b_passives)
                prob = min(1.0, prob_a + prob_b)
                seen_p[key] = (prob, f"Both parents ({prob * 100:.0f}%)")
            else:
                seen_p[key] = (prob_a, f"From {a.name} ({prob_a * 100:.0f}%)")

    for pa in b_passives:
        key = pa.lower()
        if key not in seen_p:
            if b_has_skillshare:
                seen_p[key] = (1.0, f"SkillShare+ from {b.name} (100%)")
            else:
                prob_b = passive_base * (1.0 - favor_weight) / len(b_passives)
                seen_p[key] = (prob_b, f"From {b.name} ({prob_b * 100:.0f}%)")

    for key, (prob, detail) in seen_p.items():
        results.append((_mutation_display_name(key), "passive", prob, detail))

    # Visual mutations
    mutation_base = 0.80
    a_mutations = list(a.mutations or [])
    b_mutations = list(b.mutations or [])
    seen_m: dict[str, tuple[float, str]] = {}
    b_mkeys = {x.lower() for x in b_mutations}

    for mut in a_mutations:
        key = mut.lower()
        if key in b_mkeys:
            seen_m[key] = (mutation_base, f"Both parents ({mutation_base * 100:.0f}%)")
        else:
            prob = mutation_base * favor_weight
            seen_m[key] = (prob, f"From {a.name} ({prob * 100:.0f}%)")

    for mut in b_mutations:
        key = mut.lower()
        if key not in seen_m:
            prob = mutation_base * (1.0 - favor_weight)
            seen_m[key] = (prob, f"From {b.name} ({prob * 100:.0f}%)")

    for key, (prob, detail) in seen_m.items():
        results.append((_mutation_display_name(key), "mutation", prob, detail))

    results.sort(key=lambda x: (-x[2], x[0].lower()))
    return results


def _load_ability_descriptions(gpak_path: str | None) -> dict[str, str]:
    """
    Build {normalized_ability_id: english_desc} by reading ability/passive GON files
    and combined.csv from the game's gpak. Returns {} if gpak is unavailable.

    Side effect: also rebuilds _ABILITY_NAMES from the same GON pass — each
    block's ``name "STRING_KEY"`` field resolved through the text tables, with
    ``variant_of`` chains followed so variants (BasicStraightShot_Thief,
    Pierce2, ...) inherit their base ability's display name. Save files store
    internal tokens; since the 1.1 class rework many display names diverge
    from their token (BearHug -> "Grab"), so tokens can no longer be shown
    verbatim.
    """
    if not gpak_path:
        return {}
    try:
        with open(gpak_path, "rb") as f:
            count = struct.unpack("<I", f.read(4))[0]
            entries = []
            for _ in range(count):
                name_len = struct.unpack("<H", f.read(2))[0]
                name = f.read(name_len).decode("utf-8", errors="replace")
                size = struct.unpack("<I", f.read(4))[0]
                entries.append((name, size))
            dir_end = f.tell()

            file_offsets: dict[str, tuple[int, int]] = {}
            offset = dir_end
            for name, size in entries:
                file_offsets[name] = (offset, size)
                offset += size

            game_strings = _load_gpak_text_strings(f, file_offsets)

            block_re = re.compile(r'^([A-Za-z]\w*)\s*\{', re.MULTILINE)
            desc_re = re.compile(r'^\s*desc\s+"([^"]*)"', re.MULTILINE)
            name_re = re.compile(r'^\s*name\s+"([^"]*)"', re.MULTILINE)
            variant_re = re.compile(r'^\s*variant_of\s+(\w+)', re.MULTILINE)
            tier2_block_re = re.compile(r'^\s*2\s*\{', re.MULTILINE)

            # token -> (name string key or None, variant_of token or None),
            # keyed by lowercased GON block id.
            name_info: dict[str, tuple[str | None, str | None]] = {}

            def _clean(text: str) -> str:
                text = re.sub(r'\[img:[^\]]+\]', '', text)
                text = re.sub(r'\[s:[^\]]*\]|\[/s\]', '', text)
                text = re.sub(r'\[c:[^\]]*\]|\[/c\]', '', text)
                return re.sub(r'\s+', ' ', text).strip()

            def _is_unresolved_key(text: str) -> bool:
                # A desc/name that still looks like a raw string key
                # (PASSIVE_LUCKY_DESC) means the text tables have no entry —
                # never surface it in the UI; fall back to hardcoded lookups.
                return bool(re.fullmatch(r'[A-Z0-9_]+', text or ''))

            result: dict[str, str] = {}
            for fname, (foff, fsz) in file_offsets.items():
                if not (
                    (fname.startswith("data/abilities/") or fname.startswith("data/passives/"))
                    and fname.endswith(".gon")
                ):
                    continue
                f.seek(foff)
                content = f.read(fsz).decode("utf-8", errors="replace")
                for bm in block_re.finditer(content):
                    ability_id = bm.group(1)
                    block_start = bm.end()
                    depth, idx = 1, block_start
                    while idx < len(content) and depth > 0:
                        if content[idx] == '{':
                            depth += 1
                        elif content[idx] == '}':
                            depth -= 1
                        idx += 1
                    block = content[block_start:idx - 1]
                    base_key = ability_id.lower()

                    nm = name_re.search(block)
                    vm = variant_re.search(block)
                    name_info[base_key] = (
                        nm.group(1) if nm else None,
                        vm.group(1).lower() if vm else None,
                    )

                    dm = desc_re.search(block)
                    if dm:
                        desc_val = dm.group(1)
                        desc_val = game_strings.get(desc_val, desc_val)
                        desc_val = _resolve_game_string(desc_val, game_strings)
                        if desc_val and desc_val != "nothing" and not _is_unresolved_key(desc_val):
                            result[base_key] = _clean(desc_val)

                    # Passive GON files use nested tier blocks: 2 { desc "..." }
                    # Active ability tier-2 variants are separate top-level blocks and
                    # are already captured above, so only write if not yet present.
                    tier2_key = base_key + "2"
                    if tier2_key not in result:
                        t2m = tier2_block_re.search(block)
                        if t2m:
                            t2_start = t2m.end()
                            t2_depth, t2_idx = 1, t2_start
                            while t2_idx < len(block) and t2_depth > 0:
                                if block[t2_idx] == '{':
                                    t2_depth += 1
                                elif block[t2_idx] == '}':
                                    t2_depth -= 1
                                t2_idx += 1
                            t2_block = block[t2_start:t2_idx - 1]
                            t2dm = desc_re.search(t2_block)
                            if t2dm:
                                t2_desc = t2dm.group(1)
                                t2_desc = game_strings.get(t2_desc, t2_desc)
                                t2_desc = _resolve_game_string(t2_desc, game_strings)
                                if t2_desc and t2_desc != "nothing" and not _is_unresolved_key(t2_desc):
                                    result[tier2_key] = _clean(t2_desc)

            # Resolve display names: follow variant_of chains until a block
            # with a name key is found, then look the key up in the text
            # tables. Store under _ability_tip's stripped normalization so
            # underscore tokens (BasicStraightShot_Thief) resolve too.
            names: dict[str, str] = {}
            for token in name_info:
                key, seen = token, set()
                display = None
                while key in name_info and key not in seen:
                    seen.add(key)
                    name_key, variant_of = name_info[key]
                    if name_key:
                        raw = game_strings.get(name_key, name_key)
                        resolved = _resolve_game_string(raw, game_strings)
                        if not _is_unresolved_key(resolved):
                            display = _clean(resolved)
                        break
                    if not variant_of:
                        break
                    key = variant_of
                if display:
                    names[re.sub(r'[^a-z0-9]', '', token)] = display
            _ABILITY_NAMES.clear()
            _ABILITY_NAMES.update(names)
        return result
    except Exception:
        return {}


def _cat_has_trait(cat: 'Cat', category: str, trait_key: str) -> bool:
    """Check whether *cat* carries the given trait (mutation/passive/ability)."""
    if category == "mutation":
        if '|' in trait_key:
            mid = int(trait_key.rsplit('|', 1)[1])
            return mid in (getattr(cat, "visual_mutation_ids", []) or [])
        return any(m.lower() == trait_key for m in getattr(cat, "mutations", []) or [])
    elif category == "defect":
        if '|' in trait_key:
            mid = int(trait_key.rsplit('|', 1)[1])
            entries = getattr(cat, "visual_mutation_entries", []) or []
            return any(int(e["mutation_id"]) == mid and e.get("is_defect") for e in entries)
        return any(d.lower() == trait_key for d in getattr(cat, "defects", []) or [])
    elif category == "passive":
        return any(p.lower() == trait_key for p in getattr(cat, "passive_abilities", []) or [])
    elif category == "disorder":
        return any(d.lower() == trait_key for d in getattr(cat, "disorders", []) or [])
    elif category == "ability":
        return any(a.lower() == trait_key for a in getattr(cat, "abilities", []) or [])
    return False


def _planner_trait_display_name(display: str) -> str:
    text = str(display or "").strip()
    if "] " in text:
        return text.split("] ", 1)[1]
    return text


def _planner_trait_name_palette(weight: float) -> tuple[str, str, str]:
    if float(weight or 0) > 0:
        return ("#d7f0e3", "#203a31", "#4f7b67")
    if float(weight or 0) < 0:
        return ("#f1d8de", "#412b31", "#855b64")
    return ("#dddddd", "", "")


def _planner_trait_weight(traits: Sequence[dict], *, category: str = "", key: str = "", display: str = "") -> float:
    want_category = str(category or "").strip().lower()
    want_key = str(key or "").strip().lower()
    want_display = re.sub(r"[^a-z0-9]", "", _planner_trait_display_name(display).lower())
    fallback = 0.0
    for trait in traits or []:
        if not isinstance(trait, dict):
            continue
        trait_category = str(trait.get("category") or "").strip().lower()
        trait_key = str(trait.get("key") or "").strip().lower()
        try:
            weight = float(trait.get("weight", 0) or 0)
        except (TypeError, ValueError):
            weight = 0.0
        if want_category and want_key and trait_category == want_category and trait_key == want_key:
            return weight
        if want_display:
            trait_display = re.sub(
                r"[^a-z0-9]",
                "",
                _planner_trait_display_name(str(trait.get("display") or trait.get("key") or "")).lower(),
            )
            if trait_display == want_display:
                fallback = weight
    return fallback


def _planner_trait_name_html(name: str, weight: float) -> str:
    text = html.escape(str(name or "").strip() or "?")
    fg, bg, border = _planner_trait_name_palette(weight)
    if not bg:
        return text
    return (
        f"<span style=\"color:{fg}; background-color:{bg}; border:1px solid {border};"
        " border-radius:3px; padding:1px 4px;\">"
        f"{text}</span>"
    )
