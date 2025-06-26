import streamlit as st, pandas as pd, numpy as np, openai, os, json, matplotlib.pyplot as plt
from datetime import date

# ───────────────── CONFIG
st.set_page_config("Resin Purchase Plan", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

# ───────────────── Sidebar
with st.sidebar:
    st.header("Parameters")
    m0 = st.date_input("Current inventory month", value=date.today().replace(day=1))
    horizon = st.number_input("Plan horizon (months)", 3, 12, 4, step=1)
    fg_open = st.number_input("Opening FG inventory (t)", 0., 500., 465., step=10.)
    resin_open = st.number_input("Opening resin inventory (t)", 0., 20000., 132., step=10.)
    resin_blended_open = st.number_input("Opening blended resin price (USD/t)", 0., 2000., 694., step=10.)
    prod_days = st.number_input("Production days / month", 15, 31, 25, step=1)
    usage_ratio = st.number_input("Resin usage ratio (% of prod)", 0., 1., 0.725, step=0.005)

FG_CAP = 500

# ───────────────── Historical price chart (no forecast)
hist = pd.DataFrame({
    "Month":["Jul-24","Aug-24","Sep-24","Oct-24","Nov-24","Dec-24",
             "Jan-25","Feb-25","Mar-25","Apr-25","May-25","Jun-25"],
    "USD/t":[815.95,825.77,785.28,757.06,733.74,742.33,
             733.74,724.54,718.40,694.48,694.48,694.48]})
hist["Date"] = pd.to_datetime(hist["Month"], format="%b-%y")
st.subheader("PVC Resin Price – USD/t")
fig, ax = plt.subplots()
ax.plot(hist["Date"], hist["USD/t"], marker="o")
ax.set_ylim(hist["USD/t"].min()*0.95, hist["USD/t"].max()*1.05)
ax.set_ylabel("USD / t"); ax.grid(ls=":")
st.pyplot(fig, use_container_width=True)

# ───────────────── AI outlook → safety days (baseline 7)
def ai_outlook():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return "FLAT", 0.
    tbl = "\n".join(f"{m}: {p}" for m,p in hist[["Month","USD/t"]].values)
    prompt = ("Return JSON {\"direction\":\"UP|DOWN|FLAT\",\"delta\":float} "
              "for next-month price move based on:\n"+tbl)
    try:
        rep = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            max_tokens=60
        ).choices[0].message.content
        data = json.loads(rep.splitlines()[-1]) if rep.strip().startswith("{") else json.loads(rep)
        return data["direction"], float(data["delta"])
    except Exception:
        return "FLAT", 0.

direction, delta = ai_outlook()
base = 7
safety = 14 if direction=="UP" and delta>30 else \
         10 if direction=="UP" else \
          3 if direction=="DOWN" and delta>30 else base
st.info(f"AI Outlook → {direction} {delta:+.0f} USD   |  Safety { safety } prod-days")

# ───────────────── Input table
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

# ───────────────── Planner function
def make_plan(df: pd.DataFrame):
    fg,resin,blend = fg_open, resin_open, resin_blended_open
    rows=[]
    for i,row in df.iterrows():
        sales  = row["Sales Plan (t)"]
        next_sales = df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else sales
        fg_target = safety/prod_days*next_sales
        prod = max(0, sales + fg_target - fg)
        fg_close = min(fg + prod - sales, FG_CAP)
        production = fg_close + sales - fg
        resin_use = production * usage_ratio
        next_prod = df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production
        resin_target = safety/prod_days*next_prod*usage_ratio
        price_map = {k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src, price = min(price_map, key=price_map.get), min(price_map.values())
        purchase = max(0, resin_use + resin_target - resin)
        if resin + purchase:
            blend = (resin*blend + purchase*price)/(resin + purchase)
        resin_close = resin + purchase - resin_use
        rows.append({
            "Month": row["Month"],
            "Sales": sales,
            "Production": production,
            "Stock FG": fg_close,
            # ← Days FG จาก “next month's **production**”
            "Days FG": round(fg_close / (next_prod/prod_days), 1) if next_prod else 0,
            "Incoming Resin": purchase,
            "Unit Price": price,
            "Source": src,
            "Stock Resin": resin_close,
            "Days Resin": round(resin_close / ((next_prod*usage_ratio)/prod_days),1) if next_prod else 0,
            "Blended $/t": blend
        })
        fg,resin = fg_close,resin_close
    return pd.DataFrame(rows)

# ───────────────── Button
if st.button("🚀 Generate Plan"):
    plan = make_plan(tbl.copy())

    # colour styling
    def sty(df):
        pv=df.set_index("Month").T
        orange={"Incoming Resin","Unit Price","Source","Stock Resin"}
        blue={"Days FG","Days Resin"}
        def apply(r):
            if r.name in orange: return ["background-color:#fbe5d6"]*len(r)
            if r.name in blue:   return ["color:#0073b7;font-weight:bold"]*len(r)
            return ["" for _ in r]
        return pv.style.apply(apply, axis=1)
    st.subheader("BNI Resin Games Plan")
    st.markdown(sty(plan).to_html(), unsafe_allow_html=True)
    st.download_button("⬇️ CSV", plan.to_csv(index=False).encode(),
                       "resin_plan.csv", mime="text/csv")
