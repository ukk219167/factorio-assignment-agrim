#!/usr/bin/env python3
"""
verify_belts.py

Usage:
    python verify_belts.py input.json output.json

Validates a belts solver output:
 - For "ok" status:
    * each flow is present and numeric
    * lo <= flow <= hi (+TOL)
    * node conservation: inflow + supply == outflow (+TOL), sink's demand equals total supply
    * node caps (if provided) respected
 - For "infeasible" status:
    * presence of certificate fields: cut_reachable, deficit with expected keys
Exits 0 on success, 2 on failure.
"""
import sys
import json
from collections import defaultdict

TOL = 1e-9

def load(path):
    return json.load(open(path, "r"))

def print_errors_and_exit(fails):
    print("verify_belts: FAILED")
    for f in fails:
        print(" -", f)
    sys.exit(2)

def main():
    if len(sys.argv) != 3:
        print("Usage: python verify_belts.py input.json output.json")
        sys.exit(2)
    inp = load(sys.argv[1])
    out = load(sys.argv[2])

    fails = []

    if "status" not in out:
        fails.append("Output missing 'status' field.")
        print_errors_and_exit(fails)

    status = out["status"]

    edges = inp.get("edges", [])
    sources = inp.get("sources", {})
    sink = inp.get("sink", None)
    node_caps = inp.get("node_caps", {})

    # Create mapping for edges (from,to) -> (lo,hi)
    edge_map = {}
    for e in edges:
        key = (e["from"], e["to"])
        lo = float(e.get("lo", 0.0))
        hi = float(e.get("hi", 0.0))
        if hi + TOL < lo:
            fails.append(f"Input edge {key} has hi < lo ({hi} < {lo})")
        edge_map[key] = (lo, hi)

    total_supply = sum(float(v) for v in sources.values())

    if status == "ok":
        if "flows" not in out:
            fails.append("Output missing 'flows' for status 'ok'.")
            print_errors_and_exit(fails)
        flows = out["flows"]
        # Build flow dict and validate each flow present in input edges (or allow extra edges cautiously)
        flow_map = {}
        for f in flows:
            try:
                u = f["from"]
                v = f["to"]
                val = float(f["flow"])
            except Exception as e:
                fails.append(f"Malformed flow entry: {f} ({e})")
                continue
            flow_map[(u,v)] = val
        # Check each original edge has a flow entry (if not, assume 0)
        for key, (lo, hi) in edge_map.items():
            flow = flow_map.get(key, 0.0)
            if flow + TOL < lo:
                fails.append(f"Edge {key} flow {flow} below lower bound {lo}")
            if flow - hi > TOL:
                fails.append(f"Edge {key} flow {flow} above upper bound {hi}")

        # Node conservation: inflow + supply == outflow (+TOL)
        nodes = set()
        for e in edges:
            nodes.add(e["from"]); nodes.add(e["to"])
        nodes |= set(sources.keys())
        if sink:
            nodes.add(sink)

        inflow = defaultdict(float)
        outflow = defaultdict(float)
        for (u,v), val in flow_map.items():
            outflow[u] += val
            inflow[v] += val

        # check node by node
        for n in nodes:
            supply = float(sources.get(n, 0.0))
            if n == sink:
                # sink should have no outgoing edges per spec; but if it does, handle anyway
                demand = 0.0
            else:
                demand = 0.0
            lhs = inflow.get(n, 0.0) + supply
            rhs = outflow.get(n, 0.0) + demand
            if abs(lhs - rhs) > 1e-6:
                # allow sink: for sink, outflow may be zero and inflow should equal total supply
                if n == sink:
                    # check sink inflow equals total supply
                    if abs(inflow.get(n, 0.0) - total_supply) > 1e-6:
                        fails.append(f"Sink '{n}' inflow {inflow.get(n,0.0)} != total supply {total_supply}")
                else:
                    fails.append(f"Node '{n}' conservation violated: inflow({inflow.get(n,0.0)}) + supply({supply}) != outflow({outflow.get(n,0.0)})")

        # Node caps: if node is split (node_caps provided), ensure total in->out <= cap
        # For our input, node_caps apply to specific nodes; check total outgoing or incoming as necessary.
        for node, cap in node_caps.items():
            # interpretation: total throughput (in or out) must be <= cap
            total_in = inflow.get(node, 0.0)
            total_out = outflow.get(node, 0.0)
            throughput = max(total_in, total_out)
            if throughput - float(cap) > 1e-6:
                fails.append(f"Node cap violated for '{node}': throughput {throughput} > cap {cap}")

        # Check max_flow_per_min if present matches sum flow into sink
        if "max_flow_per_min" in out:
            reported = float(out["max_flow_per_min"])
            sink_in = inflow.get(sink, 0.0)
            if abs(reported - sink_in) > 1e-6:
                fails.append(f"max_flow_per_min reported {reported} but sink inflow {sink_in}")

        if fails:
            print_errors_and_exit(fails)
        else:
            print("verify_belts: OK")
            sys.exit(0)

    else:
        # status != ok: check certificate fields exist
        if "cut_reachable" not in out:
            fails.append("Infeasible output missing 'cut_reachable'.")
        if "deficit" not in out:
            fails.append("Infeasible output missing 'deficit'.")
        else:
            deficit = out["deficit"]
            if "demand_balance" not in deficit:
                fails.append("deficit missing 'demand_balance'")
            if "tight_nodes" not in deficit:
                fails.append("deficit missing 'tight_nodes'")
            if "tight_edges" not in deficit:
                fails.append("deficit missing 'tight_edges'")

        if fails:
            print_errors_and_exit(fails)
        else:
            print("verify_belts: reported infeasible (certificate fields present).")
            sys.exit(0)

if __name__ == "__main__":
    main()
