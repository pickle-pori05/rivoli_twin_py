# Changes after the review of 30 Sept 2026

| File | Change | Why |
|---|---|---|
| `rivoli_twin/simulation_bridge.py` | Each signalised approach (A3, B2, C2) is now driven as its own link of the SUMO node `chatelet`, with the same 90 s plan as the Python model (`config.SIGNALS`: base green, offset, new green from the next cycle). Red state read per approach. | Before, `set_green('A3', …)` changed phase 0 (= C2, residential street) and phase 2 (= B2), turned the cycle into 120 s, and the red state of all approaches was read from B2. |
| `rivoli_twin/simulation_bridge.py` | Demand multiplier back to 1.0. | The 0.7 factor only compensated the wrong signal; the SUMO run must use the same synthetic demand as the twin. |
| `sumo_network/rivoli.edg.xml`, `rivoli.net.xml` | Explicit edge lengths equal to `config.py` (B2 was 418 m instead of 1 400 m); exit X with 3 lanes as in the model. Net rebuilt with `netconvert`. | The twin must reason about the same road it observes (representativeness). |
| `rivoli_twin/scenario_generator.py`, `main.py` | New `build_baseline_profiles_sumo()`, used with `--sumo`. | Inferred values in SUMO runs came from the Python simulator. |
| `main.py` | Standard set back to 7 runs (adds sensor A2 offline 15:30-16:10 and surge 15:00-15:20, with and without control). | README promised 7 runs; T3/T4 results visible in the dashboard. |
| `rivoli_twin/traffic_management.py` | VMS log no longer claims a fixed "2 s after observation". | The value was hard-coded, not measured. |
| `dashboard.py` | 3 traffic lights instead of 6; "load index from speed" instead of "traffic volume"; cost formula shows the uncertainty margin. | Consistency with the model. |
| `README.md`, `docs/C4_level4_code.md` | Correct dependencies, runs and known limitations; `MqttBroker` marked as planned. | Remove claims that were not true. |
| removed | `fix.py`, `fix_dashboard.py`, `dashboard_backup.py` | Leftover editing scripts (UTF-16, unused). |
| `data/` | Regenerated with `python main.py --sumo`. | Dashboard shows the results used in the report. |

Results reported in the report (section 7.4) come from `python main.py` and `python main.py --sumo` with this version.
