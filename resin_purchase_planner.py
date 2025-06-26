import streamlit as st
import pandas as pd
import numpy as np
import openai, os, matplotlib.pyplot as plt
from datetime import date
import json, re

# ────────── Page ──────────
st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

st.markdown("""### Overview
* Corporate **Resin Games Plan**
* FG capacity 500 t
* Historical price chart (USD/t) – *ไม่มีเส้นคาดการณ์*
* Safety stock (days) ปรับอัตโนมัติตาม AI Outlook  
  ‣ baseline 7 วัน  
  ‣ **UP** > 30 USD → 14 วัน  
  ‣ **UP** ≤ 30 USD → 10 วัน  
  ‣ **DOWN** > 30 USD → 3 วัน  
""")

# ────────── Sidebar ──────────
with st.sidebar:
    st.header("Parameters")
    m0 = st.date_input("Current inventory month (m0)", value=date.today().replace(day=1))
    horizon = st.number_input("Plan horizon (months)", 3, 12, 4, step=1)
    fg_open  = st.number_input("Opening FG inventory (t)",    0.0, 500.0,   465.0, step=10.0)
    resin_open = st.number_input("Opening resin inventory (t)",0.0,20000.0, 132.0, step=10.0)
    resin_blended_open = st.number_input("Opening blended resin price (USD/t)",
                                         0.0, 2000.0, 694.0, step=10.0)
    prod_days   = st.number_input("Production days / month", 15, 31, 25, step=1)
    usage_ratio = st.number_input("Resin usage ratio (% of production)",
                                  0.0, 1.0, 0.725, step=0.005)

FG_CAP = 500

# ────────── Historical price ──────────
hist = pd.DataFrame({
    "Month":["Jul-24","Aug-24","Sep-24","Oct-24","Nov-24","Dec-24",
             "Jan-25","Feb-25","Mar-25","Apr-25","May-25","Jun-25"],
    "USD/t":[815.95,825.77,785.28,757.06,733.74,742.33,
             733.74,724.54,718.40,694.48,694.48,694.48]})
hist["Date"] = pd.to_datetime(hist["Month"], format="%b-%y")

st.subheader("PVC Resin Price (USD/t)")
st.line_chart(hist.set_index("Date")["USD/t"], use_container_width=True)

# ────────── AI outlook & safety days ──────────
def ai_outlook():
    key = os.getenv("OPENAI_API_KEY")
    price_str = "\n".join(f"{m}: {p}" for m,p in hist.values)
    if not key:
        return "FLAT",0,"OPENAI_API_KEY not set → baseline"
    openai.api_key = key
    prompt = (
        "Return JSON {'direction':'UP|DOWN|FLAT','delta':float,'reason':'...'} "
        "for next-month price change based on this price series (USD/t):\n"+price_str)
    try:
        txt = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                           messages=[{"role":"user","content":prompt}],
                                           max_tokens=120).choices[0].message.content
        data = json.loads(re.search(r"{.*}", txt.replace("`","")).group())
        return data.get("direction","FLAT"), float(data.get("delta",0)), data.get("reason","")
    except Exception as e:
        return "FLAT",0,f"GPT error: {e}"

direction, delta, reason = ai_outlook()
baseline = 7
if direction == "UP":
    safety = 14 if delta > 30 else 10
elif direction == "DOWN":
    safety = 3 if delta > 30 else baseline
else:
    safety = baseline

st.info(f"AI Outlook → **{direction} {delta:+.0f} USD**\n\n"
        f"Guideline safety stock: **{safety} prod-days**\n\n{reason}")

# ────────── Input price table ──────────
months = pd.date_range(pd.to_datetime(m0), periods=horizon, freq="MS").strftime("%b-%y")
def default_df(lbl):
    return pd.DataFrame({
        "Month": lbl,
        "Sales Plan (t)": [800+50*i for i in range(len(lbl))],
        "Local": [690+10*i for i in range(len(lbl))],
        "TPE": [np.nan if i>1 else 760-15*i for i in range(len(lbl))],
        "China/Korea": [np.nan if i>1 else 740-11*i for i in range(len(lbl))]
    })
if "assump" not in st.session_state or st.session_state["cache"]!=(m0,horizon):
    st.session_state["assump"]=default_df(months)
    st.session_state["cache"]=(m0,horizon)
assump = st.data_editor(st.session_state["assump"], use_container_width=True)

# ────────── Planner ──────────
def compute(df):
    fg, resin, blended = fg_open, resin_open, resin_blended_open
    out=[]
    for i,row in df.iterrows():
        sales=row["Sales Plan (t)"]
        next_sales=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else sales
        fg_target=safety/prod_days*next_sales
        prod=max(0,sales+fg_target-fg)
        fg_close=min(fg+prod-sales, FG_CAP)
        production=fg_close+sales-fg
        resin_use=production*usage_ratio
        next_prod=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production
        resin_target=safety/prod_days*next_prod*usage_ratio
        prices={k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src=min(prices,key=prices.get); price=prices[src]
        purchase=max(0,resin_use+resin_target-resin)
        blended=(resin*blended+purchase*price)/(resin+purchase) if resin+purchase else blended
        resin_close=resin+purchase-resin_use
        out.append({"Month":row["Month"],"Sales":sales,"Production":production,
                    "Stock FG":fg_close,
                    "Days FG":round(fg_close/(next_sales/prod_days),1) if next_sales else 0,
                    "Incoming Resin":purchase,"Unit Price":price,"Source":src,
                    "Stock Resin":resin_close,
                    "Days Resin":round(resin_close/((next_prod*usage_ratio)/prod_days),1) if next_prod else 0,
                    "Blended $/t":blended})
        fg,resin=fg_close,resin_close
    return pd.DataFrame(out)

plan = compute(assump.copy())

# ────────── Styling ──────────
def style(df):
    pivot=df.set_index("Month").T
    orange=["Incoming Resin","Unit Price","Source","Stock Resin"]
    blue=["Days FG","Days Resin"]
    def fmt(row):
        if row.name in orange: return ["background-color:#fbe5d6"]*len(row)
        if row.name in blue:   return ["color:#0073b7;font-weight:bold"]*len(row)
        return ["" for _ in row]
    return pivot.style.apply(fmt,axis=1)

st.subheader("BNI Resin Games Plan")
st.markdown(style(plan).to_html(), unsafe_allow_html=True)
st.download_button("Download CSV", plan.to_csv(index=False).encode(),
                   "resin_plan.csv", mime="text/csv")
