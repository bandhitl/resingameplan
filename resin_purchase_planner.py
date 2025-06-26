"""Resin purchase planning tool with optional Streamlit UI."""

from __future__ import annotations

import argparse
from datetime import date

try:
    import numpy as np
    import pandas as pd
except ModuleNotFoundError as exc:  # pragma: no cover - handled via CLI fallback
    missing = exc.name
    raise SystemExit(
        f"Missing required dependency: {missing}. Please install packages from requirements.txt"
    ) from exc

try:  # Streamlit is optional
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover - handled via CLI fallback
    st = None


def default_df(months: list[str]) -> pd.DataFrame:
    """Return a basic sales and price DataFrame for the given months."""
    rows = []
    base_sales = 800
    base_price_local = 690
    for i, m in enumerate(months):
        rows.append(
            {
                "Month": m,
                "Sales Plan (t)": base_sales + i * 50,  # growth trend placeholder
                "Local": base_price_local + i * 10,
                "TPE": np.nan if i > 1 else 760 - i * 15,
                "China/Korea": np.nan if i > 1 else 740 - i * 11,
            }
        )
    return pd.DataFrame(rows)


def compute_plan(
    df: pd.DataFrame,
    fg_open: float,
    resin_open: float,
    resin_blended_open: float,
    fg_target_days: int,
    resin_target_days: int,
    prod_days: int,
    usage_ratio: float,
    *,
    use_streamlit: bool = False,
) -> pd.DataFrame:
    """Return the suggested production and purchase plan."""
    results = []
    fg_inv = fg_open
    resin_inv = resin_open
    blended_price = resin_blended_open

    for idx in range(len(df)):
        month = df.loc[idx, "Month"]
        sales = df.loc[idx, "Sales Plan (t)"]

        # Next month sales (for FG coverage)
        next_sales = df.loc[idx + 1, "Sales Plan (t)"] if idx + 1 < len(df) else sales
        fg_target_close = fg_target_days / prod_days * next_sales

        # Production needed
        production = max(0.0, sales + fg_target_close - fg_inv)

        # Resin needs
        resin_usage = production * usage_ratio
        next_prod_est = df.loc[idx + 1, "Sales Plan (t)"] if idx + 1 < len(df) else production
        resin_target_close = resin_target_days / prod_days * next_prod_est * usage_ratio

        # Cheapest source price
        price_cols = [c for c in ["Local", "TPE", "China/Korea"] if pd.notna(df.loc[idx, c])]
        if not price_cols:
            msg = f"No resin prices provided for {month}. Please fill at least one price."
            if use_streamlit and st is not None:
                st.error(msg)
                st.stop()
            raise ValueError(msg)

        prices = {c: df.loc[idx, c] for c in price_cols}
        cheapest_src = min(prices, key=prices.get)
        cheapest_price = prices[cheapest_src]

        # Purchase qty
        purchase_qty = max(0.0, resin_usage + resin_target_close - resin_inv)
        purchase_cost = purchase_qty * cheapest_price

        # Moving-average blended cost update
        total_cost = resin_inv * blended_price + purchase_cost
        closing_resin_inv = resin_inv + purchase_qty - resin_usage
        blended_price = total_cost / (resin_inv + purchase_qty) if (resin_inv + purchase_qty) else 0.0

        # FG closing stock
        closing_fg_inv = fg_inv + production - sales

        # Days of cover calculations
        fg_days = closing_fg_inv / (next_sales / prod_days) if next_sales else 0.0
        resin_days = closing_resin_inv / ((next_prod_est * usage_ratio) / prod_days) if next_prod_est else 0.0

        results.append(
            {
                "Month": month,
                "Sales (t)": sales,
                "Production (t)": production,
                "FG Close (t)": closing_fg_inv,
                "FG Days": round(fg_days, 1),
                "Resin Close (t)": closing_resin_inv,
                "Resin Days": round(resin_days, 1),
                "Purchase (t)": purchase_qty,
                "Source": cheapest_src,
                "Unit Price (USD/t)": cheapest_price,
                "Blended $/t": round(blended_price, 2),
            }
        )

        fg_inv = closing_fg_inv
        resin_inv = closing_resin_inv

    return pd.DataFrame(results)


def run_streamlit_app() -> None:
    """Launch the Streamlit user interface."""
    st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")

    st.title("📈 Resin Purchase & Production Advisor")

    with st.sidebar:
        st.header("Global Parameters")

        m0 = st.date_input(
            "Current inventory month (m0)",
            value=date.today().replace(day=1),
            format="%B %Y",
            help="Select the month that represents inventory on hand right now.",
        )

        horizon = st.number_input("Plan horizon (months)", 3, 12, 6, step=1)

        # Opening inventories
        fg_open = st.number_input("Opening FG inventory (t)", 0.0, 20_000.0, 465.0, step=10.0)
        resin_open = st.number_input("Opening resin inventory (t)", 0.0, 20_000.0, 132.0, step=10.0)
        resin_blended_open = st.number_input("Opening blended resin price (USD/t)", 0.0, 2_000.0, 694.0, step=10.0)

        # Policy settings
        fg_target_days = st.number_input("FG safety stock (days)", 0, 60, 15, step=1)
        resin_target_days = st.number_input("Resin safety stock (days)", 0, 30, 5, step=1)
        prod_days = st.number_input("Production days per month", 15, 31, 25, step=1)
        usage_ratio = st.number_input(
            "Resin usage ratio (% of production)", 0.0, 1.0, 0.725, step=0.005, format="%0.3f"
        )

    months = pd.date_range(pd.to_datetime(m0), periods=horizon, freq="MS").strftime("%b-%Y").tolist()

    if (
        "sales_price_df" not in st.session_state
        or st.session_state.get("cache_m0") != m0
        or st.session_state.get("cache_horizon") != horizon
    ):
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
            "Sales Plan (t)": st.column_config.Column(required=True, type="number"),
            "Local": st.column_config.Column(type="number"),
            "TPE": st.column_config.Column(type="number"),
            "China/Korea": st.column_config.Column(type="number"),
        },
    )

    st.divider()

    if st.button("🚀 Suggest Plan"):
        plan = compute_plan(
            df.copy(),
            fg_open,
            resin_open,
            resin_blended_open,
            fg_target_days,
            resin_target_days,
            prod_days,
            usage_ratio,
            use_streamlit=True,
        )

        st.subheader("Recommended Production & Purchase Plan")
        st.dataframe(
            plan.style.format(
                {
                    "Sales (t)": "{:.1f}",
                    "Production (t)": "{:.1f}",
                    "FG Close (t)": "{:.1f}",
                    "FG Days": "{:.1f}",
                    "Resin Close (t)": "{:.1f}",
                    "Resin Days": "{:.1f}",
                    "Purchase (t)": "{:.1f}",
                    "Unit Price (USD/t)": "{:.0f}",
                    "Blended $/t": "{:.0f}",
                }
            ),
            use_container_width=True,
        )

        csv = plan.to_csv(index=False).encode()
        st.download_button("Download CSV", csv, "resin_production_purchase_plan.csv", mime="text/csv")


def run_cli() -> None:
    """Fallback command line interface when Streamlit is unavailable."""

    parser = argparse.ArgumentParser(description="Resin purchase planner (CLI mode)")
    parser.add_argument("--horizon", type=int, default=6, help="Planning horizon in months")
    parser.add_argument("--fg-open", type=float, default=465.0, help="Opening FG inventory (t)")
    parser.add_argument("--resin-open", type=float, default=132.0, help="Opening resin inventory (t)")
    parser.add_argument(
        "--resin-price", type=float, default=694.0, help="Opening blended resin price (USD/t)"
    )
    parser.add_argument("--fg-days", type=int, default=15, help="FG safety stock (days)")
    parser.add_argument("--resin-days", type=int, default=5, help="Resin safety stock (days)")
    parser.add_argument("--prod-days", type=int, default=25, help="Production days per month")
    parser.add_argument(
        "--usage-ratio", type=float, default=0.725, help="Resin usage ratio (% of production)"
    )

    args = parser.parse_args()

    months = (
        pd.date_range(date.today().replace(day=1), periods=args.horizon, freq="MS")
        .strftime("%b-%Y")
        .tolist()
    )
    df = default_df(months)

    plan = compute_plan(
        df,
        args.fg_open,
        args.resin_open,
        args.resin_price,
        args.fg_days,
        args.resin_days,
        args.prod_days,
        args.usage_ratio,
    )

    print(plan.to_string(index=False))


if __name__ == "__main__":
    if st is not None:
        run_streamlit_app()
    else:
        run_cli()

