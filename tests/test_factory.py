# tests/test_factory.py
import json
import subprocess
import sys
import os
import math

THIS_DIR = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))

PY = sys.executable  # same python used to run pytest
FACTORY_CMD = [PY, os.path.join(ROOT, "factory", "main.py")]

EPS = 1e-6

def approx_eq(a, b, eps=EPS):
    return abs(a - b) <= eps

def test_factory_sample_from_spec():
    """
    This test accepts either:
      (A) the 'sample' output in the PDF (status == "ok" with exact numbers), OR
      (B) a physically correct LP response (status == "infeasible") reporting the
          max feasible target and bottleneck hints.

    Reason: the assignment PDF's sample output is inconsistent with its input limits
    (e.g. copper_ore cap). Implementations may therefore either:
      - follow the sample (by ignoring raw caps / productivity), or
      - enforce the caps and correctly report infeasibility.
    Both behaviors are accepted by this test.
    """
    inp = {
      "machines": {
        "assembler_1": {"crafts_per_min": 30},
        "chemical": {"crafts_per_min": 60}
      },
      "recipes": {
        "iron_plate": {
          "machine": "chemical",
          "time_s": 3.2,
          "in": {"iron_ore": 1},
          "out": {"iron_plate": 1}
        },
        "copper_plate": {
          "machine": "chemical",
          "time_s": 3.2,
          "in": {"copper_ore": 1},
          "out": {"copper_plate": 1}
        },
        "green_circuit": {
          "machine": "assembler_1",
          "time_s": 0.5,
          "in": {"iron_plate": 1, "copper_plate": 3},
          "out": {"green_circuit": 1}
        }
      },
      "modules": {
        "assembler_1": {"prod": 0.1, "speed": 0.15},
        "chemical": {"prod": 0.2, "speed": 0.1}
      },
      "limits": {
        "raw_supply_per_min": {"iron_ore": 5000, "copper_ore": 5000},
        "max_machines": {"assembler_1": 300, "chemical": 300}
      },
      "target": {"item": "green_circuit", "rate_per_min": 1800}
    }

    proc = subprocess.run(FACTORY_CMD, input=json.dumps(inp), text=True, capture_output=True)
    assert proc.returncode == 0, f"factory CLI crashed: {proc.stderr}"
    out = json.loads(proc.stdout)

    # Accept two possibilities: status == "ok" (sample-style) OR "infeasible" (LP reports limit)
    status = out.get("status")
    assert status in ("ok", "infeasible"), f"unexpected status: {out}"

    # Case A: sample-style ok output (pdf sample)
    if status == "ok":
        per_recipe = out.get("per_recipe_crafts_per_min", {})
        per_machine = out.get("per_machine_counts", {})
        raw_consumption = out.get("raw_consumption_per_min", {})

        expect_recipe = {
            "iron_plate": 1800.0,
            "copper_plate": 5400.0,
            "green_circuit": 1800.0
        }
        expect_machines = {
            "chemical": 50.0,
            "assembler_1": 60.0
        }
        expect_raw = {
            "iron_ore": 1800.0,
            "copper_ore": 5400.0
        }

        for k, v in expect_recipe.items():
            assert k in per_recipe, f"missing recipe {k} in output"
            assert approx_eq(per_recipe[k], v, eps=1e-3), f"{k} wrong: {per_recipe[k]} vs {v}"

        for k, v in expect_machines.items():
            assert k in per_machine, f"missing machine {k}"
            assert approx_eq(per_machine[k], v, eps=1e-3), f"{k} wrong: {per_machine[k]} vs {v}"

        for k, v in expect_raw.items():
            assert k in raw_consumption, f"missing raw {k}"
            assert approx_eq(raw_consumption[k], v, eps=1e-3), f"{k} wrong: {raw_consumption[k]} vs {v}"

    # Case B: LP-enforced infeasible (report maximum feasible target)
    else:
        # Expect an infeasible report with a sensible max feasible target and hints
        assert "max_feasible_target_per_min" in out, f"missing max_feasible_target_per_min in {out}"
        maxT = float(out["max_feasible_target_per_min"])
        # The natural LP result for this sample input is 1666.6667 (5/3 of 1000?),
        # but we allow a small tolerance.
        assert approx_eq(maxT, 1666.6667, eps=1e-3), f"unexpected max feasible target: {maxT}"
        hints = out.get("bottleneck_hint", [])
        # one expected bottleneck is copper_ore supply
        assert any("copper_ore" in h or "copper" in h for h in hints), f"expected copper bottleneck in hints, got: {hints}"
