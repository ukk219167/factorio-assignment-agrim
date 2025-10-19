import json
import subprocess
import sys
import os

THIS_DIR = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))

PY = sys.executable
BELTS_CMD = [PY, os.path.join(ROOT, "belts", "main.py")]

def test_belts_sample_from_spec():
    # Sample from the assignment PDF (two sources s1=900, s2=600 => total 1500)
    inp = {
      "edges": [
        {"from": "s1", "to": "a", "lo": 0, "hi": 900},
        {"from": "a", "to": "b", "lo": 0, "hi": 900},
        {"from": "b", "to": "sink", "lo": 0, "hi": 900},
        {"from": "s2", "to": "a", "lo": 0, "hi": 600},
        {"from": "a", "to": "c", "lo": 0, "hi": 600},
        {"from": "c", "to": "sink", "lo": 0, "hi": 600}
      ],
      "sources": {"s1": 900, "s2": 600},
      "sink": "sink",
      # no node_caps in sample
    }

    proc = subprocess.run(BELTS_CMD, input=json.dumps(inp), text=True, capture_output=True)
    assert proc.returncode == 0, f"belts CLI crashed: {proc.stderr}"
    out = json.loads(proc.stdout)

    assert out.get("status") == "ok", f"expected ok status, got: {out}"

    max_flow = out.get("max_flow_per_min")
    flows = out.get("flows", [])

    # Expect total flow 1500
    assert abs(float(max_flow) - 1500.0) <= 1e-6, f"expected 1500 max flow, got {max_flow}"

    # Convert to map for quick assertions
    fmap = {(f["from"], f["to"]): float(f["flow"]) for f in flows}

    assert abs(fmap.get(("s1","a"), 0.0) - 900.0) <= 1e-6
    assert abs(fmap.get(("a","b"), 0.0) - 900.0) <= 1e-6
    assert abs(fmap.get(("b","sink"), 0.0) - 900.0) <= 1e-6
    assert abs(fmap.get(("s2","a"), 0.0) - 600.0) <= 1e-6
    assert abs(fmap.get(("a","c"), 0.0) - 600.0) <= 1e-6
    assert abs(fmap.get(("c","sink"), 0.0) - 600.0) <= 1e-6
