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

try:
    cursor.execute("ALTER TABLE users ADD COLUMN onboarding_completed INTEGER NOT NULL DEFAULT 0")
    print("Coloana 'onboarding_completed' a fost adaugata!")
except sqlite3.OperationalError:
    print("'onboarding_completed' exista deja.")

cursor.execute("UPDATE users SET onboarding_completed = 0 WHERE onboarding_completed IS NULL")
cursor.execute("DROP TRIGGER IF EXISTS delete_completed_tasks_after_user_delete")

table_exists = cursor.execute(
    "SELECT COUNT(1) FROM sqlite_master WHERE type = 'table' AND name = 'completed_tasks'"
).fetchone()[0] == 1

needs_rebuild = not table_exists
if table_exists:
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(completed_tasks)").fetchall()]
    foreign_keys = cursor.execute("PRAGMA foreign_key_list(completed_tasks)").fetchall()
    fk_points_to_users = any(row[2] == "users" for row in foreign_keys)
    needs_rebuild = not {"user_id", "task_id"}.issubset(columns) or not fk_points_to_users

if needs_rebuild and table_exists:
    cursor.execute("DROP TABLE IF EXISTS completed_tasks_migration")
    cursor.execute("ALTER TABLE completed_tasks RENAME TO completed_tasks_migration")

if needs_rebuild:
    cursor.execute("""
    CREATE TABLE completed_tasks (
        user_id INTEGER NOT NULL,
        task_id TEXT NOT NULL,
        PRIMARY KEY (user_id, task_id),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

if needs_rebuild and table_exists:
    old_columns = [row[1] for row in cursor.execute("PRAGMA table_info(completed_tasks_migration)").fetchall()]
    if {"user_id", "task_id"}.issubset(old_columns):
        cursor.execute("""
        INSERT OR IGNORE INTO completed_tasks (user_id, task_id)
        SELECT user_id, task_id
        FROM completed_tasks_migration
        WHERE task_id IS NOT NULL
        AND user_id IN (SELECT id FROM users)
        """)
    cursor.execute("DROP TABLE completed_tasks_migration")

cursor.execute("""
CREATE TRIGGER delete_completed_tasks_after_user_delete
AFTER DELETE ON users
BEGIN
    DELETE FROM completed_tasks WHERE user_id = OLD.id;
END
""")

conn.commit()
conn.close()
