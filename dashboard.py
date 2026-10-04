import sqlite3
import pandas as pd
import streamlit as st
import json

st.set_page_config(page_title="Rivoli Digital Twin", layout="wide")

st.title("Digital Twin: Rivoli Route Optimization")

# --- HELPER FUNCTIONS ---
def time_to_minute(t_str):
    """Converts a time string like '14:45' to an integer minute offset from 14:00 (e.g., 45)"""
    h, m = map(int, t_str.split(':')[:2])
    return (h * 60 + m) - (14 * 60)

def draw_traffic_light(tx, ty):
    return f"""
        <g transform="translate({tx}, {ty})">
            <rect x="0" y="0" width="10" height="30" fill="#222" rx="2"/>
            <circle cx="5" cy="5" r="3" fill="#dc3545"/>
            <circle cx="5" cy="15" r="3" fill="#ffc107"/>
            <circle cx="5" cy="25" r="3" fill="#28a745"/>
        </g>
    """

@st.cache_data
def load_runs():
    conn = sqlite3.connect("data/rivoli_twin.db")
    runs = pd.read_sql("SELECT * FROM runs ORDER BY run_id DESC", conn)
    conn.close()
    return runs

@st.cache_data
def load_run_data(run_id):
    conn = sqlite3.connect("data/rivoli_twin.db")
    states = pd.read_sql("SELECT * FROM twin_states WHERE run_id = ? ORDER BY time", conn, params=(run_id,))
    actions = pd.read_sql("SELECT * FROM actions WHERE run_id = ? ORDER BY time", conn, params=(run_id,))
    decisions = pd.read_sql("SELECT * FROM decisions WHERE run_id = ? ORDER BY time", conn, params=(run_id,))
    kpis = pd.read_sql("SELECT * FROM kpis_minute WHERE run_id = ? ORDER BY time", conn, params=(run_id,))
    observations = pd.read_sql("SELECT * FROM observations WHERE run_id = ? ORDER BY time", conn, params=(run_id,))
    run_summary = pd.read_sql("SELECT * FROM run_summary WHERE run_id = ?", conn, params=(run_id,))
    conn.close()
    return states, actions, decisions, kpis, observations, run_summary

runs_df = load_runs()
if runs_df.empty:
    st.error("Database is empty. Run `python main.py` first.")
    st.stop()

# Select run
run_options = {row["run_id"]: f"Run #{row['run_id']} - {row['label']}" for _, row in runs_df.iterrows()}
st.markdown('### Controls')
col_top1, col_top2 = st.columns([1, 2])
with col_top1:
    selected_run_id = st.selectbox("Select Simulation Scenario", options=list(run_options.keys()), format_func=lambda x: run_options[x])

# Extract penalty level from label
selected_label = runs_df[runs_df["run_id"] == selected_run_id].iloc[0]["label"]
pen_level = "None (Baseline)"
if "Low" in selected_label: pen_level = "Low"
elif "Medium" in selected_label: pen_level = "Medium"
elif "High" in selected_label: pen_level = "High"

states_df, actions_df, decisions_df, kpis_df, observations_df, run_summary_df = load_run_data(selected_run_id)

if states_df.empty:
    st.error("No state data found for this run.")
    st.stop()

# --- TIMELINE SLIDER ---
with col_top2:
    time_steps = sorted(states_df["time"].unique())
    selected_time_idx = st.slider("Simulation Timeline (Minutes from start)", 
                              min_value=0, max_value=len(time_steps)-1, value=0, 
                              format="Minute %d")
    current_time = time_steps[selected_time_idx]
    current_minute = time_to_minute(current_time)

# --- MAP VARIABLES ---
current_state = states_df[states_df["time"] == current_time]
def get_color(vc_ratio):
    if pd.isna(vc_ratio): return "gray"
    if float(vc_ratio) < 0.6: return "#28a745" # Green
    if float(vc_ratio) < 0.8: return "#ffc107" # Yellow
    return "#dc3545" # Red
segments_colors = {row["segment_id"]: get_color(row["vc"]) for _, row in current_state.iterrows()}

current_actions = actions_df[actions_df["time"] == current_time]
split_share = 0.0
for _, a in current_actions.iterrows():
    if a["type"] == "routing" and a["target"] == "split":
        split_share = float(a["value"])

current_obs = observations_df[observations_df["time"] == current_time]
obs_dict = {row["segment_id"]: {"v": row["v_avg"], "n": row["n"], "status": row["status"]} for _, row in current_obs.iterrows()}

def draw_sensor(sid, cx, cy):
    data = obs_dict.get(sid, {})
    if not data or pd.isna(data.get("v")) or data.get("status") == "offline":
        label = f"{sid}: Offline"
    else:
        label = f"Sensor {sid} | {data['v']:.1f} km/h | {data['n']:.0f} cars"
    
    return f"""
    <g class="sensor-group">
        <circle cx="{cx}" cy="{cy}" r="22" fill="transparent" cursor="pointer"/>
        <circle cx="{cx}" cy="{cy}" r="9" fill="white" stroke="#333" stroke-width="2" pointer-events="none"/>
        <text x="{cx}" y="{cy - 14}" fill="#ddd" font-family="Arial" font-size="14" font-weight="bold" text-anchor="middle" pointer-events="none">{sid}</text>
        <g class="sensor-tooltip">
            <rect x="{cx - 120}" y="{cy - 55}" width="240" height="40" fill="#222" rx="6" pointer-events="none"/>
            <text x="{cx}" y="{cy - 28}" fill="white" font-family="Arial" font-size="17" font-weight="bold" text-anchor="middle" pointer-events="none">{label}</text>
        </g>
    </g>
    """

# --- MAP AND VMS LAYOUT ---
st.markdown("### Traffic Map")

# Traffic lights: only the three signalised approaches of the model (A3, B2, C2)
tl_svg = "".join([
    draw_traffic_light(635, 185), # End of A3 (Rivoli - Louvre)
    draw_traffic_light(635, 85),  # End of C2 (Rue des Bons-Enfants)
    draw_traffic_light(635, 285)  # End of B2 (Quai du Louvre)
])

svg = f"""
<svg viewBox="0 0 800 400" width="100%" height="400">
    <style>
        .sensor-tooltip {{ opacity: 0; transition: opacity 0.2s; }}
        .sensor-group:hover .sensor-tooltip {{ opacity: 1; }}
    </style>
    
    <path d="M 100 200 L 200 100 L 600 100 L 700 200" fill="none" stroke="#e0e0e0" stroke-width="15" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M 50 200 L 750 200" fill="none" stroke="#e0e0e0" stroke-width="15" stroke-linecap="round"/>
    <path d="M 100 200 L 200 300 L 600 300 L 700 200" fill="none" stroke="#e0e0e0" stroke-width="15" stroke-linecap="round" stroke-linejoin="round"/>
    
    <line x1="50" y1="200" x2="100" y2="200" stroke="{segments_colors.get('E', 'gray')}" stroke-width="10" stroke-linecap="round"/>
    
    <line x1="120" y1="200" x2="350" y2="200" stroke="{segments_colors.get('A1', 'gray')}" stroke-width="10" stroke-linecap="round"/>
    <line x1="360" y1="200" x2="550" y2="200" stroke="{segments_colors.get('A2', 'gray')}" stroke-width="10" stroke-linecap="round"/>
    <line x1="560" y1="200" x2="680" y2="200" stroke="{segments_colors.get('A3', 'gray')}" stroke-width="10" stroke-linecap="round"/>
    
    <path d="M 120 210 L 200 300 L 400 300" fill="none" stroke="{segments_colors.get('B1', 'gray')}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M 410 300 L 600 300 L 680 210" fill="none" stroke="{segments_colors.get('B2', 'gray')}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
    
    <path d="M 120 190 L 200 100 L 400 100" fill="none" stroke="{segments_colors.get('C1', 'gray')}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M 410 100 L 600 100 L 680 190" fill="none" stroke="{segments_colors.get('C2', 'gray')}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
    
    <line x1="700" y1="200" x2="750" y2="200" stroke="{segments_colors.get('X', 'gray')}" stroke-width="10" stroke-linecap="round"/>

    <text x="50" y="180" font-family="Arial" font-size="14" fill="#333">Concorde</text>
    <text x="680" y="180" font-family="Arial" font-size="14" fill="#333">Châtelet</text>
    
    <text x="350" y="185" font-family="Arial" font-size="16" font-weight="bold" fill="#333">Route A (Rivoli)</text>
    <text x="350" y="85" font-family="Arial" font-size="16" font-weight="bold" fill="#333">Route C (St-Honoré - Residential)</text>
    <text x="350" y="330" font-family="Arial" font-size="16" font-weight="bold" fill="#333">Route B (Quais - Fast)</text>

    <!-- Traffic Lights -->
    {tl_svg}

    <!-- SENSORS -->
    {draw_sensor('A1', 235, 200)}
    {draw_sensor('A2', 455, 200)}
    {draw_sensor('A3', 620, 200)}
    
    {draw_sensor('B1', 300, 300)}
    {draw_sensor('B2', 505, 300)}
    
    {draw_sensor('C1', 300, 100)}
    {draw_sensor('C2', 505, 100)}

    <!-- VMS -->
    <circle cx="110" cy="200" r="12" fill="#007bff" stroke="white" stroke-width="3"/>
    <text x="95" y="235" font-family="Arial" font-size="14" font-weight="bold" fill="#007bff">VMS</text>
</svg>
"""
st.components.v1.html(svg, height=420)


st.markdown('---')
bottom_col1, bottom_col2 = st.columns([1, 1])

with bottom_col1:
    # --- KPIs ---
    st.markdown("---")
    kpi_col1, kpi_col2 = st.columns(2)
    current_kpi = kpis_df[kpis_df["time"] == current_time]
    if not current_kpi.empty:
        rolling_trip = current_kpi.iloc[0]["avg_trip_15min"]
        val_rolling = f"{rolling_trip:.1f} min" if pd.notnull(rolling_trip) else "Gathering data..."
        kpi_col1.metric(f"Current Avg Trip Time (at Minute {current_minute})", val_rolling)
        
    kpi_col2.metric("Residential Penalty Parameter", pen_level)
    
    st.markdown("---")
    # Total Trips Breakdown
    if not run_summary_df.empty:
        sum_row = run_summary_df.iloc[0]
        t_a = sum_row.get("trips_a", 0)
        t_b = sum_row.get("trips_b", 0)
        t_c = sum_row.get("trips_c", 0)
        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("Total Completed Trips - Route A", f"{t_a} cars")
        tc2.metric("Total Completed Trips - Route B (Fast)", f"{t_b} cars")
        tc3.metric("Total Completed Trips - Route C (Residential)", f"{t_c} cars")
        st.markdown("---")
    
    # --- HISTORY LOG ---
    st.markdown("### VMS Display History")
    history_logs = decisions_df[(decisions_df["time"] <= current_time) & (decisions_df["tag"] == "REQ2")]
    
    html_history = '<div style="max-height: 200px; overflow-y: auto; border: 1px solid #444; padding: 10px; border-radius: 5px; background-color: #1a1a1a;">'
    
    if history_logs.empty:
        html_history += "<p style='color: #aaa;'>The VMS has remained inactive since Minute 0 (Fluid traffic, displaying 'Go Straight').</p>"
    else:
        for _, log in history_logs.iterrows():
            minute = time_to_minute(log['time'])
            text = log['text']
            reason = text.split('->')[0].strip()
            
            # Make reason human-readable
            if "V/C" in reason and ">" in reason:
                friendly_reason = "Congestion detected on Rivoli (load index estimated from speed above 0.80)."
            elif "<" in reason:
                friendly_reason = "Traffic on Rivoli is flowing normally again."
            else:
                friendly_reason = reason
                
            if "activated" in text or "activé" in text:
                html_history += f"<p style='margin: 5px 0;'><strong>Minute {minute}</strong> : VMS displayed <strong>Detour Recommended</strong> instead of 'Go Straight'.<br><span style='color: #ff8c00; font-size: 0.9em;'>Trigger: {friendly_reason}</span></p>"
            else:
                html_history += f"<p style='margin: 5px 0;'><strong>Minute {minute}</strong> : VMS displayed <strong>Go Straight</strong> instead of 'Detour'.<br><span style='color: #28a745; font-size: 0.9em;'>Trigger: {friendly_reason}</span></p>"
    
    html_history += "</div>"
    st.markdown(html_history, unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader(f"Network State at Minute {current_minute}")
    

    

    
    

with bottom_col2:
    st.markdown("### Variable Message Sign (VMS)")
    
    current_route_logs = decisions_df[(decisions_df["time"] == current_time) & (decisions_df["tag"] == "ROUTE")]
    if not current_route_logs.empty:
        meta_raw = current_route_logs.iloc[-1]["metadata"]
        if meta_raw:
            meta = json.loads(meta_raw)
            
            # --- VMS SIGN RENDERING ---
            # VMS recommends B or C if split_share > 0, otherwise it recommends A.
            rec_a = "#ff8c00" if split_share == 0 else "#663300"
            rec_b = "#ff8c00" if split_share > 0 and meta['probabilities']['B'] >= meta['probabilities']['C'] else "#663300"
            rec_c = "#ff8c00" if split_share > 0 and meta['probabilities']['C'] > meta['probabilities']['B'] else "#663300"
            
            # Use travel times from meta
            t_a = f"{meta['travel_min']['A']:.0f}"
            t_b = f"{meta['travel_min']['B']:.0f}"
            t_c = f"{meta['travel_min']['C']:.0f}"
            
            vms_html = f"""
            <div style="background-color: #111; padding: 15px; border-radius: 8px; border: 4px solid #222; font-family: 'Courier New', Courier, monospace; font-size: 18px; line-height: 1.5; font-weight: bold;">
                <div style="color: {rec_a};">Rivoli (A)    : Temps estimé : {t_a} min</div>
                <div style="color: {rec_c};">St-Honoré (C) : Temps estimé : {t_c} min</div>
                <div style="color: {rec_b};">Quais (B)     : Temps estimé : {t_b} min</div>
            </div>
            """
            st.markdown(vms_html, unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            
            # --- VMS EXPLANATION ---
            st.markdown("**Routing Costs (Live):**")
            st.markdown(f"- **Route A (Rivoli):** `{meta['costs']['A']} min`")
            st.markdown(f"- **Route B (Quais):** `{meta['costs']['B']} min`")
            st.markdown(f"- **Route C (St-Honoré):** `{meta['costs']['C']} min`")
            
            if split_share > 0:
                share_B = split_share * meta['probabilities'].get('B', 0)
                share_C = split_share * meta['probabilities'].get('C', 0)
                share_A = 1.0 - split_share
                
                st.info(f"**Current Action:** The main corridor is congested. The VMS is diverting **{split_share*100:.0f}%** of all approaching traffic to alternative routes:\n"
                        f"- **{share_A*100:.0f}%** stays on Route A (Rivoli)\n"
                        f"- **{share_C*100:.0f}%** goes to Route C (St-Honoré - Residential)\n"
                        f"- **{share_B*100:.0f}%** goes to Route B (Quais - Fast)", icon=" ")
            else:
                st.success(f"**Current Action:** Traffic is relatively fluid on the main corridor. The VMS recommends staying on **Route A** (100% of traffic).", icon=" ")
            
            # Store meta for bottom equation rendering
            st.session_state["meta_eq"] = meta
        else:
            st.write(f"Active Redirection: {split_share*100:.0f}% of vehicles diverted.")
    else:
        st.write("VMS Data not available for this minute.")

st.markdown("---")
st.markdown("### Algorithm Details")
if "meta_eq" in st.session_state:
    meta = st.session_state["meta_eq"]
    st.markdown("**Routing Cost Equation:**")
    st.latex(r"\text{Cost} = (\text{Travel Time} + \text{Uncertainty margin}) \times (1 + \text{Penalty} \times \text{Residential Share})")
    st.caption("Uncertainty margin = sum of (1 - confidence) x segment travel time; it is zero when all segments are observed, so the lines below show it only through the final cost.")
    st.markdown("Applying this formula to alternative routes:")
    
    st.markdown("**Route B (Quais):**")
    st.latex(rf"{meta['travel_min']['B']} \times (1 + {meta['sensitivity']} \times {meta['residential_share']['B']}) = \mathbf{{{meta['costs']['B']} \text{{ min}}}}")
    
    st.markdown("**Route C (St-Honoré):**")
    st.latex(rf"{meta['travel_min']['C']} \times (1 + {meta['sensitivity']} \times {meta['residential_share']['C']}) = \mathbf{{{meta['costs']['C']} \text{{ min}}}}")
else:
    st.markdown("Move the slider to see the live equations.")
