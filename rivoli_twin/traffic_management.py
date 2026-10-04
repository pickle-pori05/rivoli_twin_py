"""Container: Traffic management service.

Components: RuleEngine, TrafficLightController (Req 1), AlternativeRouteEngine,
ResidentialPenaltyModel, RandomDistributionEngine, VMSController (Req 2, 3).
"""
import math
import random
from dataclasses import dataclass

from .config import (ALT_ROUTES, SIGNALS, CYCLE, INTERGREEN_TOTAL, PEDESTRIAN_MIN, RESIDENTIAL_SENSITIVITY,
                     ROUTE_NAMES, free_flow_minutes, residential_fraction, fmt)
from .twin_core import SegmentEstimate


@dataclass
class RouteCost:
    route: str
    travel_min: float
    cost: float
    residential_share: float
    congested: bool


class RuleEngine:
    QUEUE_THRESHOLD = 0.8
    VC_THRESHOLD = 0.8
    VC_RELEASE = 0.7

    def __init__(self):
        self.persist = 0
        self.calm = 0

    def evaluate_congestion(self, state):
        rivoli = [state[s] for s in ALT_ROUTES["A"]]
        congested = [e.segment for e in rivoli if e.congested]
        max_vc = max(0.0 if e.signal_induced else e.vc for e in rivoli)
        low_conf = any(state[s].confidence < 1 for s in congested)
        if congested:
            self.persist += 1
            self.calm = 0
        else:
            self.persist = 0
            if max_vc < self.VC_RELEASE:
                self.calm += 1
        trigger = bool(congested) and (not low_conf or self.persist >= 2)
        waiting = bool(congested) and low_conf and self.persist < 2
        return congested, max_vc, trigger, waiting, self.calm >= 2


class TrafficLightController:
    def __init__(self, bridge, log):
        self.bridge, self.log = bridge, log
        self.extension = {sid: 0 for sid in SIGNALS}

    @staticmethod
    def extension_for(queue: float, current: int) -> int:
        if queue > RuleEngine.QUEUE_THRESHOLD:
            return min(15, 5 + round((queue - 0.8) / 0.2 * 10))
        if queue < 0.5:
            return 0
        return current

    def update(self, t, state):
        actions = []
        for sid, plan in SIGNALS.items():
            q = state[sid].queue
            target = self.extension_for(q, self.extension[sid])
            if target == self.extension[sid]:
                continue
            green = plan.base_green + target
            cross = CYCLE - green - INTERGREEN_TOTAL
            assert cross >= PEDESTRIAN_MIN, "pedestrian minimum violated"
            self.extension[sid] = target
            self.bridge.set_green(sid, green)
            actions.append(("signal", sid, green))
            if target:
                self.log.add(t, "REQ1", f"{sid} queue {q*100:.0f}% > 80% -> green {green} s (+{target} s) next cycle, "
                                        f"cross phase {cross} s >= {PEDESTRIAN_MIN} s pedestrian min OK")
            else:
                self.log.add(t, "REQ1", f"{sid} queue {q*100:.0f}% < 50% -> green back to {green} s")
        return actions


class AlternativeRouteEngine:
    """Travel time per route from the twin; inferred segments add (1 - confidence) x travel time."""

    def route_times(self, state):
        out = {}
        for r, segs in ALT_ROUTES.items():
            base = sum(state[s].travel_time_s for s in segs)
            margin = sum((1 - state[s].confidence) * state[s].travel_time_s for s in segs)
            out[r] = (base / 60, (base + margin) / 60, any(state[s].congested for s in segs))
        return out


class ResidentialPenaltyModel:
    def __init__(self, sensitivity: str = "medium"):
        self.sensitivity = sensitivity

    @property
    def s(self):
        return RESIDENTIAL_SENSITIVITY[self.sensitivity]

    def apply(self, times) -> dict:
        costs = {}
        for r, (tmin, tcautious, congested) in times.items():
            R = residential_fraction(r)
            costs[r] = RouteCost(r, tmin, tcautious * (1 + self.s * R), R, congested)
        return costs


class RandomDistributionEngine:
    """Logit split between alternatives; used by the simulator whenever a corridor vehicle departs."""

    def __init__(self, theta=0.6, compliance=0.7, seed=4242):
        self.theta, self.compliance = theta, compliance
        self.rng = random.Random(seed)
        self.active = False
        self.divert_share = 0.0
        self.p_b = 0.5
        self.counts = {"asked": 0, "B": 0, "C": 0, "ignored": 0}

    def probabilities(self, costs):
        eb, ec = math.exp(-self.theta * costs["B"].cost), math.exp(-self.theta * costs["C"].cost)
        return eb / (eb + ec)

    @staticmethod
    def diversion_share(max_vc, costs):
        if min(costs["B"].cost, costs["C"].cost) >= costs["A"].cost:
            return 0.0
        return max(0.15, min(0.55, 0.2 + (max_vc - 0.8) * 0.6))

    def choose_route(self) -> str:
        if not self.active or self.divert_share <= 0:
            return "A"
        if self.rng.random() < min(1.0, self.divert_share / self.compliance):
            self.counts["asked"] += 1
            if self.rng.random() < self.compliance:
                r = "B" if self.rng.random() < self.p_b else "C"
                self.counts[r] += 1
                return r
            self.counts["ignored"] += 1
        return "A"

    def pop_counts(self):
        c, self.counts = self.counts, {"asked": 0, "B": 0, "C": 0, "ignored": 0}
        return c


class VMSController:
    def __init__(self):
        self.on = False
        self.lines = []

    def render(self, costs):
        self.lines = [(r, f"{r}  {ROUTE_NAMES[r].upper()}", round(costs[r].travel_min),
                       round(costs[r].travel_min - free_flow_minutes(r))) for r in ("A", "B", "C")]
        return self.lines


class TrafficManagementService:
    def __init__(self, broker, bridge, log, sensitivity="medium", compliance=0.7, storage=None, run_id=None):
        self.bridge, self.log, self.storage, self.run_id = bridge, log, storage, run_id
        self.rules = RuleEngine()
        self.lights = TrafficLightController(bridge, log)
        self.routes = AlternativeRouteEngine()
        self.penalty = ResidentialPenaltyModel(sensitivity)
        self.distribution = RandomDistributionEngine(compliance=compliance)
        self.vms = VMSController()
        self._alt_congested = {}
        self._monitor_log_t = {}
        bridge.set_route_chooser(self.distribution.choose_route)
        broker.subscribe("twin/state", self.on_state)

    def on_state(self, topic, msg):
        t = msg["t"]
        state = {k: SegmentEstimate(**v) for k, v in msg["segments"].items()}
        actions = self.lights.update(t, state)                           # Req 1

        costs = self.penalty.apply(self.routes.route_times(state))      # route engine + penalty
        for r in ("B", "C"):
            if (self.vms.on and costs[r].congested and not self._alt_congested.get(r)
                    and t - self._monitor_log_t.get(r, -10**9) > 600):
                self._monitor_log_t[r] = t
                self.log.add(t, "MONITOR", f"Alternative {r} ({ROUTE_NAMES[r]}) now has a congested segment -> its updated cost "
                                           f"{costs[r].cost:.1f} min drives the next split")
            self._alt_congested[r] = costs[r].congested
        last = self.distribution.pop_counts()

        congested, max_vc, trigger, waiting, calm = self.rules.evaluate_congestion(state)
        if waiting:
            self.log.add(t, "TWIN", f"Congestion on {', '.join(congested)} is based on inferred data -> "
                                    f"waiting one more minute to confirm (cautious mode)")
        if trigger and not self.vms.on:
            self.vms.on = True
            self.distribution.active = True
            actions.append(("vms", "Concorde", 1))
            self.log.add(t, "REQ2", f"{', '.join(congested)} V/C {max_vc:.2f} > 0.80 -> VMS activated at {fmt(t)}, "
                                    f"in the same control cycle as the observation (Req 2 limit: 60 s)")
        if self.vms.on and calm:
            self.vms.on = False
            self.distribution.active = False
            self.distribution.divert_share = 0.0
            actions.append(("vms", "Concorde", 0))
            self.log.add(t, "REQ2", f"Rivoli V/C {max_vc:.2f} < 0.70 for 2 min -> VMS back to normal display")
        d = self.distribution
        if self.vms.on:
            d.p_b = d.probabilities(costs)
            d.divert_share = d.diversion_share(max_vc, costs)
            prev = (f" Previous minute: {last['asked']} drivers shown the detour -> {last['B']} took B, "
                    f"{last['C']} took C, {last['ignored']} stayed.") if last["asked"] else ""
            actions.append(("routing", "split", round(d.divert_share, 3)))
        else:
            d.p_b = d.probabilities(costs)
            d.divert_share = 0.0
            prev = ""
            
        metadata = {
            "costs": {r: round(c.cost, 1) for r, c in costs.items()},
            "travel_min": {r: round(c.travel_min, 1) for r, c in costs.items()},
            "residential_share": {r: round(c.residential_share, 2) for r, c in costs.items()},
            "sensitivity": self.penalty.s,
            "probabilities": {"B": round(d.p_b, 2), "C": round(1-d.p_b, 2)},
            "divert_share": round(d.divert_share, 2),
            "previous_minute_stats": last if last["asked"] else None
        }
        self.log.add(t, "ROUTE", f"Cost A {costs['A'].cost:.1f} / B {costs['B'].cost:.1f} / C {costs['C'].cost:.1f} min "
                                 f"(s={self.penalty.s}) -> p(B) {d.p_b:.2f}, p(C) {1-d.p_b:.2f}, "
                                 f"divert {d.divert_share*100:.0f}%.{prev}", metadata)
        self.vms.render(costs)                                           # Req 3: travel times shown
        if self.storage:
            self.storage.save_actions(self.run_id, t, actions)
