#!/usr/bin/env python3
"""
run_samples.py

Usage:
  python run_samples.py                # uses default python commands for factory & belts
  python run_samples.py "python factory/main.py" "python belts/main.py"

What it does:
 - Ensures samples exist (uses test samples if available else writes small built-in samples)
 - Runs factory and belts commands on the samples
 - Saves outputs to outputs/sample_factory_output.json and outputs/sample_belts_output.json
 - Optionally runs verify_factory.py and verify_belts.py if present
 - Prints a summary
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FACTORY_CMD = sys.argv[1] if len(sys.argv) > 1 else "python factory/main.py"
BELTS_CMD = sys.argv[2] if len(sys.argv) > 2 else "python belts/main.py"

OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(exist_ok=True)

SAMPLES_DIR = ROOT / "tests"
SAMPLES_DIR.mkdir(exist_ok=True)

# sample factory JSON (from assignment PDF)
SAMPLE_FACTORY = {
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

# sample belts JSON (from assignment PDF)
SAMPLE_BELTS = {
  "edges": [
    {"from": "s1", "to": "a", "lo": 0, "hi": 900},
    {"from": "a", "to": "b", "lo": 0, "hi": 900},
    {"from": "b", "to": "sink", "lo": 0, "hi": 900},
    {"from": "s2", "to": "a", "lo": 0, "hi": 600},
    {"from": "a", "to": "c", "lo": 0, "hi": 600},
    {"from": "c", "to": "sink", "lo": 0, "hi": 600}
  ],
  "sources": {"s1": 900, "s2": 600},
  "sink": "sink"
}

def ensure_sample(path: Path, sample):
    if path.exists():
        return path
    path.write_text(json.dumps(sample, indent=2))
    print(f"Wrote sample to {path}")
    return path

def run_command(cmd_str, input_path, output_path):
    # cmd_str might be like "python factory/main.py" - split for subprocess.
    if isinstance(cmd_str, str):
        cmd = cmd_str.split()
    else:
        cmd = cmd_str
    with open(input_path, "r") as inf, open(output_path, "w") as outf:
        proc = subprocess.run(cmd, stdin=inf, stdout=outf, stderr=subprocess.PIPE, text=True)
    return proc

def run_verifier(verifier_path, input_path, output_path):
    if not verifier_path.exists():
        return None, "missing"
    proc = subprocess.run([sys.executable, str(verifier_path), str(input_path), str(output_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc, proc.returncode

def main():
    # Prepare sample files in tests/
    sample_factory_path = SAMPLES_DIR / "sample_factory.json"
    sample_belts_path = SAMPLES_DIR / "sample_belts.json"
    ensure_sample(sample_factory_path, SAMPLE_FACTORY)
    ensure_sample(sample_belts_path, SAMPLE_BELTS)

    # Run factory
    factory_out_path = OUT_DIR / "sample_factory_output.json"
    print(f"Running factory: {FACTORY_CMD} < {sample_factory_path} > {factory_out_path}")
    proc_fact = run_command(FACTORY_CMD, sample_factory_path, factory_out_path)
    if proc_fact.returncode != 0:
        print("factory command failed (non-zero exit). stderr:")
        print(proc_fact.stderr)
    else:
        print("factory command finished (exit 0).")

    # Run belts
    belts_out_path = OUT_DIR / "sample_belts_output.json"
    print(f"Running belts: {BELTS_CMD} < {sample_belts_path} > {belts_out_path}")
    proc_belts = run_command(BELTS_CMD, sample_belts_path, belts_out_path)
    if proc_belts.returncode != 0:
        print("belts command failed (non-zero exit). stderr:")
        print(proc_belts.stderr)
    else:
        print("belts command finished (exit 0).")

    # Run verifiers if present
    verify_factory = ROOT / "verify_factory.py"
    verify_belts = ROOT / "verify_belts.py"

    print("\nRunning verifiers (if available)...")
    vf_proc, vf_code = run_verifier(verify_factory, sample_factory_path, factory_out_path)
    if vf_proc is None:
        print("verify_factory.py not found — skipping factory verification.")
    else:
        print("verify_factory.py stdout:")
        print(vf_proc.stdout.strip())
        if vf_proc.stderr.strip():
            print("verify_factory.py stderr:")
            print(vf_proc.stderr.strip())
        print("verify_factory.py exit code:", vf_proc.returncode)

    vb_proc, vb_code = run_verifier(verify_belts, sample_belts_path, belts_out_path)
    if vb_proc is None:
        print("verify_belts.py not found — skipping belts verification.")
    else:
        print("verify_belts.py stdout:")
        print(vb_proc.stdout.strip())
        if vb_proc.stderr.strip():
            print("verify_belts.py stderr:")
            print(vb_proc.stderr.strip())
        print("verify_belts.py exit code:", vb_proc.returncode)

    print("\nSummary:")
    def read_json_safe(p):
        try:
            return json.loads(open(p).read())
        except Exception as e:
            return {"_error": str(e)}
    fact_out = read_json_safe(factory_out_path)
    belts_out = read_json_safe(belts_out_path)
    print(f"factory -> {factory_out_path} : status = {fact_out.get('status') if isinstance(fact_out, dict) else fact_out}")
    print(f"belts   -> {belts_out_path} : status = {belts_out.get('status') if isinstance(belts_out, dict) else belts_out}")

    print("\nOutputs saved in", OUT_DIR)

if __name__ == "__main__":
    main()
