
import streamlit as st
import pandas as pd
import numpy as np
from datetime import date

st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

"""Input **sales plan** & **resin prices** → get a dashboard that mimics the official
“Resin Games Plan” (orange resin rows, blue day counts, grey headers)."""


# ───────────────────────── Sidebar ─────────────────────────
with st.sidebar:
    st.header("Global Parameters")

    m0 = st.date_input("Current inventory month (m0)",
                       value=date.today().replace(day=1))

    horizon = st.number_input("Plan horizon (months)", 3, 12, 4, step=1)

    fg_open = st.number_input("Opening FG inventory (t)", 0.0, 20_000.0,
                              465.0, step=10.0)
    resin_open = st.number_input("Opening resin inventory (t)", 0.0, 20_000.0,
                                 132.0, step=10.0)
    resin_blended_open = st.number_input("Opening blended resin price (USD/t)",
                                         0.0, 2_000.0, 694.0, step=10.0)

    fg_target_days = st.number_input("FG safety stock (days)", 0, 60, 15, step=1)
    resin_target_days = st.number_input("Resin safety stock (days)", 0, 30, 5, step=1)
    prod_days = st.number_input("Production days / month", 15, 31, 25, step=1)
    usage_ratio = st.number_input("Resin usage ratio (% of prod.)",
                                  0.0, 1.0, 0.725, step=0.005)

# ───────────── Build editable assumption table ─────────────
months = pd.date_range(pd.to_datetime(m0),
                       periods=horizon,
                       freq="MS").strftime("%b-%y")


def default_df(labels):
    base_sales, base_local = 800, 690
    rows = []
    for i, m in enumerate(labels):
        rows.append({
            "Month": m,
            "Sales Plan (t)": base_sales + i * 50,
            "Local": base_local + i * 10,
            "TPE": np.nan if i > 1 else 760 - i * 15,
            "China/Korea": np.nan if i > 1 else 740 - i * 11,
        })
    return pd.DataFrame(rows)


if "assump_df" not in st.session_state or         st.session_state.get("cache_m0") != m0 or         st.session_state.get("cache_h") != horizon:
    st.session_state["assump_df"] = default_df(months)
    st.session_state["cache_m0"] = m0
    st.session_state["cache_h"] = horizon

assump_df = st.data_editor(
    st.session_state["assump_df"],
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Month": st.column_config.Column(required=True),
        "Sales Plan (t)": st.column_config.NumberColumn(required=True),
        "Local": st.column_config.NumberColumn(),
        "TPE": st.column_config.NumberColumn(),
        "China/Korea": st.column_config.NumberColumn(),
    },
    key="input_table"
)

st.divider()

# ─────────────────────────── Engine ─────────────────────────
def compute(plan_df: pd.DataFrame):
    fg_inv, resin_inv, blended = fg_open, resin_open, resin_blended_open
    rows = []
    for i, row in plan_df.iterrows():
        month = row["Month"]
        sales = row["Sales Plan (t)"]
        next_sales = plan_df.iloc[i + 1]["Sales Plan (t)"] if i + 1 < len(plan_df) else sales

        fg_target_close = fg_target_days / prod_days * next_sales
        production = max(0.0, sales + fg_target_close - fg_inv)

        resin_usage = production * usage_ratio
        next_prod_est = plan_df.iloc[i + 1]["Sales Plan (t)"] if i + 1 < len(plan_df) else production
        resin_target_close = resin_target_days / prod_days * next_prod_est * usage_ratio

        prices = {src: row[src] for src in ["Local", "TPE", "China/Korea"]
                  if pd.notna(row[src])}
        cheapest_src = min(prices, key=prices.get)
        cheapest_price = prices[cheapest_src]

        purchase_qty = max(0.0, resin_usage + resin_target_close - resin_inv)
        purchase_cost = purchase_qty * cheapest_price

        total_cost = resin_inv * blended + purchase_cost
        resin_close = resin_inv + purchase_qty - resin_usage
        blended = total_cost / (resin_inv + purchase_qty) if (resin_inv + purchase_qty) else 0

        fg_close = fg_inv + production - sales

        fg_days = fg_close / (next_sales / prod_days) if next_sales else 0
        resin_days = resin_close / ((next_prod_est * usage_ratio) / prod_days) if next_prod_est else 0

        rows.append({
            "Month": month,
            "Sales Out": sales,
            "Production": production,
            "FG Stock": fg_close,
            "FG Days": fg_days,
            "Incoming Resin": purchase_qty,
            "Usage Resin": resin_usage,
            "Resin Stock": resin_close,
            "Resin Days": resin_days,
            "Blended $/t": blended,
        })

        fg_inv, resin_inv = fg_close, resin_close

    return pd.DataFrame(rows)


# ────────────────────── Styling helpers ─────────────────────
def style_report(df: pd.DataFrame):
    metrics = ["Sales Out", "Production",
               "FG Stock", "FG Days",
               "Incoming Resin", "Usage Resin", "Resin Stock", "Resin Days",
               "Blended $/t"]

    pivot = df.set_index("Month")[metrics].T
    pivot.index = ["Sales Out", "Production",
                   "Stock Finished Goods", "Days FG",
                   "Incoming Resin", "Usage Resin", "Ending Stock Resin", "Days Resin",
                   "Average Blended Usage Resin Price"]

    sty = pivot.style

    # base style
    sty.set_table_styles([
        {"selector": "th",
         "props": [("background-color", "#f2f2f2"), ("font-weight", "bold")]},
        {"selector": "td",
         "props": [("border", "1px solid #d0d0d0"),
                   ("text-align", "center")]}
    ], overwrite=False)

    # orange resin rows
    def orange(row):
        if row.name in ["Incoming Resin", "Usage Resin", "Ending Stock Resin"]:
            return ["background-color:#fbe5d6"] * len(row)
        return ["" for _ in row]

    # blue day rows
    def blue(row):
        if row.name in ["Days FG", "Days Resin"]:
            return ["color:#0073b7;font-weight:bold"] * len(row)
        return ["" for _ in row]

    sty.apply(orange, axis=1)
    sty.apply(blue, axis=1)
    sty.format(precision=0, formatter=lambda x: f"{x:.0f}" if isinstance(x, (int, float)) else x)
    return sty


# ─────────────────────────── Run ────────────────────────────
if st.button("🚀 Generate Styled Plan"):
    calc_df = compute(assump_df.copy())
    styled = style_report(calc_df)

    start_label = m0.strftime("%b %Y")
    end_label = (pd.to_datetime(m0) + pd.DateOffset(months=horizon - 1)).strftime("%b %Y")
    st.subheader(f"BNI Resin Games Plan : {start_label} – {end_label}")

    st.markdown(styled.to_html(), unsafe_allow_html=True)

    csv = calc_df.to_csv(index=False).encode()
    st.download_button("Download raw CSV", csv, "resin_plan.csv", mime="text/csv")
