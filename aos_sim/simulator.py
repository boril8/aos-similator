import random
import re
from collections import Counter
from typing import Optional

from .models import WeaponProfile
from .calculator import (
    CRIT_MORTAL, CRIT_2_HITS, CRIT_AUTO_WOUND, CRIT_D6_HITS,
    MORTAL_PER_HIT, CHARGE_PLUS1,
)


def _roll(expr: str) -> int:
    s = str(expr).strip().upper()
    m = re.match(r'^(\d*)D(\d+)([+-]\d+)?$', s)
    if m:
        mult   = int(m.group(1)) if m.group(1) else 1
        sides  = int(m.group(2))
        mod    = int(m.group(3)) if m.group(3) else 0
        return sum(random.randint(1, sides) for _ in range(mult)) + mod
    return int(float(s))


def _ward_filter(damage: int, target_ward: Optional[int]) -> int:
    """Return damage points that survive ward saves (per-point rolls)."""
    if not target_ward or damage <= 0:
        return damage
    return sum(1 for _ in range(damage) if random.randint(1, 6) < target_ward)


def simulate_weapon(
    weapon: WeaponProfile,
    model_count: int,
    target_save: int,
    target_ward: Optional[int] = None,
    is_charging: bool = False,
    n_runs: int = 10_000,
) -> Counter:
    """Monte Carlo: returns {damage_value: count} over n_runs combat rounds."""
    counts: Counter = Counter()
    abilities  = weapon.abilities or []
    equipped   = weapon.models_equipped if weapon.models_equipped is not None else model_count
    eff_save   = target_save + weapon.rend   # > 6 → save always fails

    for _ in range(n_runs):
        n_atk  = _roll(weapon.attacks) * equipped
        total  = 0

        for __ in range(n_atk):
            hit_roll = random.randint(1, 6)
            is_crit  = (hit_roll == 6)
            is_hit   = (hit_roll >= weapon.hit)

            if MORTAL_PER_HIT in abilities:
                if is_hit:
                    total += _ward_filter(1, target_ward)
                continue

            # Resolve which wounds to attempt based on crit ability
            wounds: list[bool] = []   # True = auto-wound, False = normal wound roll

            if CRIT_MORTAL in abilities:
                if is_crit:
                    total += _ward_filter(1, target_ward)
                    continue   # crit consumes the attack
                if is_hit:
                    wounds = [False]

            elif CRIT_2_HITS in abilities:
                if is_crit:
                    wounds = [False, False]
                elif is_hit:
                    wounds = [False]

            elif CRIT_AUTO_WOUND in abilities:
                if is_crit:
                    wounds = [True]
                elif is_hit:
                    wounds = [False]

            elif CRIT_D6_HITS in abilities:
                if is_crit:
                    wounds = [False] * _roll("D6")
                elif is_hit:
                    wounds = [False]

            else:
                if is_hit:
                    wounds = [False]

            for auto_wound in wounds:
                if not auto_wound and random.randint(1, 6) < weapon.wound:
                    continue
                if eff_save <= 6 and random.randint(1, 6) >= eff_save:
                    continue
                dmg = _roll(weapon.damage)
                if is_charging and CHARGE_PLUS1 in abilities:
                    dmg += 1
                total += _ward_filter(dmg, target_ward)

        counts[total] += 1

    return counts
