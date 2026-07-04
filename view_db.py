import sqlite3

def view_database():
    conn = sqlite3.connect("cohort.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM customers")
    rows = cursor.fetchall()
    
    print("\n--- RAW DATABASE CONTENTS (UNMASKED) ---")
    for row in rows:
        print(f"ID: {row[0]} | Name: {row[1]} | Phone: {row[2]} | CC: {row[3]} | Aadhaar: {row[4]} | PAN: {row[5]} | Purchases: {row[6]}")
        
    conn.close()

if __name__ == "__main__":
    view_database()
