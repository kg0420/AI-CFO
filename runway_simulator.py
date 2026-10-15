"""
Runway Simulator & Financial Survival Forecaster for aiCFO.
Tailored for Everyday People, Households & Solopreneurs / Small Organizations.

Key Focus:
- Emergency Fund / Savings Runway (How many months can I/my family survive without a paycheck?)
- Monthly Inflow (Salary / Freelance / Business income)
- Essential Burn Rate (Rent, Groceries, EMIs, Utilities) vs Discretionary (Dining, Subscriptions)
- "What-If" Life Scenarios:
    * Job loss / income pause
    * Salary hike / new income stream
    * Trimming subscriptions & lifestyle expenses
    * Major planned expense (vacation, medical, gadget, down payment)
"""

from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import math
import os
import pandas as pd
import plotly.graph_objects as go
from typing import Optional, Dict, Any, List


def parse_expense_amount(expense: dict) -> float:
    """Extract numeric grand total from an expense record."""
    totals = expense.get("financial_totals", {})
    amt = totals.get("grand_total")
    if amt is None:
        lines = expense.get("line_items", [])
        amt = sum(
            float(item.get("total_item_amount") or item.get("price") or 0.0)
            for item in lines
        )
    try:
        val = float(amt or 0.0)
        return val if not math.isnan(val) else 0.0
    except (ValueError, TypeError):
        return 0.0


def parse_expense_date(expense: dict) -> Optional[datetime]:
    """Extract datetime from expense metadata."""
    meta = expense.get("document_metadata", {})
    merchant = expense.get("merchant_info", {})
    raw_date = meta.get("invoice_date") or merchant.get("date")
    if not raw_date:
        return None
    try:
        dt = pd.to_datetime(raw_date, errors="coerce")
        return dt.to_pydatetime() if pd.notnull(dt) else None
    except Exception:
        return None


def parse_expense_category(expense: dict) -> str:
    """Extract and normalize user-friendly expense category."""
    meta = expense.get("document_metadata", {})
    cat = (
        meta.get("expense_category")
        or expense.get("category")
        or "Living & Daily Needs"
    )
    return str(cat).strip().title()


def compute_baseline_metrics(expenses: List[dict]) -> Dict[str, Any]:
    """
    Analyze historical ledger to calculate monthly living costs and category allocations.
    """
    if not expenses:
        return {
            "total_spend": 0.0,
            "monthly_burn": 30000.0,  # sensible default monthly living expense baseline
            "months_analyzed": 1,
            "category_burn": {},
            "top_categories": [],
            "monthly_history": [],
            "has_data": False,
        }

    records = []
    for exp in expenses:
        amt = parse_expense_amount(exp)
        dt = parse_expense_date(exp)
        cat = parse_expense_category(exp)
        records.append({
            "amount": amt,
            "date": dt,
            "category": cat,
            "period": dt.strftime("%Y-%m") if dt else "Recent",
        })

    df = pd.DataFrame(records)
    total_spend = float(df["amount"].sum())

    valid_dates_df = df[df["date"].notnull()]

    if not valid_dates_df.empty:
        monthly_series = valid_dates_df.groupby("period")["amount"].sum()
        months_count = max(1, len(monthly_series))
        avg_monthly_burn = float(monthly_series.mean())
        monthly_history = [
            {"period": p, "amount": round(float(a), 2)}
            for p, a in monthly_series.sort_index().items()
        ]
    else:
        months_count = 1
        avg_monthly_burn = total_spend if total_spend > 0 else 30000.0
        monthly_history = []

    cat_series = df.groupby("category")["amount"].sum().sort_values(ascending=False)
    cat_burn = {c: round(float(a), 2) for c, a in cat_series.items()}
    top_categories = [
        {
            "category": c,
            "total": round(float(a), 2),
            "monthly_est": round(float(a) / months_count, 2),
            "share_pct": round((float(a) / total_spend * 100), 1) if total_spend > 0 else 0.0,
        }
        for c, a in cat_series.head(5).items()
    ]

    if avg_monthly_burn <= 0:
        avg_monthly_burn = 30000.0

    return {
        "total_spend": round(total_spend, 2),
        "monthly_burn": round(avg_monthly_burn, 2),
        "months_analyzed": months_count,
        "category_burn": cat_burn,
        "top_categories": top_categories,
        "monthly_history": monthly_history,
        "has_data": total_spend > 0,
    }


def simulate_runway(
    savings_balance: float,
    baseline_monthly_expenses: float,
    monthly_income: float = 0.0,
    income_change_pct: float = 0.0,
    expense_cut_pct: float = 0.0,
    extra_monthly_expense: float = 0.0,
    one_time_expense: float = 0.0,
    one_time_month: int = 1,
    horizon_months: int = 24,
) -> Dict[str, Any]:
    """
    Simulate month-by-month cash trajectory for Personal/Family Survival:
    - Baseline: Current savings with current average monthly expenses (e.g. if income stops).
    - Simulated: What-If scenario (adjusting income, trimming expenses, planned one-time expense).
    """
    savings_balance = max(0.0, float(savings_balance))
    baseline_monthly_expenses = max(100.0, float(baseline_monthly_expenses))
    monthly_income = max(0.0, float(monthly_income))
    income_change_pct = float(income_change_pct) / 100.0
    expense_cut_pct = max(0.0, min(95.0, float(expense_cut_pct))) / 100.0
    extra_monthly_expense = max(0.0, float(extra_monthly_expense))
    one_time_expense = max(0.0, float(one_time_expense))
    one_time_month = max(1, min(horizon_months, int(one_time_month)))
    horizon_months = max(6, min(48, int(horizon_months)))

    today = date.today()
    start_dt = date(today.year, today.month, 1)

    months_labels = []
    baseline_balances = []
    simulated_balances = []
    simulated_net_flows = []
    simulated_incomes = []
    simulated_expenses = []

    curr_baseline_cash = savings_balance
    curr_simulated_cash = savings_balance

    baseline_runway_months = None
    simulated_runway_months = None

    for m in range(1, horizon_months + 1):
        month_dt = start_dt + relativedelta(months=m - 1)
        label = month_dt.strftime("%b %Y")
        months_labels.append(label)

        # Baseline: expenses without income (worst-case safety net)
        curr_baseline_cash -= baseline_monthly_expenses
        baseline_balances.append(round(curr_baseline_cash, 2))
        if curr_baseline_cash <= 0 and baseline_runway_months is None:
            prev_cash = savings_balance if m == 1 else baseline_balances[-2]
            fraction = prev_cash / baseline_monthly_expenses if baseline_monthly_expenses > 0 else 0
            baseline_runway_months = round((m - 1) + max(0.0, min(1.0, fraction)), 1)

        # Simulated Scenario:
        # Effective Income with % change
        effective_income = monthly_income * (1.0 + income_change_pct)
        # Effective monthly expense
        effective_expense = (baseline_monthly_expenses * (1.0 - expense_cut_pct)) + extra_monthly_expense
        if m == one_time_month:
            effective_expense += one_time_expense

        monthly_net = effective_income - effective_expense
        curr_simulated_cash += monthly_net

        simulated_balances.append(round(curr_simulated_cash, 2))
        simulated_net_flows.append(round(monthly_net, 2))
        simulated_incomes.append(round(effective_income, 2))
        simulated_expenses.append(round(effective_expense, 2))

        if curr_simulated_cash <= 0 and simulated_runway_months is None:
            prev_sim_cash = savings_balance if m == 1 else simulated_balances[-2]
            abs_net = abs(monthly_net)
            fraction = prev_sim_cash / abs_net if abs_net > 0 else 0
            simulated_runway_months = round((m - 1) + max(0.0, min(1.0, fraction)), 1)

    if baseline_runway_months is None:
        baseline_runway_months = float("inf") if curr_baseline_cash > 0 else horizon_months

    is_self_sustaining = (
        simulated_net_flows[-1] >= 0 and curr_simulated_cash > 0
    )

    if simulated_runway_months is None:
        simulated_runway_months = float("inf") if is_self_sustaining else horizon_months

    def calculate_zero_date(runway_val):
        if math.isinf(runway_val) or runway_val > horizon_months:
            return "Savings Growing / Safe"
        whole_m = int(runway_val)
        target = start_dt + relativedelta(months=whole_m)
        return target.strftime("%B %Y")

    baseline_zero_date = calculate_zero_date(baseline_runway_months)
    simulated_zero_date = calculate_zero_date(simulated_runway_months)

    if math.isinf(simulated_runway_months) and not math.isinf(baseline_runway_months):
        runway_delta_str = "+∞ (Income Exceeds Expenses!)"
        runway_delta_val = 999.0
    elif math.isinf(simulated_runway_months) and math.isinf(baseline_runway_months):
        runway_delta_str = "Stable & Growing"
        runway_delta_val = 0.0
    elif math.isinf(baseline_runway_months) and not math.isinf(simulated_runway_months):
        runway_delta_str = "Deficit Introduced"
        runway_delta_val = -999.0
    else:
        diff = round(simulated_runway_months - baseline_runway_months, 1)
        runway_delta_val = diff
        sign = "+" if diff > 0 else ""
        runway_delta_str = f"{sign}{diff} Months"

    # Personal Financial Health Badge
    if math.isinf(simulated_runway_months) or is_self_sustaining:
        status_badge = {"label": "FINANCIALLY SAFE (GROWING)", "class": "badge-success", "color": "#2E7D32"}
    elif simulated_runway_months >= 12:
        status_badge = {"label": "EXCELLENT (1+ YEAR EMERGENCY FUND)", "class": "badge-healthy", "color": "#20402F"}
    elif simulated_runway_months >= 6:
        status_badge = {"label": "GOOD (6+ MONTHS BUFFER)", "class": "badge-good", "color": "#2E7D32"}
    elif simulated_runway_months >= 3:
        status_badge = {"label": "TIGHT (3-6 MONTHS BUFFER)", "class": "badge-warning", "color": "#A9822F"}
    else:
        status_badge = {"label": "CRITICAL (< 3 MONTHS BUFFER)", "class": "badge-danger", "color": "#A5382B"}

    # ========================================================
    # PLOTLY CHARTS
    # ========================================================
    fig_trajectory = go.Figure()

    fig_trajectory.add_hline(
        y=0,
        line_dash="dash",
        line_color="#A5382B",
        annotation_text="₹0 (Savings Depleted)",
        annotation_position="bottom right",
        annotation_font_color="#A5382B",
        annotation_font_size=11,
    )

    fig_trajectory.add_trace(go.Scatter(
        x=months_labels,
        y=baseline_balances,
        mode="lines+markers",
        name="Zero-Income Baseline (Emergency Only)",
        line=dict(color="#C17569", width=2, dash="dot"),
        marker=dict(size=4),
        hovertemplate="<b>Zero-Income Baseline</b><br>%{x}: ₹%{y:,.0f}<extra></extra>",
    ))

    fig_trajectory.add_trace(go.Scatter(
        x=months_labels,
        y=simulated_balances,
        mode="lines+markers",
        name="Simulated Savings Balance",
        line=dict(color="#20402F", width=3.5),
        marker=dict(size=6, color="#A9822F"),
        fill="tozeroy",
        fillcolor="rgba(32, 64, 47, 0.08)",
        hovertemplate="<b>Simulated Savings</b><br>%{x}: ₹%{y:,.0f}<extra></extra>",
    ))

    fig_trajectory.update_layout(
        title="Your Savings Lifeline & Projected Bank Balance",
        xaxis_title="Timeline",
        yaxis_title="Projected Bank / Savings Balance (₹)",
        hovermode="x unified",
        margin=dict(t=50, b=20, l=20, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="#FBFAF2",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Work Sans, sans-serif", color="#20301F"),
    )

    # Cashflow Bar Chart
    fig_cashflow = go.Figure()
    bar_colors = ["#2E7D32" if val >= 0 else "#A5382B" for val in simulated_net_flows]

    fig_cashflow.add_trace(go.Bar(
        x=months_labels,
        y=simulated_net_flows,
        name="Monthly Savings / Deficit",
        marker_color=bar_colors,
        hovertemplate="<b>Monthly Net</b><br>%{x}: ₹%{y:,.0f}<extra></extra>",
    ))

    fig_cashflow.add_trace(go.Scatter(
        x=months_labels,
        y=simulated_incomes,
        mode="lines",
        name="Monthly Income",
        line=dict(color="#00CC96", width=2),
    ))

    fig_cashflow.add_trace(go.Scatter(
        x=months_labels,
        y=simulated_expenses,
        mode="lines",
        name="Monthly Expenses",
        line=dict(color="#EF553B", width=2, dash="dash"),
    ))

    fig_cashflow.update_layout(
        title="Monthly Inflow vs Expenses & Savings Capacity",
        xaxis_title="Timeline",
        yaxis_title="Monthly Amount (₹)",
        margin=dict(t=50, b=20, l=20, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="#FBFAF2",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Work Sans, sans-serif", color="#20301F"),
    )

    return {
        "inputs": {
            "savings_balance": savings_balance,
            "baseline_monthly_expenses": baseline_monthly_expenses,
            "monthly_income": monthly_income,
            "income_change_pct": income_change_pct * 100,
            "expense_cut_pct": expense_cut_pct * 100,
            "extra_monthly_expense": extra_monthly_expense,
            "one_time_expense": one_time_expense,
            "one_time_month": one_time_month,
            "horizon_months": horizon_months,
        },
        "results": {
            "baseline_runway_months": "∞" if math.isinf(baseline_runway_months) else f"{baseline_runway_months} mo",
            "simulated_runway_months": "Growing (Safe)" if math.isinf(simulated_runway_months) else f"{simulated_runway_months} mo",
            "baseline_runway_raw": baseline_runway_months,
            "simulated_runway_raw": simulated_runway_months,
            "runway_delta_str": runway_delta_str,
            "runway_delta_val": runway_delta_val,
            "baseline_zero_date": baseline_zero_date,
            "simulated_zero_date": simulated_zero_date,
            "is_self_sustaining": is_self_sustaining,
            "status_badge": status_badge,
            "final_cash_balance": simulated_balances[-1],
        },
        "charts": {
            "trajectory_html": fig_trajectory.to_html(full_html=False, include_plotlyjs="cdn"),
            "cashflow_html": fig_cashflow.to_html(full_html=False, include_plotlyjs=False),
        },
    }


def generate_cfo_strategic_advisory(
    baseline: Dict[str, Any],
    simulation: Dict[str, Any],
    gemini_client=None,
) -> str:
    """
    Generate personal/household financial guidance and actionable money-saving advice.
    """
    inputs = simulation.get("inputs", {})
    results = simulation.get("results", {})
    top_cats = baseline.get("top_categories", [])

    cat_summary = ", ".join(
        f"{c['category']} (₹{c['total']:,.0f}, {c['share_pct']}%)" for c in top_cats[:3]
    ) or "General Expenses"

    prompt = f"""
You are a friendly yet prudent Personal AI Financial Advisor & Household CFO.
You are helping an individual / family understand their financial survival runway and savings safety net.

Financial Data:
- Bank Savings & Emergency Fund: ₹{inputs.get('savings_balance', 0):,.2f}
- Average Monthly Living Expenses: ₹{inputs.get('baseline_monthly_expenses', 0):,.2f}
- Monthly Inflow (Salary / Freelance / Business): ₹{inputs.get('monthly_income', 0):,.2f}
- Expected Income Change: {inputs.get('income_change_pct', 0)}%
- Target Expense Cut: {inputs.get('expense_cut_pct', 0)}%
- Simulated Runway: {results.get('simulated_runway_months')} (Depletion Date: {results.get('simulated_zero_date')})
- Top Expense Categories: {cat_summary}

Formatting Rules:
1. Respond in clean, valid HTML (do NOT use Markdown asterisks or hash symbols).
2. Keep the tone encouraging, empathetic, realistic, and practical for an everyday person or household.
3. Structure your response into:
   - <h3>Household Financial Health Check</h3> (<p>)
   - <h3>3 Practical Ways to Stretch Your Savings</h3> (<ul> with <li> detailing concrete steps based on their categories)
   - <h3>Next Safety Milestone</h3> (<p> highlighting the recommended 6-month emergency buffer amount)
"""

    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            if response and response.text:
                return response.text
        except Exception as exc:
            print(f"⚠️ Gemini advisory call failed: {exc}")

    # Fallback advisory
    runway_val = results.get("simulated_runway_raw")
    zero_date = results.get("simulated_zero_date")
    top_cat_1 = top_cats[0]["category"] if len(top_cats) > 0 else "Daily Discretionary Spend"
    top_cat_2 = top_cats[1]["category"] if len(top_cats) > 1 else "Subscriptions & Shopping"
    monthly_exp = inputs.get("baseline_monthly_expenses", 30000)
    target_6mo = monthly_exp * 6

    if results.get("is_self_sustaining"):
        summary_text = (
            "Great news! Your monthly income exceeds your modeled spending, meaning your savings are "
            "<b>actively growing every month</b> rather than depleting."
        )
    else:
        summary_text = (
            f"Based on your current spending, your emergency fund provides <b>{results.get('simulated_runway_months')}</b> "
            f"of financial runway (estimated zero-cash date: <b>{zero_date}</b>). Stretching this buffer protects you from unexpected life events."
        )

    return f"""
    <h3>Household Financial Health Check</h3>
    <p>{summary_text} The golden rule of personal finance is maintaining at least <b>6 months of essential living expenses</b> in an accessible liquid account.</p>

    <h3>3 Practical Ways to Stretch Your Savings</h3>
    <ul>
        <li><b>Trim {top_cat_1}:</b> This is currently your highest expense area. Reducing non-essential purchases here by even 10–15% can add weeks of financial buffer.</li>
        <li><b>Audit {top_cat_2}:</b> Cancel recurring digital subscriptions, gym memberships, or dining out habits that you haven't actively used in the last 30 days.</li>
        <li><b>Automate Savings First:</b> Move 10–20% of your incoming income to a separate high-interest savings or liquid fund on the day it arrives before discretionary spending begins.</li>
    </ul>

    <h3>Next Safety Milestone</h3>
    <p>Aim to build a 6-month safety net of <b>₹{target_6mo:,.0f}</b>. Once reached, you'll have complete peace of mind against sudden job changes or emergencies.</p>
    """
