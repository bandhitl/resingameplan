import streamlit as st, pandas as pd, numpy as np, openai, os, json, matplotlib.pyplot as plt
from datetime import date

# ── PAGE CONFIG ───────────────────────────────────────────
st.set_page_config("Resin Purchase Plan", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

# ── SIDEBAR INPUTS ────────────────────────────────────────
with st.sidebar:
    st.header("Parameters")
    m0 = st.date_input("Current inventory month", value=date.today().replace(day=1))
    horizon = st.number_input("Plan horizon (months)", 3, 12, 4)
    fg_open  = st.number_input("Opening FG inventory (t)",    0., 500., 465., step=10.)
    resin_open = st.number_input("Opening resin inventory (t)",0., 10000., 132., step=10.)
    blended_open = st.number_input("Opening blended resin price (USD/t)", 0., 2000., 694., step=10.)
    prod_days = st.number_input("Production days / month", 15, 31, 25)
    usage_ratio = st.number_input("Resin usage ratio (% of production)", 0., 1., .725, step=.005)

FG_CAP = 500   # พื้นที่เก็บ FG สูงสุด

# ── HISTORICAL PVC PRICE ─────────────────────────────────
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

# ── AI OUTLOOK (news-driven, 3 months) ───────────────────
def ai_outlook():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return [{"month":"Jul-25","direction":"FLAT","delta":0,"reason":"OPENAI_API_KEY missing"}]*3
    openai.api_key = key
    series = "\n".join(f"{m}: {p}" for m,p in hist[["Month","USD/t"]].values)
    prompt = (
        "You are a senior petrochemical analyst.\n"
        "1) Summarise key demand-supply news in LAST 30 DAYS (plant outages, capacity, freight, macro).\n"
        "2) Forecast price delta (USD/t) vs Jun-25 (694) for Jul-25, Aug-25, Sep-25. Give UP/DOWN/FLAT.\n"
        "Return STRICT JSON list len=3:\n"
        "[{\"month\":\"Jul-25\",\"direction\":\"UP\",\"delta\":40,\"reason\":\"Formosa turnaround\"},…]\n\n"
        "Historical prices:\n"+series)
    try:
        txt = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            max_tokens=300
        ).choices[0].message.content
        data = json.loads(txt[txt.find("["):txt.rfind("]")+1])
        if isinstance(data, list) and len(data) == 3:
            return data
    except Exception as e:
        st.warning(f"GPT error → fallback FLAT | {e}")
    return [{"month":"Jul-25","direction":"FLAT","delta":0,"reason":"fallback"}]*3

outlook = ai_outlook()
avg_delta = np.mean([o["delta"] for o in outlook])
dir_main  = outlook[0]["direction"]

# Resin safety-days (FG ไม่มี safety-day มีแต่ CAP 500 t)
base = 7
resin_safety = 14 if dir_main=="UP" and avg_delta>30 else \
               10 if dir_main=="UP" else \
                3 if dir_main=="DOWN" and avg_delta>30 else base

# แสดงผล outlook ในกล่องสีฟ้า (ใช้ markdown แทน info เพื่อใช้ HTML ได้)
st.markdown(
    "<div style='border-left:4px solid #1E90FF;background:#eef6ff;"
    "padding:0.75em 1em;border-radius:4px;font-size:0.93rem'>"
    "<strong>Petrochemical Outlook (Δ vs Jun-25)</strong><br>"
    + "<br>".join(f"• <b>{o['month']}</b> → {o['direction']} {o['delta']:+.0f} USD — {o['reason']}"
                  for o in outlook)
    + f"<br><br><b>Resin safety target</b> = {resin_safety} prod-days"
    "</div>",
    unsafe_allow_html=True
)

# ── EDITABLE SALES / PRICE TABLE ─────────────────────────
months = pd.date_range(m0, periods=horizon, freq="MS").strftime("%b-%y")
def default_tbl(lbl):
    return pd.DataFrame({
        "Month": lbl,
        "Sales Plan (t)": [800 + 50*i for i in range(len(lbl))],
        "Local":  [690 + 10*i for i in range(len(lbl))],
        "TPE":    [np.nan if i>1 else 760-15*i for i in range(len(lbl))],
        "China/Korea": [np.nan if i>1 else 740-11*i for i in range(len(lbl))]
    })
if "tbl" not in st.session_state or st.session_state["cache"]!=(m0,horizon):
    st.session_state["tbl"] = default_tbl(months)
    st.session_state["cache"] = (m0,horizon)
tbl = st.data_editor(st.session_state["tbl"], use_container_width=True)

# ── PLANNER ───────────────────────────────────────────────
def make_plan(df: pd.DataFrame):
    fg, resin, blend = fg_open, resin_open, blended_open
    rows=[]
    for i,row in df.iterrows():
        sales = row["Sales Plan (t)"]

        # 1) ผลิต = Sales ยกเว้นจะทำให้ FG เกิน CAP 500
        production = sales
        if fg + production - sales > FG_CAP:
            production = max(0, FG_CAP - (fg - sales))
        fg_close = fg + production - sales    # ≤ 500

        # 2) Resin usage & purchase
        resin_use = production * usage_ratio
        next_prod = df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production
        resin_target = resin_safety / prod_days * next_prod * usage_ratio
        prices = {k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src, price = min(prices, key=prices.get), min(prices.values())
        purchase = max(0, resin_use + resin_target - resin)
        if resin + purchase:
            blend = (resin * blend + purchase * price) / (resin + purchase)
        resin_close = resin + purchase - resin_use

        rows.append({
            "Month":row["Month"],"Sales":sales,"Production":production,
            "Stock FG":fg_close,
            "Days FG": round(fg_close / (next_prod / prod_days), 1) if next_prod else 0,
            "Incoming Resin":purchase,"Unit Price":price,"Source":src,
            "Stock Resin":resin_close,
            "Days Resin": round(resin_close / ((next_prod*usage_ratio)/prod_days),1) if next_prod else 0,
            "Blended $/t":blend
        })
        fg, resin = fg_close, resin_close
    return pd.DataFrame(rows)

# ── GENERATE BUTTON ──────────────────────────────────────
if st.button("🚀 Generate Plan"):
    plan = make_plan(tbl.copy())

    def colour(df):
        pivot = df.set_index("Month").T
        orange = {"Incoming Resin","Unit Price","Source","Stock Resin"}
        blue   = {"Days FG","Days Resin"}
        def fmt(r):
            if r.name in orange: return ["background-color:#fbe5d6"]*len(r)
            if r.name in blue:   return ["color:#0073b7;font-weight:bold"]*len(r)
            return ["" for _ in r]
        return pivot.style.apply(fmt, axis=1)

    st.subheader("BNI Resin Games Plan")
    st.markdown(colour(plan).to_html(), unsafe_allow_html=True)
    st.download_button("⬇️ CSV", plan.to_csv(index=False).encode(),
                       "resin_plan.csv", mime="text/csv")
