
import streamlit as st
import pandas as pd
import numpy as np
import openai, os
import matplotlib.pyplot as plt
from datetime import date

st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

"""
* Corporate **Resin Games Plan** table  
* FG capacity capped at **500 t**  
* **Historical PVC resin price chart** (USD/t) with 3‑month dotted forecast  
* **AI PVC resin price outlook** – uses **OpenAI** only (no NewsAPI needed)
  * Set `OPENAI_API_KEY` environment variable to enable the forecast.
"""


# ───────────── Sidebar ─────────────
with st.sidebar:
    st.header("Global Parameters")
    m0 = st.date_input("Current inventory month (m0)", value=date.today().replace(day=1))
    horizon = st.number_input("Plan horizon (months)", 3, 12, 4, step=1)
    fg_open = st.number_input("Opening FG inventory (t)", 0.0, 500.0, 465.0, step=10.0)
    resin_open = st.number_input("Opening resin inventory (t)", 0.0, 20000.0, 132.0, step=10.0)
    resin_blended_open = st.number_input("Opening blended resin price (USD/t)", 0.0, 2000.0, 694.0, step=10.0)
    fg_target_days = st.number_input("FG safety stock (days)", 0, 60, 15, step=1)
    resin_target_days = st.number_input("Resin safety stock (days)", 0, 30, 5, step=1)
    prod_days = st.number_input("Production days per month", 15, 31, 25, step=1)
    usage_ratio = st.number_input("Resin usage ratio (% of production)", 0.0, 1.0, 0.725, step=0.005)

FG_CAP = 500

# ───────────── Historical price data ─────────────
hist = pd.DataFrame({
    "Month": ["Jul-24","Aug-24","Sep-24","Oct-24","Nov-24","Dec-24","Jan-25","Feb-25",
              "Mar-25","Apr-25","May-25","Jun-25"],
    "USD/t":  [815.95,825.77,785.28,757.06,733.74,742.33,733.74,724.54,718.40,694.48,694.48,694.48]
})
hist["Date"] = pd.to_datetime(hist["Month"], format="%b-%y")

# Forecast next 3 months by simple linear trend
x = np.arange(len(hist))
coef = np.polyfit(x, hist["USD/t"], 1)
slope, intercept = coef
future_x = np.arange(len(hist), len(hist)+3)
forecast_vals = intercept + slope * future_x
forecast_dates = pd.date_range(hist["Date"].iloc[-1] + pd.offsets.MonthBegin(),
                               periods=3, freq="MS")
forecast_df = pd.DataFrame({"Date": forecast_dates, "USD/t": forecast_vals, "Forecast": True})
hist["Forecast"] = False
plot_df = pd.concat([hist[["Date","USD/t","Forecast"]], forecast_df])

st.subheader("Historical PVC Resin Purchase Price (USD/t) + 3‑month forecast")
fig, ax = plt.subplots()
actual = plot_df[~plot_df["Forecast"]]
forecast = plot_df[plot_df["Forecast"]]
ax.plot(actual["Date"], actual["USD/t"], label="Actual", marker="o")
ax.plot(forecast["Date"], forecast["USD/t"], linestyle="--", marker="o", label="Forecast")
ax.set_ylabel("USD / t")
ax.set_xlabel("Month")
ax.legend()
ax.grid(True, linestyle=":")
st.pyplot(fig, use_container_width=True)

# ───────────── Assumption table ─────────────
months = pd.date_range(pd.to_datetime(m0), periods=horizon, freq="MS").strftime("%b-%y")
def default_df(labels):
    return pd.DataFrame({
        "Month": labels,
        "Sales Plan (t)": [800+50*i for i in range(len(labels))],
        "Local": [690+10*i for i in range(len(labels))],
        "TPE": [np.nan if i>1 else 760-15*i for i in range(len(labels))],
        "China/Korea": [np.nan if i>1 else 740-11*i for i in range(len(labels))]
    })
if "assump_df" not in st.session_state or st.session_state.get("cache_m0")!=m0 or st.session_state.get("cache_h")!=horizon:
    st.session_state["assump_df"]=default_df(months)
    st.session_state["cache_m0"]=m0
    st.session_state["cache_h"]=horizon
assump_df=st.data_editor(st.session_state["assump_df"], num_rows="dynamic", use_container_width=True)

st.divider()

# ───────────── Plan logic (same as before, collapsed for brevity) ─────────────
def compute(df):
    fg, resin, blended = fg_open, resin_open, resin_blended_open
    rows=[]
    for i,row in df.iterrows():
        sales=row["Sales Plan (t)"]; next_sales=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else sales
        fg_target=fg_target_days/prod_days*next_sales
        prod_raw=max(0,sales+fg_target-fg)
        fg_close=min(fg+prod_raw-sales, FG_CAP)
        production=fg_close+sales-fg
        resin_use=production*usage_ratio
        next_prod=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production
        resin_target=resin_target_days/prod_days*next_prod*usage_ratio
        price_map={k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src=min(price_map,key=price_map.get); price=price_map[src]
        purchase=max(0,resin_use+resin_target-resin)
        blended=(resin*blended+purchase*price)/(resin+purchase) if (resin+purchase) else blended
        resin_close=resin+purchase-resin_use
        rows.append({"Month":row["Month"],"Sales":sales,"Prod":production,"FG":fg_close,"Resin":resin_close,
                     "Purchase":purchase,"Price":price,"Source":src,"Blend":blended})
        fg,resin=fg_close,resin_close
    return pd.DataFrame(rows)

def style(df):
    metrics=["Sales","Prod","FG","Purchase","Price","Source","Resin","Blend"]
    piv=df.set_index("Month")[metrics].T
    sty=piv.style
    return sty

# ───────────── AI Outlook using GPT only ─────────────
def ai_outlook():
    key=os.getenv("OPENAI_API_KEY")
    if not key:
        return "N/A","Set OPENAI_API_KEY to enable AI outlook."
    openai.api_key=key
    prompt="""You are a petrochemical market analyst. 
Using the historical PVC resin price series below (USD per tonne),
along with your up‑to‑date domain knowledge of macro factors, demand/supply balances, and energy prices,
predict the price DIRECTION (UP, DOWN, or FLAT) for the next 3 months for Southeast Asia import prices.
Give 2‑3 bullet drivers. 
Historical series:
{}
""".format(hist[['Month','USD/t']].to_string(index=False))
    try:
        txt=openai.ChatCompletion.create(model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],max_tokens=160).choices[0].message.content.strip()
        return txt.split()[0],txt
    except Exception as e:
        return "N/A",f"GPT error: {e}"

if st.button("🚀 Generate Plan & AI Outlook"):
    plan_df=compute(assump_df.copy())
    st.subheader("PVC Resin Price Outlook (next 3 months)")
    trend, detail=ai_outlook()
    st.write(f"**Trend:** {trend}")
    st.markdown(detail)
    # table
    st.subheader(f"BNI Resin Games Plan : {m0.strftime('%b %Y')} – {(pd.to_datetime(m0)+pd.DateOffset(months=horizon-1)).strftime('%b %Y')}")
    st.dataframe(style(plan_df).format("{:.1f}"), use_container_width=True)
    st.download_button("Download raw CSV", plan_df.to_csv(index=False).encode(), "resin_plan.csv", mime="text/csv")
