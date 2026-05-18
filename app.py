from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, g
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from groq import Groq
from pdf_loader import load_pdf_text
import os
import json
import sqlite3
import threading
import webbrowser
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from datetime import datetime

# --- CONFIGURĂRI CĂI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
pdf_path = os.path.join(BASE_DIR, "data", "AI-tutor-linux resurse.pdf")
json_path = os.path.join(BASE_DIR, "data", "exercices.json")
PDF_CONTENT = load_pdf_text(pdf_path)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/avatars'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.secret_key = 'super_secret_ai_tutor_key'
DATABASE = os.path.join(BASE_DIR, 'database.db')

# --- CONFIGURARE MAIL (MODIFICĂ AICI!) ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'aitutor288@gmail.com' # <--- Pune mail-ul nou
app.config['MAIL_PASSWORD'] = 'ltfk rngw hiwt qkyo'      # <--- Pune codul de 16 litere
app.config['MAIL_DEFAULT_SENDER'] = 'aitutor288@gmail.com'

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.secret_key)

client=Groq(api_key="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")
model = None
model_error = None


def open_in_chrome(url):
    chrome_paths = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]

    for chrome_path in chrome_paths:
        if chrome_path and os.path.exists(chrome_path):
            webbrowser.BackgroundBrowser(chrome_path).open(url)
            return

    webbrowser.open(url)

# --- LOGICĂ BAZĂ DE DATE ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
    return db


def get_skipped_task_ids(start_world):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    skipped = []

    for lume in data["curs_linux"]:
        if lume["id_lume"] < start_world:
            for skill in lume["skill_uri"]:
                for ex in skill["exercitii"]:
                    skipped.append(ex["id"])

            if lume.get("boss_level") and lume["boss_level"].get("cerinta"):
                skipped.append(f"boss-{lume['id_lume']}")

    return skipped


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            hp INTEGER DEFAULT 5, xp INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0, last_date TEXT,
            start_world INTEGER DEFAULT 1,
            onboarding_completed INTEGER NOT NULL DEFAULT 0)''')
        ensure_column(db, 'users', 'start_world', 'INTEGER DEFAULT 1')
        ensure_onboarding_column(db)
        db.execute('UPDATE users SET onboarding_completed = 0 WHERE onboarding_completed IS NULL')
        db.execute('DROP TRIGGER IF EXISTS delete_completed_tasks_after_user_delete')
        ensure_completed_tasks_table(db)
        db.execute('''CREATE TRIGGER delete_completed_tasks_after_user_delete
            AFTER DELETE ON users
            BEGIN
                DELETE FROM completed_tasks WHERE user_id = OLD.id;
            END''')
        db.commit()


def ensure_column(db, table_name, column_name, definition):
    columns = [row['name'] for row in db.execute(f'PRAGMA table_info({table_name})').fetchall()]
    if column_name not in columns:
        db.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')


def ensure_onboarding_column(db):
    columns = db.execute('PRAGMA table_info(users)').fetchall()
    column_names = [row['name'] for row in columns]

    if 'onboarding_completed' not in column_names:
        db.execute('ALTER TABLE users ADD COLUMN onboarding_completed INTEGER NOT NULL DEFAULT 0')
        return

    onboarding_column = next(row for row in columns if row['name'] == 'onboarding_completed')
    current_default = str(onboarding_column['dflt_value'] or '').strip().strip("'\"()")
    if current_default == '0' and onboarding_column['notnull'] == 1:
        return

    db.execute('ALTER TABLE users RENAME TO users_onboarding_migration')
    db.execute('''CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        hp INTEGER DEFAULT 5,
        xp INTEGER DEFAULT 0,
        streak INTEGER DEFAULT 0,
        last_date TEXT,
        avatar TEXT,
        strike_curent INTEGER DEFAULT 0,
        record_strike INTEGER DEFAULT 0,
        start_world INTEGER DEFAULT 1,
        onboarding_completed INTEGER NOT NULL DEFAULT 0)''')

    target_columns = [
        'id',
        'username',
        'email',
        'password',
        'hp',
        'xp',
        'streak',
        'last_date',
        'avatar',
        'strike_curent',
        'record_strike',
        'start_world',
        'onboarding_completed',
    ]
    defaults = {
        'hp': '5',
        'xp': '0',
        'streak': '0',
        'last_date': 'NULL',
        'avatar': 'NULL',
        'strike_curent': '0',
        'record_strike': '0',
        'start_world': '1',
        'onboarding_completed': '0',
    }
    select_values = []
    for column in target_columns:
        if column == 'onboarding_completed' and column in column_names:
            select_values.append('COALESCE(onboarding_completed, 0)')
        elif column in column_names:
            select_values.append(column)
        else:
            select_values.append(defaults[column])

    db.execute(
        f"INSERT INTO users ({', '.join(target_columns)}) "
        f"SELECT {', '.join(select_values)} FROM users_onboarding_migration"
    )
    db.execute('DROP TABLE users_onboarding_migration')


def ensure_completed_tasks_table(db):
    table_exists = db.execute(
        "SELECT COUNT(1) AS count FROM sqlite_master WHERE type = 'table' AND name = 'completed_tasks'"
    ).fetchone()['count'] == 1

    needs_rebuild = not table_exists
    if table_exists:
        columns = db.execute('PRAGMA table_info(completed_tasks)').fetchall()
        column_names = [row['name'] for row in columns]
        foreign_keys = db.execute('PRAGMA foreign_key_list(completed_tasks)').fetchall()
        fk_points_to_users = any(row['table'] == 'users' for row in foreign_keys)
        required_columns = {'user_id', 'task_id'}
        needs_rebuild = not required_columns.issubset(column_names) or not fk_points_to_users

    if needs_rebuild and table_exists:
        db.execute('DROP TABLE IF EXISTS completed_tasks_migration')
        db.execute('ALTER TABLE completed_tasks RENAME TO completed_tasks_migration')

    if needs_rebuild:
        db.execute('''CREATE TABLE completed_tasks (
            user_id INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            PRIMARY KEY (user_id, task_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)''')

    if needs_rebuild and table_exists:
        old_columns = [row['name'] for row in db.execute('PRAGMA table_info(completed_tasks_migration)').fetchall()]
        if {'user_id', 'task_id'}.issubset(old_columns):
            db.execute('''INSERT OR IGNORE INTO completed_tasks (user_id, task_id)
                SELECT user_id, task_id
                FROM completed_tasks_migration
                WHERE task_id IS NOT NULL
                AND user_id IN (SELECT id FROM users)''')
        db.execute('DROP TABLE completed_tasks_migration')


def get_onboarding_completed(user_id):
    db = get_db()
    user = db.execute(
        'SELECT onboarding_completed FROM users WHERE id = ?',
        (user_id,)
    ).fetchone()
    if user is None:
        return 0

    try:
        return 1 if int(user['onboarding_completed'] or 0) == 1 else 0
    except (TypeError, ValueError):
        return 0


def sync_onboarding_session(user_id):
    onboarding_completed = get_onboarding_completed(user_id)
    session['onboarding_completed'] = onboarding_completed
    return onboarding_completed


def user_needs_onboarding():
    if 'user_id' not in session:
        return False

    db = get_db()
    user = db.execute(
        'SELECT onboarding_completed FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()

    if not user:
        return False

    try:
        onboarding_completed = 1 if int(user['onboarding_completed'] or 0) == 1 else 0
    except (TypeError, ValueError):
        onboarding_completed = 0

    session['onboarding_completed'] = onboarding_completed
    return onboarding_completed != 1


def redirect_to_onboarding(user_id, username=None):
    session['pending_user_id'] = user_id
    if username:
        session['pending_username'] = username
    return redirect(url_for('onboarding'))


init_db()


@app.before_request
def require_onboarding():
    allowed_routes = [
        'login',
        'register',
        'logout',
        'onboarding',
        'start_from_zero',
        'placement_test',
        'set_level_beginner',
        'submit_placement_test',
        'static'
    ]

    if request.endpoint in allowed_routes:
        return None

    if 'user_id' in session and user_needs_onboarding():
        return redirect(url_for('onboarding'))

    return None

# --- FUNCȚII TOKEN SECURITATE ---
def generate_reset_token(email):
    return serializer.dumps(email, salt='password-reset-salt')

def verify_reset_token(token, expiration=1800):
    try:
        return serializer.loads(token, salt='password-reset-salt', max_age=expiration)
    except:
        return None

# --- RUTE AUTENTIFICARE ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            timp_acum = datetime.now().strftime("%d-%m-%Y %H:%M")
            db = get_db()
            db.execute('UPDATE users SET last_date = ? WHERE id = ?', (timp_acum, user['id']))
            db.commit()
            session['username'] = user['username']
            session['onboarding_completed'] = 1 if int(user['onboarding_completed'] or 0) == 1 else 0
            if session['onboarding_completed'] == 0:
                return redirect_to_onboarding(user['id'], user['username'])
            return redirect(url_for('chat_page'))
        flash('Date incorecte!')
    return render_template('login.html')


@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    email = request.form['email']
    password = request.form['password']

    db = get_db()
    try:
        hashed_pw = generate_password_hash(password)

        cursor = db.execute(
            'INSERT INTO users (username, email, password, start_world, onboarding_completed) VALUES (?, ?, ?, ?, ?)',
            (username, email, hashed_pw, 1, 0)
        )
        db.commit()

        user_id = cursor.lastrowid

        session['user_id'] = user_id
        session['username'] = username
        session['onboarding_completed'] = 0
        session['pending_user_id'] = user_id
        session['pending_username'] = username

        return redirect(url_for('onboarding'))

    except sqlite3.IntegrityError:
        db.rollback()
        flash('Nume de utilizator sau email deja existent!')
        return redirect(url_for('login'))
    except Exception as e:
        db.rollback()
        print(f"Eroare la creare cont: {e}")
        flash('Nu am putut crea contul. Încearcă din nou.')
        return redirect(url_for('login'))

@app.route('/onboarding')
def onboarding():
    user_id = session.get('pending_user_id') or session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    sync_onboarding_session(user_id)
    if session.get('onboarding_completed') == 1:
        return redirect(url_for('chat_page'))

    session['pending_user_id'] = user_id
    if 'pending_username' not in session and session.get('username'):
        session['pending_username'] = session['username']

    return render_template('onboarding.html')


@app.route('/set_level_beginner', methods=['POST'])
def set_level_beginner():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    user_id = session['user_id']

    db.execute(
        'UPDATE users SET onboarding_completed = ?, start_world = ? WHERE id = ?',
        (1, 1, user_id)
    )
    db.commit()

    session['user_id'] = user_id
    session['username'] = session.get('pending_username') or session.get('username')
    session['onboarding_completed'] = 1

    session.pop('pending_user_id', None)
    session.pop('pending_username', None)

    return redirect(url_for('exercices'))


@app.route('/submit_placement_test', methods=['POST'])
def submit_placement_test():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']

    score = 0
    score += int(request.form.get('q1', 0))
    score += int(request.form.get('q2', 0))
    score += int(request.form.get('q3', 0))
    score += int(request.form.get('q4', 0))
    score += int(request.form.get('q5', 0))

    if score >= 4:
        start_world = 4
    elif score == 3:
        start_world = 3
    elif score == 2:
        start_world = 2
    else:
        start_world = 1

    skipped_tasks = get_skipped_task_ids(start_world)
    xp_bonus = len(skipped_tasks) * 10

    db = get_db()

    db.execute(
        'UPDATE users SET onboarding_completed = ?, start_world = ?, xp = ? WHERE id = ?',
        (1, start_world, xp_bonus, user_id)
    )

    for task_id in skipped_tasks:
        try:
            db.execute(
                'INSERT OR IGNORE INTO completed_tasks (user_id, task_id) VALUES (?, ?)',
                (user_id, task_id)
            )
        except:
            pass

    db.commit()

    session['user_id'] = user_id
    session['username'] = session.get('pending_username') or session.get('username')
    session['onboarding_completed'] = 1

    session.pop('pending_user_id', None)
    session.pop('pending_username', None)

    return render_template(
        'placement_result.html',
        score=score,
        start_world=start_world,
        xp_bonus=xp_bonus
    )


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if user:
            token = generate_reset_token(email)
            reset_url = url_for('reset_with_token', token=token, _external=True)
            msg = Message('Resetare Parolă AI Tutor', recipients=[email])
            
            # Textul simplu pentru mailurile care nu suportă HTML (foarte rar)
            msg.body = f"Salut! Copiază link-ul în browser: {reset_url}"
            
            # Design-ul mail-ului cu BUTON CLICKABIL care te duce direct pe pagină
            msg.html = f"""
            <div style="font-family: sans-serif; max-width: 500px; margin: auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                <h3 style="color: #1a1a2e; text-align: center;">Recuperare parolă - AI Tutor</h3>
                <p>Salut!</p>
                <p>Apasă pe butonul de mai jos pentru a alege o parolă nouă:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="padding: 12px 20px; background-color: #8ba888; color: white; text-decoration: none; border-radius: 8px; font-weight: bold;">Resetează parola direct aici</a>
                </div>
                <p style="font-size: 0.8em; color: #999; text-align: center; margin-top: 20px;">Link-ul expiră în 30 de minute.</p>
            </div>
            """
            
            mail.send(msg)
            flash('Ți-am trimis un e-mail cu instrucțiuni!')
        else:
            flash('Email-ul nu a fost găsit.')
    return render_template('forgot.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_with_token(token):
    email = verify_reset_token(token)
    if not email:
        flash('Link invalid sau expirat!')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        new_pw = request.form['password']
        hashed = generate_password_hash(new_pw)
        db = get_db()
        db.execute('UPDATE users SET password = ? WHERE email = ?', (hashed, email))
        db.commit()
        flash('Parola a fost schimbată!')
        return redirect(url_for('login'))
    return render_template('reset_new_password.html', token=token)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- RUTE PAGINI ---
@app.route("/")
def index():
    session.clear()
    return redirect(url_for('login'))


@app.route("/upload_avatar", methods=["POST"])
def upload_avatar():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if user_needs_onboarding():
        return redirect_to_onboarding(session['user_id'], session.get('username'))
        
    # Verificăm dacă utilizatorul a trimis un fișier
    if 'avatar' not in request.files:
        return redirect(url_for('chat_page'))
        
    file = request.files['avatar']
    
    if file.filename == '':
        return redirect(url_for('chat_page'))
        
    if file:
        # Securizăm numele fișierului și adăugăm ID-ul utilizatorului ca să nu se suprascrie între ei
        filename = secure_filename(file.filename)
        filename = f"user_{session['user_id']}_{filename}"
        
        # Salvăm fișierul fizic în folderul static/avatars
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        # Salvăm numele fișierului în baza de date
        import sqlite3
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Dacă nu există coloana 'avatar' în baza de date, o creăm automat acum
        try:
            cursor.execute("UPDATE users SET avatar = ? WHERE id = ?", (filename, session['user_id']))
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
            cursor.execute("UPDATE users SET avatar = ? WHERE id = ?", (filename, session['user_id']))
            
        conn.commit()
        conn.close()
        
    return redirect(url_for('chat_page'))


@app.route("/chat")
def chat_page():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    if user_needs_onboarding():
        return redirect_to_onboarding(session['user_id'], session.get('username'))
        
    user_id = session['user_id']
    
    import sqlite3
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    try:
        
        cursor.execute("SELECT xp, hp, strike_curent, record_strike, last_date, avatar FROM users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
    except sqlite3.OperationalError:
        user_data = None
        
    conn.close()
    
    if user_data:
        # 2. AICI AM MODIFICAT: ordinea se schimbă pentru că am adăugat un element nou în SELECT
        xp = user_data[0] if user_data[0] is not None else 0
        hp = user_data[1] if user_data[1] is not None else 5
        strike_curent = user_data[2] if user_data[2] is not None else 0
        record_strike = user_data[3] if user_data[3] is not None else 0
        last_date = user_data[4] if user_data[4] is not None else "N/A"
        
        # Avatarul este acum pe poziția [5]
        avatar_db = user_data[5] if len(user_data) > 5 and user_data[5] else None
        if avatar_db:
            avatar_url = f"/static/avatars/{avatar_db}"
        else:
            avatar_url = "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"
    else:
        # 3. Și aici am actualizat ca să reflecte noile variabile
        xp, hp, strike_curent, record_strike, last_date, avatar_url = 0, 5, 0, 0, "N/A", "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"
        
    if xp < 50:
        rang = "🟢 Newbie Linux"
    elif xp < 150:
        rang = "🔵 Terminal Explorer"
    else:
        rang = "🟣 Script Hacker"
        
    # 4. Aici ai făcut tu bine, le trimitem pe amândouă către index.html
    return render_template("index.html", xp=xp, hp=hp, strike_curent=strike_curent, record_strike=record_strike, last_date=last_date, rang=rang, avatar_url=avatar_url)


# 1. Ruta care trimite datele exercițiilor (din JSON) către Javascript
@app.route('/api/exercices')
def api_exercices():
    import json
    from flask import jsonify
    with open('data/exercices.json', 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))


# 2. Ruta care afișează pagina web (HTML)
@app.route('/exercices')
def exercices():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if user_needs_onboarding():
        return redirect_to_onboarding(session['user_id'], session.get('username'))
    
    db = get_db()
    user = db.execute(
        'SELECT xp, hp, strike_curent, record_strike, start_world, last_date, avatar FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()
    
    xp = user['xp']
    hp = user['hp']
    strike_curent = user['strike_curent'] if user['strike_curent'] is not None else 0
    record_strike = user['record_strike'] if user['record_strike'] is not None else 0
    start_world = user['start_world'] if user['start_world'] is not None else 1
    last_date = user['last_date'] if user['last_date'] is not None else "N/A"
    avatar_url = f"/static/avatars/{user['avatar']}" if user['avatar'] else "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"

    if xp < 50:
        rang = "🟢 Newbie Linux"
    elif xp < 150:
        rang = "🔵 Terminal Explorer"
    else:
        rang = "🟣 Script Hacker"

    if start_world > 1:
        for task_id in get_skipped_task_ids(start_world):
            db.execute(
                'INSERT OR IGNORE INTO completed_tasks (user_id, task_id) VALUES (?, ?)',
                (session['user_id'], task_id)
            )
        db.commit()
    completed_task_rows = db.execute(
        'SELECT task_id FROM completed_tasks WHERE user_id = ?',
        (session['user_id'],)
    ).fetchall()
    completed_tasks = [row['task_id'] for row in completed_task_rows]
    
    return render_template(
        'exercices.html',
        xp=xp,
        hp=hp,
        strike_curent=strike_curent,
        record_strike=record_strike,
        start_world=start_world,
        username=session['username'],
        user_id=session['user_id'],
        completed_tasks=completed_tasks,
        avatar_url=avatar_url,
        rang=rang,
        last_date=last_date
    )

# Setează un context scurt ca să nu proceseze mii de cuvinte
SYSTEM_PROMPT = """Ești un Profesor de Linux dedicat și răbdător. 
Scopul tău este să transformi un începător absolut într-un utilizator avansat.

REGULI DE AUR:
1. EDUCAȚIE: Când cineva spune că nu știe nimic sau cere să învețe, NU da doar comenzi. Explică CONCEPTUL (ce este un terminal, ce este un sistem de fișiere, de ce folosim linii de comandă).
2. STRUCTURĂ: Împarte informația în lecții logice. Folosește titluri, bold și liste.
3. EXEMPLE: Fiecare bucată de teorie trebuie să aibă un exemplu practic de comandă.
4. ÎNCURAJARE: La finalul unei lecții, întreabă utilizatorul dacă a înțeles sau dacă vrea să treacă la pasul următor.
5. LIMBA: Răspunde exclusiv în limba română, într-un stil prietenos dar profesional."""


@app.route('/api/ask', methods=['POST'])
def ask():
    try:
        data = request.json
        user_query = data.get('question', '') or data.get('text', '')

        # Folosim contextul din PDF (variabila pe care o ai deja la începutul codului)
        # Luăm doar o parte din el ca să fie rapid
        context = PDF_CONTENT[:3000] if 'PDF_CONTENT' in globals() else ""

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_query}
            ],
            temperature=0.4, # Puțin mai mare pentru a fi mai creativ în explicații
            max_tokens=1200
        )

        raspuns_final = completion.choices[0].message.content
        
        # Trimitem ambele chei ca să fim siguri că JavaScript-ul o găsește pe cea bună
        return jsonify({
            "ok": True,
            "result": raspuns_final,
            "answer": raspuns_final
        })

    except Exception as e:
        print(f"Eroare: {e}")
        return jsonify({"ok": False, "result": "Eroare la AI", "answer": "Eroare la AI"}), 500
    

@app.route('/api/check_answer', methods=['POST'])
def check_answer():
    if 'user_id' not in session:
        return jsonify({"error": "Neautentificat. Te rog să te autentifici."}), 401

    data = request.json
    cerinta = data.get('cerinta', '')
    raspuns_utilizator = data.get('raspuns', '')
    task_id = data.get('task_id')

    if not cerinta or not raspuns_utilizator:
        return jsonify({"error": "Date incomplete."}), 400

    try:
        # 1. NOUL PROMPT: Evaluator strict + Anti-Trișat + Scor pe 4 trepte
        eval_prompt = f"""Ești un profesor de Linux prietenos, dar strict. Evaluezi răspunsul utilizatorului pentru o cerință.

        Cerința: {cerinta}
        Răspunsul utilizatorului: {raspuns_utilizator}

        REGULI STRICTE:
        1. Dacă răspunsul este complet corect, confirmă scurt și felicită-l.
        2. Dacă răspunsul este greșit:
        - ESTE STRICT INTERZIS SĂ ÎI SPUI COMANDA CORECTĂ! Nu îi da soluția!
        - Explică-i pe scurt ce face de fapt comanda introdusă de el (ex: "Ai folosit 'cd', dar această comandă te mută în alt folder, nu afișează unde ești").
        - Oferă-i un singur indiciu (hint) conceptual care să îl ajute să își amintească sau să caute comanda corectă (ex: "Gândește-te la acronimul pentru 'Print Working Directory'").
        3. Fii concis, clar și folosește limba română.
        
        Reguli Anti-Trișat (CRITIC):
        Un terminal Linux acceptă doar comenzi pure. Dacă răspunsul utilizatorului conține cuvinte conversaționale ("comanda este", "salut"), explicații sau folosește formatare specifică AI (backticks, ghilimele), dă automat nota 0.
        
        Reguli de Punctare:
        - 10: DOAR comanda corectă, perfectă și optimă.
        - 7: Comanda rezolvă corect cerința, dar nu este cea mai eficientă (flag-uri inutile, cale prea lungă).
        - 5: A nimerit comanda de bază, dar a greșit/uitat un parametru critic sau calea (ex: a uitat -r). Comanda e pe aproape.
        - 0: Comandă total greșită sau încalcă Regulile Anti-Trișat.
        
        Răspunde STRICT în format JSON valid, exact cu această structură:
        {{
            "scor": număr (10, 7, 5 sau 0), 
            "feedback": "Explicație scurtă (1-2 propoziții) în limba română."
        }}"""

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": eval_prompt}],
            temperature=0.1, 
            response_format={"type": "json_object"} 
        )

        # Extragem răspunsul AI-ului
        rezultat_ai = json.loads(completion.choices[0].message.content)
        scor = rezultat_ai.get("scor", 0)
        feedback = rezultat_ai.get("feedback", "Fără feedback.")

        # 2. Actualizăm Baza de Date
        db = get_db()
        user_id = session['user_id']
        
        # Extragem noile coloane în loc de streak
        user = db.execute('SELECT xp, hp, strike_curent, record_strike FROM users WHERE id = ?', (user_id,)).fetchone()
        
        xp = user['xp']
        hp = user['hp']
        strike_curent = user['strike_curent'] if user['strike_curent'] is not None else 0
        record_strike = user['record_strike'] if user['record_strike'] is not None else 0

        # Logica pentru Gamification bazată pe noul scor
        already_completed = False
        if task_id:
            already_completed = db.execute(
                'SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ?',
                (user_id, str(task_id))
            ).fetchone() is not None

        este_corect = scor in (10, 7)

        if scor == 10 and not already_completed:
            xp += 10
            strike_curent += 1
            if strike_curent > record_strike:
                record_strike = strike_curent
        elif scor == 7 and not already_completed:
            xp += 7
            strike_curent += 1
            if strike_curent > record_strike:
                record_strike = strike_curent
        elif este_corect:
            pass
        else:
            hp -= 1
            strike_curent = 0
            if hp < 0: 
                hp = 0

        # Salvăm noile statistici în baza de date
        db.execute('UPDATE users SET xp = ?, hp = ?, strike_curent = ?, record_strike = ? WHERE id = ?', 
                   (xp, hp, strike_curent, record_strike, user_id))
        if este_corect and task_id and not already_completed:
            db.execute(
                'INSERT OR IGNORE INTO completed_tasks (user_id, task_id) VALUES (?, ?)',
                (user_id, str(task_id))
            )
        db.commit()

        print("CORECT:", este_corect)
        print("XP:", xp)
        print("HP:", hp)
        print("STRIKE:", strike_curent)

        # 3. Trimitem rezultatul către frontend (browser)
        return jsonify({
            "scor": scor,               # Trimitem scorul pentru a declanșa animația
            "corect": este_corect,      # Decide dacă exercițiul devine verde/bifat
            "feedback": feedback,
            "new_xp": xp,
            "new_hp": hp,
            "strike_curent": strike_curent # Frontend-ul are nevoie doar de cel curent pentru animație
        })

    except Exception as e:
        print(f"Eroare la verificare AI: {e}")
        return jsonify({"error": "Eroare la evaluarea răspunsului."}), 500


@app.route('/api/reset_lives', methods=['POST'])
def reset_lives():
    if 'user_id' not in session:
        return jsonify({"error": "Neautentificat"}), 401

    db = get_db()
    db.execute(
        'UPDATE users SET hp = ? WHERE id = ?',
        (5, session['user_id'])
    )
    db.commit()

    return jsonify({
        "ok": True,
        "hp": 5
    })


if __name__ == "__main__":
    init_db()
    threading.Timer(1.0, open_in_chrome, args=("http://127.0.0.1:5000",)).start()
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
