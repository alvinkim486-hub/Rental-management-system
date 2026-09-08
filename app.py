import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('property.db')
    c = conn.cursor()

    # Create Units Table (Now with deposit_held)
    c.execute('''
        CREATE TABLE IF NOT EXISTS units (
            id INTEGER PRIMARY KEY,
            unit_name TEXT,
            status TEXT,
            tenant_name TEXT,
            rent_amount REAL,
            deposit_held REAL DEFAULT 0.0
        )
    ''')

    # Create Payments Table (Now with payment_type)
    c.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_name TEXT,
            payment_type TEXT,
            amount REAL,
            date TEXT,
            mpesa_receipt TEXT
        )
    ''')

    # Initialize your specific 12 units
    custom_units = ['11', '12', '13', '14', '21', '22', '23', '24', '31', '32', '33', '34']

    c.execute('SELECT COUNT(*) FROM units')
    if c.fetchone()[0] == 0:
        for u in custom_units:
            c.execute('INSERT INTO units (unit_name, status, tenant_name, rent_amount, deposit_held) VALUES (?, ?, ?, ?, ?)',
                      (u, 'Vacant', 'None', 15000.0, 0.0))
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    return sqlite3.connect('property.db')

# --- STREAMLIT USER INTERFACE ---
st.set_page_config(page_title="Rental Dashboard", layout="wide")

st.sidebar.title("Landlord Controls")
page = st.sidebar.radio("Navigation", ["Dashboard Overview", "Manage Units", "Log Payment"])

if page == "Dashboard Overview":
    st.title("Financial & Occupancy Dashboard")

    conn = get_db_connection()
    units_df = pd.read_sql_query("SELECT * FROM units", conn)
    # Only calculate rent income for the dashboard, exclude deposits
    payments_df = pd.read_sql_query("SELECT * FROM payments", conn)
    rent_payments = pd.read_sql_query("SELECT * FROM payments WHERE payment_type LIKE '%Rent%'", conn)
    conn.close()

    # Dynamic Calculations
    total_expected = units_df['rent_amount'].sum()
    total_rent_collected = rent_payments['amount'].sum() if not rent_payments.empty else 0
    total_deposits_held = units_df['deposit_held'].sum()
    occupied_units = len(units_df[units_df['status'].str.contains('Occupied')])

    # Top Metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Rent Logged", f"KSh {total_rent_collected:,.2f}")
    col2.metric("Total Deposits Held", f"KSh {total_deposits_held:,.2f}")
    col3.metric("Expected Monthly Rent", f"KSh {total_expected:,.2f}")
    col4.metric("Occupancy", f"{occupied_units}/12 Units")

    st.divider()

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Unit Status & Balances")
        # Display unit statuses along with their custom rent and held deposits
        st.dataframe(units_df[['unit_name', 'tenant_name', 'status', 'rent_amount', 'deposit_held']], use_container_width=True)

    with col_right:
        st.subheader("Recent Transactions")
        if not payments_df.empty:
            st.dataframe(payments_df[['date', 'unit_name', 'payment_type', 'amount', 'mpesa_receipt']].sort_values(by="date", ascending=False).head(10), use_container_width=True)
        else:
            st.info("No transactions logged yet.")

elif page == "Manage Units":
    st.title("Move In / Move Out & Adjust Rent")

    conn = get_db_connection()
    units_df = pd.read_sql_query("SELECT * FROM units", conn)

    selected_unit = st.selectbox("Select Unit", units_df['unit_name'])
    unit_data = units_df[units_df['unit_name'] == selected_unit].iloc[0]

    with st.form("update_unit_form"):
        st.write(f"### Editing Unit {selected_unit}")

        new_tenant = st.text_input("Tenant Name (Clear this if they move out)", value=unit_data['tenant_name'])
        status_options = ["Vacant", "Occupied & Paid", "Occupied & Arrears"]
        new_status = st.selectbox("Status", status_options, index=status_options.index(unit_data['status']))

        # Landlord can adjust the expected rent here dynamically
        new_rent = st.number_input("Expected Monthly Rent (KSh)", value=float(unit_data['rent_amount']), step=500.0)

        # Manual override for deposit if needed (usually handled in Log Payment)
        new_deposit = st.number_input("Deposit Held (KSh) - Edit manually if refunding/deducting", value=float(unit_data['deposit_held']), step=500.0)

        if st.form_submit_button("Save Unit Changes"):
            c = conn.cursor()
            c.execute('''
                UPDATE units 
                SET tenant_name = ?, status = ?, rent_amount = ?, deposit_held = ?
                WHERE unit_name = ?
            ''', (new_tenant, new_status, new_rent, new_deposit, selected_unit))
            conn.commit()
            st.success(f"Unit {selected_unit} updated successfully!")
    conn.close()

elif page == "Log Payment":
    st.title("Record Transaction (Rent/Deposit)")

    conn = get_db_connection()
    # Allow logging payments for any unit, including vacant ones (for move-in deposits)
    units_df = pd.read_sql_query("SELECT unit_name FROM units", conn)

    with st.form("payment_form"):
        unit = st.selectbox("Select Unit", units_df['unit_name'])

        payment_type = st.selectbox("Payment Type", ["Rent Only", "Rent + Deposit", "Deposit Only", "Deposit Refund (Outgoing)"])

        amount = st.number_input("Total Amount Transacted (KSh)", min_value=0.0, step=500.0)

        # If they paid rent and deposit together, ask how much goes to the deposit
        deposit_portion = 0.0
        if payment_type == "Rent + Deposit":
            deposit_portion = st.number_input("How much of the total amount is the Deposit? (KSh)", min_value=0.0, max_value=amount, step=500.0)

        receipt = st.text_input("M-Pesa Receipt Code / Transaction ID")
        date = st.date_input("Transaction Date", datetime.today())

        if st.form_submit_button("Log Transaction"):
            if amount > 0 and receipt:
                c = conn.cursor()

                # 1. Log the transaction in the history
                c.execute('INSERT INTO payments (unit_name, payment_type, amount, date, mpesa_receipt) VALUES (?, ?, ?, ?, ?)',
                          (unit, payment_type, amount, date.strftime("%Y-%m-%d"), receipt.upper()))

                # 2. Update the Unit Status and Deposit Balances intelligently
                if payment_type == "Rent Only":
                    c.execute("UPDATE units SET status = 'Occupied & Paid' WHERE unit_name = ?", (unit,))

                elif payment_type == "Deposit Only":
                    c.execute("UPDATE units SET deposit_held = deposit_held + ? WHERE unit_name = ?", (amount, unit))

                elif payment_type == "Rent + Deposit":
                    c.execute("UPDATE units SET deposit_held = deposit_held + ?, status = 'Occupied & Paid' WHERE unit_name = ?", (deposit_portion, unit))

                elif payment_type == "Deposit Refund (Outgoing)":
                    c.execute("UPDATE units SET deposit_held = deposit_held - ? WHERE unit_name = ?", (amount, unit))

                conn.commit()
                st.success(f"{payment_type} of KSh {amount} for Unit {unit} recorded successfully!")
            else:
                st.error("Please enter an amount greater than 0 and a receipt code.")
    conn.close()
