
import streamlit as st, pandas as pd, numpy as np, openai, os, json, matplotlib.pyplot as plt
from datetime import date

# ---------- page config ----------
st.set_page_config(page_title="Resin Purchase Plan", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

# ---------- sidebar ----------
with st.sidebar:
    st.header("Parameters")
    m0 = st.date_input("Current inventory month", value=date.today().replace(day=1))
    horizon = st.number_input("Plan horizon (months)", 3, 12, 4)
    fg_open = st.number_input("Opening FG inventory (t)",    0., 500., 465., step=10.)
    resin_open = st.number_input("Opening resin inventory (t)",0., 10000.,132., step=10.)
    blended_open = st.number_input("Opening blended resin price (USD/t)",0.,2000.,694.,step=10.)
    prod_days = st.number_input("Production days / month",15,31,25)
    usage_ratio = st.number_input("Resin usage ratio (% of production)",0.,1.,0.725,step=0.005)

FG_CAP = 500
RESIN_SAFETY_MIN = 7
RESIN_SAFETY_MAX = 10

# ---------- historical price ----------
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

# ---------- AI trend ----------
def ai_trend():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return {"trend":"FLAT","factors":["OPENAI_API_KEY missing"]}
    openai.api_key = key
    prompt = (
        "You are a petrochemical analyst. "
        "Summarise overall price trend for PVC resin in SE Asia for the next three months "
        "(UP / DOWN / FLAT only) together with 3 concise demand‑supply factors. "
        "Return strict JSON: {\"trend\":\"UP\",\"factors\":["...","..."]}"
    )
    try:
        txt = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            max_tokens=150
        ).choices[0].message.content
        data = json.loads(txt[txt.find("{"):txt.rfind("}")+1])
        if "trend" in data and "factors" in data:
            return data
    except Exception as e:
        st.warning(f"GPT error – fallback FLAT | {e}")
    return {"trend":"FLAT","factors":["fallback"]}

trend_info = ai_trend()
trend = trend_info["trend"].upper()
resin_safety = RESIN_SAFETY_MAX if trend=="UP" else RESIN_SAFETY_MIN

st.markdown(
    "<div style='border-left:4px solid #1E90FF;background:#eef6ff;padding:.75em 1em;border-radius:4px;'>"
    f"<b>Price trend (next 3 mo): {trend}</b><br>"
    + "<br>".join(f"• {f}" for f in trend_info["factors"])
    + f"<br><br><b>Resin safety target = {resin_safety} prod‑days</b>"
    "</div>",
    unsafe_allow_html=True
)

# ---------- editable table ----------
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
    st.session_state["tbl"]=default_tbl(months)
    st.session_state["cache"]=(m0,horizon)
tbl = st.data_editor(st.session_state["tbl"],use_container_width=True)

# ---------- planner ----------
def plan(df: pd.DataFrame):
    fg, resin, blend = fg_open, resin_open, blended_open
    out=[]
    for i,row in df.iterrows():
        sales = row["Sales Plan (t)"]
        # Produce = sales plus extra to reach FG_CAP if stock < FG_CAP
        production = sales
        if fg - sales + production < FG_CAP:
            production += FG_CAP - (fg - sales + production)
        # if overshoot cap after extra, trim
        if fg + production - sales > FG_CAP:
            production = production - (fg + production - sales - FG_CAP)
        fg_close = fg + production - sales
        next_prod = df.iloc[i+1]["Sales Plan (t)"] if i+1<len(df) else production
        resin_use = production * usage_ratio
        resin_target = resin_safety / prod_days * next_prod * usage_ratio
        prices={k:row[k] for k in ["Local","TPE","China/Korea"] if pd.notna(row[k])}
        src, price = min(prices, key=prices.get), min(prices.values())
        purchase = max(0,resin_use + resin_target - resin)
        if resin + purchase:
            blend = (resin*blend + purchase*price)/(resin+purchase)
        resin_close = resin + purchase - resin_use
        out.append({
            "Month":row["Month"], "Sales":sales,"Production":production,
            "Stock FG":fg_close,"Days FG":round(fg_close/(next_prod/prod_days),1) if next_prod else 0,
            "Incoming Resin":purchase,"Unit Price":price,"Source":src,
            "Stock Resin":resin_close,
            "Days Resin":round(resin_close/((next_prod*usage_ratio)/prod_days),1) if next_prod else 0,
            "Blended $/t":blend
        })
        fg, resin = fg_close, resin_close
    return pd.DataFrame(out)

# ---------- generate ----------
if st.button("🚀 Generate Plan"):
    result = plan(tbl.copy())

    def style(df):
        pv=df.set_index("Month").T
        orange={"Incoming Resin","Unit Price","Source","Stock Resin"}
        blue={"Days FG","Days Resin"}
        def fmt(r):
            if r.name in orange: return ["background-color:#fbe5d6"]*len(r)
            if r.name in blue: return ["color:#0073b7;font-weight:bold"]*len(r)
            return ["" for _ in r]
        return pv.style.apply(fmt, axis=1)
    st.subheader("BNI Resin Games Plan")
    st.markdown(style(result).to_html(), unsafe_allow_html=True)
    st.download_button("⬇️ CSV", result.to_csv(index=False).encode(),
                       "resin_plan.csv", mime="text/csv")
