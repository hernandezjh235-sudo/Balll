import streamlit as st
import pandas as pd
import numpy as np

from engines.bayesian import BayesianLayer
from engines.markov import MarkovSimulator
from engines.monte_carlo import MonteCarloEngine
from engines.confidence import confidence_tier
from engines.betting_math import expected_value, kelly_fraction

st.set_page_config(
    page_title="MLB Quant Engine v3310",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.stApp {
    background: radial-gradient(circle at top,#16202c 0%,#0b0f14 45%,#05070a 100%);
    color:white;
}
.block-container {
    padding-top:1.2rem;
    max-width:1500px;
}
.big-title {
    font-size:44px;
    font-weight:950;
    color:#2ecc71;
    letter-spacing:-1px;
}
.sub-title {
    color:#b7c5d3;
    font-size:15px;
    margin-bottom:18px;
}
.card {
    background:linear-gradient(145deg,#11161d,#0d1117);
    padding:20px;
    border-radius:18px;
    border:1px solid #1f2a34;
    margin-bottom:16px;
    box-shadow:0 0 24px rgba(46,204,113,.12);
}
.green {color:#2ecc71;font-weight:900;}
.yellow {color:#f1c40f;font-weight:900;}
.red {color:#ff6b6b;font-weight:900;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="big-title">MLB QUANT ENGINE v3310</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Bayesian + Monte Carlo + Markov + XGBoost Framework + Multi-Prop Suite</div>',
    unsafe_allow_html=True
)

prop_page = st.sidebar.selectbox(
    "Select Prop Market",
    [
        "Pitcher Strikeouts",
        "Pitching Outs",
        "Earned Runs Allowed",
        "Hits Allowed",
        "Batter Hits",
        "RBIs",
        "Runs",
        "Walks",
        "Total Bases",
        "Hits+Runs+RBIs"
    ]
)

bankroll = st.sidebar.number_input("Bankroll", min_value=10.0, value=1000.0, step=50.0)
sims = st.sidebar.slider("Monte Carlo Sims", 1000, 25000, 15000, step=1000)
use_xgb = st.sidebar.checkbox("Experimental XGBoost Assist", value=False)
st.sidebar.caption("Keep XGBoost OFF until enough graded history is collected.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Selected Market", prop_page)
c2.metric("Simulation Runs", f"{sims:,}")
c3.metric("Bankroll", f"${bankroll:,.0f}")
c4.metric("XGBoost", "ON" if use_xgb else "OFF")

st.markdown("## Live Prop Board")

st.markdown("""
<div class="card">
<h3>Core Engines Active</h3>
<p>
Bayesian uncertainty, Monte Carlo simulation, Markov game-flow framework,
confidence filters, EV/Kelly structure, CLV tracking framework,
and gated XGBoost assist are loaded.
</p>
</div>
""", unsafe_allow_html=True)

# Demo board placeholder so Railway deploys cleanly.
# Replace this table with your live Underdog/API rows from the production file.
demo_rows = []
for player, line, projection, odds in [
    ("Demo Pitcher", 5.5, 6.4, -110),
    ("Demo Batter", 1.5, 1.3, -110),
]:
    edge = projection - line
    prob = 0.50 + max(min(edge * 0.08, 0.18), -0.18)
    ev = expected_value(prob, odds)
    kelly = kelly_fraction(prob, odds)
    tier = confidence_tier(abs(edge) * 10)
    rec = "STRONG WATCH" if tier in ["ELITE", "STRONG"] and ev > 0 else "PASS"
    demo_rows.append({
        "Player": player,
        "Prop": prop_page,
        "Line": line,
        "Projection": round(projection, 2),
        "Edge": round(edge, 2),
        "Probability": round(prob, 3),
        "EV": round(ev, 3),
        "Kelly": round(kelly, 3),
        "Confidence": tier,
        "Recommendation": rec,
    })

demo = pd.DataFrame(demo_rows)
st.dataframe(demo, use_container_width=True, hide_index=True)

st.markdown("## Engine Test")
try:
    bayes = BayesianLayer(hist_std=1.8, sample_size=60)
    dist = bayes.distribution(6.2)
    markov = MarkovSimulator(steps=24)
    mc = MonteCarloEngine(markov, sims=min(sims, 3000))
    results = mc.simulate(dist)
    st.success(f"Engine test passed. Sim mean: {np.mean(results):.2f}")
except Exception as e:
    st.error(f"Engine test failed: {e}")

st.markdown("## Deployment Status")
st.info("Railway-ready: Procfile uses --server.port=$PORT and --server.address=0.0.0.0")
