"""Container: Data storage (SQLite here; PostgreSQL + TimescaleDB in production)."""
import csv
import os
import sqlite3
from datetime import datetime

from .config import SEGMENTS, ROUTES, SIGNALS, CYCLE, fmt
from .scenario_generator import demand_table

SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (id TEXT PRIMARY KEY, name TEXT, length_m REAL, free_speed_kmh REAL,
    lanes INTEGER, residential INTEGER, signalised INTEGER, sensor_id TEXT);
CREATE TABLE IF NOT EXISTS routes (route TEXT, seq INTEGER, segment_id TEXT REFERENCES segments(id),
    PRIMARY KEY (route, seq));
CREATE TABLE IF NOT EXISTS signal_plans (segment_id TEXT PRIMARY KEY REFERENCES segments(id), cycle_s INTEGER,
    base_green_s INTEGER, offset_s INTEGER, pedestrian_min_s INTEGER);
CREATE TABLE IF NOT EXISTS demand_profile (minute INTEGER PRIMARY KEY, time TEXT, corridor_vph REAL,
    quais_local_vph REAL, sthonore_local_vph REAL);
CREATE TABLE IF NOT EXISTS baseline_profiles (segment_id TEXT, minute INTEGER, time TEXT, speed_kmh REAL,
    PRIMARY KEY (segment_id, minute));
CREATE TABLE IF NOT EXISTS runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, controlled INTEGER,
    seed INTEGER, residential_sens TEXT, inferred_confidence REAL, compliance REAL, events TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS observations (run_id INTEGER, time TEXT, sensor_id TEXT, segment_id TEXT,
    v_avg REAL, n INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS twin_states (run_id INTEGER, time TEXT, segment_id TEXT, speed_kmh REAL, source TEXT,
    confidence REAL, vc REAL, queue REAL, red_share REAL, signal_induced INTEGER, travel_time_s REAL);
CREATE TABLE IF NOT EXISTS decisions (run_id INTEGER, time TEXT, tag TEXT, text TEXT, metadata TEXT);
CREATE TABLE IF NOT EXISTS actions (run_id INTEGER, time TEXT, type TEXT, target TEXT, value REAL);
CREATE TABLE IF NOT EXISTS kpis_minute (run_id INTEGER, time TEXT, veh_in_system INTEGER, waiting_to_enter INTEGER,
    tts_veh_h REAL, avg_trip_15min REAL, a2_speed_kmh REAL, a3_queue REAL, vms_on INTEGER, a3_green_s INTEGER);
CREATE TABLE IF NOT EXISTS run_summary (run_id INTEGER PRIMARY KEY, avg_trip_min REAL, tts_veh_h REAL, trips INTEGER,
    trips_a INTEGER, trips_b INTEGER, trips_c INTEGER, max_queue_a3 REAL, vms_minutes INTEGER);
"""


class DataStorage:
    def __init__(self, path: str):
        if os.path.exists(path):
            os.remove(path)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self._write_static()

    def _write_static(self):
        self.db.executemany("INSERT INTO segments VALUES (?,?,?,?,?,?,?,?)", [
            (s.id, s.name, s.length_m, s.free_speed_kmh, s.lanes, s.residential, int(s.signal),
             None if s.id in ("E", "X") else "S-" + s.id) for s in SEGMENTS.values()])
        self.db.executemany("INSERT INTO routes VALUES (?,?,?)",
                            [(r, i, sid) for r, segs in ROUTES.items() for i, sid in enumerate(segs)])
        self.db.executemany("INSERT INTO signal_plans VALUES (?,?,?,?,?)",
                            [(sid, CYCLE, p.base_green, p.offset, 6) for sid, p in SIGNALS.items()])
        self.db.executemany("INSERT INTO demand_profile VALUES (?,?,?,?,?)", demand_table())
        self.db.commit()

    def save_profiles(self, profiles):
        from .config import T0
        self.db.executemany("INSERT INTO baseline_profiles VALUES (?,?,?,?)", [
            (sid, m, fmt(T0 + (m + 1) * 60), round(v, 2)) for sid, vals in profiles.items() for m, v in enumerate(vals)])
        self.db.commit()

    def new_run(self, label, controlled, seed, sens, conf, comp, events):
        cur = self.db.execute("INSERT INTO runs (label, controlled, seed, residential_sens, inferred_confidence, compliance,"
                              " events, created_at) VALUES (?,?,?,?,?,?,?,?)",
                              (label, int(controlled), seed, sens, conf, comp, events, datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid

    def save_observations(self, run_id, t, msgs):
        self.db.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?)", [
            (run_id, fmt(t), m.get("sensor", "S-" + sid), sid, m.get("v_avg"), m.get("n"), m.get("status"))
            for sid, m in msgs.items()])

    def save_states(self, run_id, t, state):
        self.db.executemany("INSERT INTO twin_states VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            (run_id, fmt(t), e.segment, round(e.speed_kmh, 2), e.source, e.confidence, round(e.vc, 3), round(e.queue, 3),
             round(e.red_share, 3), int(e.signal_induced), round(e.travel_time_s, 1)) for e in state.values()])

    def save_actions(self, run_id, t, actions):
        self.db.executemany("INSERT INTO actions VALUES (?,?,?,?,?)", [(run_id, fmt(t), *a) for a in actions])

    def save_decisions(self, run_id, entries):
        self.db.executemany("INSERT INTO decisions VALUES (?,?,?,?,?)", [(run_id, fmt(t), tag, txt, meta) for t, tag, txt, meta in entries])

    def save_kpi(self, run_id, row):
        self.db.execute("INSERT INTO kpis_minute VALUES (?,?,?,?,?,?,?,?,?,?)", (run_id, *row))

    def save_summary(self, run_id, row):
        self.db.execute("INSERT INTO run_summary VALUES (?,?,?,?,?,?,?,?,?)", (run_id, *row))
        self.db.commit()

    def export_csv(self, folder):
        os.makedirs(folder, exist_ok=True)
        tables = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for tname in tables:
            cur = self.db.execute(f"SELECT * FROM {tname}")
            with open(os.path.join(folder, tname + ".csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([d[0] for d in cur.description])
                w.writerows(cur)
