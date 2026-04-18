import sqlite3

# Conectează-te la baza de date (asigură-te că numele fișierului e corect, poate fi și instance/database.db)
conn = sqlite3.connect('database.db') 
cursor = conn.cursor()

# Resetează HP-ul la 5 pentru absolut toți utilizatorii din tabel
cursor.execute("UPDATE users SET hp = 5")

conn.commit()
conn.close()

print("✅ Vietile au fost resetate la 5 direct in baza de date!")