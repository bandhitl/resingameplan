
import streamlit as st
import pandas as pd
import numpy as np
import openai, os
import matplotlib.pyplot as plt
from datetime import date

# ----------------- Page config -----------------
st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

st.markdown(
    "* Corporate **Resin Games Plan**  
"
    "* FG capacity 500 t  
"
    "* Historical price chart (USD/t) + dotted 3‑month forecast  
"
    "* **AI Outlook** – ใช้เพียง `OPENAI_API_KEY` เท่านั้น"
)

# ----------------- Sidebar -----------------
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

FG_CAP = 500  # hard cap on FG inventory

# ----------------- Historical price -----------------
hist = pd.DataFrame({
    "Month": ["Jul-24","Aug-24","Sep-24","Oct-24","Nov-24","Dec-24","Jan-25","Feb-25",
              "Mar-25","Apr-25","May-25","Jun-25"],
    "USD/t":  [815.95,825.77,785.28,757.06,733.74,742.33,733.74,724.54,718.40,694.48,694.48,694.48]
})
hist["Date"] = pd.to_datetime(hist["Month"], format="%b-%y")

# simple linear trend forecast for next 3 months
x = np.arange(len(hist))
slope, intercept = np.polyfit(x, hist["USD/t"], 1)
future_x = np.arange(len(hist), len(hist)+3)
forecast_vals = intercept + slope*future_x
future_dates = pd.date_range(hist["Date"].iloc[-1] + pd.offsets.MonthBegin(), periods=3, freq="MS")
forecast_df = pd.DataFrame({"Date": future_dates, "USD/t": forecast_vals, "Forecast": True})
hist_plot = hist.copy()
hist_plot["Forecast"] = False
plot_df = pd.concat([hist_plot[["Date","USD/t","Forecast"]], forecast_df])

st.subheader("PVC Resin Purchase Price – USD/t")
fig, ax = plt.subplots()
actual = plot_df[plot_df["Forecast"]==False]
pred   = plot_df[plot_df["Forecast"]==True]
ax.plot(actual["Date"], actual["USD/t"], marker="o", label="Actual")
ax.plot(pred["Date"], pred["USD/t"], linestyle="--", marker="o", label="Forecast")
ax.set_ylabel("USD / t")
ax.grid(True, linestyle=":")
ax.legend()
st.pyplot(fig, use_container_width=True)

# ----------------- Editable assumptions -----------------
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

assump_df = st.data_editor(st.session_state["assump_df"],
                           num_rows="dynamic",
                           use_container_width=True)

st.divider()

# ----------------- Core planner -----------------
def compute(df):
    fg, resin, blended = fg_open, resin_open, resin_blended_open
    out=[]
    for i,row in df.iterrows():
        sales=row["Sales Plan (t)"]
        next_sales=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else sales
        fg_target = fg_target_days/prod_days * next_sales
        prod_raw  = max(0, sales + fg_target - fg)
        fg_close  = min(fg + prod_raw - sales, FG_CAP)
        production= fg_close + sales - fg
        resin_use = production * usage_ratio
        next_prod = df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production
        resin_target = resin_target_days/prod_days * next_prod * usage_ratio
        prices={k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src=min(prices,key=prices.get); price=prices[src]
        purchase = max(0, resin_use + resin_target - resin)
        if resin + purchase:
            blended = (resin*blended + purchase*price)/(resin+purchase)
        resin_close = resin + purchase - resin_use
        out.append({"Month":row["Month"],"Sales":sales,"Production":production,
                    "FG Close":fg_close,"Incoming Resin":purchase,"Unit Price":price,"Source":src,
                    "Resin Close":resin_close,"Blended $/t":blended})
        fg, resin = fg_close, resin_close
    return pd.DataFrame(out)

def style(df):
    pivot = df.set_index("Month").T
    sty = pivot.style
    sty.set_table_styles([{"selector":"th","props":[("background-color","#f2f2f2"),("font-weight","bold")]},
                          {"selector":"td","props":[("border","1px solid #d0d0d0"),("text-align","center")]}],
                          overwrite=False)
    return sty

# ----------------- AI outlook -----------------
def ai_outlook():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return "N/A","ตั้ง OPENAI_API_KEY ก่อนเพื่อเปิด AI forecast"
    openai.api_key = key
    prompt = ("You are a petrochemical market analyst. Here is historical monthly PVC resin price "
              "series in USD/t:

" +
              hist[['Month','USD/t']].to_string(index=False) +
              "

Predict whether the price in the next 3 months will trend UP, DOWN, or FLAT, "
              "and list 2-3 key demand/supply drivers.")
    try:
        resp=openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                          messages=[{"role":"user","content":prompt}],
                                          max_tokens=160)
        text=resp.choices[0].message.content.strip()
        return text.split()[0], text
    except Exception as e:
        return "N/A", f"GPT error: {e}"

# ----------------- Action button -----------------
if st.button("🚀 Generate Plan & AI Outlook"):
    plan = compute(assump_df.copy())
    trend, explanation = ai_outlook()
    st.subheader("PVC Resin Price Outlook (next 3 months)")
    st.write(f"**Trend:** {trend}")
    st.write(explanation)
    st.subheader(f"BNI Resin Games Plan : {m0.strftime('%b %Y')} – "
                 f"{(pd.to_datetime(m0)+pd.DateOffset(months=horizon-1)).strftime('%b %Y')}")
    st.markdown(style(plan).to_html(), unsafe_allow_html=True)
    st.download_button("Download raw CSV", plan.to_csv(index=False).encode(),
                       "resin_plan.csv", mime="text/csv")
