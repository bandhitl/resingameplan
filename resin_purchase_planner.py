
import streamlit as st
import pandas as pd
import numpy as np
import requests, os, openai
from datetime import date, timedelta

st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

"""
Enhanced dashboard with:

* Corporate **Resin Games Plan** table  
* FG capacity hard‑capped at **500 t**  
* **Historical PVC resin purchase price chart** (IDR/kg & USD/t)  
* **AI PVC price outlook** (next 3 months) – auto‑summarises fresh demand‑supply news  
  (Requires `NEWS_API_KEY`; add `OPENAI_API_KEY` to use GPT)
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

FG_CAP = 500  # tonnes


# ───────────── Historical price data & chart ─────────────
hist_df = pd.DataFrame({
    "Month": ["Jul-24","Aug-24","Sep-24","Oct-24","Nov-24","Dec-24",
              "Jan-25","Feb-25","Mar-25","Apr-25","May-25","Jun-25"],
    "IDR/kg": [13300,13460,12800,12340,11960,12100,11960,11810,11710,11320,11320,11320],
    "USD/t":  [815.95,825.77,785.28,757.06,733.74,742.33,733.74,724.54,718.40,694.48,694.48,694.48]
})
hist_df["Date"] = pd.to_datetime(hist_df["Month"], format="%b-%y")

st.subheader("Historical PVC Resin Purchase Price")
st.line_chart(
    hist_df.set_index("Date")[["IDR/kg","USD/t"]],
    height=300,
    use_container_width=True
)

# ───────────── Build editable assumptions table ─────────────
months = pd.date_range(pd.to_datetime(m0), periods=horizon, freq="MS").strftime("%b-%y")
def default_df(labels):
    return pd.DataFrame({
        "Month": labels,
        "Sales Plan (t)": [800 + 50*i for i in range(len(labels))],
        "Local": [690 + 10*i for i in range(len(labels))],
        "TPE": [np.nan if i>1 else 760 - 15*i for i in range(len(labels))],
        "China/Korea": [np.nan if i>1 else 740 - 11*i for i in range(len(labels))]
    })

if "assump_df" not in st.session_state or st.session_state.get("cache_m0")!=m0 or st.session_state.get("cache_h")!=horizon:
    st.session_state["assump_df"] = default_df(months)
    st.session_state["cache_m0"] = m0
    st.session_state["cache_h"] = horizon

assump_df = st.data_editor(
    st.session_state["assump_df"],
    num_rows="dynamic",
    use_container_width=True,
    key="input_table"
)

st.divider()

# ───────────── Core plan computation (unchanged logic) ─────────────
def compute(df: pd.DataFrame):
    fg_inv, resin_inv, blended = fg_open, resin_open, resin_blended_open
    rows=[]
    for i,row in df.iterrows():
        month=row["Month"]; sales=row["Sales Plan (t)"]
        next_sales=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else sales
        fg_target_close=fg_target_days/prod_days*next_sales
        prod_raw=max(0,sales+fg_target_close-fg_inv)
        fg_close_raw=fg_inv+prod_raw-sales
        if fg_close_raw>FG_CAP:
            production=max(0,prod_raw-(fg_close_raw-FG_CAP)); fg_close=FG_CAP
        else:
            production=prod_raw; fg_close=fg_close_raw
        resin_usage=production*usage_ratio
        next_prod=df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production
        resin_target_close=resin_target_days/prod_days*next_prod*usage_ratio
        price_map={k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src=min(price_map,key=price_map.get); price=price_map[src]
        purchase=max(0,resin_usage+resin_target_close-resin_inv)
        blended=(resin_inv*blended+purchase*price)/(resin_inv+purchase) if (resin_inv+purchase) else blended
        resin_close=resin_inv+purchase-resin_usage
        fg_days=fg_close/(next_sales/prod_days) if next_sales else 0
        resin_days=resin_close/((next_prod*usage_ratio)/prod_days) if next_prod else 0
        rows.append({
            "Month":month,"Sales Out":sales,"Production":production,
            "FG Stock":fg_close,"FG Days":fg_days,
            "Incoming Resin":purchase,"Unit Price Resin":price,"Source Resin":src,
            "Usage Resin":resin_usage,"Resin Stock":resin_close,"Resin Days":resin_days,
            "Blended $/t":blended
        })
        fg_inv,resin_inv=fg_close,resin_close
    return pd.DataFrame(rows)

def style(df):
    metrics=["Sales Out","Production","FG Stock","FG Days","Incoming Resin","Unit Price Resin","Source Resin","Usage Resin","Resin Stock","Resin Days","Blended $/t"]
    pivot=df.set_index("Month")[metrics].T
    pivot.index=["Sales Out","Production","Stock Finished Goods","Days FG","Incoming Resin","Unit Price Resin","Source Resin","Usage Resin","Ending Stock Resin","Days Resin","Average Blended Usage Resin Price"]
    sty=pivot.style
    sty.set_table_styles([{"selector":"th","props":[("background-color","#f2f2f2"),("font-weight","bold")]},{"selector":"td","props":[("border","1px solid #d0d0d0"),("text-align","center")]}],overwrite=False)
    orange=["Incoming Resin","Unit Price Resin","Source Resin","Usage Resin","Ending Stock Resin"]
    sty.apply(lambda r:["background-color:#fbe5d6"]*len(r) if r.name in orange else ["" for _ in r],axis=1)
    sty.apply(lambda r:["color:#0073b7;font-weight:bold"]*len(r) if r.name in ["Days FG","Days Resin"] else ["" for _ in r],axis=1)
    sty.format(precision=0, formatter=lambda x:f"{x:.0f}" if isinstance(x,(int,float)) else x)
    return sty

# ───────────── AI helpers ─────────────
def fetch_news():
    key=os.getenv("NEWS_API_KEY")
    if not key: return []
    start=date.today()-timedelta(days=30)
    url=f"https://newsapi.org/v2/everything?q=PVC%%20resin%%20price%%20OR%%20PVC%%20demand%%20supply&from={start}&language=en&sortBy=publishedAt&pageSize=20&apiKey={key}"
    try:
        return [a["title"] for a in requests.get(url,timeout=10).json().get("articles",[])]
    except Exception: return []

def summarize(headlines):
    key=os.getenv("OPENAI_API_KEY")
    if not key or not headlines: return "N/A","(Provide API keys to enable AI forecast.)"
    openai.api_key=key
    prompt="You are a petrochemical analyst. Using these headlines, state whether PVC resin price trend next 3 months in SE Asia is UP, DOWN, or FLAT, then give key drivers.\n\n"+"\n".join(headlines)
    try:
        txt=openai.ChatCompletion.create(model="gpt-3.5-turbo",messages=[{"role":"user","content":prompt}],max_tokens=150).choices[0].message.content.strip()
        return txt.split()[0],txt
    except Exception as e:
        return "N/A",f"GPT error: {e}"

# ───────────── Main button ─────────────
if st.button("🚀 Generate Styled Plan"):
    calc=compute(assump_df.copy())
    st.subheader(f"BNI Resin Games Plan : {m0.strftime('%b %Y')} – {(pd.to_datetime(m0)+pd.DateOffset(months=horizon-1)).strftime('%b %Y')}")
    st.markdown(style(calc).to_html(),unsafe_allow_html=True)

    st.subheader("PVC Resin Price Outlook (next 3 months)")
    news=fetch_news()
    trend,rationale=summarize(news)
    st.write(f"**Trend:** {trend}")
    st.write(rationale)
    if news:
        with st.expander("News headlines considered"):
            for h in news: st.markdown(f"- {h}")

    st.download_button("Download raw CSV", calc.to_csv(index=False).encode(), "resin_plan.csv", mime="text/csv")
