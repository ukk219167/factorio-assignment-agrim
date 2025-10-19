#!/usr/bin/env python3
# gen_belts.py
# Generate synthetic belts (bounded flow) JSON testcases for belts/main.py

import json
import random
import argparse
from collections import defaultdict

def make_args():
    p = argparse.ArgumentParser(description="Generate belts JSON testcases")
    p.add_argument("--seed", type=int, default=0, help="random seed")
    p.add_argument("--n_sources", type=int, default=2, help="number of sources")
    p.add_argument("--n_mid", type=int, default=4, help="number of intermediate nodes")
    p.add_argument("--max_supply", type=int, default=1000, help="max supply per source")
    p.add_argument("--node_caps_prob", type=float, default=0.3, help="probability a node has a cap")
    p.add_argument("--force-infeasible", action="store_true", help="make a likely-infeasible instance")
    p.add_argument("--outfile", type=str, default=None, help="write JSON to file instead of stdout")
    return p.parse_args()

def generate(args):
    random.seed(args.seed)
    sources = {}
    edges = []
    sink = "sink"
    mids = [f"n{i}" for i in range(1, args.n_mid + 1)]
    all_nodes = []

    # create sources with random supplies
    for i in range(1, args.n_sources + 1):
        sname = f"s{i}"
        supply = random.choice([200, 300, 500, 600, 800, 1000])
        supply = min(supply, args.max_supply)
        sources[sname] = float(supply)

    # Ensure connectivity: create paths from each source through some mids to sink
    for sname, supply in sources.items():
        path_len = random.randint(1, max(1, len(mids)))
        chosen = random.sample(mids, k=path_len)
        prev = sname
        # first edge lo=0 hi >= supply
        for idx, node in enumerate(chosen):
            lo = 0.0
            hi = float(max(200, int(supply * random.uniform(0.8, 1.5))))
            edges.append({"from": prev, "to": node, "lo": lo, "hi": hi})
            prev = node
        # connect last mid to sink
        edges.append({"from": prev, "to": sink, "lo": 0.0, "hi": float(max(200, int(supply * random.uniform(0.8, 1.5))))})

    # add some random cross edges between mids to create alternative paths
    for _ in range(len(mids) * 2):
        u, v = random.sample(mids, 2)
        if u == v:
            continue
        lo = 0.0
        hi = float(random.choice([100,200,300,500,800,1000]))
        edges.append({"from": u, "to": v, "lo": lo, "hi": hi})

    # optionally add edges directly source->sink for variety
    for s in list(sources.keys()):
        if random.random() < 0.4:
            edges.append({"from": s, "to": sink, "lo": 0.0, "hi": float(sources[s])})

    # node caps: randomly assign caps to some mids
    node_caps = {}
    for m in mids:
        if random.random() < args.node_caps_prob:
            node_caps[m] = float(random.choice([200, 300, 500, 800, 1000]))

    # If force_infeasible, artificially reduce some hi to make total capacity < total supply
    if args.force_infeasible:
        total_supply = sum(sources.values())
        # find edges entering sink and reduce their hi so sum < total_supply
        sink_in_edges = [e for e in edges if e["to"] == sink]
        if sink_in_edges:
            # set all their hi to small values
            for e in sink_in_edges:
                e["hi"] = float(random.choice([50, 100, 150]))
        else:
            # if none, reduce caps on random edges
            for _ in range(max(1, len(edges)//4)):
                e = random.choice(edges)
                e["hi"] = float(random.choice([50,100,150]))

    # remove duplicate edges by merging (keep max hi and max lo)
    merged = {}
    for e in edges:
        key = (e["from"], e["to"])
        if key not in merged:
            merged[key] = {"from": e["from"], "to": e["to"], "lo": e.get("lo",0.0), "hi": e.get("hi",0.0)}
        else:
            merged[key]["lo"] = max(merged[key]["lo"], e.get("lo",0.0))
            merged[key]["hi"] = max(merged[key]["hi"], e.get("hi",0.0))
    final_edges = list(merged.values())

    data = {"edges": final_edges, "sources": sources, "sink": sink}
    if node_caps:
        data["node_caps"] = node_caps
    return data

def main():
    args = make_args()
    data = generate(args)
    out = json.dumps(data, indent=2)
    if args.outfile:
        with open(args.outfile, "w") as f:
            f.write(out)
        print(f"Wrote belts test to {args.outfile}")
    else:
        print(out)

if __name__ == "__main__":
    main()
