import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np

def generate_graphs(expenses_list: list) -> dict:
    """Generates multiple interactive Plotly visualizations for the CFO dashboard."""
    empty_msg = "<p class='text-muted text-center py-10' style='padding:30px 0; color:#8B9682; text-align:center;'>No data available to display this graph.</p>"
    
    graph_keys = [
        "graph_donut",
        "graph_vendor",
        "graph_timeline",
        "graph_cumulative",
        "graph_tax",
        "graph_gst",
        "graph_payment_status",
        "graph_payment_method",
        "graph_treemap",
        "graph_line_items",
        "graph_source"
    ]
    
    if not expenses_list:
        return {k: empty_msg for k in graph_keys}
    
    df = pd.json_normalize(expenses_list)
    
    # Safely ensure all required columns exist to prevent crashes
    required_cols = {
        'document_metadata.expense_category': 'Uncategorized',
        'document_metadata.invoice_date': None,
        'document_metadata.payment_mode': None,
        'seller_details.vendor_name': None,
        'seller_details.platform_or_marketplace': None,
        'financial_totals.grand_total': 0.0,
        'financial_totals.taxable_amount_subtotal': 0.0,
        'financial_totals.total_tax_amount': 0.0,
        'financial_totals.amount_paid': 0.0,
        'financial_totals.balance_due': 0.0,
        'tax_breakdown.cgst_amount': 0.0,
        'tax_breakdown.sgst_amount': 0.0,
        'tax_breakdown.igst_amount': 0.0,
        'tax_breakdown.tax_cess_amount': 0.0,
        'tax_breakdown.vat_amount': 0.0,
        'payment_details.payment_method': None,
        'data_source': 'manual_entry'
    }
    
    for col, default_val in required_cols.items():
        if col not in df.columns:
            df[col] = default_val

    # Clean numerics
    numeric_cols = [
        'financial_totals.grand_total',
        'financial_totals.taxable_amount_subtotal',
        'financial_totals.total_tax_amount',
        'financial_totals.amount_paid',
        'financial_totals.balance_due',
        'tax_breakdown.cgst_amount',
        'tax_breakdown.sgst_amount',
        'tax_breakdown.igst_amount',
        'tax_breakdown.tax_cess_amount',
        'tax_breakdown.vat_amount'
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    # Resolved Vendor Name (prefers vendor_name, then platform_or_marketplace)
    def resolve_vendor(row):
        v = row.get('seller_details.vendor_name')
        if pd.notna(v) and str(v).strip() and str(v).strip().lower() != 'null':
            return str(v).strip()
        p = row.get('seller_details.platform_or_marketplace')
        if pd.notna(p) and str(p).strip() and str(p).strip().lower() != 'null':
            return str(p).strip()
        return 'Unknown Vendor'

    df['resolved_vendor'] = df.apply(resolve_vendor, axis=1)

    # Common CFO layout styling helper
    # Does not render redundant internal titles so the card exhibit title and chart don't collide.
    def apply_cfo_theme(fig):
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Work Sans, sans-serif", color="#20301F", size=11),
            margin=dict(t=20, b=35, l=35, r=25),
        )
        return fig

    fig_config = {'responsive': True, 'displayModeBar': False}

    # 1. Donut Chart (Category Breakdown)
    cat_df = df.groupby('document_metadata.expense_category')['financial_totals.grand_total'].sum().reset_index()
    cat_df = cat_df.sort_values(by='financial_totals.grand_total', ascending=False)
    fig_donut = px.pie(
        cat_df, values='financial_totals.grand_total', names='document_metadata.expense_category',
        hole=0.48, color_discrete_sequence=px.colors.qualitative.Pastel
    )
    apply_cfo_theme(fig_donut)
    fig_donut.update_traces(
        textposition='inside',
        textinfo='percent',
        hovertemplate="<b>%{label}</b><br>Spend: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
        marker=dict(line=dict(color='#FBFAF2', width=1.5))
    )
    fig_donut.update_layout(
        uniformtext_minsize=10,
        uniformtext_mode='hide',
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.06,
            xanchor="center",
            x=0.5,
            font=dict(size=10.5)
        ),
        margin=dict(t=15, b=45, l=15, r=15)
    )

    # 2. Bar Chart (Top Vendors - Horizontal to eliminate long vendor name overlap)
    ven_df = df.groupby('resolved_vendor')['financial_totals.grand_total'].sum().reset_index()
    ven_df = ven_df.sort_values(by='financial_totals.grand_total', ascending=True).tail(8)
    ven_df['short_name'] = ven_df['resolved_vendor'].apply(lambda x: x[:20] + '…' if len(x) > 22 else x)
    max_v = float(ven_df['financial_totals.grand_total'].max()) if not ven_df.empty else 1.0

    fig_vendor = px.bar(
        ven_df, x='financial_totals.grand_total', y='short_name',
        orientation='h', color_discrete_sequence=['#20402F'],
        custom_data=['resolved_vendor']
    )
    apply_cfo_theme(fig_vendor)
    fig_vendor.update_traces(
        texttemplate='₹%{x:,.0f}',
        textposition='outside',
        cliponaxis=False,
        hovertemplate='<b>%{customdata[0]}</b><br>Total Spend: ₹%{x:,.2f}<extra></extra>'
    )
    fig_vendor.update_layout(
        xaxis=dict(title='Spend (₹)', range=[0, max_v * 1.25], tickfont=dict(size=10)),
        yaxis=dict(title='', tickfont=dict(size=10.5)),
        margin=dict(l=145, r=45, t=20, b=40)
    )

    # 3. Line Chart (Timeline) & 4. Cumulative Area (Burn Rate)
    df['document_metadata.invoice_date'] = pd.to_datetime(df['document_metadata.invoice_date'], errors='coerce')
    time_df = df.dropna(subset=['document_metadata.invoice_date'])
    if not time_df.empty:
        time_df = time_df.groupby('document_metadata.invoice_date')['financial_totals.grand_total'].sum().reset_index()
        time_df = time_df.sort_values('document_metadata.invoice_date')
        
        # Cash Flow Timeline
        fig_timeline = px.line(
            time_df, x='document_metadata.invoice_date', y='financial_totals.grand_total',
            markers=True, color_discrete_sequence=['#00CC96']
        )
        apply_cfo_theme(fig_timeline)
        fig_timeline.update_traces(
            line_width=2.5,
            marker=dict(size=7),
            hovertemplate="<b>%{x|%b %d, %Y}</b><br>Daily Spend: ₹%{y:,.2f}<extra></extra>"
        )
        fig_timeline.update_layout(
            xaxis=dict(title="Invoice Date", tickangle=-20, tickformat="%b %d, %Y", tickfont=dict(size=10)),
            yaxis=dict(title="Amount (₹)", tickfont=dict(size=10)),
            margin=dict(t=25, b=50, l=60, r=30)
        )
        html_timeline = fig_timeline.to_html(full_html=False, include_plotlyjs=False, config=fig_config)

        # Cumulative Burn Rate
        time_df['cumulative_total'] = time_df['financial_totals.grand_total'].cumsum()
        fig_cum = px.area(
            time_df, x='document_metadata.invoice_date', y='cumulative_total',
            color_discrete_sequence=['#A9822F']
        )
        apply_cfo_theme(fig_cum)
        fig_cum.update_traces(
            line_width=2,
            hovertemplate="<b>%{x|%b %d, %Y}</b><br>Cumulative Spend: ₹%{y:,.2f}<extra></extra>"
        )
        fig_cum.update_layout(
            xaxis=dict(title="Invoice Date", tickangle=-20, tickformat="%b %d, %Y", tickfont=dict(size=10)),
            yaxis=dict(title="Cumulative Total (₹)", tickfont=dict(size=10)),
            margin=dict(t=25, b=50, l=65, r=30)
        )
        html_cumulative = fig_cum.to_html(full_html=False, include_plotlyjs=False, config=fig_config)
    else:
        html_timeline = "<p class='text-slate-500 text-center py-10' style='padding:30px 0; color:#8B9682; text-align:center;'>No valid dates found in ledger to plot timeline.</p>"
        html_cumulative = "<p class='text-slate-500 text-center py-10' style='padding:30px 0; color:#8B9682; text-align:center;'>No valid dates found to calculate cumulative burn rate.</p>"

    # 5. Stacked Bar (Tax vs Base)
    tax_df = df.groupby('resolved_vendor')[['financial_totals.taxable_amount_subtotal', 'financial_totals.total_tax_amount']].sum().reset_index()
    tax_df['total_val'] = tax_df['financial_totals.taxable_amount_subtotal'] + tax_df['financial_totals.total_tax_amount']
    tax_df = tax_df.sort_values(by='total_val', ascending=False).head(7)
    tax_df['short_name'] = tax_df['resolved_vendor'].apply(lambda x: x[:14] + '…' if len(x) > 16 else x)

    fig_tax = go.Figure(data=[
        go.Bar(
            name='Base Amount',
            x=tax_df['short_name'],
            y=tax_df['financial_totals.taxable_amount_subtotal'],
            customdata=tax_df['resolved_vendor'],
            marker_color='#20402F',
            hovertemplate="<b>%{customdata}</b><br>Base Amount: ₹%{y:,.2f}<extra></extra>"
        ),
        go.Bar(
            name='Tax Paid',
            x=tax_df['short_name'],
            y=tax_df['financial_totals.total_tax_amount'],
            customdata=tax_df['resolved_vendor'],
            marker_color='#A5382B',
            hovertemplate="<b>%{customdata}</b><br>Tax Paid: ₹%{y:,.2f}<extra></extra>"
        )
    ])
    apply_cfo_theme(fig_tax)
    fig_tax.update_layout(
        barmode='stack',
        xaxis=dict(title="", tickangle=-25, tickfont=dict(size=10)),
        yaxis=dict(title="Amount (₹)", tickfont=dict(size=10)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
        margin=dict(t=35, b=65, l=55, r=20)
    )

    # 6. GST Tax Breakdown
    gst_sums = {
        'CGST (Central)': df['tax_breakdown.cgst_amount'].sum(),
        'SGST (State)': df['tax_breakdown.sgst_amount'].sum(),
        'IGST (Integrated)': df['tax_breakdown.igst_amount'].sum(),
        'Cess': df['tax_breakdown.tax_cess_amount'].sum(),
        'VAT': df['tax_breakdown.vat_amount'].sum()
    }
    gst_items = [{"Tax Type": k, "Amount": float(v)} for k, v in gst_sums.items() if float(v) > 0]
    if gst_items and sum(item["Amount"] for item in gst_items) > 0:
        gst_df = pd.DataFrame(gst_items)
        max_gst = float(gst_df['Amount'].max())
        fig_gst = px.bar(
            gst_df, x='Tax Type', y='Amount',
            color='Tax Type', color_discrete_sequence=['#20402F', '#5F7A5A', '#A9822F', '#A5382B', '#7A8B71']
        )
        apply_cfo_theme(fig_gst)
        fig_gst.update_traces(
            texttemplate='₹%{y:,.0f}',
            textposition='outside',
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>Tax Amount: ₹%{y:,.2f}<extra></extra>"
        )
        fig_gst.update_layout(
            showlegend=False,
            xaxis=dict(title="", tickfont=dict(size=10.5)),
            yaxis=dict(title="Tax Amount (₹)", range=[0, max_gst * 1.25], tickfont=dict(size=10)),
            margin=dict(t=25, b=40, l=55, r=20)
        )
        html_gst = fig_gst.to_html(full_html=False, include_plotlyjs=False, config=fig_config)
    else:
        html_gst = "<p class='text-muted text-center py-10' style='padding:30px 0; color:#8B9682; text-align:center;'>No itemized tax/GST components detected.</p>"

    # 7. Payment Status (Accounts Payable: Paid vs Outstanding)
    paid = float(df['financial_totals.amount_paid'].sum())
    due = float(df['financial_totals.balance_due'].sum())
    if paid == 0 and due == 0:
        paid = float(df['financial_totals.grand_total'].sum())
    status_df = pd.DataFrame([
        {"Status": "Amount Settled (Paid)", "Amount": paid},
        {"Status": "Outstanding (Due)", "Amount": due}
    ])
    fig_status = px.pie(
        status_df, names="Status", values="Amount", hole=0.5,
        color="Status", color_discrete_map={"Amount Settled (Paid)": "#20402F", "Outstanding (Due)": "#A5382B"}
    )
    apply_cfo_theme(fig_status)
    fig_status.update_traces(
        textposition='inside',
        textinfo='percent',
        hovertemplate="<b>%{label}</b><br>Amount: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
        marker=dict(line=dict(color='#FBFAF2', width=1.5))
    )
    fig_status.update_layout(
        uniformtext_minsize=10,
        uniformtext_mode='hide',
        legend=dict(orientation="h", yanchor="top", y=-0.06, xanchor="center", x=0.5, font=dict(size=10.5)),
        margin=dict(t=15, b=45, l=15, r=15)
    )
    html_payment_status = fig_status.to_html(full_html=False, include_plotlyjs=False, config=fig_config)

    # 8. Payment Method / Mode Distribution
    def resolve_pay_method(row):
        m = row.get('payment_details.payment_method')
        if pd.notna(m) and str(m).strip() and str(m).strip().lower() != 'null':
            val = str(m).strip()
            return 'UPI' if val.lower() == 'pi' else val
        m2 = row.get('document_metadata.payment_mode')
        if pd.notna(m2) and str(m2).strip() and str(m2).strip().lower() != 'null':
            val = str(m2).strip()
            return 'UPI' if val.lower() == 'pi' else val
        return 'Not Specified'

    df['resolved_pay_method'] = df.apply(resolve_pay_method, axis=1)
    pay_df = df.groupby('resolved_pay_method')['financial_totals.grand_total'].sum().reset_index()
    fig_pay = px.pie(
        pay_df, names="resolved_pay_method", values="financial_totals.grand_total", hole=0.48,
        color_discrete_sequence=px.colors.qualitative.Antique
    )
    apply_cfo_theme(fig_pay)
    fig_pay.update_traces(
        textposition='inside',
        textinfo='percent',
        hovertemplate="<b>%{label}</b><br>Spend: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
        marker=dict(line=dict(color='#FBFAF2', width=1.5))
    )
    fig_pay.update_layout(
        uniformtext_minsize=10,
        uniformtext_mode='hide',
        legend=dict(orientation="h", yanchor="top", y=-0.06, xanchor="center", x=0.5, font=dict(size=10.5)),
        margin=dict(t=15, b=45, l=15, r=15)
    )
    html_payment_method = fig_pay.to_html(full_html=False, include_plotlyjs=False, config=fig_config)

    # 9. Treemap (Hierarchy)
    tree_df = df.fillna({'document_metadata.expense_category': 'Unknown Category'})
    tree_df['short_vendor'] = tree_df['resolved_vendor'].apply(lambda x: x[:18] + '…' if len(x) > 20 else x)
    fig_tree = px.treemap(
        tree_df, path=[px.Constant("All Spend"), 'document_metadata.expense_category', 'short_vendor'], 
        values='financial_totals.grand_total', color_discrete_sequence=px.colors.qualitative.Pastel
    )
    apply_cfo_theme(fig_tree)
    fig_tree.update_traces(
        root_color="#E4E2D2",
        texttemplate="<b>%{label}</b><br>₹%{value:,.0f}",
        hovertemplate="<b>%{label}</b><br>Spend: ₹%{value:,.2f}<extra></extra>"
    )
    fig_tree.update_layout(
        uniformtext=dict(minsize=9, mode='hide'),
        margin=dict(t=15, b=15, l=15, r=15)
    )

    # 10. Top Line Items / Products (Horizontal)
    item_records = []
    for exp in expenses_list:
        items = exp.get("line_items") or []
        for item in items:
            desc = item.get("description") or item.get("item_id_or_sku")
            if not desc or str(desc).strip().lower() == "null":
                continue
            price = item.get("total_price") or item.get("taxable_value")
            if price is None:
                q = item.get("quantity") or 1
                u = item.get("unit_price") or 0
                price = q * u
            try:
                price = float(price)
            except (ValueError, TypeError):
                price = 0.0
            if price > 0:
                item_records.append({"item": str(desc), "price": price})

    if item_records:
        items_df = pd.DataFrame(item_records)
        items_agg = items_df.groupby("item")["price"].sum().reset_index()
        items_agg = items_agg.sort_values(by="price", ascending=True).tail(7)
        items_agg['short_desc'] = items_agg['item'].apply(lambda x: x[:22] + '…' if len(x) > 24 else x)
        max_p = float(items_agg['price'].max())
        
        fig_items = px.bar(
            items_agg, x="price", y="short_desc", orientation='h',
            color_discrete_sequence=['#5F7A5A'],
            custom_data=['item']
        )
        apply_cfo_theme(fig_items)
        fig_items.update_traces(
            texttemplate='₹%{x:,.0f}',
            textposition='outside',
            cliponaxis=False,
            hovertemplate="<b>%{customdata[0]}</b><br>Total Cost: ₹%{x:,.2f}<extra></extra>"
        )
        fig_items.update_layout(
            xaxis=dict(title="Total Spend (₹)", range=[0, max_p * 1.25], tickfont=dict(size=10)),
            yaxis=dict(title="", tickfont=dict(size=10.5)),
            margin=dict(t=20, b=40, l=150, r=45)
        )
        html_line_items = fig_items.to_html(full_html=False, include_plotlyjs=False, config=fig_config)
    else:
        html_line_items = "<p class='text-muted text-center py-10' style='padding:30px 0; color:#8B9682; text-align:center;'>No granular line items recorded.</p>"

    # 11. Source Pie (AI vs Manual)
    source_df = df.groupby('data_source')['financial_totals.grand_total'].sum().reset_index()
    fig_source = px.pie(
        source_df, names='data_source', values='financial_totals.grand_total', hole=0.48,
        color_discrete_sequence=['#20402F', '#A9822F']
    )
    apply_cfo_theme(fig_source)
    fig_source.update_traces(
        textposition='inside',
        textinfo='percent',
        hovertemplate="<b>%{label}</b><br>Amount: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
        marker=dict(line=dict(color='#FBFAF2', width=1.5))
    )
    fig_source.update_layout(
        uniformtext_minsize=10,
        uniformtext_mode='hide',
        legend=dict(orientation="h", yanchor="top", y=-0.06, xanchor="center", x=0.5, font=dict(size=10.5)),
        margin=dict(t=15, b=45, l=15, r=15)
    )

    return {
        "graph_donut": fig_donut.to_html(full_html=False, include_plotlyjs='cdn', config=fig_config),
        "graph_vendor": fig_vendor.to_html(full_html=False, include_plotlyjs=False, config=fig_config),
        "graph_timeline": html_timeline,
        "graph_cumulative": html_cumulative,
        "graph_tax": fig_tax.to_html(full_html=False, include_plotlyjs=False, config=fig_config),
        "graph_gst": html_gst,
        "graph_payment_status": html_payment_status,
        "graph_payment_method": html_payment_method,
        "graph_treemap": fig_tree.to_html(full_html=False, include_plotlyjs=False, config=fig_config),
        "graph_line_items": html_line_items,
        "graph_source": fig_source.to_html(full_html=False, include_plotlyjs=False, config=fig_config)
    }
