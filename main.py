"""Run the Rivoli digital twin experiments and build the SQLite database.

Examples
  python main.py                                   # standard experiment set -> data/rivoli_twin.db + CSV
  python main.py --single --res high --echo        # one controlled run, decisions printed live
  python main.py --single --fail A2@15:30-16:10 --surge 15:20
"""
import argparse
import time

from rivoli_twin.config import parse_hhmm
from rivoli_twin.scenario_generator import (Scenario, Surge, SensorFailure, build_baseline_profiles,
                                           build_baseline_profiles_sumo)
from rivoli_twin.storage import DataStorage
from rivoli_twin.system import run, RunConfig

HEADER = f"{'run':<34}{'avg trip':>9}{'TTS veh.h':>11}{'trips':>7}{'via A':>7}{'via B':>7}{'via C':>7}{'max A3 q':>10}{'VMS min':>9}"


def show(label, s):
    print(f"{label:<34}{s[0]:>8.1f}m{s[1]:>11.0f}{s[2]:>7}{s[3]:>7}{s[4]:>7}{s[5]:>7}{s[6]*100:>9.0f}%{s[7]:>9}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/rivoli_twin.db")
    ap.add_argument("--csv", default="data/csv")
    ap.add_argument("--single", action="store_true", help="one controlled run + its baseline")
    ap.add_argument("--res", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--confidence", type=float, default=0.6)
    ap.add_argument("--compliance", type=float, default=0.7)
    ap.add_argument("--fail", action="append", default=[], help="SEG@HH:MM-HH:MM, e.g. A2@15:30-16:10")
    ap.add_argument("--surge", action="append", default=[], help="HH:MM start of a 20 min +45%% surge")
    ap.add_argument("--echo", action="store_true", help="print decisions as they happen")
    ap.add_argument("--sumo", action="store_true", help="Use SUMO instead of the internal Python traffic simulator")
    a = ap.parse_args()

    import os
    os.makedirs(os.path.dirname(a.db) or ".", exist_ok=True)
    t0 = time.time()
    storage = DataStorage(a.db)
    print("Generating baseline profiles (previous synthetic Saturday)...")
    profiles = build_baseline_profiles_sumo(seed=99) if a.sumo else build_baseline_profiles(seed=99)
    storage.save_profiles(profiles)

    def scenario(fails=(), surges=()):
        sc = Scenario(seed=7)
        for f in fails:
            seg, win = f.split("@")
            s, e = win.split("-")
            sc.sensor_failures.append(SensorFailure(seg, parse_hhmm(s), parse_hhmm(e)))
        for s in surges:
            st = parse_hhmm(s)
            sc.surges.append(Surge(st, st + 1200))
        return sc

    if a.single:
        plan = [(scenario(a.fail, a.surge), RunConfig("Baseline (No VMS Control)", controlled=False)),
                (scenario(a.fail, a.surge), RunConfig(f"VMS Controlled - {a.res.capitalize()} Residential Penalty", True, a.res, a.confidence, a.compliance))]
    else:
        fail, surge = ["A2@15:30-16:10"], ["15:00"]
        plan = [(scenario(), RunConfig("Baseline (No VMS Control)", controlled=False)),
                (scenario(), RunConfig("VMS Controlled - Low Residential Penalty", True, "low")),
                (scenario(), RunConfig("VMS Controlled - Medium Residential Penalty", True, "medium")),
                (scenario(), RunConfig("VMS Controlled - High Residential Penalty", True, "high")),
                (scenario(fails=fail), RunConfig("VMS Controlled - Medium - Sensor A2 offline 15:30-16:10", True, "medium")),
                (scenario(surges=surge), RunConfig("Baseline (No VMS Control) - Surge 15:00-15:20", controlled=False)),
                (scenario(surges=surge), RunConfig("VMS Controlled - Medium - Surge 15:00-15:20", True, "medium"))]

    print(HEADER)
    for sc, cfg in plan:
        summary, _ = run(sc, cfg, profiles, storage, echo=a.echo and cfg.controlled, use_sumo=a.sumo)
        show(cfg.label, summary)
    storage.export_csv(a.csv)
    print(f"\nDatabase: {a.db}   CSV: {a.csv}/   ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
