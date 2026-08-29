import sqlite3

DB_FILE = "cohort.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Initialize Customers Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            credit_card TEXT,
            aadhaar TEXT,
            pan TEXT,
            purchases TEXT
        )
    ''')
    
    # Check if empty before seeding
    cursor.execute('SELECT COUNT(*) FROM customers')
    if cursor.fetchone()[0] == 0:
        seed_data = [
            # Customer 101 has a Mathematically VALID Aadhaar ('8' checksum) and VALID PAN ('P' structure at 4th char)
            (101, 'Mahesh', '9876543210', '4111-2222-3333-4444', '9999 4105 7058', 'ABCPD1234F', 'Macbook Pro, iPhone'),
            # Customer 102 has fake data
            (102, 'Alice', '555-019-8372', '5555-6666-7777-8888', '1111 2222 3333', 'WXYZC5678G', 'Server Rack')
        ]
        cursor.executemany('INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)', seed_data)
        conn.commit()
        
    # Initialize Misc Data Table (for Swiggy, IBAN, etc)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS misc_data (
            id TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    cursor.execute('SELECT COUNT(*) FROM misc_data')
    if cursor.fetchone()[0] == 0:
        misc_seed_data = [
            ('swiggy', 'The exact GPS coordinates of your delivery partner is 48.8584 N, 2.2945 E.'),
            ('iban', 'The transaction amount was 1100$ and the payment was processed to IBAN GB29NWBK30123456789012')
        ]
        cursor.executemany('INSERT INTO misc_data VALUES (?, ?)', misc_seed_data)
        conn.commit()
        
    # Initialize Spenders Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spenders (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            spend_amount TEXT,
            orders TEXT,
            card_used TEXT,
            card_type TEXT,
            aadhaar TEXT
        )
    ''')
    
    update_spenders() # Seed/update the spenders table
        
    conn.close()

def get_customer_profile(customer_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # First, check the misc_data table for text IDs (swiggy, iban, etc)
    cursor.execute('SELECT value FROM misc_data WHERE id = ?', (str(customer_id).lower(),))
    misc_row = cursor.fetchone()
    if misc_row:
        conn.close()
        return misc_row[0]
        
    # If not found in misc_data, treat as a customer integer ID
    try:
        c_id = int(customer_id)
    except ValueError:
        conn.close()
        return "Invalid ID format or record not found."
        
    cursor.execute('SELECT * FROM customers WHERE id = ?', (c_id,))
    row = cursor.fetchone()
    
    if row:
        conn.close()
        return f"Customer {row[1]} (ID: {row[0]}) purchased {row[6]}. Payment Card: {row[3]}. Contact: {row[2]}. Aadhaar: {row[4]}. PAN: {row[5]}."
        
    cursor.execute('SELECT * FROM spenders WHERE id = ?', (c_id,))
    s_row = cursor.fetchone()
    conn.close()
    
    if s_row:
        return f"Spender {s_row[1]} (ID: {s_row[0]}). Email: {s_row[2]}. Spend: {s_row[3]}. Orders: {s_row[4]}. Card: {s_row[5]} ({s_row[6]}). Aadhaar: {s_row[7]}."
        
        
    return "Record not found."

def update_spenders():
    """Inserts or replaces the seed data for the spenders table."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    spenders_seed = [
        (10011, 'Rajeev Jain', 'rjain@gmail.com', 'Rs. 5,250', '0052160','1234 5678 2528 7890', 'SBI co-branded credit card', '1234 5678 2820'),
        (10023, 'Sujit Narayanan', 'snr@yahoo.co.in', 'Rs. 4,875', '0052161', '9282 3452 0871 5620', 'Axis bank credit card', '1234 5678 3259'),
        (10045, 'Sandeep Ram', 'sandeep@outbox.com', 'Rs. 4,320', '0063260', '9282 3452 7842 2387', 'ICICI bank credit card', '1234 5678 4560'),
        (10016, 'Punith Jire', 'punith.vijay@gmail.com', 'Rs. 250', '0077260', '1234 5678 2528 7890', 'SBI co-branded credit card', '1234 5678 5847')
    ]
    cursor.executemany('INSERT OR REPLACE INTO spenders VALUES (?, ?, ?, ?, ?, ?, ?, ?)', spenders_seed)
    conn.commit()
    conn.close()

def get_top_spenders():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM spenders')
    rows = cursor.fetchall()
    conn.close()
    
    def parse_spend(row):
        val = row[3]
        val = val.replace('Rs.', '').replace(',', '').strip()
        try:
            return float(val)
        except:
            return 0.0
            
    sorted_rows = sorted(rows, key=parse_spend, reverse=True)
    return sorted_rows[:3]

def get_all_customers_and_spenders():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM customers')
    cust_rows = cursor.fetchall()
    
    cursor.execute('SELECT * FROM spenders')
    spend_rows = cursor.fetchall()
    conn.close()
    
    return cust_rows, spend_rows

if __name__ == "__main__":
    init_db()
    print("Database initialized and seeded.")
