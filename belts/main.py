#!/usr/bin/env python3
"""
belts/main.py

Reads JSON from stdin and writes JSON to stdout.

Implements max-flow with lower bounds and node capacity handling (node-splitting).

Input expected (JSON):
{
  "edges": [
    {"from": "s1", "to": "a", "lo": 0, "hi": 900},
    ...
  ],
  "sources": {"s1": 900, "s2": 600},
  "sink": "sink",
  "node_caps": {"a": 2000, "b": 1000}   # optional
}

Output (success):
{
  "status": "ok",
  "max_flow_per_min": 1500,
  "flows": [
    {"from":"s1","to":"a","flow":900},
    ...
  ]
}

On infeasible (lower bounds can't be satisfied):
{
  "status": "infeasible",
  "cut_reachable": [...],
  "deficit": {
     "demand_balance": X,
     "tight_nodes": [...],
     "tight_edges": [{"from":..., "to":..., "flow_needed": ...}, ...]
  }
}
"""
import json
import sys
from collections import defaultdict, deque
import math

import networkx as nx

EPS = 1e-9


def read_input():
    data = json.load(sys.stdin)
    edges = data.get("edges", [])
    sources = data.get("sources", {})
    sink = data.get("sink")
    node_caps = data.get("node_caps", {})
    return edges, sources, sink, node_caps


def transform_node_name(node, kind):
    # helper to produce node_in / node_out names
    return f"{node}__{kind}"


def build_transformed_graph(edges, node_caps, sources, sink):
    """
    Build transformed graph for lower bounds check:
    - Node-splitting for nodes that have caps, excluding sources and sink.
    - For each original edge (u->v) with lo & hi:
       add edge from u_out (or u) to v_in (or v) with capacity (hi - lo)
       track mapping from original edge index -> transformed edge (u_t, v_t)
    Returns:
      G (DiGraph), demands dict (node -> demand), mapping list per edge:
      orig_edges_info = list of dicts for each original edge with keys:
         { 'u':u, 'v':v, 'lo':lo, 'hi':hi, 'u_t':u_t, 'v_t':v_t }
    """
    G = nx.DiGraph()
    demands = defaultdict(float)

    # Determine which nodes to split: those in node_caps but not sources/sink
    all_nodes = set()
    for e in edges:
        all_nodes.add(e["from"])
        all_nodes.add(e["to"])
    split_nodes = set(node_caps.keys()) - set(sources.keys())
    if sink in split_nodes:
        split_nodes.remove(sink)

    # For nodes: add either single node or node_in/node_out
    node_map_in = {}
    node_map_out = {}
    for n in all_nodes:
        if n in split_nodes:
            node_map_in[n] = transform_node_name(n, "in")
            node_map_out[n] = transform_node_name(n, "out")
            # add edge in->out with capacity = node cap
            cap = float(node_caps.get(n, 0.0))
            G.add_edge(node_map_in[n], node_map_out[n], capacity=cap)
        else:
            node_map_in[n] = n
            node_map_out[n] = n

    # For each original edge create transformed edge with capacity hi-lo
    orig_edges_info = []
    for e in edges:
        u = e["from"]
        v = e["to"]
        lo = float(e.get("lo", 0.0))
        hi = float(e.get("hi", 0.0))
        if hi < lo - EPS:
            # impossible single-edge constraint -- make capacity negative to fail later
            cap = -1.0
        else:
            cap = hi - lo
        # transformed endpoints: from u_out to v_in
        u_t = node_map_out[u]
        v_t = node_map_in[v]
        # ensure nodes in graph
        if u_t not in G:
            G.add_node(u_t)
        if v_t not in G:
            G.add_node(v_t)
        # add transformed edge with capacity cap
        G.add_edge(u_t, v_t, capacity=cap)
        # accumulate demands
        demands[u_t] -= lo
        demands[v_t] += lo
        orig_edges_info.append({
            "u": u,
            "v": v,
            "lo": lo,
            "hi": hi,
            "u_t": u_t,
            "v_t": v_t
        })

    return G, demands, orig_edges_info, node_map_in, node_map_out, split_nodes


def run_feasibility_check(G, demands):
    """
    Create super-source s* and super-sink t*.
    For nodes with demand > 0 add edge s*->node (cap = demand).
    For demand < 0 add edge node->t* (cap = -demand).
    Run max_flow(s*, t*). Return (flow_value, flow_dict, s_star, t_star, total_pos_demand)
    """
    s_star = "__SUPER_SRC__"
    t_star = "__SUPER_SNK__"
    H = G.copy()
    H.add_node(s_star)
    H.add_node(t_star)
    total_pos = 0.0
    for n, d in demands.items():
        if d > EPS:
            H.add_edge(s_star, n, capacity=d)
            total_pos += d
        elif d < -EPS:
            H.add_edge(n, t_star, capacity=-d)

    # networkx.maximum_flow is deterministic enough (edmonds_karp default)
    flow_value, flow_dict = nx.maximum_flow(H, s_star, t_star, capacity="capacity")
    return flow_value, flow_dict, s_star, t_star, total_pos, H


def reconstruct_base_circulation(orig_edges_info, flow_on_transformed):
    """
    Given the flow_on_transformed (dict from run_feasibility_check),
    compute f' for each original edge (flow on transformed edge),
    then f0 = f' + lo (baseline actual flows achiving lower bounds).
    Returns dict mapping (u,v,index)-> f0 and also maps transformed edge flows f'.
    """
    f_prime = []  # flows on transformed edges in same order as orig_edges_info
    # flow_on_transformed is dict[u_t][v_t] = flow
    for einfo in orig_edges_info:
        u_t = einfo["u_t"]
        v_t = einfo["v_t"]
        flow_uv = 0.0
        if u_t in flow_on_transformed and v_t in flow_on_transformed[u_t]:
            flow_uv = float(flow_on_transformed[u_t][v_t])
        # f' is the flow found on transformed edge; f0 = f' + lo
        f_prime.append(flow_uv)
    f0 = []
    for idx, einfo in enumerate(orig_edges_info):
        f0.append(f_prime[idx] + float(einfo["lo"]))
    return f_prime, f0


def build_residual_graph_for_supply(orig_edges_info, node_map_in, node_map_out, split_nodes, f0):
    """
    Build residual graph (with transformed node names) where capacities are hi - f0.
    We'll return a DiGraph with capacity attributes and also keep mapping from transformed edge -> original edge index.
    """
    R = nx.DiGraph()
    # add nodes
    nodes = set()
    for e in orig_edges_info:
        nodes.add(e["u_t"])
        nodes.add(e["v_t"])
    # ensure node-split edges (node_in->node_out) are included as nodes already
    for n in nodes:
        R.add_node(n)
    # add transformed edges with residual capacities
    transformed_to_index = {}
    for i, e in enumerate(orig_edges_info):
        u_t = e["u_t"]
        v_t = e["v_t"]
        hi = float(e["hi"])
        flow0 = float(f0[i])
        residual = hi - flow0
        if residual < 0 and residual > -1e-9:
            residual = 0.0
        if residual < -EPS:
            # negative residual means infeasible; but keep 0 capacity to allow detection
            residual = 0.0
        R.add_edge(u_t, v_t, capacity=residual)
        transformed_to_index[(u_t, v_t)] = i
    return R, transformed_to_index


def add_source_supply_and_compute(R, sources, node_map_out, sink, node_map_in):
    """
    Add a super-source S connected to source nodes (their transformed node is source_out),
    and compute max flow from S to sink_transformed (sink_in or sink).
    Return flow value and flow dict.
    """
    S = "__SRC_AGG__"
    R2 = R.copy()
    R2.add_node(S)
    total_supply = 0.0
    for sname, supply in sources.items():
        supply_f = float(supply)
        total_supply += supply_f
        s_t = node_map_out.get(sname, sname)
        # ensure node exists
        if s_t not in R2:
            R2.add_node(s_t)
        R2.add_edge(S, s_t, capacity=supply_f)
    # sink transformed node is sink_in (if split) or sink
    sink_t = node_map_in.get(sink, sink)
    if sink_t not in R2:
        R2.add_node(sink_t)

    # compute max flow
    flow_value, flow_dict = nx.maximum_flow(R2, S, sink_t, capacity="capacity")
    return flow_value, flow_dict, S, sink_t, total_supply, R2


def add_flows_together(orig_edges_info, f0, added_flow_transformed, transformed_to_index):
    """
    added_flow_transformed is flow dict returned from maxflow on residual graph with S included.
    We need to extract added flows on transformed edges and add to f0 (per original edge).
    Return final flows list aligned with orig_edges_info.
    """
    added = [0.0] * len(orig_edges_info)
    # added_flow_transformed is dict[u][v] = flow (includes S edges). We consider only edges that map to original edges
    for u_t, inner in added_flow_transformed.items():
        for v_t, val in inner.items():
            if (u_t, v_t) in transformed_to_index:
                idx = transformed_to_index[(u_t, v_t)]
                added[idx] = float(val)
    final = []
    for i, e in enumerate(orig_edges_info):
        final.append(float(f0[i]) + float(added[i]))
    return final


def flows_on_transformed_from_flowdict(flow_dict):
    """
    Normalize networkx flow_dict which is nested dicts; produce same structure.
    """
    return flow_dict


def compute_flow_into_sink_from_f0(orig_edges_info, f0, sink, node_map_in):
    """
    Compute how much flow f0 already sends into sink (sum of flows on edges whose transformed v_t == sink_in).
    """
    sink_t = node_map_in.get(sink, sink)
    total = 0.0
    for i, e in enumerate(orig_edges_info):
        if e["v_t"] == sink_t:
            total += float(f0[i])
    return total


def build_residual_from_flow_dict(H, flow_dict, s_star, t_star):
    """
    Given a graph H (used in feasibility check) and the flow_dict returned by maximum_flow,
    build the residual graph and return set of nodes reachable from s_star in the residual.
    Residual forward capacity: capacity - flow.
    Residual backward capacity: flow.
    """
    R = nx.DiGraph()
    for u in H.nodes():
        R.add_node(u)
    for u, vattrs in H.adj.items():
        for v, attr in vattrs.items():
            cap = float(attr.get("capacity", 0.0))
            flow = 0.0
            if u in flow_dict and v in flow_dict[u]:
                flow = float(flow_dict[u][v])
            fwd = cap - flow
            if fwd > EPS:
                R.add_edge(u, v, capacity=fwd)
            if flow > EPS:
                # backward residual
                R.add_edge(v, u, capacity=flow)
    # BFS from s_star
    q = deque([s_star])
    seen = set([s_star])
    while q:
        cur = q.popleft()
        for _, nbr, data in R.out_edges(cur, data=True):
            if data.get("capacity", 0.0) > EPS and nbr not in seen:
                seen.add(nbr)
                q.append(nbr)
    return seen, R


def format_output_success(orig_edges_info, final_flows):
    flows_out = []
    # Present flows using original node names and full flow value
    for i, e in enumerate(orig_edges_info):
        flows_out.append({
            "from": e["u"],
            "to": e["v"],
            "flow": float(final_flows[i])
        })
    return flows_out


def format_infeasible_certificate(H, flow_value, total_pos, s_star, t_star, flow_dict, orig_edges_info, node_map_in, node_map_out, split_nodes):
    # Build residual, get reachable nodes from s_star
    reachable, residual = build_residual_from_flow_dict(H, flow_dict, s_star, t_star)
    # For reporting cut_reachable, map back to original node names (remove __in/__out suffixes)
    reachable_original = set()
    for rn in reachable:
        if rn in (s_star, t_star):
            continue
        # if it's a split name like "a__in" or "a__out", reduce to 'a'
        if rn.endswith("__in"):
            reachable_original.add(rn[:-len("__in")])
        elif rn.endswith("__out"):
            reachable_original.add(rn[:-len("__out")])
        else:
            reachable_original.add(rn)
    # demand_balance = total_pos - flow_value
    demand_balance = float(max(0.0, total_pos - flow_value))
    # tight_nodes: nodes (original) whose node-in->node-out edge is saturated and node_in is reachable
    tight_nodes = []
    for n in split_nodes:
        n_in = node_map_in[n]
        n_out = node_map_out[n]
        # check saturation of edge n_in -> n_out in H
        cap = 0.0
        flow_on_edge = 0.0
        if H.has_edge(n_in, n_out):
            cap = float(H[n_in][n_out].get("capacity", 0.0))
            # flow on edge from flow_dict
            if n_in in flow_dict and n_out in flow_dict[n_in]:
                flow_on_edge = float(flow_dict[n_in][n_out])
        # saturated if cap - flow <= EPS
        if cap > 0 and (cap - flow_on_edge) <= 1e-7:
            # check if n_in in reachable set (meaning on source side of cut)
            if n_in in reachable:
                tight_nodes.append(n)
    # tight_edges: edges crossing cut (from reachable to unreachable) that are saturated; include how much flow needed (capacity - flow)
    tight_edges = []
    for u, v, attr in H.edges(data=True):
        # original nodes only (skip s* and t*)
        if u in (s_star, t_star) or v in (s_star, t_star):
            continue
        # crossing from reachable to unreachable?
        if (u in reachable) and (v not in reachable):
            cap = float(attr.get("capacity", 0.0))
            flow_on_edge = 0.0
            if u in flow_dict and v in flow_dict[u]:
                flow_on_edge = float(flow_dict[u][v])
            remaining = cap - flow_on_edge
            if remaining <= 1e-7:
                # find corresponding original edge(s) mapped to this transformed u->v
                original_refs = []
                # map back: transformed nodes may be like 'a__out' -> original 'a' etc.
                u_orig = u
                v_orig = v
                if u.endswith("__out"):
                    u_orig = u[:-len("__out")]
                elif u.endswith("__in"):
                    u_orig = u[:-len("__in")]
                if v.endswith("__in"):
                    v_orig = v[:-len("__in")]
                elif v.endswith("__out"):
                    v_orig = v[:-len("__out")]
                tight_edges.append({
                    "from": u_orig,
                    "to": v_orig,
                    "flow_needed": 0.0  # saturated => needs more to satisfy demand beyond capacity
                })
    return list(sorted(reachable_original)), {
        "demand_balance": demand_balance,
        "tight_nodes": sorted(tight_nodes),
        "tight_edges": tight_edges
    }


def main():
    edges, sources, sink, node_caps = read_input()

    # Build transformed graph and demands
    G, demands, orig_edges_info, node_map_in, node_map_out, split_nodes = build_transformed_graph(edges, node_caps, sources, sink)

    # Run feasibility check for lower bounds
    flow_value, flow_dict, s_star, t_star, total_pos, H = run_feasibility_check(G, demands)

    if flow_value + 1e-9 < total_pos - 1e-12:
        # infeasible
        cut_reachable, deficit = format_infeasible_certificate(H, flow_value, total_pos, s_star, t_star, flow_dict, orig_edges_info, node_map_in, node_map_out, split_nodes)
        out = {
            "status": "infeasible",
            "cut_reachable": cut_reachable,
            "deficit": deficit
        }
        print(json.dumps(out, indent=2))
        return

    # feasible for lower-bounds: reconstruct base circulation f0
    # flow_dict here is on H (which included edges from s_star/t_star). We only need flows on transformed edges corresponding to original edges.
    f_prime, f0 = reconstruct_base_circulation(orig_edges_info, flow_dict)

    # compute how much f0 already sends to sink
    base_into_sink = compute_flow_into_sink_from_f0(orig_edges_info, f0, sink, node_map_in)

    # Build residual graph capacities (hi - f0)
    R, transformed_to_index = build_residual_graph_for_supply(orig_edges_info, node_map_in, node_map_out, split_nodes, f0)

    # Run max flow from aggregated source (connected to sources) to sink on residual graph
    added_flow_value, added_flow_dict, S, sink_t, total_supply, R2 = add_source_supply_and_compute(R, sources, node_map_out, sink, node_map_in)

    # total flow to sink = base_into_sink + added_flow_value
    total_flow_to_sink = base_into_sink + float(added_flow_value)

    # Extract added flows on transformed edges and sum with f0 to get final flows per original edge
    final_flows = add_flows_together(orig_edges_info, f0, added_flow_dict, transformed_to_index)

    flows_out = format_output_success(orig_edges_info, final_flows)

    out = {
        "status": "ok",
        "max_flow_per_min": float(total_flow_to_sink),
        "flows": flows_out
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()