# Rivoli Digital Twin (Python implementation)

Closed-loop IoT / Digital Twin demonstrator for a synthetic Rue de Rivoli corridor:
simulator -> virtual sensors -> message broker -> digital twin core -> traffic management -> simulator.
One module per C4 container, one class per C4 component (see docs/C4_level4_code.md).

## Two interchangeable traffic simulators
| Option | Simulator | Bridge class |
|---|---|---|
| default | Built-in Python car-following model (`traffic_simulator.py`) | `LocalSimulationBridge` |
| `--sumo` | Eclipse SUMO through TraCI (`sumo_network/`) | `SumoSimulationBridge` |

Both use the same road network (lengths, speeds, signal plans from `config.py`) and the same synthetic demand.

## Run
    python main.py                 # 7 standard runs, Python simulator -> data/rivoli_twin.db + data/csv/
    python main.py --sumo          # same 7 runs with SUMO/TraCI
    python main.py --single --res high --echo
    python main.py --single --fail A2@15:30-16:10 --surge 15:20 --echo
    streamlit run dashboard.py     # replay dashboard over data/rivoli_twin.db

Standard runs: no control; twin with low / medium / high residential sensitivity;
twin medium with sensor S-A2 offline 15:30-16:10; no control and twin medium with a +45 % surge 15:00-15:20.

## Requirements
- Python 3.9+. The simulation itself (default mode) uses only the standard library.
- `pip install -r requirements.txt` for the dashboard (streamlit, pandas) and for `--sumo` (traci).
- `--sumo` also needs Eclipse SUMO installed (`sumo` and `netconvert` on the PATH).
  Rebuild the network after editing nodes/edges: `sumo_network/build_network.bat`.

## Data (all synthetic)
| Table | Content |
|---|---|
| segments, routes, signal_plans | Static road network (road network model) |
| demand_profile | Synthetic demand per minute (corridor + local traffic) |
| baseline_profiles | Speed per segment per minute from an uncontrolled "previous Saturday" (seed 99), used for inference |
| runs | One row per experiment with its parameters and events |
| observations | Every sensor message (1 per sensor per minute) |
| twin_states | Twin estimate per segment per minute (observed/inferred, confidence, load index, queue) |
| decisions | Decision log (REQ1, REQ2, ROUTE, MONITOR, TWIN, SENSOR) |
| actions | Commands sent to lights, VMS and routing |
| kpis_minute | Ground-truth KPIs per minute (read from the simulator, not from the sensors) |
| run_summary | Final KPIs per run |

## Known limitations
- The message broker is `InMemoryBroker` (MQTT-style topics and wildcards, JSON payloads).
  A real MQTT adapter (e.g. paho-mqtt + Mosquitto) with the same `subscribe/publish` interface is not implemented yet.
- In SUMO the three signalised approaches (A3, B2, C2) are three controlled links of one node (chatelet);
  each link is driven with its own 90 s plan, like three independent signals.
- When a sensor is offline the twin uses the baseline profile of an *uncontrolled* Saturday, which over-estimates
  congestion while the twin is acting (see report, section 7.3, test T3).
