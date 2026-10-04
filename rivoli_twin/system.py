"""Wiring of all containers for one run (controlled or no-control baseline) + KPI evaluation."""
from dataclasses import dataclass

from .config import T0, DURATION, fmt
from .scenario_generator import Scenario
from .traffic_simulator import TrafficSimulator
from .simulation_bridge import LocalSimulationBridge
from .broker import InMemoryBroker
from .sensors import SensorSimulator
from .twin_core import DigitalTwinCore
from .traffic_management import TrafficManagementService
from .decision_log import DecisionLog


class KPIEvaluator:
    """Ground-truth KPIs read from the simulator (not from the twin's sensors)."""

    def __init__(self, bridge, storage=None, run_id=None):
        self.bridge, self.storage, self.run_id = bridge, storage, run_id
        self.a2, self.a3 = [], []
        self.max_queue_a3 = 0.0
        self.vms_minutes = 0

    def tick(self, t, tms=None):
        if t % 5 == 0:
            self.a2.append(self.bridge.read_segment("A2").speed_kmh)
            self.a3.append(self.bridge.read_segment("A3").queue_occupancy)
        if t % 60 == 0:
            sim = self.bridge.sim
            q = max(self.a3)
            self.max_queue_a3 = max(self.max_queue_a3, q)
            vms = int(bool(tms and tms.vms.on))
            self.vms_minutes += vms
            avg = sim.avg_recent_trip_min()
            if self.storage:
                self.storage.save_kpi(self.run_id, (fmt(t), sim.in_system, len(sim.pending["corridor"]),
                                                    round(sim.tts / 3600, 2), None if avg is None else round(avg, 2),
                                                    round(sum(self.a2) / len(self.a2), 2), round(q, 3), vms,
                                                    sim.green_time["A3"]))
            self.a2, self.a3 = [], []

    def summary(self):
        s = self.bridge.sim
        return (round(s.sum_trip_time / max(1, s.trips) / 60, 2), round(s.tts / 3600, 1), s.trips,
                s.trips_by_route["A"], s.trips_by_route["B"], s.trips_by_route["C"],
                round(self.max_queue_a3, 3), self.vms_minutes)


@dataclass
class RunConfig:
    label: str
    controlled: bool = True
    sensitivity: str = "medium"
    inferred_confidence: float = 0.6
    compliance: float = 0.7


def run(scenario: Scenario, cfg: RunConfig, profiles: dict, storage=None, echo=False, use_sumo=False):
    if use_sumo:
        from .simulation_bridge import SumoSimulationBridge
        from .config import SEGMENTS
        edge_ids = {s: s for s in SEGMENTS}
        detector_ids = {s: f"det_{s}" for s in SEGMENTS if SEGMENTS[s].signal}
        tls_ids = {s: "chatelet" for s in ["A3", "B2", "C2"]}  # one TLS node, one controlled link per approach
        bridge = SumoSimulationBridge("sumo_network/rivoli.sumocfg", edge_ids, detector_ids, tls_ids, scenario)
    else:
        sim = TrafficSimulator(scenario)
        bridge = LocalSimulationBridge(sim)
        
    log = DecisionLog(echo=echo)
    events = "; ".join([f"surge {fmt(s.start)}-{fmt(s.end)} x{s.factor}" for s in scenario.surges] +
                       [f"S-{f.segment} offline {fmt(f.start)}-{fmt(f.end)}" for f in scenario.sensor_failures])
    run_id = storage.new_run(cfg.label, cfg.controlled, scenario.seed, cfg.sensitivity if cfg.controlled else None,
                             cfg.inferred_confidence, cfg.compliance, events) if storage else None
    tms = None
    if cfg.controlled:
        from .broker import InMemoryBroker
        broker = InMemoryBroker()
        
        sensors = SensorSimulator(bridge, broker, scenario)
        core = DigitalTwinCore(broker, profiles, log, storage, run_id)
        core.inference.confidence = cfg.inferred_confidence
        tms = TrafficManagementService(broker, bridge, log, cfg.sensitivity, cfg.compliance, storage, run_id)
    kpi = KPIEvaluator(bridge, storage, run_id)
    while bridge.time < T0 + DURATION:
        bridge.step()
        t = bridge.time
        if cfg.controlled:
            sensors.tick(t)          # 5 s samples, 1 min publish -> broker -> twin core -> traffic management
        kpi.tick(t, tms)
    summary = kpi.summary()
    if storage:
        storage.save_decisions(run_id, log.entries)
        storage.save_summary(run_id, summary)
    bridge.close()
    return summary, log
