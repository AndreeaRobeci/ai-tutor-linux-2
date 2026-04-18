import sqlite3

conn = sqlite3.connect('database.db')
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE users ADD COLUMN last_date TEXT")
    print("✅ Coloana 'last_date' a fost adăugată cu succes!")
except sqlite3.OperationalError:
    print("⚠️ Coloana există deja. Totul e în regulă!")

conn.commit()
conn.close()