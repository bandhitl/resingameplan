
import streamlit as st
import pandas as pd
import numpy as np
import openai, os
import matplotlib.pyplot as plt
from datetime import date

# ---------- Page config ----------
st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

st.markdown(
    """### Overview
* Corporate **Resin Games Plan**
* FG capacity **500 t**
* Historical price chart (USD/t) with dotted 3‑month forecast
* **AI Outlook** – ใช้เพียง `OPENAI_API_KEY`
    """)

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Parameters")
    m0 = st.date_input("Current inventory month (m0)", value=date.today().replace(day=1))
    horizon = st.number_input("Plan horizon (months)", 3, 12, 4, step=1)
    fg_open = st.number_input("Opening FG inventory (t)", 0.0, 500.0, 465.0, step=10.0)
    resin_open = st.number_input("Opening resin inventory (t)", 0.0, 20000.0, 132.0, step=10.0)
    resin_blended_open = st.number_input("Opening blended resin price (USD/t)", 0.0, 2000.0, 694.0, step=10.0)
    fg_target_days = st.number_input("FG safety stock (days)", 0, 60, 15, step=1)
    resin_target_days = st.number_input("Resin safety stock (days)", 0, 30, 5, step=1)
    prod_days = st.number_input("Production days / month", 15, 31, 25, step=1)
    usage_ratio = st.number_input("Resin usage ratio (% of production)", 0.0, 1.0, 0.725, step=0.005)

FG_CAP = 500  # tonnes

# ---------- Historical price ----------
hist = pd.DataFrame({
    "Month": ["Jul-24","Aug-24","Sep-24","Oct-24","Nov-24","Dec-24","Jan-25",
              "Feb-25","Mar-25","Apr-25","May-25","Jun-25"],
    "USD/t":  [815.95,825.77,785.28,757.06,733.74,742.33,733.74,
               724.54,718.40,694.48,694.48,694.48]
})
hist["Date"] = pd.to_datetime(hist["Month"], format="%b-%y")

# trend forecast
x = np.arange(len(hist))
slope, intercept = np.polyfit(x, hist["USD/t"], 1)
future_x = np.arange(len(hist), len(hist)+3)
future_dates = pd.date_range(hist["Date"].iloc[-1] + pd.offsets.MonthBegin(), periods=3, freq="MS")
forecast_vals = intercept + slope*future_x
forecast_df = pd.DataFrame({"Date": future_dates, "USD/t": forecast_vals, "Forecast": True})
plot_df = pd.concat([hist.assign(Forecast=False)[["Date","USD/t","Forecast"]], forecast_df])

st.subheader("PVC Resin Price (USD/t)")
fig, ax = plt.subplots()
ax.plot(plot_df[plot_df["Forecast"]==False]["Date"],
        plot_df[plot_df["Forecast"]==False]["USD/t"],
        marker="o", label="Actual")
ax.plot(plot_df[plot_df["Forecast"]==True]["Date"],
        plot_df[plot_df["Forecast"]==True]["USD/t"],
        linestyle="--", marker="o", label="Forecast")
ax.set_ylabel("USD / t")
ax.grid(True, linestyle=":")
ax.legend()
st.pyplot(fig, use_container_width=True)

# ---------- Editable sales & price table ----------
months = pd.date_range(pd.to_datetime(m0), periods=horizon, freq="MS").strftime("%b-%y").tolist()
def default_df(labels):
    return pd.DataFrame({
        "Month": labels,
        "Sales Plan (t)": [800+50*i for i in range(len(labels))],
        "Local": [690+10*i for i in range(len(labels))],
        "TPE": [np.nan if i>1 else 760-15*i for i in range(len(labels))],
        "China/Korea": [np.nan if i>1 else 740-11*i for i in range(len(labels))]
    })
if "assump_df" not in st.session_state or st.session_state.get("cache_m0")!=m0 or st.session_state.get("cache_h")!=horizon:
    st.session_state["assump_df"] = default_df(months)
    st.session_state["cache_m0"] = m0
    st.session_state["cache_h"]  = horizon
assump_df = st.data_editor(st.session_state["assump_df"], num_rows="dynamic", use_container_width=True)

st.divider()

# ---------- Planner ----------
def compute(df):
    fg, resin, blended = fg_open, resin_open, resin_blended_open
    rows=[]
    for i,row in df.iterrows():
        sales=row["Sales Plan (t)"]
        next_sales=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else sales
        fg_target = fg_target_days/prod_days*next_sales
        prod_raw = max(0, sales+fg_target-fg)
        fg_close = min(fg + prod_raw - sales, FG_CAP)
        production = fg_close + sales - fg
        resin_use = production*usage_ratio
        next_prod = df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production
        resin_target = resin_target_days/prod_days*next_prod*usage_ratio
        price_map={k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src=min(price_map,key=price_map.get); price=price_map[src]
        purchase=max(0, resin_use + resin_target - resin)
        if resin+purchase:
            blended = (resin*blended + purchase*price)/(resin+purchase)
        resin_close = resin + purchase - resin_use
        rows.append({"Month":row["Month"],"Sales":sales,"Production":production,"FG":fg_close,
                     "Purchase":purchase,"Unit Price":price,"Source":src,"Resin":resin_close,
                     "Blended":blended})
        fg, resin = fg_close, resin_close
    return pd.DataFrame(rows)

def style(df):
    pivot = df.set_index("Month").T
    return pivot.style

# ---------- AI forecast ----------
def ai_outlook():
    key=os.getenv("OPENAI_API_KEY")
    if not key:
        return "N/A","OPENAI_API_KEY not set"
    openai.api_key=key
    prompt = ("You are a petrochemical market analyst.
"
              "Historical PVC resin prices (USD/t):
" +
              hist[['Month','USD/t']].to_string(index=False) +
              "

Predict price direction (UP, DOWN, FLAT) next 3 months and give 2-3 drivers.")
    try:
        resp=openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                          messages=[{"role":"user","content":prompt}],
                                          max_tokens=150)
        txt=resp.choices[0].message.content.strip()
        return txt.split()[0], txt
    except Exception as e:
        return "N/A", f"GPT error: {e}"

if st.button("🚀 Generate Plan & AI Outlook"):
    plan = compute(assump_df.copy())
    trend, detail = ai_outlook()
    st.subheader("PVC Resin Outlook (next 3 months)")
    st.write(f"**Trend:** {trend}")
    st.write(detail)
    st.subheader(f"BNI Resin Games Plan : {m0:%b %Y} – {(pd.to_datetime(m0)+pd.DateOffset(months=horizon-1)):%b %Y}")
    st.markdown(style(plan).to_html(), unsafe_allow_html=True)
    st.download_button("Download CSV", plan.to_csv(index=False).encode(), "resin_plan.csv", mime="text/csv")
