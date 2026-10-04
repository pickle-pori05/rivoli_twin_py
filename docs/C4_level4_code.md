# C4 Level 4 - Code

Derived from the Python reference implementation in `rivoli_twin/`. One module per container, one class per component.

| C4 container | Python module | Main classes |
|---|---|---|
| Scenario generator | `scenario_generator.py` | `Scenario`, `Surge`, `SensorFailure`, `build_baseline_profiles()` |
| SUMO (stand-in) | `traffic_simulator.py` | `TrafficSimulator`, `Vehicle`, `Measurement` |
| Simulation bridge | `simulation_bridge.py` | `SimulationBridge`, `LocalSimulationBridge`, `SumoSimulationBridge` |
| Sensor simulator | `sensors.py` | `SensorSimulator`, `SpeedSensor`, `LaneAreaDetector` |
| Message broker | `broker.py` | `InMemoryBroker` (an `MqttBroker` adapter with the same interface is planned, not implemented) |
| Digital twin core | `twin_core.py` | `DigitalTwinCore` + 5 components |
| Traffic management | `traffic_management.py` | `TrafficManagementService` + 6 components |
| Data storage | `storage.py` | `DataStorage` (SQLite schema) |
| Wiring / KPIs | `system.py` | `run()`, `KPIEvaluator` |

## Digital twin core
```mermaid
classDiagram
  direction LR
  class DigitalTwinCore {
    +RoadNetworkModel network
    +ObservationIngestor ingestor
    +InferenceModule inference
    +SignalAwareInterpreter interpreter
    +TrafficStateEstimator estimator
    +dict state
    +on_cycle(topic, msg)
  }
  class ObservationIngestor {
    +dict speed
    +dict detector
    +on_speed(topic, msg)
    +on_detector(topic, msg)
    +pop_cycle() tuple
  }
  class InferenceModule {
    +dict profiles
    +float confidence
    +infer(sid, minute_index, fallback) float
  }
  class SignalAwareInterpreter {
    +RED_SHARE_MIN = 0.4
    +QUEUE_MAX = 0.5
    +is_signal_induced(signalised, vc, red_share, queue) bool
  }
  class TrafficStateEstimator {
    +vc(sid, speed) float
    +travel_time(sid, speed) float
  }
  class RoadNetworkModel {
    +dict segments
    +dict routes
    +free_speed(sid) float
    +length(sid) float
    +is_signalised(sid) bool
  }
  class SegmentEstimate {
    <<dataclass>>
    +str segment
    +float speed_kmh
    +str source
    +float confidence
    +float vc
    +float queue
    +float red_share
    +bool signal_induced
    +float travel_time_s
    +congested() bool
  }
  DigitalTwinCore *-- ObservationIngestor
  DigitalTwinCore *-- InferenceModule
  DigitalTwinCore *-- SignalAwareInterpreter
  DigitalTwinCore *-- TrafficStateEstimator
  DigitalTwinCore *-- RoadNetworkModel
  TrafficStateEstimator --> RoadNetworkModel
  DigitalTwinCore ..> SegmentEstimate : creates
  DigitalTwinCore ..> InMemoryBroker : subscribes speed, detector, cycle / publishes twin-state
  DigitalTwinCore ..> DataStorage : save_observations, save_states
  DigitalTwinCore ..> DecisionLog : SENSOR, TWIN
```

## Traffic management service
```mermaid
classDiagram
  direction LR
  class TrafficManagementService {
    +RuleEngine rules
    +TrafficLightController lights
    +AlternativeRouteEngine routes
    +ResidentialPenaltyModel penalty
    +RandomDistributionEngine distribution
    +VMSController vms
    +on_state(topic, msg)
  }
  class RuleEngine {
    +QUEUE_THRESHOLD = 0.8
    +VC_THRESHOLD = 0.8
    +VC_RELEASE = 0.7
    +int persist
    +int calm
    +evaluate_congestion(state) tuple
  }
  class TrafficLightController {
    +dict extension
    +extension_for(queue, current)$ int
    +update(t, state) list
  }
  class AlternativeRouteEngine {
    +route_times(state) dict
  }
  class ResidentialPenaltyModel {
    +str sensitivity
    +s() float
    +apply(times) dict
  }
  class RandomDistributionEngine {
    +float theta
    +float compliance
    +bool active
    +float divert_share
    +float p_b
    +probabilities(costs) float
    +diversion_share(max_vc, costs)$ float
    +choose_route() str
    +pop_counts() dict
  }
  class VMSController {
    +bool on
    +list lines
    +render(costs) list
  }
  class RouteCost {
    <<dataclass>>
    +str route
    +float travel_min
    +float cost
    +float residential_share
    +bool congested
  }
  TrafficManagementService *-- RuleEngine
  TrafficManagementService *-- TrafficLightController
  TrafficManagementService *-- AlternativeRouteEngine
  TrafficManagementService *-- ResidentialPenaltyModel
  TrafficManagementService *-- RandomDistributionEngine
  TrafficManagementService *-- VMSController
  ResidentialPenaltyModel ..> RouteCost : creates
  TrafficLightController --> SimulationBridge : set_green
  TrafficManagementService ..> SimulationBridge : set_route_chooser(choose_route)
  TrafficManagementService ..> InMemoryBroker : subscribes twin-state
  TrafficManagementService ..> DataStorage : save_actions
```

## Sensing, broker, bridge and simulator
```mermaid
classDiagram
  direction LR
  class SimulationBridge {
    <<abstract>>
    +time() int
    +step()
    +read_segment(segment_id) Measurement
    +set_green(segment_id, green_s)
    +set_route_chooser(chooser)
  }
  class LocalSimulationBridge
  class SumoSimulationBridge {
    +traci
    +dict edge_ids
    +dict detector_ids
    +dict tls_ids
  }
  class TrafficSimulator {
    +int t
    +dict veh
    +dict green_time
    +route_chooser
    +step()
    +is_green(sid) bool
    +set_next_green(sid, green)
    +measure(sid) Measurement
    +avg_recent_trip_min() float
  }
  class Vehicle {
    +str route
    +list path
    +float s
    +float v
    +int t0
    +bool corridor
  }
  class Measurement {
    <<dataclass>>
    +float speed_kmh
    +float queue_occupancy
    +bool red
    +int vehicles
  }
  class SensorSimulator {
    +dict sensors
    +dict detectors
    +tick(t)
    +set_offline(segment_id, offline)
  }
  class SpeedSensor {
    +str segment_id
    +float noise_sd
    +list samples
  }
  class LaneAreaDetector {
    +list queue
    +list red
  }
  class InMemoryBroker {
    +subscribe(pattern, callback)
    +publish(topic, payload)
  }
  class MqttBroker {
    <<planned>>
  }
  class Scenario {
    +int seed
    +list surges
    +list sensor_failures
    +demand_factor(t) float
    +sensor_offline(segment, t) bool
  }
  SimulationBridge <|-- LocalSimulationBridge
  SimulationBridge <|-- SumoSimulationBridge
  LocalSimulationBridge --> TrafficSimulator
  TrafficSimulator o-- Vehicle
  TrafficSimulator ..> Measurement : returns
  TrafficSimulator --> Scenario
  SensorSimulator *-- SpeedSensor
  SensorSimulator *-- LaneAreaDetector
  SensorSimulator --> SimulationBridge : read_segment every 5 s
  SensorSimulator --> InMemoryBroker : publish every 60 s
  SensorSimulator --> Scenario : failures
  InMemoryBroker .. MqttBroker : same interface
```

## Code-level sequence: one minute
```mermaid
sequenceDiagram
  participant Sim as TrafficSimulator
  participant Br as SimulationBridge
  participant Sen as SensorSimulator
  participant MQ as Broker
  participant Core as DigitalTwinCore
  participant TM as TrafficManagementService
  loop every 1 s
    Br->>Sim: step()
  end
  loop every 5 s
    Sen->>Br: read_segment(seg)
    Br-->>Sen: Measurement
  end
  Note over Sen: minute boundary: average 12 samples + noise
  Sen->>MQ: paris/rivoli/{seg}/speed (x7)
  Sen->>MQ: paris/rivoli/{seg}/detector (x3)
  Sen->>MQ: paris/rivoli/cycle
  MQ->>Core: on_speed / on_detector / on_cycle
  Core->>Core: infer, interpret red phase, estimate V/C
  Core->>MQ: twin/state
  MQ->>TM: on_state(state)
  TM->>Br: set_green(A3, 55)
  TM->>TM: costs, penalty, logit, VMS
  Sim->>TM: choose_route() for each departing vehicle
```

## Data storage schema
```mermaid
erDiagram
  SEGMENTS ||--o{ ROUTES : "is part of"
  SEGMENTS ||--o| SIGNAL_PLANS : "may have"
  SEGMENTS ||--o{ BASELINE_PROFILES : "has per minute"
  RUNS ||--o{ OBSERVATIONS : records
  RUNS ||--o{ TWIN_STATES : records
  RUNS ||--o{ DECISIONS : logs
  RUNS ||--o{ ACTIONS : logs
  RUNS ||--o{ KPIS_MINUTE : measures
  RUNS ||--|| RUN_SUMMARY : summarises
  SEGMENTS ||--o{ OBSERVATIONS : "observed on"
  SEGMENTS ||--o{ TWIN_STATES : "estimated for"
  SEGMENTS { text id PK
    text name
    real length_m
    real free_speed_kmh
    int residential
    int signalised }
  ROUTES { text route PK
    int seq PK
    text segment_id FK }
  SIGNAL_PLANS { text segment_id PK
    int cycle_s
    int base_green_s
    int offset_s }
  DEMAND_PROFILE { int minute PK
    real corridor_vph
    real quais_local_vph }
  BASELINE_PROFILES { text segment_id PK
    int minute PK
    real speed_kmh }
  RUNS { int run_id PK
    text label
    int controlled
    text residential_sens
    text events }
  OBSERVATIONS { int run_id FK
    text time
    text sensor_id
    real v_avg
    text status }
  TWIN_STATES { int run_id FK
    text segment_id FK
    real vc
    text source
    real confidence }
  DECISIONS { int run_id FK
    text time
    text tag
    text text }
  ACTIONS { int run_id FK
    text type
    text target
    real value }
  KPIS_MINUTE { int run_id FK
    int veh_in_system
    real tts_veh_h
    real a2_speed_kmh }
  RUN_SUMMARY { int run_id PK
    real avg_trip_min
    int trips_c }
```
