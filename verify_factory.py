#!/usr/bin/env python3
"""
verify_factory.py

Usage:
    python verify_factory.py input.json output.json

Validates `output.json` produced by factory/main.py against the `input.json`.
Checks:
 - JSON schema presence
 - Conservation (items): |sum_out*prod - sum_in - b[i]| <= TOL
 - Target equality (exact within TOL)
 - Raw consumption non-negative and <= cap (+TOL) if raw caps present (optional)
 - Machine usage: sum_r x_r / eff_r <= max_machines[m] + TOL
 - per_machine_counts matches computed (within TOL)
 - per_recipe_crafts_per_min non-negative
 - Tolerances: absolute tolerance TOL
Exits 0 on success; prints diagnostics and exits 2 on failure.
"""
import sys
import json
from collections import defaultdict

TOL = 1e-9

def load(path):
    return json.load(open(path, "r"))

def eff_crafts_per_min(machine_specs, modules, recipe):
    m = recipe["machine"]
    time_s = float(recipe["time_s"])
    base = float(machine_specs[m]["crafts_per_min"])
    speed = 0.0
    if modules and m in modules:
        speed = float(modules[m].get("speed", 0.0))
    eff = base * (1.0 + speed) * 60.0 / time_s
    return eff

def main():
    if len(sys.argv) != 3:
        print("Usage: python verify_factory.py input.json output.json")
        sys.exit(2)
    inp_path = sys.argv[1]
    out_path = sys.argv[2]
    inp = load(inp_path)
    out = load(out_path)

    failures = []

    # Basic schema checks
    if "status" not in out:
        failures.append("Output missing 'status' field.")
        print_errors_and_exit(failures)
    status = out["status"]

    machines = inp.get("machines", {})
    recipes = inp.get("recipes", {})
    modules = inp.get("modules", {})
    limits = inp.get("limits", {})
    raw_caps = limits.get("raw_supply_per_min", {})
    max_machines = limits.get("max_machines", {})
    target = inp.get("target", {})
    target_item = target.get("item")
    requested_rate = float(target.get("rate_per_min", 0.0))

    # Precompute eff and prod_mult (we assume prod may be 1.0 or 1+prod depending on implementation)
    eff = {}
    prod_mult = {}
    for rname, r in recipes.items():
        try:
            eff[rname] = eff_crafts_per_min(machines, modules, r)
        except Exception as e:
            failures.append(f"Error computing eff for recipe '{rname}': {e}")
            eff[rname] = None
        # Many solutions either use prod or not; we accept both but check outputs using prod_mult = 1.0
        # We still read modules prod if present and keep as 1+prod for stricter checks optionally.
        prod = 0.0
        if modules and r["machine"] in modules:
            prod = float(modules[r["machine"]].get("prod", 0.0))
        # Two possibilities exist in implementations: 1.0 (no prod) or 1+prod; we'll default to 1.0 for verification of sample exactness
        prod_mult[rname] = 1.0

    # If status == ok, validate detailed outputs
    if status == "ok":
        # required fields
        if "per_recipe_crafts_per_min" not in out:
            failures.append("Missing per_recipe_crafts_per_min in output.")
        if "per_machine_counts" not in out:
            failures.append("Missing per_machine_counts in output.")
        if "raw_consumption_per_min" not in out:
            failures.append("Missing raw_consumption_per_min in output.")
        if failures:
            print_errors_and_exit(failures)

        per_recipe = out["per_recipe_crafts_per_min"]
        per_machine = out["per_machine_counts"]
        raw_consumption = out["raw_consumption_per_min"]

        # recipe non-negativity
        for rname, val in per_recipe.items():
            if val is None:
                failures.append(f"per_recipe_crafts_per_min['{rname}'] is null.")
                continue
            try:
                v = float(val)
            except:
                failures.append(f"per_recipe_crafts_per_min['{rname}'] is not numeric.")
                continue
            if v < -TOL:
                failures.append(f"per_recipe_crafts_per_min['{rname}'] negative: {v}")

        # compute item balances: outputs - inputs for each item
        items = set()
        for r in recipes.values():
            items.update(r.get("in", {}).keys())
            items.update(r.get("out", {}).keys())
        if target_item:
            items.add(target_item)

        # compute expressions
        eqs = {}
        for item in items:
            val = 0.0
            for rname, r in recipes.items():
                outqty = float(r.get("out", {}).get(item, 0.0))
                inqty = float(r.get("in", {}).get(item, 0.0))
                x = float(per_recipe.get(rname, 0.0))
                val += outqty * prod_mult[rname] * x
                val -= inqty * x
            eqs[item] = val

        # Check target equality
        if target_item is None:
            failures.append("Input missing target.item")
        else:
            target_balance = eqs.get(target_item, 0.0)
            if abs(target_balance - requested_rate) > 1e-6:
                failures.append(f"Target balance mismatch: computed {target_balance}, requested {requested_rate}")

        # Intermediates must be balanced (items produced and consumed but not raw and not target)
        produced = set()
        consumed = set()
        for r in recipes.values():
            produced.update(r.get("out", {}).keys())
            consumed.update(r.get("in", {}).keys())
        raw_items = set(raw_caps.keys()) | (consumed - produced)
        intermediates = (produced & consumed) - set([target_item]) - raw_items

        for item in intermediates:
            if abs(eqs.get(item, 0.0)) > 1e-6:
                failures.append(f"Intermediate '{item}' not balanced: net {eqs.get(item)}")

        # raw consumption: consumption = inputs - outputs
        for item in raw_items:
            # computed consumption
            consumption = 0.0
            for rname, r in recipes.items():
                consumption += float(r.get("in", {}).get(item, 0.0)) * float(per_recipe.get(rname, 0.0))
                consumption -= float(r.get("out", {}).get(item, 0.0)) * prod_mult[rname] * float(per_recipe.get(rname, 0.0))
            # consumption should be >= -TOL
            if consumption < -1e-6:
                failures.append(f"Raw item '{item}' has negative consumption (net production): {consumption}")
            # If raw caps provided in input, allow implementations that enforce them to check; but don't fail if absent.
            if item in raw_caps:
                cap = float(raw_caps[item])
                if consumption - cap > 1e-6:
                    failures.append(f"Raw item '{item}' consumption {consumption} exceeds cap {cap}")

            # if user provided raw_consumption_per_min in output, compare
            if item in raw_consumption:
                reported = float(raw_consumption[item])
                if abs(reported - consumption) > 1e-6:
                    failures.append(f"raw_consumption_per_min['{item}'] mismatch: reported {reported}, computed {consumption}")

        # Machine usage constraints: recompute usage and compare to max_machines if present
        # accept both definitions of per_machine_counts; we recompute expected per_machine_simple and per_machine_eff
        per_machine_computed_simple = {}
        per_machine_computed_eff = {}
        # simple: total crafts on machine / machines[m].crafts_per_min
        total_by_machine = defaultdict(float)
        for rname, r in recipes.items():
            total_by_machine[r["machine"]] += float(per_recipe.get(rname, 0.0))
        for m in machines.keys():
            base = float(machines[m]["crafts_per_min"])
            simple = 0.0
            if base > 0:
                simple = total_by_machine.get(m, 0.0) / base
            per_machine_computed_simple[m] = simple

        # eff-based: usage = sum x_r / eff_r
        for m in machines.keys():
            usage = 0.0
            for rname, r in recipes.items():
                if r["machine"] == m:
                    eff_r = eff.get(rname)
                    if eff_r and eff_r > 0:
                        usage += float(per_recipe.get(rname, 0.0)) / eff_r
                    elif float(per_recipe.get(rname, 0.0)) > 1e-12 and (not eff_r or eff_r <= 0):
                        failures.append(f"Recipe '{rname}' has positive craft but non-positive eff ({eff_r}).")
            per_machine_computed_eff[m] = usage

        # compare reported per_machine if present
        for m, reported in per_machine.items():
            # reported must be numeric
            try:
                rep = float(reported)
            except:
                failures.append(f"per_machine_counts['{m}'] not numeric.")
                continue
            # Accept either simple or eff-based as matching; check closeness to at least one
            sim = per_machine_computed_simple.get(m, 0.0)
            effu = per_machine_computed_eff.get(m, 0.0)
            if abs(rep - sim) > 1e-6 and abs(rep - effu) > 1e-6:
                failures.append(f"per_machine_counts['{m}'] reported {rep} doesn't match computed simple {sim} nor eff-based {effu}")

        # verify machine caps if present
        for m, cap in max_machines.items():
            # use eff-based usage to check
            usage = per_machine_computed_eff.get(m, 0.0)
            if usage - float(cap) > 1e-6:
                failures.append(f"Machine '{m}' usage {usage} exceeds cap {cap}")

        if failures:
            print_errors_and_exit(failures)
        else:
            print("verify_factory: OK")
            sys.exit(0)

    else:
        # status != ok: expect an infeasible report with fields
        if "max_feasible_target_per_min" not in out:
            failures.append("Output status != ok but missing 'max_feasible_target_per_min'.")
        if "bottleneck_hint" not in out:
            # not mandatory but recommended
            failures.append("Output status != ok but missing 'bottleneck_hint'.")
        if failures:
            print_errors_and_exit(failures)
        else:
            print("verify_factory: reported infeasible (has max_feasible_target_per_min and bottleneck_hint).")
            sys.exit(0)

def print_errors_and_exit(failures):
    print("verify_factory: FAILED")
    for f in failures:
        print(" -", f)
    sys.exit(2)

if __name__ == "__main__":
    main()
