import streamlit as st, pandas as pd, numpy as np, openai, os, json, matplotlib.pyplot as plt
from datetime import date

# ── PAGE CONFIG ───────────────────────────────────────────
st.set_page_config(page_title="Resin Purchase Plan", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

# ── SIDEBAR ───────────────────────────────────────────────
with st.sidebar:
    st.header("Parameters")
    m0 = st.date_input("Current inventory month", value=date.today().replace(day=1))
    horizon = st.number_input("Plan horizon (months)", 3, 12, 4)
    fg_open  = st.number_input("Opening FG inventory (t)",    0., 500., 465., step=10.)
    resin_open = st.number_input("Opening resin inventory (t)", 0., 10_000., 132., step=10.)
    blended_open = st.number_input("Opening blended resin price (USD/t)", 0., 2_000., 694., step=10.)
    prod_days = st.number_input("Production days / month", 15, 31, 25)
    usage_ratio = st.number_input("Resin usage ratio (% of production)", 0., 1., .725, step=.005)

FG_CAP = 500
SAFETY_MIN, SAFETY_MAX = 7, 10  # Resin safety-stock bounds

# ── HISTORICAL PRICE ─────────────────────────────────────
hist = pd.DataFrame({
    "Month":["Jul-24","Aug-24","Sep-24","Oct-24","Nov-24","Dec-24",
             "Jan-25","Feb-25","Mar-25","Apr-25","May-25","Jun-25"],
    "USD/t":[815.95,825.77,785.28,757.06,733.74,742.33,
             733.74,724.54,718.40,694.48,694.48,694.48]})
hist["Date"] = pd.to_datetime(hist["Month"], format="%b-%y")
st.subheader("PVC Resin Import Price (USD/t)")
fig, ax = plt.subplots(figsize=(7,3))
ax.plot(hist["Date"], hist["USD/t"], marker="o")
ax.set_ylim(hist["USD/t"].min()*0.95, hist["USD/t"].max()*1.05)
ax.set_ylabel("USD / t"); ax.grid(ls=":")
st.pyplot(fig, use_container_width=True)

# ── AI TREND (Macro: CN/IN/ID) ───────────────────────────
def ai_trend():
    """
    Return dict{trend:"UP|DOWN|FLAT", factors:[...]}
    Focus on macro supply-demand of China, India, Indonesia
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return {"trend":"FLAT","factors":["OPENAI_API_KEY missing"]}
    openai.api_key = key

    prompt = (
        "You are a senior petrochemical analyst tasked with assessing the PVC import-price OUTLOOK "
        "for South-East Asia over the NEXT 3 MONTHS.\n"
        "Analyse macro SUPPLY-DEMAND with explicit emphasis on the THREE BIG MARKETS:\n"
        "  • China (housing stimulus, infrastructure starts, plant turnarounds)\n"
        "  • India  (monsoon season, infrastructure, import tariffs)\n"
        "  • Indonesia (construction pipeline, rupiah FX, import quota)\n"
        "Also cover global crude / ethylene trends, freight, new capacities in NA-ME.\n"
        "Choose **one** overall direction — UP / DOWN / FLAT — (no numbers!).\n"
        "List 3-4 concise bullet factors explaining this direction.\n"
        "Return STRICT JSON:\n"
        "{\"trend\":\"UP\",\"factors\":[\"…\",\"…\",\"…\"]}"
    )
    try:
        txt = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            max_tokens=180
        ).choices[0].message.content
        data = json.loads(txt[txt.find("{"):txt.rfind("}")+1])
        if "trend" in data and "factors" in data:
            return data
    except Exception as e:
        st.warning(f"GPT error → fallback FLAT | {e}")
    return {"trend":"FLAT","factors":["fallback"]}

trend_info   = ai_trend()
trend        = trend_info["trend"].upper()
resin_safety = SAFETY_MAX if trend == "UP" else SAFETY_MIN

# ── Display trend box ────────────────────────────────────
html_box = (
    f"<b>Price trend (next 3 mo): {trend}</b><br>"
    + "<br>".join("• "+f for f in trend_info["factors"])
    + f"<br><br><b>Resin safety target:</b> {resin_safety} prod-days"
)
st.markdown(
    f"<div style='border-left:4px solid #1E90FF;background:#eef6ff;"
    f"padding:.75em 1em;border-radius:4px;font-size:0.93rem'>{html_box}</div>",
    unsafe_allow_html=True
)

# ── EDITABLE ASSUMPTIONS TABLE ───────────────────────────
months = pd.date_range(m0, periods=horizon, freq="MS").strftime("%b-%y")
def default_tbl(lbl):
    return pd.DataFrame({
        "Month": lbl,
        "Sales Plan (t)": [800+50*i for i in range(len(lbl))],
        "Local":  [690+10*i for i in range(len(lbl))],
        "TPE":    [np.nan if i>1 else 760-15*i for i in range(len(lbl))],
        "China/Korea":[np.nan if i>1 else 740-11*i for i in range(len(lbl))]
    })
if "tbl" not in st.session_state or st.session_state["cache"]!=(m0,horizon):
    st.session_state["tbl"] = default_tbl(months)
    st.session_state["cache"] = (m0,horizon)
tbl = st.data_editor(st.session_state["tbl"], use_container_width=True)

# ── PLANNER ──────────────────────────────────────────────
def make_plan(df: pd.DataFrame) -> pd.DataFrame:
    fg, resin, blend = fg_open, resin_open, blended_open
    rows=[]
    for i,row in df.iterrows():
        sales = row["Sales Plan (t)"]

        # 1) Base production = sales
        production = sales

        # 2) Top-up production until FG hits 500 if short
        top_up = max(0, FG_CAP - (fg + production - sales))
        production += top_up

        # 3) Trim if overshoot
        if fg + production - sales > FG_CAP:
            production -= (fg + production - sales - FG_CAP)

        fg_close = fg + production - sales
        next_prod = df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production

        resin_use    = production * usage_ratio
        resin_target = resin_safety / prod_days * next_prod * usage_ratio
        prices = {k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src, price   = min(prices, key=prices.get), min(prices.values())
        purchase     = max(0, resin_use + resin_target - resin)

        if resin + purchase:
            blend = (resin*blend + purchase*price)/(resin+purchase)
        resin_close = resin + purchase - resin_use

        rows.append({
            "Month":row["Month"], "Sales":sales, "Production":production,
            "Stock FG":fg_close,
            "Days FG":round(fg_close/(next_prod/prod_days),1) if next_prod else 0,
            "Incoming Resin":purchase,"Unit Price":price,"Source":src,
            "Stock Resin":resin_close,
            "Days Resin":round(resin_close/((next_prod*usage_ratio)/prod_days),1) if next_prod else 0,
            "Blended $/t":blend
        })
        fg, resin = fg_close, resin_close
    return pd.DataFrame(rows)

# ── OUTPUT ───────────────────────────────────────────────
if st.button("🚀 Generate Plan"):
    plan = make_plan(tbl.copy())

    def colour(df):
        pv=df.set_index("Month").T
        orange={"Incoming Resin","Unit Price","Source","Stock Resin"}
        blue={"Days FG","Days Resin"}
        def fmt(r):
            if r.name in orange:return ["background-color:#fbe5d6"]*len(r)
            if r.name in blue:  return ["color:#0073b7;font-weight:bold"]*len(r)
            return ["" for _ in r]
        return pv.style.apply(fmt, axis=1)

    st.subheader("BNI Resin Games Plan")
    st.markdown(colour(plan).to_html(), unsafe_allow_html=True)
    st.download_button("⬇️ CSV", plan.to_csv(index=False).encode(),
                       "resin_plan.csv", mime="text/csv")
