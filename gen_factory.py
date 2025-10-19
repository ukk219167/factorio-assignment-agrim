#!/usr/bin/env python3
# gen_factory.py
# Generate synthetic factory JSON testcases for factory/main.py

import json
import random
import argparse
from math import ceil

RAW_ITEM_PREFIX = "ore_"
INTERMEDIATE_PREFIX = "item_"
MACHINE_PREFIX = "machine_"
RECIPE_PREFIX = "recipe_"

def make_args():
    p = argparse.ArgumentParser(description="Generate factory JSON testcases")
    p.add_argument("--seed", type=int, default=0, help="random seed (deterministic)")
    p.add_argument("--n_machines", type=int, default=3, help="number of machine types")
    p.add_argument("--n_recipes", type=int, default=8, help="number of recipes")
    p.add_argument("--n_raw", type=int, default=3, help="number of raw items (ores)")
    p.add_argument("--target_rate_min", type=int, default=100, help="min target rate")
    p.add_argument("--target_rate_max", type=int, default=2000, help="max target rate")
    p.add_argument("--outfile", type=str, default=None, help="write JSON to file instead of stdout")
    return p.parse_args()

def uniform_choice_not_none(seq):
    return seq[random.randrange(len(seq))]

def generate(args):
    random.seed(args.seed)
    n_m = args.n_machines
    n_r = args.n_recipes
    n_raw = args.n_raw

    machines = {}
    for i in range(n_m):
        name = f"{MACHINE_PREFIX}{i+1}"
        # crafts_per_min base roughly 20..120
        machines[name] = {"crafts_per_min": float(random.choice([15,20,30,40,60,90]))}

    # raw items
    raw_items = [f"{RAW_ITEM_PREFIX}{i+1}" for i in range(n_raw)]
    # intermediate pool (names) we'll create
    intermediates = [f"{INTERMEDIATE_PREFIX}{i+1}" for i in range(max(1, n_r // 2))]

    # Build recipes: mix of raw->intermediate, intermediate->intermediate, combine -> final
    recipes = {}
    for i in range(n_r):
        rname = f"{RECIPE_PREFIX}{i+1}"
        machine = random.choice(list(machines.keys()))
        # time_s small fractional: between 0.2 and 5.0
        time_s = round(random.uniform(0.2, 5.0), 3)
        # choose whether this recipe produces a raw-derived intermediate or final
        produces = random.choice(intermediates + [f"product_{(i%3)+1}"])
        # pick 1-3 inputs from raw + intermediates
        num_inputs = random.choice([1,1,2,2,3])
        pools = raw_items + intermediates
        ins = {}
        for _ in range(num_inputs):
            itm = uniform_choice_not_none(pools)
            qty = random.choice([1,1,1,2,3])
            ins[itm] = ins.get(itm, 0) + qty
        outs = {produces: random.choice([1,1,1,2])}
        recipes[rname] = {"machine": machine, "time_s": time_s, "in": ins, "out": outs}

    # Add one recipe that directly makes a target product from intermediates (ensure target exists)
    target_item = "final_widget"
    # create recipe that consumes 1-3 intermediates into final_widget
    final_in = {}
    choose_from = intermediates + raw_items
    for _ in range(random.choice([1,2,3])):
        itm = uniform_choice_not_none(choose_from)
        final_in[itm] = final_in.get(itm, 0) + random.choice([1,2])
    recipes["make_" + target_item] = {"machine": random.choice(list(machines.keys())), "time_s": round(random.uniform(0.2, 2.0), 3), "in": final_in, "out": {target_item: 1}}

    # Modules: randomly include speed and/or prod modifiers for some machines
    modules = {}
    for m in machines.keys():
        if random.random() < 0.6:
            modules[m] = {}
            if random.random() < 0.7:
                modules[m]["speed"] = round(random.uniform(0.0, 0.3), 3)
            if random.random() < 0.4:
                modules[m]["prod"] = round(random.uniform(0.0, 0.25), 3)
            if modules[m] == {}:
                modules.pop(m, None)

    # Limits: raw_supply caps and max_machines
    raw_supply = {}
    for r in raw_items:
        # cap between 500 and 10000
        raw_supply[r] = float(random.choice([500,1000,2000,3000,5000,10000]))
    max_machines = {}
    for m in machines.keys():
        max_machines[m] = float(random.choice([10,20,50,100,200,500]))

    target_rate = float(random.randint(args.target_rate_min, args.target_rate_max))

    data = {
        "machines": machines,
        "recipes": recipes,
        "modules": modules,
        "limits": {"raw_supply_per_min": raw_supply, "max_machines": max_machines},
        "target": {"item": target_item, "rate_per_min": target_rate}
    }
    return data

def main():
    args = make_args()
    data = generate(args)
    out = json.dumps(data, indent=2)
    if args.outfile:
        with open(args.outfile, "w") as f:
            f.write(out)
        print(f"Wrote factory test to {args.outfile}")
    else:
        print(out)

if __name__ == "__main__":
    main()
