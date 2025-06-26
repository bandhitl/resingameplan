
import streamlit as st
import pandas as pd
import numpy as np
import openai, os
import matplotlib.pyplot as plt
from datetime import date

st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

st.markdown("""### Overview
* Corporate **Resin Games Plan**
* FG capacity 500 t
* Historical price chart (USD/t) (no future dots)
* **Automatic FG / Resin safety days** based on AI price outlook
  * baseline 7 prod‑days
  * if AI predicts **UP** > 30 USD → 14 days
  * if **UP** ≤ 30 USD → 10 days
  * if **DOWN** > 30 USD → 3 days
  * otherwise keep 7 days
""")

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Parameters")
    m0 = st.date_input("Current inventory month (m0)", value=date.today().replace(day=1))
    horizon = st.number_input("Plan horizon (months)", 3, 12, 4, step=1)
    fg_open = st.number_input("Opening FG inventory (t)", 0.0, 500.0, 465.0, step=10.0)
    resin_open = st.number_input("Opening resin inventory (t)", 0.0, 20000.0, 132.0, step=10.0)
    resin_blended_open = st.number_input("Opening blended resin price (USD/t)", 0.0, 2000.0, 694.0, step=10.0)
    prod_days = st.number_input("Production days / month", 15, 31, 25, step=1)
    usage_ratio = st.number_input("Resin usage ratio (% of production)", 0.0, 1.0, 0.725, step=0.005)

FG_CAP = 500

# ---------- Historical price ----------
hist = pd.DataFrame({
    "Month": ["Jul-24","Aug-24","Sep-24","Oct-24","Nov-24","Dec-24","Jan-25",
              "Feb-25","Mar-25","Apr-25","May-25","Jun-25"],
    "USD/t": [815.95,825.77,785.28,757.06,733.74,742.33,733.74,
              724.54,718.40,694.48,694.48,694.48]
})
hist["Date"] = pd.to_datetime(hist["Month"], format="%b-%y")

st.subheader("PVC Resin Price (USD/t)")
st.line_chart(hist.set_index("Date")["USD/t"], use_container_width=True)

# ---------- AI price outlook ----------
def ai_outlook():
    key=os.getenv("OPENAI_API_KEY")
    price_series = "\n".join(f"{m}: {p}" for m,p in zip(hist['Month'], hist['USD/t']))
    if not key:
        return "FLAT", 0.0, "OPENAI_API_KEY not set, using FLAT"
    openai.api_key = key
    prompt = (
        "You are a petrochemical analyst. Historical PVC resin prices (USD/t):\n"
        f"{price_series}\n\n"
        "Estimate the average price change expected for NEXT month (positive = UP, negative = DOWN). "
        "Return a JSON object like {"direction":"UP","delta":25,"reason":"..."} "
    )
    try:
        ans = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                           messages=[{"role":"user","content":prompt}],
                                           max_tokens=100).choices[0].message.content.strip()
        data = json.loads(ans)
        return data.get("direction","FLAT"), float(data.get("delta",0)), data.get("reason","")
    except Exception as e:
        return "FLAT",0.0,f"GPT error:{e}"

direction, delta, reason = ai_outlook()
st.subheader("AI Outlook")
st.write(f"**Trend:** {direction}  |  **Δ ≈ {delta:+.0f} USD**")
st.write(reason)

# ---------- Determine safety days ----------
baseline = 7
if direction=="UP":
    fg_days = resin_days = 14 if delta>30 else 10
elif direction=="DOWN":
    fg_days = resin_days = 3 if delta>30 else baseline
else:
    fg_days = resin_days = baseline

st.info(f"Safety stock guideline set to **{fg_days} production‑days** based on outlook.")

# ---------- Editable sales/price table ----------
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
    st.session_state["assump_df"]=default_df(months)
    st.session_state["cache_m0"]=m0
    st.session_state["cache_h"]=horizon
assump_df = st.data_editor(st.session_state["assump_df"], use_container_width=True)

st.divider()

# ---------- Planner ----------
def compute(df):
    fg,resin,blended=fg_open,resin_open,resin_blended_open
    rows=[]
    for i,row in df.iterrows():
        sales=row["Sales Plan (t)"]
        next_sales=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else sales
        fg_target=fg_days/prod_days*next_sales
        prod_raw=max(0,sales+fg_target-fg)
        fg_close=min(fg+prod_raw-sales, FG_CAP)
        production=fg_close+sales-fg
        resin_use=production*usage_ratio
        next_prod=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production
        resin_target=resin_days/prod_days*next_prod*usage_ratio
        prices={k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src=min(prices,key=prices.get); price=prices[src]
        purchase=max(0,resin_use+resin_target-resin)
        blended=(resin*blended+purchase*price)/(resin+purchase) if (resin+purchase) else blended
        resin_close=resin+purchase-resin_use
        rows.append({"Month":row["Month"],"Sales":sales,"Production":production,"FG Close":fg_close,
                     "Days FG":round(fg_close/(next_sales/prod_days),1) if next_sales else 0,
                     "Purchase":purchase,"Unit Price":price,"Source":src,
                     "Resin Close":resin_close,
                     "Days Resin":round(resin_close/((next_prod*usage_ratio)/prod_days),1) if next_prod else 0,
                     "Blended":blended})
        fg,resin=fg_close,resin_close
    return pd.DataFrame(rows)

plan_df = compute(assump_df.copy())
st.subheader("Plan Summary")
st.dataframe(plan_df, use_container_width=True)
st.download_button("Download CSV", plan_df.to_csv(index=False).encode(), "resin_plan.csv", mime="text/csv")
