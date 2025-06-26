
import streamlit as st
import pandas as pd
import numpy as np
from datetime import date

st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

"""App to suggest monthly production and resin purchases based on sales plan & resin prices."""


# ---- Sidebar ----
with st.sidebar:
    st.header("Global Parameters")

    m0 = st.date_input(
        "Current inventory month (m0)",
        value=date.today().replace(day=1),
        help="Month representing current inventory"
    )

    horizon = st.number_input("Plan horizon (months)", 3, 12, 6, step=1)

    fg_open = st.number_input("Opening FG inventory (t)", 0.0, 20000.0, 465.0, step=10.0)
    resin_open = st.number_input("Opening resin inventory (t)", 0.0, 20000.0, 132.0, step=10.0)
    resin_blended_open = st.number_input("Opening blended resin price (USD/t)", 0.0, 2000.0, 694.0, step=10.0)

    fg_target_days = st.number_input("FG safety stock (days)", 0, 60, 15, step=1)
    resin_target_days = st.number_input("Resin safety stock (days)", 0, 30, 5, step=1)
    prod_days = st.number_input("Production days per month", 15, 31, 25, step=1)
    usage_ratio = st.number_input("Resin usage ratio (% of production)", 0.0, 1.0, 0.725, step=0.005)

# ---- Rolling month list ----
months = pd.date_range(pd.to_datetime(m0), periods=horizon, freq="MS").strftime("%b-%Y")

# ---- Default table ----
def default_df(labels):
    rows = []
    base_sales = 800
    base_local = 690
    for i, m in enumerate(labels):
        rows.append({
            "Month": m,
            "Sales Plan (t)": base_sales + 50*i,
            "Local": base_local + 10*i,
            "TPE": np.nan if i>1 else 760 - 15*i,
            "China/Korea": np.nan if i>1 else 740 - 11*i,
        })
    return pd.DataFrame(rows)

if "sales_price_df" not in st.session_state or    st.session_state.get("cache_m0") != m0 or    st.session_state.get("cache_horizon") != horizon:
    st.session_state["sales_price_df"] = default_df(months)
    st.session_state["cache_m0"] = m0
    st.session_state["cache_horizon"] = horizon

df = st.data_editor(
    st.session_state["sales_price_df"],
    num_rows="dynamic",
    use_container_width=True,
    key="data_editor",
    column_config={
        "Month": st.column_config.Column(required=True),
        "Sales Plan (t)": st.column_config.NumberColumn(required=True),
        "Local": st.column_config.NumberColumn(),
        "TPE": st.column_config.NumberColumn(),
        "China/Korea": st.column_config.NumberColumn(),
    },
)

st.divider()

# ---- Core planner ----
def compute_plan(df, fg_open, resin_open, resin_blended_open,
                 fg_target_days, resin_target_days,
                 prod_days, usage_ratio):

    results = []
    fg_inv = fg_open
    resin_inv = resin_open
    blended_price = resin_blended_open

    for idx in range(len(df)):
        month = df.at[idx, "Month"]
        sales = df.at[idx, "Sales Plan (t)"]

        next_sales = df.at[idx+1, "Sales Plan (t)"] if idx+1 < len(df) else sales
        fg_target_close = fg_target_days / prod_days * next_sales
        production = max(0.0, sales + fg_target_close - fg_inv)

        resin_usage = production * usage_ratio
        next_prod_est = df.at[idx+1, "Sales Plan (t)"] if idx+1 < len(df) else production
        resin_target_close = resin_target_days / prod_days * next_prod_est * usage_ratio

        price_cols = [c for c in ["Local", "TPE", "China/Korea"] if pd.notna(df.at[idx, c])]
        prices = {c: df.at[idx, c] for c in price_cols}
        cheapest_src = min(prices, key=prices.get)
        cheapest_price = prices[cheapest_src]

        purchase_qty = max(0.0, resin_usage + resin_target_close - resin_inv)
        purchase_cost = purchase_qty * cheapest_price

        total_cost = resin_inv * blended_price + purchase_cost
        closing_resin_inv = resin_inv + purchase_qty - resin_usage
        blended_price = total_cost / (resin_inv + purchase_qty) if (resin_inv + purchase_qty) else 0.0

        closing_fg_inv = fg_inv + production - sales
        fg_days = closing_fg_inv / (next_sales / prod_days) if next_sales else 0.0
        resin_days = closing_resin_inv / ((next_prod_est * usage_ratio) / prod_days) if next_prod_est else 0.0

        results.append({
            "Month": month,
            "Sales (t)": sales,
            "Production (t)": production,
            "FG Close (t)": closing_fg_inv,
            "FG Days": round(fg_days,1),
            "Resin Close (t)": closing_resin_inv,
            "Resin Days": round(resin_days,1),
            "Purchase (t)": purchase_qty,
            "Source": cheapest_src,
            "Unit Price (USD/t)": cheapest_price,
            "Blended $/t": round(blended_price,2),
        })

        fg_inv = closing_fg_inv
        resin_inv = closing_resin_inv

    return pd.DataFrame(results)

if st.button("🚀 Suggest Plan"):
    plan = compute_plan(df.copy(),
                        fg_open, resin_open, resin_blended_open,
                        fg_target_days, resin_target_days,
                        prod_days, usage_ratio)

    st.subheader("Recommended Production & Purchase Plan")
    st.dataframe(plan.style.format({
        "Sales (t)": "{:.1f}",
        "Production (t)": "{:.1f}",
        "FG Close (t)": "{:.1f}",
        "FG Days": "{:.1f}",
        "Resin Close (t)": "{:.1f}",
        "Resin Days": "{:.1f}",
        "Purchase (t)": "{:.1f}",
        "Unit Price (USD/t)": "{:.0f}",
        "Blended $/t": "{:.0f}",
    }), use_container_width=True)

    csv = plan.to_csv(index=False).encode()
    st.download_button("Download CSV", csv,
                       file_name="resin_production_purchase_plan.csv",
                       mime="text/csv")
