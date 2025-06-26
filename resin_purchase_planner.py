import streamlit as st, pandas as pd, numpy as np, openai, os, json, matplotlib.pyplot as plt
from datetime import date

# ─── CONFIG ────────────────────────────────────────────────
st.set_page_config("Resin Purchase Plan", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

# ─── SIDEBAR ───────────────────────────────────────────────
with st.sidebar:
    st.header("Parameters")
    m0  = st.date_input("Current inventory month", value=date.today().replace(day=1))
    tz  = pd.date_range(m0, periods=1, freq="MS")[0]  # for month-format later
    horizon = st.number_input("Plan horizon (months)", 3, 12, 4)
    fg_open  = st.number_input("Opening FG inventory (t)",    0., 500.,   465., step=10.)
    resin_open = st.number_input("Opening resin inventory (t)",0., 10000., 132., step=10.)
    blended_open = st.number_input("Opening blended resin price (USD/t)", 0., 2000., 694., step=10.)
    prod_days = st.number_input("Production days / month", 15, 31, 25)
    usage_ratio = st.number_input("Resin usage ratio (% of production)", 0., 1., 0.725, step=0.005)

FG_CAP = 500      # พื้นที่เก็บ FG สูงสุด

# ─── HISTORICAL PVC PRICE ─────────────────────────────────
hist = pd.DataFrame({
    "Month":["Jul-24","Aug-24","Sep-24","Oct-24","Nov-24","Dec-24",
             "Jan-25","Feb-25","Mar-25","Apr-25","May-25","Jun-25"],
    "USD/t":[815.95,825.77,785.28,757.06,733.74,742.33,
             733.74,724.54,718.40,694.48,694.48,694.48]
})
hist["Date"] = pd.to_datetime(hist["Month"], format="%b-%y")
st.subheader("PVC Resin Import Price (USD/t)")
fig, ax = plt.subplots(figsize=(7,3))
ax.plot(hist["Date"], hist["USD/t"], marker="o")
ax.set_ylim(hist["USD/t"].min()*0.95, hist["USD/t"].max()*1.05)
ax.set_ylabel("USD / t"); ax.grid(ls=":")
st.pyplot(fig, use_container_width=True)

# ─── AI OUTLOOK (ข่าว demand-supply 3 เดือน) ──────────────
def ai_outlook():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return [{"month":"Jul-25","direction":"FLAT","delta":0,"reason":"OPENAI_API_KEY missing"}]*3
    openai.api_key = key
    series = "\n".join(f"{m}: {p}" for m,p in hist[["Month","USD/t"]].values)

    prompt = (
        "You are a senior petrochemical analyst.\n"
        "Step-1: Summarise the most impactful demand-supply news on PVC (Asia) from the **last 30 days** "
        "(plant outages, freight, economics, capacity, policy).\n"
        "Step-2: Using those factors + the historical price series below, forecast the average **price delta** (USD/t) "
        "vs Jun-25 level (694 USD) for each of **Jul-25, Aug-25, Sep-25**. "
        "Classify direction as UP / DOWN / FLAT.\n"
        "Return STRICT JSON list length 3, e.g.\n"
        "[{\"month\":\"Jul-25\",\"direction\":\"UP\",\"delta\":40,\"reason\":\"Major Formosa turnaround\"}, …]\n\n"
        "Historical prices:\n"+series
    )
    try:
        txt = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            max_tokens=300
        ).choices[0].message.content
        j = txt[txt.find("["): txt.rfind("]")+1]
        data = json.loads(j)
        if isinstance(data, list) and len(data) == 3:
            return data
    except Exception as e:
        st.warning(f"GPT error → fallback FLAT | {e}")
    return [{"month":"Jul-25","direction":"FLAT","delta":0,"reason":"fallback"}]*3

outlook = ai_outlook()
avg_delta = np.mean([o["delta"] for o in outlook])
dir_main  = outlook[0]["direction"]

# Resin safety-day rule (FG ไม่มี safety-day มีแต่เพดาน 500 t)
base = 7
resin_safety = 14 if dir_main=="UP" and avg_delta>30 else \
               10 if dir_main=="UP" else \
                3 if dir_main=="DOWN" and avg_delta>30 else base

st.info(
    "### Petrochemical Outlook (Δ vs Jun-25)\n"
    + "\n".join(f"* **{o['month']}** → {o['direction']} {o['delta']:+.0f} USD — {o['reason']}" for o in outlook)
    + f"\n\n➡️ **Resin safety target** = {resin_safety} prod-days",
    icon="🛢️", unsafe_allow_html=True
)

# ─── EDITABLE ASSUMPTION TABLE ────────────────────────────
months = pd.date_range(m0, periods=horizon, freq="MS").strftime("%b-%y")
def default_tbl(lbl):
    return pd.DataFrame({
        "Month": lbl,
        "Sales Plan (t)": [800 + 50*i for i in range(len(lbl))],
        "Local":  [690 + 10*i for i in range(len(lbl))],
        "TPE":    [np.nan if i>1 else 760-15*i for i in range(len(lbl))],
        "China/Korea":[np.nan if i>1 else 740-11*i for i in range(len(lbl))]
    })
if "tbl" not in st.session_state or st.session_state["cache"] != (m0, horizon):
    st.session_state["tbl"] = default_tbl(months)
    st.session_state["cache"] = (m0, horizon)
tbl = st.data_editor(st.session_state["tbl"], use_container_width=True)

# ─── PLANNER ──────────────────────────────────────────────
def calc_plan(df: pd.DataFrame) -> pd.DataFrame:
    fg, resin, blend = fg_open, resin_open, blended_open
    rows = []

    for i, row in df.iterrows():
        sales = row["Sales Plan (t)"]

        # 1) ผลิต ≈ Sales เว้นแต่จะทำให้ FG เกิน 500 t
        production = sales
        if fg + production - sales > FG_CAP:
            production = max(0, FG_CAP - (fg - sales))
        fg_close = fg + production - sales     # จะไม่เกิน 500

        # 2) Resin usage & safety
        resin_use = production * usage_ratio
        next_prod = df.iloc[i+1]["Sales Plan (t)"] if i+1 < len(df) else production
        resin_target = resin_safety / prod_days * next_prod * usage_ratio

        # 3) เลือกแหล่งราคาถูกสุด
        prices = {k: row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src, price = min(prices, key=prices.get), min(prices.values())

        # 4) สั่งซื้อ resin
        purchase = max(0, resin_use + resin_target - resin)
        if resin + purchase:
            blend = (resin * blend + purchase * price) / (resin + purchase)
        resin_close = resin + purchase - resin_use

        # 5) Days FG / Resin
        days_fg    = round(fg_close / (next_prod / prod_days), 1) if next_prod else 0
        days_resin = round(resin_close / ((next_prod*usage_ratio) / prod_days), 1) if next_prod else 0

        rows.append({
            "Month": row["Month"], "Sales": sales, "Production": production,
            "Stock FG": fg_close, "Days FG": days_fg,
            "Incoming Resin": purchase, "Unit Price": price, "Source": src,
            "Stock Resin": resin_close, "Days Resin": days_resin,
            "Blended $/t": blend
        })
        fg, resin = fg_close, resin_close
    return pd.DataFrame(rows)

# ─── OUTPUT ───────────────────────────────────────────────
if st.button("🚀 Generate Plan"):
    plan = calc_plan(tbl.copy())

    def colour(df):
        pv = df.set_index("Month").T
        orange = {"Incoming Resin","Unit Price","Source","Stock Resin"}
        blue   = {"Days FG","Days Resin"}
        def fmt(r):
            if r.name in orange: return ["background-color:#fbe5d6"]*len(r)
            if r.name in blue:   return ["color:#0073b7;font-weight:bold"]*len(r)
            return ["" for _ in r]
        return pv.style.apply(fmt, axis=1)

    st.subheader("BNI Resin Games Plan")
    st.markdown(colour(plan).to_html(), unsafe_allow_html=True)
    st.download_button("⬇️ Download CSV", plan.to_csv(index=False).encode(),
                       "resin_plan.csv", mime="text/csv")
