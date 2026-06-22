import shutil
from collections import defaultdict, Counter
from dataclasses import replace as dc_replace
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from typing import Optional

from .loader import find_units
from .calculator import DamageCalculator

app = typer.Typer(help="Age of Sigmar damage simulator", add_completion=False, no_args_is_help=True)
console = Console(width=shutil.get_terminal_size(fallback=(120, 24)).columns)
calc = DamageCalculator()


@app.callback()
def _root():
    """Age of Sigmar damage simulator."""


_SAVES = [(2, "2+"), (3, "3+"), (4, "4+"), (5, "5+"), (6, "6+"), (7, "—")]


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_num(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.1f}"


def _dmg_color(v: float) -> str:
    if v >= 10: return "bright_red"
    if v >= 6:  return "red"
    if v >= 3:  return "yellow"
    if v >= 1:  return "green"
    return "dim"


def _fmt_dmg(v: float) -> str:
    color = _dmg_color(v)
    return f"[{color}]{v:.2f}[/{color}]"


# ── Per-weapon conditional rows ───────────────────────────────────────────────

def _unit_in_scope(unit, scope: str) -> bool:
    """Return True if unit matches a friendly_buff scope string."""
    if scope in ("friendly_units", "friendly_units_within_12", "friendly_units_in_combat_range_of_general"):
        return True
    if scope == "friendly_non_hero_units":
        return "Hero" not in unit.keywords
    # Pattern: "friendly_{keyword}_unit_within_{range}" or "friendly_{keyword}_unit"
    import re
    m = re.match(r"friendly_(\w+)_unit", scope)
    if m:
        return m.group(1).capitalize() in unit.keywords
    return False


def _collect_weapon_variants(unit, spearhead) -> dict:
    """Return {weapon_idx: [(label, modified_WeaponProfile, p_weight)]} for all conditionals.

    p_weight = 1.0 for deterministic buffs, 0 < p < 1 for roll-gated ones.
    """
    out = defaultdict(list)
    weapon_by_name = {w.name: (i, w) for i, w in enumerate(unit.weapons)}

    def _mod(weapon, **kw):
        return dc_replace(weapon, **kw)

    def _append(wi, label, weapon, p_weight=1.0, exclusive_group=None, **overrides):
        out[wi].append((label, _mod(weapon, **overrides), p_weight, exclusive_group))

    # ── Unit passive abilities ────────────────────────────────────────────────
    for ab in unit.passive_abilities:
        effect = ab.get("effect", {})
        wname  = effect.get("weapon")
        etype  = effect.get("type")
        label  = f"[yellow]({ab['name']})[/yellow]"

        if etype in ("conditional_buff", "self_damage_then_buff") and not wname:
            modifier       = effect.get("modifier", "")
            target_weapons = effect.get("target_weapons", "")
            if modifier == "wound_bonus":
                bonus = effect["value"]
                for wi, w in enumerate(unit.weapons):
                    if not target_weapons or target_weapons == w.type:
                        _append(wi, label, w, wound=max(2, w.wound - bonus))
            elif modifier == "damage_bonus":
                bonus = effect["value"]
                for wi, w in enumerate(unit.weapons):
                    if not target_weapons or target_weapons == w.type:
                        _append(wi, label, w, damage=str(calc.parse_dice(w.damage) + bonus))
            elif modifier == "attacks_bonus":
                bonus = effect["value"]
                for wi, w in enumerate(unit.weapons):
                    if not target_weapons or target_weapons == w.type:
                        base    = calc.parse_dice(w.attacks)
                        new_atk = str(int(base + bonus)) if base == int(base) else w.attacks
                        _append(wi, label, w, attacks=new_atk)
            continue

        if not wname or wname not in weapon_by_name:
            continue
        wi, weapon = weapon_by_name[wname]

        if etype == "conditional_buff" and effect.get("modifier") == "attacks_bonus":
            bonus   = effect["value"]
            base    = calc.parse_dice(weapon.attacks)
            new_atk = str(int(base + bonus)) if base == int(base) else weapon.attacks
            _append(wi, label, weapon, attacks=new_atk)

        elif etype == "weapon_override_with_risk" and effect.get("modifier") == "damage":
            p_ok = (7 - effect["roll_required"]) / 6
            _append(wi, label, weapon, p_ok, damage=str(effect["value_on_success"]))

    # ── Enhancements — general only ──────────────────────────────────────────
    if unit.role == "general":
        for enh in spearhead.enhancements:
            effect   = enh.get("effect", {})
            wname    = effect.get("weapon")
            etype    = effect.get("type")
            modifier = effect.get("modifier")
            if not wname or wname not in weapon_by_name or etype != "weapon_override":
                continue
            wi, weapon = weapon_by_name[wname]
            label = f"[yellow]({enh['name']})[/yellow]"
            if modifier == "attacks":
                _append(wi, label, weapon, attacks=str(effect["value"]))
            elif modifier == "damage":
                _append(wi, label, weapon, damage=str(effect["value"]))
            elif modifier == "rend":
                _append(wi, label, weapon, rend=int(effect["value"]))
            elif modifier == "add_ability":
                _append(wi, label, weapon, abilities=list(weapon.abilities or []) + [effect["value"]])

    # ── General's friendly buffs — applies to all units including the general ─
    general = next((u for u in spearhead.units if u.role == "general"), None)
    if general:
        for ab in general.passive_abilities:
            effect = ab.get("effect", {})
            if effect.get("type") != "friendly_buff":
                continue
            if not _unit_in_scope(unit, effect.get("scope", "")):
                continue
            modifier        = effect.get("modifier", "")
            target_weapons  = effect.get("target_weapons", "")
            roll_req        = effect.get("roll_required")
            p_ok            = (7 - roll_req) / 6 if roll_req else 1.0
            label           = f"[yellow]({ab['name']})[/yellow]"
            exclusive_group = ab.get("exclusive_group")

            # Combined multi-modifier effect (e.g. Song of the Hunt 3+ chords)
            if "modifiers" in effect:
                for wi, w in enumerate(unit.weapons):
                    if not target_weapons or w.type == target_weapons:
                        combined = w
                        for m in effect["modifiers"]:
                            if m["modifier"] == "hit_bonus":
                                combined = _mod(combined, hit=max(2, combined.hit - m["value"]))
                            elif m["modifier"] == "wound_bonus":
                                combined = _mod(combined, wound=max(2, combined.wound - m["value"]))
                        out[wi].append((label, combined, p_ok, exclusive_group))
                continue

            if modifier == "hit_bonus":
                bonus = effect["value"]
                for wi, w in enumerate(unit.weapons):
                    if not target_weapons or w.type == target_weapons:
                        _append(wi, label, w, p_ok, exclusive_group=exclusive_group, hit=max(2, w.hit - bonus))
            elif modifier == "wound_bonus":
                bonus = effect["value"]
                for wi, w in enumerate(unit.weapons):
                    if not target_weapons or w.type == target_weapons:
                        _append(wi, label, w, p_ok, exclusive_group=exclusive_group, wound=max(2, w.wound - bonus))

        # Enhancements on the general that buff all friendly units
        for enh in spearhead.enhancements:
            effect = enh.get("effect", {})
            if effect.get("type") != "friendly_buff":
                continue
            if not _unit_in_scope(unit, effect.get("scope", "")):
                continue
            modifier       = effect.get("modifier", "")
            target_weapons = effect.get("target_weapons", "")
            label          = f"[yellow]({enh['name']})[/yellow]"
            if modifier == "hit_bonus":
                bonus = effect["value"]
                for wi, w in enumerate(unit.weapons):
                    if not target_weapons or w.type == target_weapons:
                        _append(wi, label, w, hit=max(2, w.hit - bonus))
            elif modifier == "wound_bonus":
                bonus = effect["value"]
                for wi, w in enumerate(unit.weapons):
                    if not target_weapons or w.type == target_weapons:
                        _append(wi, label, w, wound=max(2, w.wound - bonus))

    # ── Regiment abilities ────────────────────────────────────────────────────
    if "Hero" not in unit.keywords:
        for ra in spearhead.regiment_abilities:
            effect   = ra.get("effect", {})
            scope    = effect.get("scope", "")
            modifier = effect.get("modifier", "")
            if effect.get("type") == "friendly_buff" and scope == "friendly_non_hero_units" and modifier == "wound_bonus":
                bonus          = effect["value"]
                target_weapons = effect.get("target_weapons", "melee")
                label          = f"[yellow]({ra['name']})[/yellow]"
                for wi, w in enumerate(unit.weapons):
                    if not target_weapons or w.type == target_weapons:
                        _append(wi, label, w, wound=max(2, w.wound - bonus))

    return out


def _collect_weapon_conditionals(unit, spearhead, save_results, ward):
    """Return {weapon_idx: [(label, [dmg_per_save], exclusive_group)]}."""
    out = defaultdict(list)
    for wi, variant_list in _collect_weapon_variants(unit, spearhead).items():
        for label, modified_weapon, p_weight, exclusive_group in variant_list:
            dmg_ok = [
                round(calc.weapon_damage(modified_weapon, unit.model_count, sv, ward).expected_damage, 3)
                for sv, _ in _SAVES
            ]
            if p_weight < 1.0:
                dmg_base = [save_results[si].weapons[wi].expected_damage for si in range(len(_SAVES))]
                dmg_ok = [round(p_weight * b + (1 - p_weight) * n, 3) for b, n in zip(dmg_ok, dmg_base)]
            out[wi].append((label, dmg_ok, exclusive_group))
    return out


# ── Healing rows ──────────────────────────────────────────────────────────────

def _collect_healing(unit, spearhead, save_results):
    """Return [(label, [heal_per_save_column])] for all applicable healing sources."""
    rows = []

    def _resolve(name, effect):
        trigger  = effect.get("trigger")
        heal_val = effect.get("heal")

        if trigger == "critical_hit" and isinstance(heal_val, (int, float)):
            h = calc.heal_from_crits(unit, float(heal_val))
            return (name, [h] * len(save_results))

        if trigger == "after_fight_ability" and heal_val == "damage_dealt":
            heals = [
                round(sum(wr.expected_damage for wr in r.weapons if wr.weapon_type == "melee"), 2)
                for r in save_results
            ]
            return (name, heals)

        return None

    for ab in unit.passive_abilities:
        effect = ab.get("effect", {})
        if effect.get("type") == "self_heal":
            result = _resolve(ab["name"], effect)
            if result:
                rows.append(result)

    for bt in spearhead.battle_traits:
        effect = bt.get("effect", {})
        if effect.get("type") != "self_heal":
            continue
        applies_to = effect.get("applies_to", "")
        if applies_to == "friendly_vampire_units" and "Vampire" not in unit.keywords:
            continue
        result = _resolve(bt["name"], effect)
        if result:
            rows.append(result)

    if unit.role == "general":
        for enh in spearhead.enhancements:
            effect = enh.get("effect", {})
            if effect.get("type") == "self_heal":
                result = _resolve(f"{enh['name']} [enhancement]", effect)
                if result:
                    rows.append(result)

    return rows


# ── Commands ──────────────────────────────────────────────────────────────────

@app.command()
def damage(
    faction: str = typer.Argument(..., help="Faction short name (e.g. soulblight, skaven)"),
    unit_name: str = typer.Argument(..., help="Unit name or substring (e.g. 'Wight King', 'Clanrats')"),
    ward: Optional[int] = typer.Option(None, "--ward", "-w", help="Target ward save, e.g. 5 for 5+"),
    charging: bool = typer.Option(False, "--charging", "-c", help="Apply Charge (+1 Damage) bonuses"),
):
    """Expected damage output of a unit vs every save value."""
    matches = find_units(faction, unit_name)

    if not matches:
        console.print(f"[red]No unit found[/red] matching '[bold]{unit_name}[/bold]' "
                      f"in faction '[bold]{faction}[/bold]'.")
        console.print("[dim]Available factions: soulblight, skaven[/dim]")
        raise typer.Exit(1)

    for unit, spearhead in matches:
        # ── Header ────────────────────────────────────────────────────────────
        ward_str  = f"Ward {unit.stats.ward}+" if unit.stats.ward else "No Ward"
        kw_str    = ", ".join(unit.keywords) if unit.keywords else "—"
        count_str = f"{unit.model_count} model{'s' if unit.model_count > 1 else ''}"
        s = unit.stats

        header = (
            f"[bold white]{unit.name}[/bold white]\n"
            f"[dim]{spearhead.faction} · {spearhead.name}[/dim]\n"
            f"[dim]{count_str} · [blue]Move {s.move}\"[/blue] · [red]Health {s.health}[/red] · [green]Save {s.save}+[/green] · {ward_str} · [yellow]Control {s.control}[/yellow][/dim]\n"
            f"[dim]{kw_str}[/dim]"
        )
        if ward:
            header += f"\n[dim]Target ward: {ward}+[/dim]"
        if charging:
            header += "\n[dim]Charging: Charge (+1 Damage) applied[/dim]"

        console.print()
        console.print(Panel(header, expand=False, border_style="dim"))
        console.print()

        # ── Compute damage per save ────────────────────────────────────────────
        save_results = [
            calc.unit_damage(unit, sv, target_ward=ward, is_charging=charging)
            for sv, _ in _SAVES
        ]

        has_charge = any("Charge (+1 Damage)" in (w.abilities or []) for w in unit.weapons)
        charge_results = None
        if has_charge and not charging:
            charge_results = [
                calc.unit_damage(unit, sv, target_ward=ward, is_charging=True)
                for sv, _ in _SAVES
            ]

        weapon_conditionals = _collect_weapon_conditionals(unit, spearhead, save_results, ward)

        # ── Build table ───────────────────────────────────────────────────────
        table = Table(box=box.SIMPLE_HEAD, padding=(0, 1), show_edge=False)
        table.add_column("Weapon", style="white", no_wrap=True)
        table.add_column("T", style="dim", no_wrap=True)
        table.add_column("Atk", justify="right", style="dim", min_width=4)
        for _, label in _SAVES:
            table.add_column(label, justify="right", min_width=6, header_style="dim")

        col_totals = [0.0] * len(_SAVES)
        all_notes: set[str] = set()

        for wi, weapon in enumerate(unit.weapons):
            equipped  = weapon.models_equipped if weapon.models_equipped is not None else unit.model_count
            avg_atk   = calc.parse_dice(weapon.attacks) * equipped
            type_abbr = "R" if weapon.type == "ranged" else "M"

            dmg_cells = []
            for si, unit_result in enumerate(save_results):
                wr = unit_result.weapons[wi]
                col_totals[si] += wr.expected_damage
                all_notes.update(wr.notes)
                dmg_cells.append(_fmt_dmg(wr.expected_damage))

            table.add_row(weapon.name, type_abbr, _fmt_num(avg_atk), *dmg_cells)

            # Charge (+1 Damage) row
            if charge_results and "Charge (+1 Damage)" in (weapon.abilities or []):
                charge_cells = [
                    f"[yellow]({charge_results[si].weapons[wi].expected_damage:.2f})[/yellow]"
                    for si in range(len(_SAVES))
                ]
                table.add_row("[yellow](charging)[/yellow]", "", "", *charge_cells)

            # Per-weapon conditional ability rows
            for cond_label, dmg_per_save, _eg in weapon_conditionals.get(wi, []):
                cond_cells = [f"[yellow]({v:.2f})[/yellow]" for v in dmg_per_save]
                table.add_row(cond_label, "", "", *cond_cells)

        # ── Total rows ────────────────────────────────────────────────────────────
        # Build best exclusive-group variant per weapon:
        # {group_name: {wi: (rich_label, best_WeaponProfile)}}
        variants = _collect_weapon_variants(unit, spearhead)
        best_by_group: dict[str, dict[int, tuple[str, object]]] = defaultdict(dict)
        for wi, variant_list in variants.items():
            by_eg: dict[str, list] = defaultdict(list)
            for label, weapon, p_weight, eg in variant_list:
                if eg:
                    by_eg[eg].append((label, weapon))
            sv_mid = _SAVES[2][0]   # use save 4+ as tie-breaker
            for eg, cands in by_eg.items():
                best_label, best_wp = max(
                    cands,
                    key=lambda c: calc.weapon_damage(c[1], unit.model_count, sv_mid, ward).expected_damage,
                )
                best_by_group[eg][wi] = (best_label, best_wp)

        table.add_section()
        table.add_row(
            "[bold]Total[/bold]", "", "",
            *[f"[bold cyan]{t:.2f}[/bold cyan]" for t in col_totals],
        )

        if charge_results:
            table.add_row(
                "[bold]Total [yellow](charging)[/yellow][/bold]", "", "",
                *[f"[yellow]({cr.total:.2f})[/yellow]" for cr in charge_results],
            )

        # Collect independent buff deltas: {label: {wi: [delta_per_save]}}
        indep_by_label: dict[str, dict[int, list]] = defaultdict(dict)
        for wi, cond_list in weapon_conditionals.items():
            for label, dmg_per_save, eg in cond_list:
                if eg is None and wi not in indep_by_label[label]:
                    base_dmg = [save_results[si].weapons[wi].expected_damage for si in range(len(_SAVES))]
                    indep_by_label[label][wi] = [dmg_per_save[si] - base_dmg[si] for si in range(len(_SAVES))]

        # Buff dimensions: exclusive groups + independent buffs
        # Each dim: (display_label, kind, data)
        #   kind="excl" → data = {wi: (label, best_wp)}
        #   kind="indep" → data = {wi: [delta_per_save]}
        buff_dims = (
            [(next(iter(wb.values()))[0], "excl", wb) for wb in best_by_group.values()] +
            [(lbl, "indep", wd) for lbl, wd in indep_by_label.items()]
        )

        def _combo_totals(subset, is_charging=False):
            """Exact for excl-group weapons; delta-based for indep buffs."""
            totals = []
            wi_override = {wi: wp for _, k, d in subset if k == "excl" for wi, (_, wp) in d.items()}
            for si, (sv, _) in enumerate(_SAVES):
                t = sum(
                    calc.weapon_damage(wi_override.get(wi, w), unit.model_count, sv, ward, is_charging).expected_damage
                    for wi, w in enumerate(unit.weapons)
                )
                for _, k, d in subset:
                    if k == "indep":
                        t += sum(deltas[si] for deltas in d.values())
                totals.append(t)
            return totals

        from itertools import combinations as _combos
        for r in range(1, len(buff_dims) + 1):
            for subset in _combos(buff_dims, r):
                combo_label = " + ".join(lbl for lbl, _, _ in subset)
                totals = _combo_totals(subset, is_charging=False)
                table.add_row(
                    f"[bold]Total {combo_label}[/bold]", "", "",
                    *[f"[yellow]({t:.2f})[/yellow]" for t in totals],
                )
                if charge_results:
                    cg_totals = _combo_totals(subset, is_charging=True)
                    table.add_row(
                        f"[bold]Total {combo_label} [yellow]+ charging[/yellow][/bold]", "", "",
                        *[f"[yellow]({t:.2f})[/yellow]" for t in cg_totals],
                    )

        # Healing rows
        healing_rows = _collect_healing(unit, spearhead, save_results)
        if healing_rows:
            table.add_section()
            for name, heals in healing_rows:
                table.add_row(
                    f"[green]↑ {name}[/green]", "", "",
                    *[f"[green]+{h:.2f}[/green]" for h in heals],
                )

        console.print(table)

        # ── Footer notes ──────────────────────────────────────────────────────
        if all_notes:
            console.print("[dim]" + " · ".join(sorted(all_notes)) + "[/dim]")
        console.print()


@app.command()
def distribution(
    faction: str = typer.Argument(..., help="Faction short name (e.g. soulblight, skaven)"),
    unit_name: str = typer.Argument(..., help="Unit name, substring, or spearhead short name"),
    save: int = typer.Argument(..., help="Target save value (e.g. 4 for 4+; use 7 for no save)"),
    ward: Optional[int] = typer.Argument(None, help="Target ward save (e.g. 6 for 6+)"),
    charging: bool = typer.Option(False, "--charging", "-c", help="Apply Charge (+1 Damage) bonuses"),
    runs: int = typer.Option(10_000, "--runs", "-n", help="Number of Monte Carlo simulations"),
):
    """Damage probability distribution per weapon vs a specific save value."""
    from .simulator import simulate_weapon as _sim_weapon

    matches = find_units(faction, unit_name)
    if not matches:
        console.print(f"[red]No unit found[/red] matching '[bold]{unit_name}[/bold]' in faction '[bold]{faction}[/bold]'.")
        raise typer.Exit(1)

    for unit, spearhead in matches:
        s         = unit.stats
        ward_str  = f"Ward {s.ward}+" if s.ward else "No Ward"
        kw_str    = ", ".join(unit.keywords) if unit.keywords else "—"
        count_str = f"{unit.model_count} model{'s' if unit.model_count > 1 else ''}"

        header = (
            f"[bold white]{unit.name}[/bold white]\n"
            f"[dim]{spearhead.faction} · {spearhead.name}[/dim]\n"
            f"[dim]{count_str} · [blue]Move {s.move}\"[/blue] · [red]Health {s.health}[/red] · [green]Save {s.save}+[/green] · {ward_str} · [yellow]Control {s.control}[/yellow][/dim]\n"
            f"[dim]{kw_str}[/dim]\n"
            f"[dim]Distribution vs Save {save}+{f' · Ward {ward}+' if ward else ''} · {runs:,} runs[/dim]"
        )
        console.print()
        console.print(Panel(header, expand=False, border_style="dim"))
        console.print()

        variants   = _collect_weapon_variants(unit, spearhead)
        has_charge = any("Charge (+1 Damage)" in (w.abilities or []) for w in unit.weapons)

        # ── Simulate all weapon rows ─────────────────────────────────────────
        # rows: (label, type_abbr, atk_str, Counter)
        rows = []
        for wi, weapon in enumerate(unit.weapons):
            equipped  = weapon.models_equipped if weapon.models_equipped is not None else unit.model_count
            avg_atk   = calc.parse_dice(weapon.attacks) * equipped
            type_abbr = "R" if weapon.type == "ranged" else "M"
            base_counts = _sim_weapon(weapon, unit.model_count, save, ward, charging, runs)
            rows.append((weapon.name, type_abbr, _fmt_num(avg_atk), base_counts))

            # Charging variant
            if has_charge and not charging and "Charge (+1 Damage)" in (weapon.abilities or []):
                charge_counts = _sim_weapon(weapon, unit.model_count, save, ward, True, runs)
                rows.append(("[yellow](charging)[/yellow]", "", "", charge_counts))

            # Conditional buff variants
            for label, modified_weapon, p_weight, _eg in variants.get(wi, []):
                buffed_counts = _sim_weapon(modified_weapon, unit.model_count, save, ward, charging, runs)
                if p_weight < 1.0:
                    # Blend boosted and base distributions
                    merged: Counter = Counter()
                    for d, c in buffed_counts.items():
                        merged[d] += round(c * p_weight)
                    for d, c in base_counts.items():
                        merged[d] += round(c * (1 - p_weight))
                    rows.append((label, "", "", merged))
                else:
                    rows.append((label, "", "", buffed_counts))

        # ── Determine damage column range ─────────────────────────────────────
        max_dmg = 0
        for _, _, _, counts in rows:
            for d, c in counts.items():
                if c / runs * 100 >= 0.5:
                    max_dmg = max(max_dmg, d)

        dmg_range = range(0, max_dmg + 1)

        # ─�� Build table ───────────────────────────────────────────────────────
        table = Table(box=box.SIMPLE_HEAD, padding=(0, 1), show_edge=False)
        table.add_column("Weapon", style="white", no_wrap=True)
        table.add_column("T", style="dim", no_wrap=True)
        table.add_column("Atk", justify="right", style="dim", min_width=4)
        for d in dmg_range:
            table.add_column(str(d), justify="right", min_width=4, header_style="dim")

        for label, type_abbr, atk_str, counts in rows:
            cells = []
            for d in dmg_range:
                pct = counts[d] / runs * 100
                if pct < 0.5:
                    cells.append("[dim]·[/dim]")
                else:
                    color = _dmg_color(d)
                    cells.append(f"[{color}]{pct:.0f}%[/{color}]")
            table.add_row(label, type_abbr, atk_str, *cells)

        console.print(table)
        console.print()
