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
    conn.close()
    
    if row:
        return f"Customer {row[1]} (ID: {row[0]}) purchased {row[6]}. Payment Card: {row[3]}. Contact: {row[2]}. Aadhaar: {row[4]}. PAN: {row[5]}."
    return "Record not found."

if __name__ == "__main__":
    init_db()
    print("Database initialized and seeded.")
