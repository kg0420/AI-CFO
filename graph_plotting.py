import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

def generate_graphs(expenses_list: list) -> dict:
    """Generates multiple interactive Plotly visualizations."""
    empty_msg = "<p class='text-muted text-center py-10'>No data available to display this graph.</p>"
    
    # 🔴 FIX: Ensure the empty state returns the EXACT new keys 
    if not expenses_list:
        return {
            "graph_donut": empty_msg, 
            "graph_vendor": empty_msg, 
            "graph_timeline": empty_msg, 
            "graph_tax": empty_msg, 
            "graph_treemap": empty_msg, 
            "graph_source": empty_msg
        }
    
    df = pd.json_normalize(expenses_list)
    
    # Safely ensure all required columns exist to prevent crashes
    required_cols = {
        'document_metadata.expense_category': 'Uncategorized',
        'seller_details.platform_or_marketplace': 'Unknown Vendor',
        'financial_totals.grand_total': 0.0,
        'financial_totals.taxable_amount_subtotal': 0.0,
        'financial_totals.total_tax_amount': 0.0,
        'document_metadata.invoice_date': None,
        'data_source': 'manual_entry'
    }
    
    for col, default_val in required_cols.items():
        if col not in df.columns:
            df[col] = default_val

    # Clean numerics and dates
    numeric_cols = ['financial_totals.grand_total', 'financial_totals.taxable_amount_subtotal', 'financial_totals.total_tax_amount']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        
    df['document_metadata.invoice_date'] = pd.to_datetime(df['document_metadata.invoice_date'], errors='coerce')

    # 1. Donut Chart (Category)
    cat_df = df.groupby('document_metadata.expense_category')['financial_totals.grand_total'].sum().reset_index()
    fig_donut = px.pie(cat_df, values='financial_totals.grand_total', names='document_metadata.expense_category',
                       title='Expense Breakdown by Category', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
    fig_donut.update_layout(margin=dict(t=40, b=10, l=10, r=10))

    # 2. Bar Chart (Top Vendors)
    ven_df = df.groupby('seller_details.platform_or_marketplace')['financial_totals.grand_total'].sum().reset_index()
    ven_df = ven_df.sort_values(by='financial_totals.grand_total', ascending=False)
    fig_vendor = px.bar(ven_df, x='seller_details.platform_or_marketplace', y='financial_totals.grand_total',
                        title='Total Spend by Vendor', text_auto='.2s')
    fig_vendor.update_traces(marker_color='#636EFA')
    fig_vendor.update_layout(margin=dict(t=40, b=10, l=10, r=10), xaxis_title="", yaxis_title="Spent (₹)")

    # 3. Line Chart (Timeline)
    time_df = df.dropna(subset=['document_metadata.invoice_date'])
    if not time_df.empty:
        time_df = time_df.groupby('document_metadata.invoice_date')['financial_totals.grand_total'].sum().reset_index()
        time_df = time_df.sort_values('document_metadata.invoice_date')
        fig_timeline = px.line(time_df, x='document_metadata.invoice_date', y='financial_totals.grand_total',
                               title='Cash Flow Timeline', markers=True)
        fig_timeline.update_traces(line_color='#00CC96', line_width=3, marker=dict(size=8))
        fig_timeline.update_layout(margin=dict(t=40, b=10, l=10, r=10), xaxis_title="Date", yaxis_title="Amount (₹)")
        html_timeline = fig_timeline.to_html(full_html=False, include_plotlyjs=False)
    else:
        html_timeline = "<p class='text-slate-500 text-center py-10'>No valid dates found in ledger to plot timeline.</p>"

    # 4. Stacked Bar (Tax vs Base)
    tax_df = df.groupby('seller_details.platform_or_marketplace')[['financial_totals.taxable_amount_subtotal', 'financial_totals.total_tax_amount']].sum().reset_index()
    fig_tax = go.Figure(data=[
        go.Bar(name='Base Amount', x=tax_df['seller_details.platform_or_marketplace'], y=tax_df['financial_totals.taxable_amount_subtotal'], marker_color='#AB63FA'),
        go.Bar(name='Tax Paid', x=tax_df['seller_details.platform_or_marketplace'], y=tax_df['financial_totals.total_tax_amount'], marker_color='#EF553B')
    ])
    fig_tax.update_layout(title='Tax vs. Base Amount', barmode='stack', margin=dict(t=40, b=10, l=10, r=10))

    # 5. Treemap (Hierarchy)
    tree_df = df.fillna({'document_metadata.expense_category': 'Unknown Category', 'seller_details.platform_or_marketplace': 'Unknown Vendor'})
    fig_tree = px.treemap(tree_df, path=[px.Constant("All Spend"), 'document_metadata.expense_category', 'seller_details.platform_or_marketplace'], 
                          values='financial_totals.grand_total', title='Spend Hierarchy')
    fig_tree.update_traces(root_color="lightgrey")
    fig_tree.update_layout(margin=dict(t=40, b=10, l=10, r=10))

    # 6. Source Pie (AI vs Manual)
    source_df = df.groupby('data_source')['financial_totals.grand_total'].sum().reset_index()
    fig_source = px.pie(source_df, names='data_source', values='financial_totals.grand_total', title='Data Source (AI vs Manual)', hole=0.4)
    fig_source.update_layout(margin=dict(t=40, b=10, l=10, r=10))

    # 🔴 FIX: Ensure the populated state returns the EXACT new keys
    return {
        "graph_donut": fig_donut.to_html(full_html=False, include_plotlyjs='cdn'),
        "graph_vendor": fig_vendor.to_html(full_html=False, include_plotlyjs=False),
        "graph_timeline": html_timeline,
        "graph_tax": fig_tax.to_html(full_html=False, include_plotlyjs=False),
        "graph_treemap": fig_tree.to_html(full_html=False, include_plotlyjs=False),
        "graph_source": fig_source.to_html(full_html=False, include_plotlyjs=False)
    }
