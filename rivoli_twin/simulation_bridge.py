"""Container: Simulation bridge.

Single entry point between the twin and the traffic simulator. The demo uses
LocalSimulationBridge; SumoSimulationBridge shows the same interface on top of TraCI.
"""
from abc import ABC, abstractmethod

from .traffic_simulator import TrafficSimulator, Measurement
from .config import SIGNALS, CYCLE


class SimulationBridge(ABC):
    @property
    @abstractmethod
    def time(self) -> int: ...

    @abstractmethod
    def step(self) -> None: ...

    @abstractmethod
    def read_segment(self, segment_id: str) -> Measurement: ...

    @abstractmethod
    def set_green(self, segment_id: str, green_s: int) -> None: ...

    @abstractmethod
    def set_route_chooser(self, chooser) -> None: ...

    def close(self) -> None:
        pass


class LocalSimulationBridge(SimulationBridge):
    def __init__(self, simulator: TrafficSimulator):
        self.sim = simulator

    @property
    def time(self) -> int:
        return self.sim.t

    def step(self):
        self.sim.step()

    def read_segment(self, segment_id):
        return self.sim.measure(segment_id)

    def set_green(self, segment_id, green_s):
        self.sim.set_next_green(segment_id, green_s)

    def set_route_chooser(self, chooser):
        self.sim.route_chooser = chooser


class SumoSimStats:
    def __init__(self):
        self.in_system = 0
        self.pending = {"corridor": []}
        self.tts = 0
        self.green_time = {"A3": 40}
        self.sum_trip_time = 0
        self.trips = 0
        self.trips_by_route = {"A": 0, "B": 0, "C": 0}
        self.recent = []
        
    def avg_recent_trip_min(self):
        if self.trips == 0:
            return None
        return self.sum_trip_time / self.trips / 60

class SumoSimulationBridge(SimulationBridge):
    """Same interface on top of SUMO/TraCI (requires SUMO and a .sumocfg built from OSM).

    Not used by the demo. Edge ids, lane-area detector ids and TLS ids must match the SUMO network.
    """

    def __init__(self, sumocfg: str, edge_ids: dict, detector_ids: dict, tls_ids: dict, scenario=None):
        import traci  # noqa: provided by the SUMO installation
        self.traci = traci
        # Use start instead of start+label to avoid the "already active" issue, or close properly. 
        # Using a label is sometimes safer, but we already fixed it with close()
        traci.start(["sumo", "-c", sumocfg, "--step-length", "1", "--no-warnings"])
        self.edge_ids, self.detector_ids, self.tls_ids = edge_ids, detector_ids, tls_ids
        self.chooser = lambda: "A"
        self.sim = SumoSimStats()
        self.scenario = scenario
        self._vid = 0
        import random
        self.rng = random.Random(scenario.seed if scenario else 42)
        self.depart_times = {}
        # Signals: SUMO has one TLS node (chatelet) with one controlled link per approach.
        # Each link is driven with the SAME plan as the Python simulator (config.SIGNALS:
        # 90 s cycle, own base green and offset), so both simulators share one signal logic.
        self.link_index = {}
        for tls in set(tls_ids.values()):
            for idx, links in enumerate(self.traci.trafficlight.getControlledLinks(tls)):
                for (in_lane, _out, _via) in links:
                    edge = in_lane.rsplit("_", 1)[0]
                    for seg, e in edge_ids.items():
                        if e == edge and seg in tls_ids:
                            self.link_index[seg] = (tls, idx)
        self.green_time = {seg: SIGNALS[seg].base_green for seg in self.link_index}
        self.next_green = dict(self.green_time)
        self._apply_signals(self.time)

    @property
    def time(self) -> int:
        return int(self.traci.simulation.getTime())

    def step(self):
        from .scenario_generator import corridor_rate, quais_local_rate, sthonore_local_rate
        
        t = self.time
        
        # Inject vehicles dynamically if scenario is provided
        if self.scenario:
            # Same synthetic demand as the Python simulator (set < 1.0 only for sensitivity tests).
            demand_multiplier = 1.0
            
            expected_corridor = (corridor_rate(t) * self.scenario.demand_factor(t) / 3600) * demand_multiplier
            for _ in range(int(expected_corridor) + (1 if self.rng.random() < (expected_corridor % 1) else 0)):
                self._vid += 1
                vid = f"corridor_{self._vid}"
                route = self.chooser()
                self.traci.vehicle.add(vid, f"corridor_{route}", typeID="car")
                self.depart_times[vid] = (t, route)
                self.sim.in_system += 1
                
            expected_b = (quais_local_rate(t) / 3600) * demand_multiplier
            for _ in range(int(expected_b) + (1 if self.rng.random() < (expected_b % 1) else 0)):
                self._vid += 1
                self.traci.vehicle.add(f"localB_{self._vid}", "local_B", typeID="car")
                
            expected_c = (sthonore_local_rate(t) / 3600) * demand_multiplier
            for _ in range(int(expected_c) + (1 if self.rng.random() < (expected_c % 1) else 0)):
                self._vid += 1
                self.traci.vehicle.add(f"localC_{self._vid}", "local_C", typeID="car")

        # Signal plan for the next second (new green applied at the start of each approach's cycle)
        self._apply_signals(t + 1)
        self.traci.simulationStep()
        
        # Track departed (in case they were buffered)
        # Track arrived
        for vid in self.traci.simulation.getArrivedIDList():
            if vid in self.depart_times:
                self.sim.in_system -= 1
                depart_t, route = self.depart_times[vid]
                tt = self.time - depart_t
                self.sim.sum_trip_time += tt
                self.sim.trips += 1
                
                # Update recent trips for KPI
                self.sim.recent.append((self.time, tt))
                while self.sim.recent and self.sim.recent[0][0] < self.time - 900:
                    self.sim.recent.pop(0)
                    
                if route in self.sim.trips_by_route:
                    self.sim.trips_by_route[route] += 1
                
        # Update tts
        self.sim.tts += self.sim.in_system

    def read_segment(self, segment_id):
        edge = self.edge_ids[segment_id]
        speed = self.traci.edge.getLastStepMeanSpeed(edge) * 3.6
        n = self.traci.edge.getLastStepVehicleNumber(edge)
        queue, red = 0.0, False
        if segment_id in self.detector_ids:
            det = self.detector_ids[segment_id]
            queue = self.traci.lanearea.getJamLengthMeters(det) / self.traci.lanearea.getLength(det)
            red = not self._is_green(segment_id, self.time)
        return Measurement(speed, min(1.0, queue), red, n)

    def _is_green(self, seg, t):
        return ((t + SIGNALS[seg].offset) % CYCLE) < self.green_time[seg]

    def _apply_signals(self, t):
        states = {}
        for seg, (tls, idx) in self.link_index.items():
            if (t + SIGNALS[seg].offset) % CYCLE == 0:
                self.green_time[seg] = self.next_green[seg]
            st = states.setdefault(tls, list(self.traci.trafficlight.getRedYellowGreenState(tls)))
            st[idx] = "G" if self._is_green(seg, t) else "r"
        for tls, st in states.items():
            self.traci.trafficlight.setRedYellowGreenState(tls, "".join(st))
        if "A3" in self.green_time:
            self.sim.green_time["A3"] = self.green_time["A3"]

    def set_green(self, segment_id, green_s):
        """Same contract as the Python simulator: the new green applies from the next cycle of that approach."""
        self.next_green[segment_id] = green_s

    def set_route_chooser(self, chooser):
        self.chooser = chooser

    def close(self):
        self.traci.close()
