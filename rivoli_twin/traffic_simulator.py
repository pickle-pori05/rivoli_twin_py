"""External system stand-in: a lightweight car-following simulator replacing SUMO.

Each vehicle follows a Newell-type rule: v = min(v_free, v + a, gap / tau), with parallel
update (leaders' previous positions), signal stop lines and spillback between segments.
In the full project this module is replaced by SUMO, reached through the Simulation bridge.
"""
import random
from collections import deque
from dataclasses import dataclass

from .config import (SEGMENTS, ROUTES, SIGNALS, UPDATE_ORDER, CYCLE, TAU, JAM, ACC, T0)
from .scenario_generator import Scenario, corridor_rate, quais_local_rate, sthonore_local_rate


class Vehicle:
    __slots__ = ("id", "route", "path", "ri", "s", "ps", "v", "t0", "corridor")

    def __init__(self, vid, route, t0, v, corridor):
        self.id, self.route, self.path, self.ri = vid, route, ROUTES[route], 0
        self.s = self.ps = 0.0
        self.v, self.t0, self.corridor = v, t0, corridor


@dataclass
class Measurement:
    speed_kmh: float
    queue_occupancy: float
    red: bool
    vehicles: int


class TrafficSimulator:
    def __init__(self, scenario: Scenario, route_chooser=None):
        self.scenario = scenario
        self.t = T0
        self.rng = random.Random(scenario.seed)
        self.route_chooser = route_chooser or (lambda: "A")
        self.veh = {sid: [] for sid in SEGMENTS}
        self.green_time = {sid: p.base_green for sid, p in SIGNALS.items()}
        self.next_green = dict(self.green_time)
        self.pending = {"corridor": deque(), "bB": deque(), "bC": deque()}
        self._vid = 0
        self.in_system = 0                 # corridor vehicles waiting or driving
        self.tts = 0                       # total time spent, vehicle-seconds
        self.trips = 0
        self.sum_trip_time = 0
        self.trips_by_route = {"A": 0, "B": 0, "C": 0}
        self.recent = deque()              # (finish_time, trip_time) over the last 15 min

    # ---- signals --------------------------------------------------------------
    def is_green(self, sid: str) -> bool:
        if sid not in SIGNALS:
            return True
        return ((self.t + SIGNALS[sid].offset) % CYCLE) < self.green_time[sid]

    def set_next_green(self, sid: str, green: int):
        self.next_green[sid] = green

    # ---- demand ----------------------------------------------------------------
    def _insert(self, sid, queue, route_fn, corridor):
        if not queue:
            return
        seg, vs = SEGMENTS[sid], self.veh[sid]
        last = vs[-1] if vs else None
        if last and last.s < JAM / seg.lanes + 2:
            return
        self._vid += 1
        v0 = min(seg.free_speed_kmh / 3.6, last.v) if last else seg.free_speed_kmh / 3.6
        vs.append(Vehicle(self._vid, route_fn(), queue.popleft(), v0, corridor))

    # ---- main loop -------------------------------------------------------------
    def step(self):
        self.t += 1
        t = self.t
        for sid, plan in SIGNALS.items():
            if (t + plan.offset) % CYCLE == 0:
                self.green_time[sid] = self.next_green[sid]

        r1, r2, r3 = self.rng.random(), self.rng.random(), self.rng.random()
        if r1 < corridor_rate(t) * self.scenario.demand_factor(t) / 3600:
            self.pending["corridor"].append(t)
            self.in_system += 1
        if r2 < quais_local_rate(t) / 3600:
            self.pending["bB"].append(t)
        if r3 < sthonore_local_rate(t) / 3600:
            self.pending["bC"].append(t)
        self._insert("E", self.pending["corridor"], self.route_chooser, True)
        self._insert("B1", self.pending["bB"], lambda: "bB", False)
        self._insert("C1", self.pending["bC"], lambda: "bC", False)

        for sid in UPDATE_ORDER:
            seg, arr = SEGMENTS[sid], self.veh[sid]
            L, vf = seg.length_m, seg.free_speed_kmh / 3.6
            jam, tau = JAM / seg.lanes, TAU / seg.lanes
            red = seg.signal and not self.is_green(sid)
            n_out = 0
            for i, v in enumerate(arr):
                own = v.s
                if i > 0:
                    gap = arr[i - 1].ps - v.s - jam
                else:
                    dist = L - v.s
                    nxt = v.path[v.ri + 1] if v.ri + 1 < len(v.path) else None
                    if nxt is None:
                        gap = 1e9
                    else:
                        nv_ = self.veh[nxt]
                        gap = dist + nv_[-1].ps - JAM / SEGMENTS[nxt].lanes if nv_ else 1e9
                if red and v.s < L:
                    gap = min(gap, L - v.s - 0.5)
                speed = max(0.0, min(vf, v.v + ACC, max(0.0, gap) / tau))
                v.ps, v.v = own, speed
                v.s += speed
                if v.s >= L and i == n_out:
                    n_out += 1
            for _ in range(n_out):
                v = arr.pop(0)
                v.s -= L
                v.ps = v.s
                v.ri += 1
                if v.ri >= len(v.path):
                    self._finish(v)
                else:
                    self.veh[v.path[v.ri]].append(v)
        self.tts += self.in_system

    def _finish(self, v: Vehicle):
        if not v.corridor:
            return
        self.in_system -= 1
        tt = self.t - v.t0
        self.trips += 1
        self.sum_trip_time += tt
        self.trips_by_route[v.route] += 1
        self.recent.append((self.t, tt))
        while self.recent and self.recent[0][0] < self.t - 900:
            self.recent.popleft()

    # ---- measurement (what a loop detector / lane-area detector would return) ----
    def measure(self, sid: str) -> Measurement:
        seg, arr = SEGMENTS[sid], self.veh[sid]
        if arr:
            speed = sum(v.v for v in arr) / len(arr) * 3.6
            slow = [v.s for v in arr if v.v < 2]
            queue = max(0.0, min(1.0, (seg.length_m - min(slow)) / seg.length_m)) if slow else 0.0
        else:
            speed, queue = seg.free_speed_kmh, 0.0
        return Measurement(speed, queue, seg.signal and not self.is_green(sid), len(arr))

    def avg_recent_trip_min(self):
        return sum(tt for _, tt in self.recent) / len(self.recent) / 60 if self.recent else None
