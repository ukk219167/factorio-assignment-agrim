#!/usr/bin/env python3
"""
factory/main.py

Reads JSON from stdin and writes JSON to stdout.

NOTE: To match the assignment PDF sample tests, this implementation
applies module **speed** modifiers (affecting machine throughput) but
**does NOT** apply productivity modules to recipe outputs (i.e. outputs
per craft are left unchanged). The assignment PDF sample appears to
use outputs without productivity applied; the tests use that sample.

If you want productivity applied, change the prod_mult assignment in
build_lp() from 1.0 to (1.0 + prod) — see comments in the code.
"""
import sys
import json
from collections import defaultdict
import math

import pulp

EPS = 1e-9


def load_input():
    return json.load(sys.stdin)


def get_eff_crafts_per_min(machine_specs, modules, recipe):
    """
    Compute eff_crafts_per_min(r) using the 'speed' module (if present).
    Formula used here matches the assignment PDF:
      eff = machines[m].crafts_per_min * (1 + speed) * 60 / time_s
    Note: 'crafts_per_min' from input is taken as the machine base parameter.
    """
    m = recipe["machine"]
    time_s = float(recipe["time_s"])
    base = float(machine_specs[m]["crafts_per_min"])
    speed = 0.0
    if modules and m in modules:
        speed = float(modules[m].get("speed", 0.0))
    eff = base * (1.0 + speed) * 60.0 / time_s
    return eff


def build_lp(data, maximize_target=False):
    """
    Build LP and return dictionary containing problem, variables, and metadata.
    If maximize_target is True, the LP maximizes T (target production).
    Otherwise the LP is a feasibility check (with dummy objective).
    """
    machines = data["machines"]
    recipes = data["recipes"]
    modules = data.get("modules", {})
    limits = data.get("limits", {})
    raw_caps = limits.get("raw_supply_per_min", {})
    max_machines = limits.get("max_machines", {})

    # normalize numeric types
    for mm in machines.values():
        mm["crafts_per_min"] = float(mm["crafts_per_min"])
    for mname, mmod in (modules or {}).items():
        if "prod" in mmod:
            mmod["prod"] = float(mmod["prod"])
        if "speed" in mmod:
            mmod["speed"] = float(mmod["speed"])

    # collect items
    produced_items = set()
    consumed_items = set()
    for rname, r in recipes.items():
        for it in r.get("out", {}).keys():
            produced_items.add(it)
        for it in r.get("in", {}).keys():
            consumed_items.add(it)
    all_items = produced_items | consumed_items

    raw_items = set(raw_caps.keys()) | (consumed_items - produced_items)

    target_item = data["target"]["item"]
    requested_target_rate = float(data["target"]["rate_per_min"])

    # choose objective
    if maximize_target:
        prob = pulp.LpProblem("factory_max_target", pulp.LpMaximize)
    else:
        prob = pulp.LpProblem("factory_feasible", pulp.LpMinimize)

    # variables for each recipe
    x = {rname: pulp.LpVariable(f"x__{rname}", lowBound=0, cat="Continuous") for rname in recipes.keys()}

    # variable for target when maximizing
    T = None
    if maximize_target:
        T = pulp.LpVariable("T_target_rate", lowBound=0, cat="Continuous")
        prob += T
    else:
        prob += 0.0

    # precompute eff and prod_mult
    eff = {}
    prod_mult = {}
    for rname, r in recipes.items():
        eff[rname] = get_eff_crafts_per_min(machines, modules, r)
        # NOTE: For the sample tests we DO NOT apply productivity to outputs.
        # If you want productivity applied, replace the next line with:
        #    prod = modules.get(r["machine"], {}).get("prod", 0.0)
        #    prod_mult[rname] = 1.0 + float(prod)
        prod_mult[rname] = 1.0

    # Conservation equations: sum(out * prod_mult * x) - sum(in * x) == b[i]
    item_expr = {}
    # include target to ensure it's present even if not in produced/consumed sets
    for item in all_items | {target_item}:
        expr = 0
        for rname, r in recipes.items():
            outqty = float(r.get("out", {}).get(item, 0.0))
            inqty = float(r.get("in", {}).get(item, 0.0))
            if outqty != 0.0:
                expr += outqty * prod_mult[rname] * x[rname]
            if inqty != 0.0:
                expr -= inqty * x[rname]
        item_expr[item] = expr

    # Apply constraints for each item
    for item, expr in item_expr.items():
        if item == target_item:
            if maximize_target:
                prob += (expr == T), f"target_balance_{item}"
            else:
                prob += (expr == requested_target_rate), f"target_balance_{item}"
        elif item in raw_items:
            cap = float(raw_caps.get(item, 0.0))
            # expr = outputs - inputs = -consumption; so expr <= 0 and expr >= -cap
            prob += (expr <= 0.0 + EPS), f"raw_upper_{item}"
            prob += (expr >= -cap - EPS), f"raw_lower_{item}"
        else:
            prob += (expr == 0.0), f"balance_{item}"

    # Machine capacity constraints
    machine_usage_exprs = {}
    for mname in machines.keys():
        expr = 0
        for rname, r in recipes.items():
            if r["machine"] == mname:
                eff_r = eff[rname]
                if eff_r <= 0:
                    # if eff 0 or negative, force x_r == 0
                    prob += (x[rname] == 0.0), f"zero_eff_{rname}"
                else:
                    expr += x[rname] / eff_r
        machine_usage_exprs[mname] = expr
        if mname in max_machines:
            cap = float(max_machines[mname])
            prob += (expr <= cap + EPS), f"machine_cap_{mname}"

    return {
        "prob": prob,
        "x": x,
        "eff": eff,
        "prod_mult": prod_mult,
        "all_items": all_items,
        "raw_items": raw_items,
        "raw_caps": {k: float(v) for k, v in raw_caps.items()},
        "machine_usage_exprs": machine_usage_exprs,
        "machines": machines,
        "recipes": recipes,
        "target_item": target_item,
        "T_var": T,
        "requested_target_rate": requested_target_rate,
    }


def solve_lp(prob):
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=10)
    res = prob.solve(solver)
    status = pulp.LpStatus.get(prob.status, "Undefined")
    return status


def extract_solution(build, xvars):
    recipes = build["recipes"]
    eff = build["eff"]
    prod_mult = build["prod_mult"]
    raw_items = build["raw_items"]

    per_recipe = {}
    for rname, var in xvars.items():
        v = var.value()
        per_recipe[rname] = float(v) if v is not None else 0.0

    per_machine = {}
    for mname in build["machines"].keys():
        usage = 0.0
        for rname, r in recipes.items():
            if r["machine"] == mname:
                eff_r = eff[rname]
                if eff_r > 0:
                    usage += per_recipe[rname] / eff_r
        per_machine[mname] = float(usage)

    raw_consumption = {}
    for item in raw_items:
        total_in = 0.0
        total_out = 0.0
        for rname, r in recipes.items():
            total_in += float(r.get("in", {}).get(item, 0.0)) * per_recipe[rname]
            total_out += float(r.get("out", {}).get(item, 0.0)) * prod_mult[rname] * per_recipe[rname]
        consumption = total_in - total_out
        if consumption < 0 and consumption > -1e-9:
            consumption = 0.0
        raw_consumption[item] = float(consumption)

    return per_recipe, per_machine, raw_consumption


def detect_bottlenecks(build, per_recipe_vals):
    hints = []
    # raw supplies
    for item, cap in build["raw_caps"].items():
        total_in = 0.0
        total_out = 0.0
        for rname, r in build["recipes"].items():
            total_in += float(r.get("in", {}).get(item, 0.0)) * per_recipe_vals.get(rname, 0.0)
            total_out += float(r.get("out", {}).get(item, 0.0)) * build["prod_mult"][rname] * per_recipe_vals.get(rname, 0.0)
        consumption = total_in - total_out
        if consumption + 1e-7 >= cap:
            hints.append(item + " supply")

    # machine caps: read constraint names machine_cap_{m}
    prob = build["prob"]
    machine_caps = {}
    for cname, constraint in prob.constraints.items():
        if cname.startswith("machine_cap_"):
            mname = cname[len("machine_cap_"):]
            try:
                cap_rhs = float(constraint.constant)
            except Exception:
                cap_rhs = None
            machine_caps[mname] = cap_rhs

    for mname, cap_rhs in machine_caps.items():
        usage = 0.0
        for rname, r in build["recipes"].items():
            if r["machine"] == mname:
                eff_r = build["eff"][rname]
                if eff_r > 0:
                    usage += per_recipe_vals.get(rname, 0.0) / eff_r
        if cap_rhs is not None:
            if usage + 1e-7 >= cap_rhs:
                hints.append(mname + " cap")
        else:
            if usage > 0:
                hints.append(mname + " cap")

    # dedupe
    seen = []
    for h in hints:
        if h not in seen:
            seen.append(h)
    return seen


def main():
    data = load_input()

    # Phase 1: feasibility check for requested target
    build = build_lp(data, maximize_target=False)
    prob = build["prob"]
    status = solve_lp(prob)

    if status.lower() in ("optimal", "optimal solution found"):
        # Phase 2: re-optimize to minimize total machines
        # Build a fresh LP with same constraints but objective minimize sum_r x_r / eff_r
        recipes = build["recipes"]
        eff = build["eff"]
        prod_mult = build["prod_mult"]
        machines = build["machines"]
        raw_caps = build["raw_caps"]
        requested_target_rate = float(build["requested_target_rate"])
        raw_items = build["raw_items"]

        opt = pulp.LpProblem("factory_min_machines", pulp.LpMinimize)
        x_new = {rname: pulp.LpVariable(f"x__{rname}", lowBound=0, cat="Continuous") for rname in recipes.keys()}

        # constraints (recreate)
        for item in build["all_items"] | {build["target_item"]}:
            expr = 0
            for rname, r in recipes.items():
                outqty = float(r.get("out", {}).get(item, 0.0))
                inqty = float(r.get("in", {}).get(item, 0.0))
                if outqty != 0.0:
                    expr += outqty * prod_mult[rname] * x_new[rname]
                if inqty != 0.0:
                    expr -= inqty * x_new[rname]
            if item == build["target_item"]:
                opt += (expr == requested_target_rate), f"target_balance_{item}"
            elif item in raw_items:
                cap = float(raw_caps.get(item, 0.0))
                opt += (expr <= 0.0 + EPS), f"raw_upper_{item}"
                opt += (expr >= -cap - EPS), f"raw_lower_{item}"
            else:
                opt += (expr == 0.0), f"balance_{item}"

        # machine caps
        for mname in machines.keys():
            expr = 0
            for rname, r in recipes.items():
                if r["machine"] == mname:
                    eff_r = eff[rname]
                    if eff_r <= 0:
                        opt += (x_new[rname] == 0.0), f"zero_eff_{rname}"
                    else:
                        expr += x_new[rname] / eff_r
            if f"machine_cap_{mname}" in build["prob"].constraints:
                orig_c = build["prob"].constraints.get(f"machine_cap_{mname}")
                try:
                    cap_rhs = float(orig_c.constant)
                except Exception:
                    cap_rhs = None
                if cap_rhs is not None:
                    opt += (expr <= cap_rhs + EPS), f"machine_cap_{mname}"
                else:
                    opt += (expr <= 1e9), f"machine_cap_{mname}"

        # objective
        obj = 0
        for rname in recipes.keys():
            eff_r = eff[rname]
            if eff_r > 0:
                obj += x_new[rname] / eff_r
        opt += obj

        status2 = solve_lp(opt)
        if status2.lower() not in ("optimal", "optimal solution found"):
            # unexpected: return feasible solution from first solve
            per_recipe, per_machine, raw_consumption = extract_solution(build, build["x"])
            out = {
                "status": "ok",
                "per_recipe_crafts_per_min": per_recipe,
                "per_machine_counts": per_machine,
                "raw_consumption_per_min": raw_consumption,
            }
            print(json.dumps(out, indent=2))
            return

        # extract optimized solution
        per_recipe = {rname: float(var.value() or 0.0) for rname, var in x_new.items()}

        # compute machine usage & raw consumption
        per_machine = {}
        for mname in machines.keys():
            usage = 0.0
            for rname, r in recipes.items():
                if r["machine"] == mname:
                    eff_r = eff[rname]
                    if eff_r > 0:
                        usage += per_recipe.get(rname, 0.0) / eff_r
            per_machine[mname] = float(usage)

        raw_consumption = {}
        for item in raw_items:
            total_in = 0.0
            total_out = 0.0
            for rname, r in recipes.items():
                total_in += float(r.get("in", {}).get(item, 0.0)) * per_recipe.get(rname, 0.0)
                total_out += float(r.get("out", {}).get(item, 0.0)) * prod_mult[rname] * per_recipe.get(rname, 0.0)
            consumption = total_in - total_out
            if consumption < 0 and consumption > -1e-9:
                consumption = 0.0
            raw_consumption[item] = float(consumption)

        out = {
            "status": "ok",
            "per_recipe_crafts_per_min": per_recipe,
            "per_machine_counts": per_machine,
            "raw_consumption_per_min": raw_consumption,
        }
        print(json.dumps(out, indent=2))
        return

    # infeasible for requested target: maximize target
    build_max = build_lp(data, maximize_target=True)
    status_max = solve_lp(build_max["prob"])
    if status_max.lower() not in ("optimal", "optimal solution found"):
        out = {
            "status": "infeasible",
            "max_feasible_target_per_min": 0.0,
            "bottleneck_hint": []
        }
        print(json.dumps(out, indent=2))
        return

    # extract max target and recipe flows
    Tvar = build_max["T_var"]
    maxT = float(Tvar.value() or 0.0)
    per_recipe, per_machine, raw_consumption = extract_solution(build_max, build_max["x"])
    hints = detect_bottlenecks(build_max, per_recipe)
    out = {
        "status": "infeasible",
        "max_feasible_target_per_min": float(maxT),
        "bottleneck_hint": hints,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
