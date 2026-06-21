from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WeaponProfile:
    name: str
    type: str                          # "melee" | "ranged"
    attacks: str                       # dice expression: "5", "D6", "2D6", "D3+3"
    hit: int                           # minimum roll to hit (e.g. 4 for 4+)
    wound: int                         # minimum roll to wound (7 = N/A, handled by ability)
    rend: int
    damage: str                        # dice expression
    abilities: list[str] = field(default_factory=list)
    range: Optional[int] = None        # inches, ranged weapons only
    models_equipped: Optional[int] = None  # when only some models carry this weapon
    note: Optional[str] = None


@dataclass
class UnitStats:
    move: int
    health: int                        # per model
    save: int                          # minimum roll (e.g. 4 for 4+)
    ward: Optional[int]                # minimum roll, None = no ward
    control: int                       # per model


@dataclass
class Unit:
    name: str
    role: str                          # "general" | "unit"
    unit_count: int                    # number of this unit in the spearhead
    model_count: int                   # models per unit
    keywords: list[str]
    stats: UnitStats
    weapons: list[WeaponProfile]
    passive_abilities: list[dict] = field(default_factory=list)
    spearhead_name: str = ""
    faction: str = ""
    faction_short: str = ""


@dataclass
class Spearhead:
    name: str
    short_name: str
    faction: str
    faction_short: str
    battle_traits: list[dict]
    regiment_abilities: list[dict]
    enhancements: list[dict]
    units: list[Unit]
