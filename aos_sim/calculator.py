"""
Analytical damage calculator for Age of Sigmar (4th edition).

DamageCalculator computes expected damage values from weapon profiles.
The design intentionally separates probability math from dice rolling so
a future DamageSimulator can reuse the same interface with Monte-Carlo
rolls instead of closed-form expectations.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from .models import WeaponProfile, Unit


# ── Ability tags recognised by the calculator ───────────────────────────────

CRIT_MORTAL     = "Crit (Mortal)"       # crit hit → 1 mortal damage
CRIT_2_HITS     = "Crit (2 Hits)"       # crit hit → 2 hits
CRIT_AUTO_WOUND = "Crit (Auto-wound)"   # crit hit → skip wound roll
CRIT_D6_HITS    = "Crit (D6 Hits)"      # crit hit → D6 hits (avg 3.5)
MORTAL_PER_HIT  = "Mortal per Hit"      # every hit → 1 mortal, ignores save
CHARGE_PLUS1    = "Charge (+1 Damage)"  # +1 damage when charging
COMPANION       = "Companion"           # mount weapon; no buff eligibility (no math change)


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class WeaponResult:
    weapon_name: str
    weapon_type: str
    avg_attacks: float          # total expected attacks (all equipped models)
    p_hit: float
    p_wound: float
    p_not_saved: float          # at the requested target save
    avg_damage: float           # expected damage per wound that passes save
    expected_damage: float      # final expected damage
    models_contributing: int
    notes: list[str] = field(default_factory=list)


@dataclass
class UnitResult:
    unit_name: str
    model_count: int
    target_save: int            # 2-7; 7 means "no save"
    target_ward: Optional[int]
    weapons: list[WeaponResult]
    total: float


# ── Calculator ────────────────────────────────────────────────────────────────

class DamageCalculator:
    """
    Computes expected damage analytically.

    Convention for save values: the integer is the minimum D6 roll required
    (e.g. 4 for a 4+ save). Pass 7 for "no save / unmodifiable".
    Rend is added to the save threshold, increasing it (harder to save).
    Ward saves also use the minimum-roll convention and are applied after
    regular saves and to mortal wounds.
    """

    # ── Dice ─────────────────────────────────────────────────────────────────

    def parse_dice(self, expr: str) -> float:
        """Expected value of a dice expression: '5', 'D6', '2D6', 'D3+3'."""
        if expr is None:
            return 0.0
        s = str(expr).strip().upper()
        m = re.match(r'^(\d*)D(\d+)([+-]\d+)?$', s)
        if m:
            mult = int(m.group(1)) if m.group(1) else 1
            sides = int(m.group(2))
            mod = int(m.group(3)) if m.group(3) else 0
            return mult * (sides + 1) / 2 + mod
        try:
            return float(s)
        except ValueError:
            return 0.0

    # ── Probability helpers ──────────────────────────────────────────────────

    def p_success(self, target: int) -> float:
        """P(D6 >= target)."""
        if target <= 1:
            return 1.0
        if target > 6:
            return 0.0
        return (7 - target) / 6

    def p_save(self, save: int, rend: int) -> float:
        return self.p_success(save + rend)

    # ── Core weapon calculation ───────────────────────────────────────────────

    def weapon_damage(
        self,
        weapon: WeaponProfile,
        model_count: int,
        target_save: int,
        target_ward: Optional[int] = None,
        is_charging: bool = False,
    ) -> WeaponResult:
        abilities = weapon.abilities or []
        notes: list[str] = []

        equipped = weapon.models_equipped if weapon.models_equipped is not None else model_count
        avg_attacks = self.parse_dice(weapon.attacks) * equipped
        avg_dmg = self.parse_dice(weapon.damage)

        if is_charging and CHARGE_PLUS1 in abilities:
            avg_dmg += 1
            notes.append("charging (+1 dmg)")

        p_hit   = self.p_success(weapon.hit)
        p_wound = self.p_success(weapon.wound)

        ps = self.p_save(target_save, weapon.rend)
        p_not_saved = 1.0 - ps

        p_ward = self.p_success(target_ward) if target_ward else 0.0
        p_not_warded = 1.0 - p_ward

        expected = self._expected(
            avg_attacks, p_hit, p_wound, p_not_saved, avg_dmg,
            abilities, p_not_warded, notes,
        )

        return WeaponResult(
            weapon_name=weapon.name,
            weapon_type=weapon.type,
            avg_attacks=avg_attacks,
            p_hit=p_hit,
            p_wound=p_wound,
            p_not_saved=p_not_saved,
            avg_damage=avg_dmg,
            expected_damage=round(expected, 3),
            models_contributing=equipped,
            notes=notes,
        )

    def unit_damage(
        self,
        unit: Unit,
        target_save: int,
        target_ward: Optional[int] = None,
        is_charging: bool = False,
    ) -> UnitResult:
        weapon_results = [
            self.weapon_damage(w, unit.model_count, target_save, target_ward, is_charging)
            for w in unit.weapons
        ]
        total = sum(r.expected_damage for r in weapon_results)
        return UnitResult(
            unit_name=unit.name,
            model_count=unit.model_count,
            target_save=target_save,
            target_ward=target_ward,
            weapons=weapon_results,
            total=round(total, 3),
        )

    # ── Healing ──────────────────────────────────────────────────────────────

    def heal_from_crits(self, unit: Unit, heal_per_crit: float) -> float:
        """Expected healing when an ability heals N per critical hit (any weapon)."""
        total_attacks = sum(
            self.parse_dice(w.attacks) * (w.models_equipped if w.models_equipped is not None else unit.model_count)
            for w in unit.weapons
        )
        return round(total_attacks / 6 * heal_per_crit, 3)

    # ── Damage formula dispatch ───────────────────────────────────────────────

    def _expected(
        self,
        attacks: float,
        p_hit: float,
        p_wound: float,
        p_not_saved: float,
        avg_dmg: float,
        abilities: list[str],
        p_not_warded: float,
        notes: list[str],
    ) -> float:
        p_crit        = 1 / 6
        p_normal_hit  = max(0.0, p_hit - p_crit)

        if MORTAL_PER_HIT in abilities:
            # Each hit = 1 mortal; bypasses wound roll and save, ward still applies.
            notes.append("each hit = 1 mortal (ignores save)")
            return attacks * p_hit * 1.0 * p_not_warded

        if CRIT_MORTAL in abilities:
            # Crit → 1 mortal (bypasses wound + save); normal hit goes through full chain.
            mortal = attacks * p_crit * 1.0 * p_not_warded
            normal = attacks * p_normal_hit * p_wound * p_not_saved * avg_dmg * p_not_warded
            notes.append("crits → 1 mortal")
            return mortal + normal

        if CRIT_2_HITS in abilities:
            # Crit → 2 hits instead of 1.
            effective_hits = attacks * (p_normal_hit + 2 * p_crit)
            notes.append("crits → 2 hits")
            return effective_hits * p_wound * p_not_saved * avg_dmg * p_not_warded

        if CRIT_AUTO_WOUND in abilities:
            # Crit → auto-wound (skip wound roll).
            auto   = attacks * p_crit       * p_not_saved * avg_dmg * p_not_warded
            normal = attacks * p_normal_hit * p_wound * p_not_saved * avg_dmg * p_not_warded
            notes.append("crits → auto-wound")
            return auto + normal

        if CRIT_D6_HITS in abilities:
            # Crit → D6 hits (expected 3.5).
            effective_hits = attacks * (p_normal_hit + 3.5 * p_crit)
            notes.append("crits → D6 hits (avg 3.5)")
            return effective_hits * p_wound * p_not_saved * avg_dmg * p_not_warded

        # Standard path — no special crit behaviour.
        return attacks * p_hit * p_wound * p_not_saved * avg_dmg * p_not_warded
