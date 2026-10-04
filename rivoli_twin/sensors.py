"""Container: Sensor simulator.

Speed sensors sample every 5 s, add noise, and publish one average per minute.
Lane-area detectors on signalised approaches publish queue occupancy and red share.
"""
import random
from dataclasses import dataclass, field

from .config import SENSOR_SEGMENTS, SEGMENTS, SAMPLE_PERIOD, AGGREGATION_PERIOD, fmt


@dataclass
class SpeedSensor:
    segment_id: str
    noise_sd: float = 1.5
    online: bool = True
    samples: list = field(default_factory=list)

    @property
    def sensor_id(self):
        return "S-" + self.segment_id


@dataclass
class LaneAreaDetector:
    segment_id: str
    queue: list = field(default_factory=list)
    red: list = field(default_factory=list)


class SensorSimulator:
    def __init__(self, bridge, broker, scenario, seed: int = 777):
        self.bridge, self.broker, self.scenario = bridge, broker, scenario
        self.rng = random.Random(seed)
        self.sensors = {s: SpeedSensor(s) for s in SENSOR_SEGMENTS}
        self.detectors = {s: LaneAreaDetector(s) for s in SENSOR_SEGMENTS if SEGMENTS[s].signal}
        self.manual_offline = set()

    def set_offline(self, segment_id: str, offline: bool = True):
        (self.manual_offline.add if offline else self.manual_offline.discard)(segment_id)

    def tick(self, t: int):
        if t % SAMPLE_PERIOD == 0:
            self._sample()
        if t % AGGREGATION_PERIOD == 0:
            self._publish(t)

    def _sample(self):
        for sid, sensor in self.sensors.items():
            m = self.bridge.read_segment(sid)
            sensor.samples.append(m.speed_kmh)
            if sid in self.detectors:
                self.detectors[sid].queue.append(m.queue_occupancy)
                self.detectors[sid].red.append(1 if m.red else 0)

    def _publish(self, t: int):
        hh = fmt(t)
        for sid, sensor in self.sensors.items():
            offline = sid in self.manual_offline or self.scenario.sensor_offline(sid, t)
            if offline:
                msg = {"sensor": sensor.sensor_id, "t": hh, "status": "offline"}
            else:
                noisy = [max(0.0, v + self.rng.gauss(0, sensor.noise_sd)) for v in sensor.samples]
                msg = {"sensor": sensor.sensor_id, "t": hh, "v_avg": round(sum(noisy) / len(noisy), 1),
                       "n": len(noisy), "status": "ok"}
            sensor.samples = []
            self.broker.publish(f"paris/rivoli/{sid}/speed", msg)
        for sid, det in self.detectors.items():
            self.broker.publish(f"paris/rivoli/{sid}/detector", {
                "segment": sid, "t": hh, "queue_max": round(max(det.queue), 3),
                "red_share": round(sum(det.red) / len(det.red), 3)})
            det.queue, det.red = [], []
        self.broker.publish("paris/rivoli/cycle", {"t": t})
