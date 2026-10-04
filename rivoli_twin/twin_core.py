"""Container: Digital twin core.

Components: ObservationIngestor, SignalAwareInterpreter, InferenceModule,
TrafficStateEstimator, RoadNetworkModel, DigitalTwinCore (orchestrates them).
"""
from dataclasses import dataclass, asdict

from .config import SEGMENTS, SENSOR_SEGMENTS, ROUTES, T0, fmt


@dataclass
class SegmentEstimate:
    segment: str
    speed_kmh: float
    source: str            # "observed" | "inferred"
    confidence: float
    vc: float              # volume/capacity estimated from speed
    queue: float
    red_share: float
    signal_induced: bool
    travel_time_s: float

    @property
    def congested(self) -> bool:
        return self.vc > 0.8 and not self.signal_induced


class RoadNetworkModel:
    def __init__(self):
        self.segments = SEGMENTS
        self.routes = ROUTES

    def free_speed(self, sid):
        return self.segments[sid].free_speed_kmh

    def length(self, sid):
        return self.segments[sid].length_m

    def is_signalised(self, sid):
        return self.segments[sid].signal


class ObservationIngestor:
    """Validates messages and keeps the latest one per segment for the current cycle."""

    def __init__(self):
        self.speed = {}
        self.detector = {}

    def on_speed(self, topic, msg):
        sid = topic.split("/")[2]
        if sid not in SENSOR_SEGMENTS:
            return
        if msg.get("status") == "ok" and not (0 <= msg.get("v_avg", -1) <= 150):
            msg = {**msg, "status": "invalid"}
        self.speed[sid] = msg

    def on_detector(self, topic, msg):
        self.detector[msg["segment"]] = msg

    def pop_cycle(self):
        s, d = self.speed, self.detector
        self.speed, self.detector = {}, {}
        return s, d


class InferenceModule:
    """Replaces a missing observation with the baseline profile (same day, same minute)."""

    def __init__(self, profiles: dict, confidence: float = 0.6):
        self.profiles = profiles
        self.confidence = confidence

    def infer(self, sid: str, minute_index: int, fallback: float) -> float:
        p = self.profiles.get(sid, [])
        return p[minute_index] if 0 <= minute_index < len(p) else fallback


class SignalAwareInterpreter:
    """A low speed with mostly red time and a short queue is the light, not congestion."""

    RED_SHARE_MIN = 0.4
    QUEUE_MAX = 0.5

    def is_signal_induced(self, signalised: bool, vc: float, red_share: float, queue: float) -> bool:
        return signalised and vc > 0.8 and red_share > self.RED_SHARE_MIN and queue < self.QUEUE_MAX


class TrafficStateEstimator:
    """Greenshields: V/C ~= 2 (1 - v / v_free); travel time = length / speed."""

    def __init__(self, network: RoadNetworkModel):
        self.network = network

    def vc(self, sid, speed):
        return max(0.0, min(2.0, 2 * (1 - speed / self.network.free_speed(sid))))

    def travel_time(self, sid, speed):
        return self.network.length(sid) / (max(speed, 3.0) / 3.6)


class DigitalTwinCore:
    def __init__(self, broker, profiles, log, storage=None, run_id=None):
        self.broker, self.log, self.storage, self.run_id = broker, log, storage, run_id
        self.network = RoadNetworkModel()
        self.ingestor = ObservationIngestor()
        self.inference = InferenceModule(profiles)
        self.interpreter = SignalAwareInterpreter()
        self.estimator = TrafficStateEstimator(self.network)
        self.state = {}
        self._was_offline = set()
        self._signal_log_t = {}
        broker.subscribe("paris/rivoli/+/speed", self.ingestor.on_speed)
        broker.subscribe("paris/rivoli/+/detector", self.ingestor.on_detector)
        broker.subscribe("paris/rivoli/cycle", self.on_cycle)

    def on_cycle(self, topic, msg):
        t = msg["t"]
        minute_index = round((t - T0) / 60) - 1
        speed_msgs, det_msgs = self.ingestor.pop_cycle()
        for sid in SENSOR_SEGMENTS:
            m = speed_msgs.get(sid, {"status": "missing"})
            d = det_msgs.get(sid, {"queue_max": 0.0, "red_share": 0.0})
            if m.get("status") == "ok":
                speed, conf, src = m["v_avg"], 1.0, "observed"
                if sid in self._was_offline:
                    self._was_offline.discard(sid)
                    self.log.add(t, "SENSOR", f"S-{sid} back online -> observed data restored")
            else:
                speed = self.inference.infer(sid, minute_index, self.network.free_speed(sid))
                conf, src = self.inference.confidence, "inferred"
                if sid not in self._was_offline:
                    self._was_offline.add(sid)
                    self.log.add(t, "SENSOR", f"S-{sid} {m.get('status')} -> speed inferred from baseline profile "
                                              f"(Sat {fmt(t)}): {speed:.0f} km/h, confidence {conf:.2f}")
            vc = self.estimator.vc(sid, speed)
            induced = self.interpreter.is_signal_induced(self.network.is_signalised(sid), vc, d["red_share"], d["queue_max"])
            if induced and t - self._signal_log_t.get(sid, -10**9) > 1200:
                self._signal_log_t[sid] = t
                self.log.add(t, "TWIN", f"{sid} low speed {speed:.0f} km/h with {d['red_share']*100:.0f}% red time and "
                                        f"short queue -> attributed to the red phase, not congestion")
            self.state[sid] = SegmentEstimate(sid, speed, src, conf, vc, d["queue_max"], d["red_share"], induced,
                                              self.estimator.travel_time(sid, speed))
        if self.storage:
            self.storage.save_observations(self.run_id, t, speed_msgs)
            self.storage.save_states(self.run_id, t, self.state)
        self.broker.publish("twin/state", {"t": t, "segments": {k: asdict(v) for k, v in self.state.items()}})
