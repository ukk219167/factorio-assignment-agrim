## 1. Environment setup (one-time)

From the project root (`part2_assignment/`):

Create and activate a virtual environment:

Windows:
python -m venv venv
venv\Scripts\activate


macOS / Linux:
python -m venv venv
source venv/bin/activate



Install dependencies:
pip install pulp networkx pytest



## 2. Project layout

part2_assignment/
├─ factory/
│ └─ main.py
├─ belts/
│ └─ main.py
├─ tests/
│ ├─ test_factory.py
│ └─ test_belts.py
├─ verify_factory.py
├─ verify_belts.py
├─ gen_factory.py
├─ gen_belts.py
├─ run_samples.py
├─ README.md
└─ RUN.md



## 3. Running a single solver

Each solver reads JSON from stdin and writes JSON to stdout (no extra prints).

Factory:
python factory/main.py < input.json > output.json



Belts:
python belts/main.py < input.json > output.json



## 4. Running sample testcases with automation

`run_samples.py` executes both solvers on built-in sample inputs (or `tests/sample_*.json` if present), stores outputs in `outputs/`, and runs verifiers if available.

Examples:
default
python run_samples.py

pass custom commands (e.g., use a different python)
python run_samples.py "python factory/main.py" "python belts/main.py"


After running you'll find:
- `outputs/sample_factory_output.json`
- `outputs/sample_belts_output.json`

and verifier messages printed to stdout.

---

## 5. Running unit tests

Run all tests:
pytest -q


Run just factory tests:
pytest -q tests/test_factory.py

Run just belts tests:
pytest -q tests/test_belts.py


---
