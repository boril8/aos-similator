# AoS Simulator

A CLI damage simulator for **Age of Sigmar 4th Edition** spearheads. Calculate expected damage, probability distributions, and generate Markdown reference sheets from spearhead data.

## Installation

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync
```

## Commands

### `damage` — Expected damage vs every save

Shows expected damage per weapon across all save values (2+–no save), with conditional rows for abilities and combined totals for every buff combination.

```
uv run aos-sim damage <faction> <unit>
```

**Options:**
- `--ward / -w <N>` — target has a ward save (e.g. `-w 6` for 6+)
- `--charging / -c` — apply Charge (+1 Damage) bonuses

**Example:**

```
uv run aos-sim damage skaven clawlord
```

```
╭──────────────────────────────────────────────────────────────╮
│ Clawlord on Gnaw-beast                                       │
│ Skaven · Gnawfeast Clawpack                                  │
│ 1 model · Move 9" · Health 7 · Save 4+ · Ward 6+ · Control 2 │
│ Hero, Cavalry                                                │
╰──────────────────────────────────────────────────────────────╯

 Weapon                                        T   Atk     2+     3+     4+     5+     6+     —
────────────────────────────────────────────────────────────────────────────────────────────────
 Ratling Pistol                                R   3.5   0.58   0.88   1.17   1.46   1.75   1.75
 (Skryre Connections)                                  (1.17) (1.75) (2.33) (2.92) (3.50) (3.50)
 Warpforged Halberd                            M     5   1.11   1.67   2.22   2.78   3.33   3.33
 (Cornered Rat)                                        (1.78) (2.67) (3.56) (4.44) (5.33) (5.33)
 Gnaw-beast's Chisel Fangs                     M     4   0.89   1.33   1.78   2.22   2.67   2.67

 Total                                                  2.58   3.88   5.17   6.46   7.75   7.75
 Total (Cornered Rat)                                  (3.25) (4.88) (6.50) (8.12) (9.75) (9.75)
 Total (Skryre Connections)                            (3.17) (4.75) (6.33) (7.92) (9.50) (9.50)
 Total (Cornered Rat) + (Skryre Connections)           (3.83) (5.75) (7.67) (9.58)(11.50)(11.50)
```

Indented rows in parentheses show the buffed value for that ability. Total rows enumerate every combination of applicable buffs.

---

### `distribution` — Damage probability distribution

Monte Carlo simulation showing the probability of each damage outcome for a specific save value.

```
uv run aos-sim distribution <faction> <unit> <save> [ward]
```

**Options:**
- `--charging / -c` — apply Charge (+1 Damage) bonuses
- `--runs / -n <N>` — number of simulations (default: 10 000)

**Example:**

```
uv run aos-sim distribution skaven clawlord 4
uv run aos-sim distribution skaven clawlord 4 6   # target has 6+ ward
```

---

### `generate` — Markdown reference sheets

Generates `.md` files from spearhead JSON data — full stat blocks, weapons, and abilities, without lore.

```
uv run aos-sim generate [faction] [spearhead] [--dir <path>]
```

- No arguments: generates everything
- Faction only: generates all spearheads for that faction
- Faction + spearhead: generates one file

Files are written to `output/` by default, named `<faction>_<spearhead>.md`.

**Examples:**

```bash
uv run aos-sim generate                        # all spearheads
uv run aos-sim generate skaven                 # all Skaven spearheads
uv run aos-sim generate sylvaneth spitewing    # one spearhead
uv run aos-sim generate skaven --dir sheets/   # custom output directory
```

---

## Unit lookup

All commands accept a unit name, substring, spearhead short name, or unit short name:

```bash
uv run aos-sim damage soulblight vampire      # short name → Vampire Lord
uv run aos-sim damage soulblight knights      # short name → Blood Knights
uv run aos-sim damage stormcast yndrasta      # spearhead short name → all units
uv run aos-sim damage sylvaneth "Gossamid"    # substring match
```

---

## Spearhead data

Spearhead definitions live in `data/factions/` as JSON files. Each file covers one spearhead and includes units, weapons, passive abilities, battle traits, regiment abilities, and enhancements.

### Supported factions

| Faction short name | Spearhead |
|---|---|
| `skaven` | Gnawfeast Clawpack, Warpspark Convocation |
| `soulblight` | Bloodcrave Hunt, Deathrattle Legion |
| `stormcast` | Lord-Vigilant's Spearhead, Yndrasta's Spearhead |
| `sylvaneth` | Spitewing Flight |

### Modelled abilities

- Weapon abilities: `Crit (Mortal)`, `Crit (2 Hits)`, `Crit (Auto-wound)`, `Crit (D6 Hits)`, `Charge (+1 Damage)`, `Companion`, `Shoot in Combat`, `Mortal per Hit`
- Unit abilities: conditional buffs, `self_damage_then_buff`, `weapon_override`, `weapon_override_with_risk`
- General's auras: `friendly_buff` (hit/wound bonus) applied to all units in scope, with `exclusive_group` for mutually exclusive states (e.g. Song of the Hunt chord stages)
- Enhancement abilities: `weapon_override` (general only), `friendly_buff` (army-wide)
- Regiment abilities: `friendly_buff` for non-hero units
- `target_weapons` field restricts a buff to `"melee"` or `"ranged"`; omit to apply to all weapons

---

## Development

```bash
uv run aos-sim --help
uv run python -c "from aos_sim import calculator; ..."
```
