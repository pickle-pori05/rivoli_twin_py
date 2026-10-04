"""Container: Scenario generator.

Produces everything that would come from real data if it existed:
synthetic demand, local traffic, operator events and baseline speed profiles.
"""
import math
from dataclasses import dataclass, field

from .config import T0, DURATION, SENSOR_SEGMENTS, SAMPLE_PERIOD, fmt


def corridor_rate(t: int) -> float:
    """Vehicles/hour entering at Concorde: 430 base + tourist peak of 540 at 15:45."""
    h = (t - T0) / 3600
    return 430 + 540 * math.exp(-(((h - 1.75) / 0.7) ** 2))


def quais_local_rate(t: int) -> float:
    h = (t - T0) / 3600
    return 400 + 140 * math.exp(-(((h - 2.0) / 0.9) ** 2))


def sthonore_local_rate(t: int) -> float:
    return 90.0


@dataclass
class Surge:
    start: int
    end: int
    factor: float = 1.45


@dataclass
class SensorFailure:
    segment: str
    start: int
    end: int


@dataclass
class Scenario:
    name: str = "saturday_tourist_peak"
    seed: int = 7
    surges: list = field(default_factory=list)
    sensor_failures: list = field(default_factory=list)

    def demand_factor(self, t: int) -> float:
        f = 1.0
        for s in self.surges:
            if s.start <= t < s.end:
                f *= s.factor
        return f

    def sensor_offline(self, segment: str, t: int) -> bool:
        return any(f.segment == segment and f.start <= t < f.end for f in self.sensor_failures)


def demand_table():
    """One row per minute: the synthetic demand that drives the simulator."""
    rows = []
    for m in range(DURATION // 60):
        t = T0 + m * 60
        rows.append((m, fmt(t), round(corridor_rate(t), 1), round(quais_local_rate(t), 1), round(sthonore_local_rate(t), 1)))
    return rows


def build_baseline_profiles(seed: int = 99) -> dict:
    """Run an uncontrolled 'previous Saturday' and keep the mean speed per segment per minute.

    These profiles play the role of historical data: the twin uses them when a sensor is offline.
    """
    from .traffic_simulator import TrafficSimulator  # local import avoids a cycle

    sim = TrafficSimulator(Scenario(name="baseline_profile_run", seed=seed))
    profiles = {s: [] for s in SENSOR_SEGMENTS}
    acc = {s: [] for s in SENSOR_SEGMENTS}
    while sim.t < T0 + DURATION:
        sim.step()
        if sim.t % SAMPLE_PERIOD == 0:
            for s in SENSOR_SEGMENTS:
                acc[s].append(sim.measure(s).speed_kmh)
        if sim.t % 60 == 0:
            for s in SENSOR_SEGMENTS:
                profiles[s].append(sum(acc[s]) / len(acc[s]))
                acc[s] = []
    return profiles


def build_baseline_profiles_sumo(seed: int = 99) -> dict:
    """Same as build_baseline_profiles, but the 'previous Saturday' is an uncontrolled SUMO run.

    Used with --sumo so that inferred values come from the same traffic model the twin observes.
    """
    from .config import SEGMENTS
    from .simulation_bridge import SumoSimulationBridge

    bridge = SumoSimulationBridge("sumo_network/rivoli.sumocfg", {s: s for s in SEGMENTS},
                                  {s: f"det_{s}" for s in SEGMENTS if SEGMENTS[s].signal},
                                  {s: "chatelet" for s in SEGMENTS if SEGMENTS[s].signal},
                                  Scenario(name="baseline_profile_run", seed=seed))
    profiles = {s: [] for s in SENSOR_SEGMENTS}
    acc = {s: [] for s in SENSOR_SEGMENTS}
    while bridge.time < T0 + DURATION:
        bridge.step()
        t = bridge.time
        if t % SAMPLE_PERIOD == 0:
            for s in SENSOR_SEGMENTS:
                acc[s].append(bridge.read_segment(s).speed_kmh)
        if t % 60 == 0:
            for s in SENSOR_SEGMENTS:
                profiles[s].append(sum(acc[s]) / len(acc[s]) if acc[s] else SEGMENTS[s].free_speed_kmh)
                acc[s] = []
    bridge.close()
    return profiles
