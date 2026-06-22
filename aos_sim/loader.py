import json
from pathlib import Path
from .models import WeaponProfile, UnitStats, Unit, Spearhead

DATA_DIR = Path(__file__).parent.parent / "data" / "factions"


def load_spearhead(path: Path) -> Spearhead:
    with open(path) as f:
        data = json.load(f)

    units = []
    for u in data["units"]:
        s = u["stats"]
        stats = UnitStats(
            move=s["move"],
            health=s["health"],
            save=s["save"],
            ward=s.get("ward"),
            control=s["control"],
        )
        weapons = []
        for w in u["weapons"]:
            weapons.append(WeaponProfile(
                name=w["name"],
                type=w["type"],
                attacks=str(w["attacks"]),
                hit=w.get("hit") or 7,
                wound=w.get("wound") or 7,   # 7 = impossible; handled by ability
                rend=w.get("rend") or 0,
                damage=str(w["damage"]) if w.get("damage") is not None else "0",
                abilities=w.get("abilities") or [],
                range=w.get("range"),
                models_equipped=w.get("models_equipped"),
                note=w.get("note"),
            ))
        units.append(Unit(
            name=u["name"],
            short_name=u.get("short_name", ""),
            role=u.get("role", "unit"),
            unit_count=u.get("unit_count", 1),
            model_count=u.get("model_count", 1),
            keywords=u.get("keywords") or [],
            stats=stats,
            weapons=weapons,
            passive_abilities=u.get("passive_abilities") or [],
            spearhead_name=data["name"],
            faction=data["faction"],
            faction_short=data["faction_short"],
        ))

    return Spearhead(
        name=data["name"],
        short_name=data.get("short_name", ""),
        faction=data["faction"],
        faction_short=data["faction_short"],
        battle_traits=data.get("battle_traits") or [],
        regiment_abilities=data.get("regiment_abilities") or [],
        enhancements=data.get("enhancements") or [],
        units=units,
    )


def load_all_spearheads() -> list[Spearhead]:
    return [load_spearhead(p) for p in sorted(DATA_DIR.glob("*.json"))]


def find_units(faction_short: str, unit_name: str) -> list[tuple[Unit, Spearhead]]:
    """Return all distinct (unit, spearhead) pairs matching faction + name substring.

    If unit_name matches a spearhead's short_name (case-insensitive), all units
    in that spearhead are returned instead of filtering by unit name.
    """
    name_lower = unit_name.lower().strip()
    faction_lower = faction_short.lower().strip()

    seen: set[tuple[str, str]] = set()
    results: list[tuple[Unit, Spearhead]] = []

    for path in sorted(DATA_DIR.glob("*.json")):
        spearhead = load_spearhead(path)
        if spearhead.faction_short.lower() != faction_lower:
            continue

        spearhead_match = spearhead.short_name.lower() == name_lower

        for unit in spearhead.units:
            key = (spearhead.name, unit.name)
            if key in seen:
                continue
            unit_match = (
                name_lower in unit.name.lower()
                or (unit.short_name and unit.short_name.lower() == name_lower)
            )
            if spearhead_match or unit_match:
                seen.add(key)
                results.append((unit, spearhead))

    return results
