import sqlite3

conn = sqlite3.connect('database.db')
cursor = conn.cursor()

# Coloana existentă
try:
    cursor.execute("ALTER TABLE users ADD COLUMN last_date TEXT")
    print("✅ Coloana 'last_date' a fost adăugată!")
except sqlite3.OperationalError:
    print("⚠️ 'last_date' există deja.")

# 🆕 Coloana pentru nivel
try:
    cursor.execute("ALTER TABLE users ADD COLUMN start_world INTEGER DEFAULT 1")
    print("✅ Coloana 'start_world' a fost adăugată!")
except sqlite3.OperationalError:
    print("⚠️ 'start_world' există deja.")


#coloana pentru a vedea din ce lume incepe utilizatorul, pentru a putea să îi oferim exerciții din lumea respectivă
try:
    cursor.execute("ALTER TABLE users ADD COLUMN start_world INTEGER DEFAULT 1")
    print("✅ Coloana 'start_world' a fost adăugată!")
except sqlite3.OperationalError:
    print("⚠️ 'start_world' există deja.")

conn.commit()
conn.close()