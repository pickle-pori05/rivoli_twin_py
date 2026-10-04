"""Static configuration: road network, routes, signal plans and model constants.

Container: Digital twin core -> component "Road network model" (static part).
"""
from dataclasses import dataclass

T0 = 14 * 3600            # scenario start: 14:00 (seconds since midnight)
DURATION = 4 * 3600       # 4 simulated hours
CYCLE = 90                # signal cycle length (s)
TAU = 1.8                 # driver reaction/headway time (s)
JAM = 7.0                 # jam spacing per vehicle (m)
ACC = 2.0                 # max acceleration (m/s per 1 s step)
PEDESTRIAN_MIN = 6        # minimum pedestrian green on the cross phase (s)
INTERGREEN_TOTAL = 6      # two intergreens of 3 s
SAMPLE_PERIOD = 5         # sensor sampling period (s)
AGGREGATION_PERIOD = 60   # sensor output period (s)

RESIDENTIAL_SENSITIVITY = {"low": 0.2, "medium": 0.5, "high": 0.8}


@dataclass(frozen=True)
class Segment:
    id: str
    name: str
    length_m: float
    free_speed_kmh: float
    lanes: int
    residential: int
    signal: bool = False


@dataclass(frozen=True)
class SignalPlan:
    base_green: int
    offset: int


SEGMENTS = {
    "E":  Segment("E",  "Entry - Concorde",          300,  40, 2, 0),
    "A1": Segment("A1", "Rue de Rivoli - Concorde",  800,  40, 1, 0),
    "A2": Segment("A2", "Rue de Rivoli - Tuileries", 700,  40, 1, 0),
    "A3": Segment("A3", "Rue de Rivoli - Louvre",    400,  40, 1, 0, True),
    "B1": Segment("B1", "Quai des Tuileries",        1600, 50, 1, 0),
    "B2": Segment("B2", "Quai du Louvre",            1400, 50, 1, 0, True),
    "C1": Segment("C1", "Rue Saint-Honore",          1000, 30, 1, 1),
    "C2": Segment("C2", "Rue des Bons-Enfants",      900,  30, 1, 1, True),
    "X":  Segment("X",  "Exit - Chatelet",           300,  40, 3, 0),
}
SENSOR_SEGMENTS = ["A1", "A2", "A3", "B1", "B2", "C1", "C2"]
# downstream first, so every vehicle reacts to the already-updated segment ahead
UPDATE_ORDER = ["X", "A3", "B2", "C2", "A2", "B1", "C1", "A1", "E"]

ROUTES = {
    "A": ["E", "A1", "A2", "A3", "X"],   # corridor via Rue de Rivoli
    "B": ["E", "B1", "B2", "X"],         # corridor diverted to the quais
    "C": ["E", "C1", "C2", "X"],         # corridor diverted through residential streets
    "bB": ["B1", "B2", "X"],             # local traffic on the quais
    "bC": ["C1", "C2", "X"],             # local traffic in Saint-Honore
}
ALT_ROUTES = {"A": ["A1", "A2", "A3"], "B": ["B1", "B2"], "C": ["C1", "C2"]}
ROUTE_NAMES = {"A": "Rivoli", "B": "Quais", "C": "St-Honore"}

SIGNALS = {"A3": SignalPlan(40, 0), "B2": SignalPlan(45, 30), "C2": SignalPlan(36, 60)}


def free_flow_minutes(route: str) -> float:
    return sum(SEGMENTS[s].length_m / (SEGMENTS[s].free_speed_kmh / 3.6) for s in ALT_ROUTES[route]) / 60


def residential_fraction(route: str) -> float:
    segs = [SEGMENTS[s] for s in ALT_ROUTES[route]]
    return sum(s.length_m * s.residential for s in segs) / sum(s.length_m for s in segs)


def fmt(t: int) -> str:
    h, m, s = t // 3600, (t // 60) % 60, t % 60
    return f"{h:02d}:{m:02d}" + (f":{s:02d}" if s else "")


def parse_hhmm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 3600 + int(m) * 60
