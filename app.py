from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, g, send_from_directory
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from groq import Groq
from pdf_loader import load_pdf_text
import os
import json
import sqlite3
import threading
import webbrowser
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from datetime import datetime, timedelta

# --- CONFIGURĂRI CĂI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
pdf_path = os.path.join(BASE_DIR, "data", "AI-tutor-linux resurse.pdf")
json_path = os.path.join(BASE_DIR, "data", "exercices.json")
PDF_CONTENT = load_pdf_text(pdf_path)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/avatars'
app.config['GALLERY_UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'gallery')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GALLERY_UPLOAD_FOLDER'], exist_ok=True)
app.secret_key = 'super_secret_ai_tutor_key'
DATABASE = os.path.join(BASE_DIR, 'database.db')
ALLOWED_GALLERY_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
MAX_GALLERY_PHOTO_SIZE = 5 * 1024 * 1024
ALLOWED_AVATAR_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

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


def parse_cooldown(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def active_cooldown_seconds(cooldown_until):
    cooldown_time = parse_cooldown(cooldown_until)
    if not cooldown_time:
        return 0

    remaining = int((cooldown_time - datetime.now()).total_seconds())
    return max(0, remaining)


def create_cooldown():
    return (datetime.now() + timedelta(minutes=15)).isoformat(timespec='seconds')


def allowed_gallery_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_GALLERY_EXTENSIONS


def allowed_avatar_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS


def parse_last_login(value):
    if not value:
        return None

    for date_format in ("%d-%m-%Y %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, date_format)
        except (TypeError, ValueError):
            continue

    return None


def refresh_lives_after_24h(db, user):
    last_login = parse_last_login(user['last_date'])
    if not last_login:
        return False

    if datetime.now() - last_login < timedelta(hours=24):
        return False

    db.execute(
        'UPDATE users SET hp = ?, cooldown_until = NULL WHERE id = ?',
        (5, user['id'])
    )
    return True


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
            avatar TEXT,
            hp INTEGER DEFAULT 5, xp INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0, last_date TEXT,
            strike_curent INTEGER DEFAULT 0,
            record_strike INTEGER DEFAULT 0,
            start_world INTEGER DEFAULT 1,
            onboarding_completed INTEGER NOT NULL DEFAULT 0,
            cooldown_until TEXT,
            role TEXT DEFAULT 'user')''')
        ensure_column(db, 'users', 'avatar', 'TEXT')
        ensure_column(db, 'users', 'strike_curent', 'INTEGER DEFAULT 0')
        ensure_column(db, 'users', 'record_strike', 'INTEGER DEFAULT 0')
        ensure_column(db, 'users', 'start_world', 'INTEGER DEFAULT 1')
        ensure_column(db, 'users', 'cooldown_until', 'TEXT')
        ensure_column(db, 'users', 'role', "TEXT DEFAULT 'user'")
        ensure_onboarding_column(db)
        db.execute("UPDATE users SET role = 'user' WHERE role IS NULL OR role = ''")
        db.execute('UPDATE users SET onboarding_completed = 0 WHERE onboarding_completed IS NULL')
        db.execute('DROP TRIGGER IF EXISTS delete_completed_tasks_after_user_delete')
        ensure_completed_tasks_table(db)
        ensure_user_photos_table(db)
        ensure_social_tables(db)
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
        onboarding_completed INTEGER NOT NULL DEFAULT 0,
        cooldown_until TEXT,
        role TEXT DEFAULT 'user')''')

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
        'cooldown_until',
        'role',
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
        'cooldown_until': 'NULL',
        'role': "'user'",
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


def ensure_user_photos_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS user_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)''')


def ensure_social_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS friend_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE)''')
    db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_friend_requests_pair_pending
        ON friend_requests(sender_id, receiver_id)
        WHERE status = 'pending' ''')
    db.execute('''CREATE TABLE IF NOT EXISTS friendships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        friend_id INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (friend_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, friend_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_read INTEGER DEFAULT 0,
        FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE)''')


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


def current_user_is_admin():
    if 'user_id' not in session:
        return False

    db = get_db()
    user = db.execute(
        'SELECT role FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()
    return bool(user and user['role'] == 'admin')


def require_admin_access():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if not current_user_is_admin():
        return redirect(url_for('chat_page'))
    return None


def require_login_access():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return None


def get_rank_for_xp(xp):
    xp = xp or 0
    if xp < 50:
        return "🟢 Newbie Linux"
    if xp < 150:
        return "🔵 Terminal Explorer"
    return "🟣 Script Hacker"


def get_avatar_url(user):
    avatar = user['avatar'] if user and 'avatar' in user.keys() else None
    if avatar:
        return f"/static/avatars/{avatar}"
    return "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"


def are_friends(db, user_id, friend_id):
    if user_id == friend_id:
        return False

    friendship = db.execute(
        'SELECT 1 FROM friendships WHERE user_id = ? AND friend_id = ?',
        (user_id, friend_id)
    ).fetchone()
    return friendship is not None


def get_completed_count(db, user_id):
    table_exists = db.execute(
        "SELECT COUNT(1) AS count FROM sqlite_master WHERE type = 'table' AND name = 'completed_tasks'"
    ).fetchone()['count'] == 1
    if not table_exists:
        return 0

    return db.execute(
        'SELECT COUNT(*) AS count FROM completed_tasks WHERE user_id = ?',
        (user_id,)
    ).fetchone()['count']


def get_unread_message_count(user_id):
    if not user_id:
        return 0

    db = get_db()
    ensure_social_tables(db)
    return db.execute(
        '''SELECT COUNT(*) AS count
           FROM messages
           WHERE receiver_id = ? AND is_read = 0''',
        (user_id,)
    ).fetchone()['count']


def get_pending_friend_request_count(user_id):
    if not user_id:
        return 0

    db = get_db()
    ensure_social_tables(db)
    return db.execute(
        '''SELECT COUNT(*) AS count
           FROM friend_requests
           WHERE receiver_id = ? AND status = 'pending' ''',
        (user_id,)
    ).fetchone()['count']


def get_social_notification_count(user_id):
    return get_unread_message_count(user_id) + get_pending_friend_request_count(user_id)


def get_latest_unread_sender_id(user_id):
    if not user_id:
        return None

    db = get_db()
    ensure_social_tables(db)
    row = db.execute(
        '''SELECT sender_id
           FROM messages
           WHERE receiver_id = ? AND is_read = 0
           ORDER BY created_at DESC, id DESC
           LIMIT 1''',
        (user_id,)
    ).fetchone()
    return row['sender_id'] if row else None


@app.context_processor
def inject_message_notifications():
    if 'user_id' not in session:
        return {
            'unread_message_count': 0,
            'pending_friend_request_count': 0,
            'social_notification_count': 0,
            'latest_unread_sender_id': None
        }

    unread_count = get_unread_message_count(session['user_id'])
    pending_friend_count = get_pending_friend_request_count(session['user_id'])
    return {
        'unread_message_count': unread_count,
        'pending_friend_request_count': pending_friend_count,
        'social_notification_count': unread_count + pending_friend_count,
        'latest_unread_sender_id': get_latest_unread_sender_id(session['user_id']) if unread_count else None
    }


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
        'admin',
        'admin_delete_user',
        'admin_reset_user_xp',
        'admin_reset_user_hp',
        'admin_reset_user_strike',
        'admin_reset_user_onboarding',
        'admin_reset_user_progress',
        'admin_toggle_user_role',
        'admin_set_user_role',
        'friends',
        'send_friend_request',
        'accept_friend_request',
        'reject_friend_request',
        'public_user_profile',
        'messages_page',
        'send_message',
        'leaderboard',
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
            refresh_lives_after_24h(db, user)
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
        
    if 'avatar' not in request.files:
        return redirect(url_for('profile'))
        
    file = request.files['avatar']
    
    if file.filename == '':
        return redirect(url_for('profile'))

    if not allowed_avatar_file(file.filename):
        flash('Format invalid. Sunt acceptate doar JPG, JPEG, PNG și WEBP.')
        return redirect(url_for('profile'))
        
    if file:
        original_name = secure_filename(file.filename)
        extension = original_name.rsplit('.', 1)[1].lower()
        filename = f"user_{session['user_id']}_{uuid.uuid4().hex}.{extension}"
        
        file.save(os.path.join(BASE_DIR, app.config['UPLOAD_FOLDER'], filename))
        
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
        
    return redirect(url_for('profile'))


@app.route("/profile/photos/<int:photo_id>")
def gallery_photo(photo_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    ensure_user_photos_table(db)
    photo = db.execute(
        'SELECT filename FROM user_photos WHERE id = ? AND user_id = ?',
        (photo_id, session['user_id'])
    ).fetchone()

    if not photo:
        return redirect(url_for('profile'))

    return send_from_directory(
        os.path.join(BASE_DIR, app.config['GALLERY_UPLOAD_FOLDER']),
        photo['filename']
    )


@app.route("/user/photos/<int:photo_id>")
def public_gallery_photo(photo_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    ensure_user_photos_table(db)
    photo = db.execute(
        'SELECT filename FROM user_photos WHERE id = ?',
        (photo_id,)
    ).fetchone()

    if not photo:
        return redirect(url_for('friends'))

    return send_from_directory(
        os.path.join(BASE_DIR, app.config['GALLERY_UPLOAD_FOLDER']),
        photo['filename']
    )


@app.route("/profile/photos/upload", methods=["POST"])
def upload_gallery_photo():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if user_needs_onboarding():
        return redirect_to_onboarding(session['user_id'], session.get('username'))

    if request.content_length and request.content_length > MAX_GALLERY_PHOTO_SIZE + 2048:
        flash('Fotografia depășește limita de 5 MB.')
        return redirect(url_for('profile'))

    file = request.files.get('photo')
    if not file or file.filename == '':
        flash('Alege o fotografie înainte de încărcare.')
        return redirect(url_for('profile'))

    if not allowed_gallery_file(file.filename):
        flash('Format invalid. Sunt acceptate doar JPG, JPEG, PNG și WEBP.')
        return redirect(url_for('profile'))

    original_name = secure_filename(file.filename)
    extension = original_name.rsplit('.', 1)[1].lower()
    filename = f"user_{session['user_id']}_{uuid.uuid4().hex}.{extension}"
    upload_path = os.path.join(BASE_DIR, app.config['GALLERY_UPLOAD_FOLDER'], filename)
    file.save(upload_path)

    if os.path.getsize(upload_path) > MAX_GALLERY_PHOTO_SIZE:
        os.remove(upload_path)
        flash('Fotografia depășește limita de 5 MB.')
        return redirect(url_for('profile'))

    db = get_db()
    ensure_user_photos_table(db)
    db.execute(
        'INSERT INTO user_photos (user_id, filename) VALUES (?, ?)',
        (session['user_id'], filename)
    )
    db.commit()

    return redirect(url_for('profile'))


@app.route("/profile/photos/<int:photo_id>/delete", methods=["POST"])
def delete_gallery_photo(photo_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if user_needs_onboarding():
        return redirect_to_onboarding(session['user_id'], session.get('username'))

    db = get_db()
    ensure_user_photos_table(db)
    photo = db.execute(
        'SELECT filename FROM user_photos WHERE id = ? AND user_id = ?',
        (photo_id, session['user_id'])
    ).fetchone()

    if photo:
        photo_path = os.path.join(BASE_DIR, app.config['GALLERY_UPLOAD_FOLDER'], photo['filename'])
        if os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except OSError:
                pass
        db.execute(
            'DELETE FROM user_photos WHERE id = ? AND user_id = ?',
            (photo_id, session['user_id'])
        )
        db.commit()

    return redirect(url_for('profile'))


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
        
        cursor.execute("SELECT xp, hp, strike_curent, record_strike, last_date, avatar, cooldown_until FROM users WHERE id = ?", (user_id,))
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


def build_task_catalog():
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    catalog = {}
    ordered_ids = []

    for lume in data.get("curs_linux", []):
        world_title = lume.get("titlu", "Lume Linux")

        for skill in lume.get("skill_uri", []):
            skill_title = skill.get("titlu", "Exerciții")
            for index, exercise in enumerate(skill.get("exercitii", []), start=1):
                task_id = exercise.get("id")
                if not task_id:
                    continue

                ordered_ids.append(task_id)
                catalog[task_id] = {
                    "id": task_id,
                    "titlu": f"Exercițiul {index}",
                    "descriere": exercise.get("cerinta", "Exercițiu Linux"),
                    "categorie": skill_title,
                    "lume": world_title,
                    "tip": "Exercițiu"
                }

        boss_level = lume.get("boss_level") or {}
        if boss_level.get("cerinta"):
            task_id = f"boss-{lume.get('id_lume')}"
            ordered_ids.append(task_id)
            catalog[task_id] = {
                "id": task_id,
                "titlu": "Provocare boss",
                "descriere": boss_level.get("cerinta", "Provocare finală"),
                "categorie": "Boss",
                "lume": world_title,
                "tip": "Provocare"
            }

    return catalog, ordered_ids


@app.route('/friends')
def friends():
    redirect_response = require_login_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_social_tables(db)
    user_id = session['user_id']
    query = request.args.get('q', '').strip()
    search_results = []

    if query:
        search_results = db.execute(
            '''SELECT id, username, avatar, xp, strike_curent, record_strike
               FROM users
               WHERE id != ?
               AND username LIKE ?
               ORDER BY username ASC
               LIMIT 12''',
            (user_id, f'%{query}%')
        ).fetchall()

    received_requests = db.execute(
        '''SELECT fr.id, fr.created_at, u.id AS user_id, u.username, u.avatar, u.xp
           FROM friend_requests fr
           JOIN users u ON u.id = fr.sender_id
           WHERE fr.receiver_id = ? AND fr.status = 'pending'
           ORDER BY fr.created_at DESC''',
        (user_id,)
    ).fetchall()
    sent_requests = db.execute(
        '''SELECT fr.id, fr.created_at, u.id AS user_id, u.username, u.avatar, u.xp
           FROM friend_requests fr
           JOIN users u ON u.id = fr.receiver_id
           WHERE fr.sender_id = ? AND fr.status = 'pending'
           ORDER BY fr.created_at DESC''',
        (user_id,)
    ).fetchall()
    friend_rows = db.execute(
        '''SELECT u.id, u.username, u.avatar, u.xp, u.strike_curent, u.record_strike
           FROM friendships f
           JOIN users u ON u.id = f.friend_id
           WHERE f.user_id = ?
           ORDER BY u.username ASC''',
        (user_id,)
    ).fetchall()
    friend_ids = {row['id'] for row in friend_rows}
    pending_sent_ids = {row['user_id'] for row in sent_requests}
    pending_received_ids = {row['user_id'] for row in received_requests}
    unread_by_friend = {
        row['sender_id']: row['unread_count']
        for row in db.execute(
            '''SELECT sender_id, COUNT(*) AS unread_count
               FROM messages
               WHERE receiver_id = ? AND is_read = 0
               GROUP BY sender_id''',
            (user_id,)
        ).fetchall()
    }

    return render_template(
        'friends.html',
        query=query,
        search_results=search_results,
        received_requests=received_requests,
        sent_requests=sent_requests,
        friends=friend_rows,
        friend_ids=friend_ids,
        pending_sent_ids=pending_sent_ids,
        pending_received_ids=pending_received_ids,
        unread_by_friend=unread_by_friend,
        get_avatar_url=get_avatar_url,
        get_rank_for_xp=get_rank_for_xp
    )


@app.route('/send_friend_request/<int:user_id>', methods=['POST'])
def send_friend_request(user_id):
    redirect_response = require_login_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_social_tables(db)
    current_user_id = session['user_id']
    if user_id == current_user_id:
        flash('Nu îți poți trimite cerere de prietenie singur.')
        return redirect(url_for('friends'))

    target_user = db.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
    if not target_user:
        flash('Utilizatorul nu există.')
        return redirect(url_for('friends'))

    if are_friends(db, current_user_id, user_id):
        flash('Sunteți deja prieteni.')
        return redirect(url_for('friends'))

    existing_pending = db.execute(
        '''SELECT id FROM friend_requests
           WHERE status = 'pending'
           AND ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?))''',
        (current_user_id, user_id, user_id, current_user_id)
    ).fetchone()
    if existing_pending:
        flash('Există deja o cerere de prietenie în așteptare.')
        return redirect(url_for('friends'))

    db.execute(
        'INSERT INTO friend_requests (sender_id, receiver_id) VALUES (?, ?)',
        (current_user_id, user_id)
    )
    db.commit()
    flash('Cererea de prietenie a fost trimisă.')
    return redirect(request.referrer or url_for('friends'))


@app.route('/accept_friend_request/<int:request_id>', methods=['POST'])
def accept_friend_request(request_id):
    redirect_response = require_login_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_social_tables(db)
    friend_request = db.execute(
        '''SELECT id, sender_id, receiver_id
           FROM friend_requests
           WHERE id = ? AND receiver_id = ? AND status = 'pending' ''',
        (request_id, session['user_id'])
    ).fetchone()
    if not friend_request:
        flash('Cererea nu poate fi acceptată.')
        return redirect(url_for('friends'))

    db.execute("UPDATE friend_requests SET status = 'accepted' WHERE id = ?", (request_id,))
    db.execute(
        'INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)',
        (friend_request['receiver_id'], friend_request['sender_id'])
    )
    db.execute(
        'INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)',
        (friend_request['sender_id'], friend_request['receiver_id'])
    )
    db.commit()
    flash('Cererea de prietenie a fost acceptată.')
    return redirect(url_for('friends'))


@app.route('/reject_friend_request/<int:request_id>', methods=['POST'])
def reject_friend_request(request_id):
    redirect_response = require_login_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_social_tables(db)
    updated = db.execute(
        '''UPDATE friend_requests
           SET status = 'rejected'
           WHERE id = ? AND receiver_id = ? AND status = 'pending' ''',
        (request_id, session['user_id'])
    ).rowcount
    db.commit()
    flash('Cererea a fost refuzată.' if updated else 'Cererea nu poate fi refuzată.')
    return redirect(url_for('friends'))


@app.route('/user/<int:user_id>')
def public_user_profile(user_id):
    redirect_response = require_login_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_social_tables(db)
    user = db.execute(
        '''SELECT id, username, avatar, xp, strike_curent, record_strike, start_world
           FROM users
           WHERE id = ?''',
        (user_id,)
    ).fetchone()
    if not user:
        return redirect(url_for('friends'))

    current_user_id = session['user_id']
    is_self = current_user_id == user_id
    is_friend = are_friends(db, current_user_id, user_id)
    pending_request = db.execute(
        '''SELECT id, sender_id, receiver_id
           FROM friend_requests
           WHERE status = 'pending'
           AND ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?))''',
        (current_user_id, user_id, user_id, current_user_id)
    ).fetchone()
    completed_count = get_completed_count(db, user_id)
    photo_rows = db.execute(
        '''SELECT id, filename, uploaded_at
           FROM user_photos
           WHERE user_id = ?
           ORDER BY uploaded_at DESC, id DESC''',
        (user_id,)
    ).fetchall()
    public_gallery_photos = [
        {
            "id": row['id'],
            "filename": row['filename'],
            "uploaded_at": row['uploaded_at'],
            "url": url_for('public_gallery_photo', photo_id=row['id'])
        }
        for row in photo_rows
    ]

    return render_template(
        'public_user.html',
        public_user=user,
        avatar_url=get_avatar_url(user),
        rang=get_rank_for_xp(user['xp']),
        completed_count=completed_count,
        is_self=is_self,
        is_friend=is_friend,
        pending_request=pending_request,
        public_gallery_photos=public_gallery_photos
    )


@app.route('/messages/<int:friend_id>')
def messages_page(friend_id):
    redirect_response = require_login_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_social_tables(db)
    user_id = session['user_id']
    if not are_friends(db, user_id, friend_id):
        flash('Poți trimite mesaje doar prietenilor.')
        return redirect(url_for('friends'))

    friend = db.execute(
        'SELECT id, username, avatar FROM users WHERE id = ?',
        (friend_id,)
    ).fetchone()
    if not friend:
        return redirect(url_for('friends'))

    db.execute(
        'UPDATE messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ? AND is_read = 0',
        (friend_id, user_id)
    )
    db.commit()
    conversation = db.execute(
        '''SELECT id, sender_id, receiver_id, message, created_at
           FROM messages
           WHERE (sender_id = ? AND receiver_id = ?)
           OR (sender_id = ? AND receiver_id = ?)
           ORDER BY created_at ASC, id ASC''',
        (user_id, friend_id, friend_id, user_id)
    ).fetchall()

    return render_template(
        'messages.html',
        friend=friend,
        friend_avatar_url=get_avatar_url(friend),
        conversation=conversation,
        current_user_id=user_id
    )


@app.route('/send_message/<int:friend_id>', methods=['POST'])
def send_message(friend_id):
    redirect_response = require_login_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_social_tables(db)
    user_id = session['user_id']
    if not are_friends(db, user_id, friend_id):
        flash('Poți trimite mesaje doar prietenilor.')
        return redirect(url_for('friends'))

    message = request.form.get('message', '').strip()
    if message:
        db.execute(
            'INSERT INTO messages (sender_id, receiver_id, message) VALUES (?, ?, ?)',
            (user_id, friend_id, message)
        )
        db.commit()

    return redirect(url_for('messages_page', friend_id=friend_id))


@app.route('/leaderboard')
def leaderboard():
    redirect_response = require_login_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_social_tables(db)
    user_id = session['user_id']
    rows = db.execute(
        '''SELECT id, username, avatar, xp, strike_curent, record_strike
           FROM users
           WHERE id = ?
           OR id IN (
               SELECT friend_id FROM friendships WHERE user_id = ?
           )
           ORDER BY xp DESC, record_strike DESC, strike_curent DESC, username ASC''',
        (user_id, user_id)
    ).fetchall()

    return render_template(
        'leaderboard.html',
        entries=rows,
        current_user_id=user_id,
        get_avatar_url=get_avatar_url,
        get_rank_for_xp=get_rank_for_xp
    )


def get_user_completed_counts(db):
    table_exists = db.execute(
        "SELECT COUNT(1) AS count FROM sqlite_master WHERE type = 'table' AND name = 'completed_tasks'"
    ).fetchone()['count'] == 1

    if not table_exists:
        return {}

    rows = db.execute(
        '''SELECT user_id, COUNT(task_id) AS completed_count
           FROM completed_tasks
           GROUP BY user_id'''
    ).fetchall()
    return {row['user_id']: row['completed_count'] for row in rows}


def get_total_completed_tasks(db):
    table_exists = db.execute(
        "SELECT COUNT(1) AS count FROM sqlite_master WHERE type = 'table' AND name = 'completed_tasks'"
    ).fetchone()['count'] == 1

    if not table_exists:
        return 0

    return db.execute('SELECT COUNT(*) AS count FROM completed_tasks').fetchone()['count']


def delete_user_gallery_files(db, user_id):
    ensure_user_photos_table(db)
    photos = db.execute(
        'SELECT filename FROM user_photos WHERE user_id = ?',
        (user_id,)
    ).fetchall()

    for photo in photos:
        photo_path = os.path.join(BASE_DIR, app.config['GALLERY_UPLOAD_FOLDER'], photo['filename'])
        if os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except OSError:
                pass


@app.route('/admin')
def admin():
    redirect_response = require_admin_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_column(db, 'users', 'role', "TEXT DEFAULT 'user'")
    db.execute("UPDATE users SET role = 'user' WHERE role IS NULL OR role = ''")
    db.commit()

    stats = db.execute(
        '''SELECT
            COUNT(*) AS total_users,
            COALESCE(SUM(xp), 0) AS total_xp,
            SUM(CASE WHEN last_date IS NOT NULL AND last_date != '' THEN 1 ELSE 0 END) AS active_users,
            SUM(CASE WHEN hp = 0 THEN 1 ELSE 0 END) AS zero_hp_users
           FROM users'''
    ).fetchone()
    total_completed_tasks = get_total_completed_tasks(db)

    users = db.execute(
        '''SELECT id, username, email, xp, hp, strike_curent, last_date, role
           FROM users
           ORDER BY id ASC'''
    ).fetchall()

    return render_template(
        'admin.html',
        stats=stats,
        total_completed_tasks=total_completed_tasks,
        users=users,
        current_user_id=session['user_id']
    )


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    redirect_response = require_admin_access()
    if redirect_response:
        return redirect_response

    if user_id == session['user_id']:
        flash('Nu poți șterge contul administrativ activ.')
        return redirect(url_for('admin'))

    db = get_db()
    delete_user_gallery_files(db, user_id)
    db.execute('DELETE FROM completed_tasks WHERE user_id = ?', (user_id,))
    db.execute('DELETE FROM user_photos WHERE user_id = ?', (user_id,))
    db.execute('DELETE FROM friend_requests WHERE sender_id = ? OR receiver_id = ?', (user_id, user_id))
    db.execute('DELETE FROM friendships WHERE user_id = ? OR friend_id = ?', (user_id, user_id))
    db.execute('DELETE FROM messages WHERE sender_id = ? OR receiver_id = ?', (user_id, user_id))
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    flash('Utilizatorul a fost șters.')
    return redirect(url_for('admin'))


@app.route('/admin/users/<int:user_id>/reset-xp', methods=['POST'])
def admin_reset_user_xp(user_id):
    redirect_response = require_admin_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    db.execute('UPDATE users SET xp = 0 WHERE id = ?', (user_id,))
    db.commit()
    flash('XP-ul utilizatorului a fost resetat.')
    return redirect(url_for('admin'))


@app.route('/admin/users/<int:user_id>/reset-hp', methods=['POST'])
def admin_reset_user_hp(user_id):
    redirect_response = require_admin_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    db.execute('UPDATE users SET hp = 5 WHERE id = ?', (user_id,))
    db.commit()
    flash('HP-ul utilizatorului a fost resetat.')
    return redirect(url_for('admin'))


@app.route('/admin/users/<int:user_id>/reset-strike', methods=['POST'])
def admin_reset_user_strike(user_id):
    redirect_response = require_admin_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    db.execute(
        'UPDATE users SET strike_curent = 0, record_strike = 0 WHERE id = ?',
        (user_id,)
    )
    db.commit()
    flash('Strike-ul utilizatorului a fost resetat.')
    return redirect(url_for('admin'))


@app.route('/admin/users/<int:user_id>/reset-onboarding', methods=['POST'])
def admin_reset_user_onboarding(user_id):
    redirect_response = require_admin_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    db.execute('UPDATE users SET onboarding_completed = 0 WHERE id = ?', (user_id,))
    db.commit()
    flash('Onboarding-ul utilizatorului a fost resetat.')
    return redirect(url_for('admin'))


@app.route('/admin/users/<int:user_id>/reset-progress', methods=['POST'])
def admin_reset_user_progress(user_id):
    redirect_response = require_admin_access()
    if redirect_response:
        return redirect_response

    db = get_db()
    ensure_completed_tasks_table(db)
    db.execute('DELETE FROM completed_tasks WHERE user_id = ?', (user_id,))
    db.commit()
    flash('Progresul utilizatorului a fost resetat.')
    return redirect(url_for('admin'))


@app.route('/admin/users/<int:user_id>/toggle-role', methods=['POST'])
def admin_toggle_user_role(user_id):
    redirect_response = require_admin_access()
    if redirect_response:
        return redirect_response

    if user_id == session['user_id']:
        flash('Nu poți schimba rolul contului administrativ activ.')
        return redirect(url_for('admin'))

    db = get_db()
    user = db.execute('SELECT role FROM users WHERE id = ?', (user_id,)).fetchone()
    if user:
        new_role = 'admin' if user['role'] != 'admin' else 'user'
        db.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
        db.commit()
        flash('Rolul utilizatorului a fost actualizat.')

    return redirect(url_for('admin'))


@app.route('/admin/users/<int:user_id>/set-role/<role>', methods=['POST'])
def admin_set_user_role(user_id, role):
    redirect_response = require_admin_access()
    if redirect_response:
        return redirect_response

    if role not in ('admin', 'user'):
        flash('Rol invalid.')
        return redirect(url_for('admin'))

    if user_id == session['user_id'] and role != 'admin':
        flash('Nu poți elimina rolul de admin al contului activ.')
        return redirect(url_for('admin'))

    db = get_db()
    db.execute('UPDATE users SET role = ? WHERE id = ?', (role, user_id))
    db.commit()
    flash('Rolul utilizatorului a fost actualizat.')
    return redirect(url_for('admin'))


@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if user_needs_onboarding():
        return redirect_to_onboarding(session['user_id'], session.get('username'))

    db = get_db()
    ensure_user_photos_table(db)
    user = db.execute(
        '''SELECT username, xp, hp, strike_curent, record_strike, last_date, avatar
           FROM users
           WHERE id = ?''',
        (session['user_id'],)
    ).fetchone()

    if not user:
        return redirect(url_for('logout'))

    xp = user['xp'] if user['xp'] is not None else 0
    hp = user['hp'] if user['hp'] is not None else 5
    strike_curent = user['strike_curent'] if user['strike_curent'] is not None else 0
    record_strike = user['record_strike'] if user['record_strike'] is not None else 0
    last_date = user['last_date'] if user['last_date'] is not None else "N/A"
    avatar_url = f"/static/avatars/{user['avatar']}" if user['avatar'] else "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"

    if xp < 50:
        rang = "🟢 Newbie Linux"
    elif xp < 150:
        rang = "🔵 Terminal Explorer"
    else:
        rang = "🟣 Script Hacker"

    task_catalog, ordered_task_ids = build_task_catalog()
    completed_task_rows = db.execute(
        'SELECT task_id FROM completed_tasks WHERE user_id = ?',
        (session['user_id'],)
    ).fetchall()
    completed_tasks = [row['task_id'] for row in completed_task_rows]
    completed_set = set(completed_tasks)

    total_tasks = len(ordered_task_ids)
    completed_count = sum(1 for task_id in ordered_task_ids if task_id in completed_set)
    progress_percent = round((completed_count / total_tasks) * 100) if total_tasks else 0

    recent_rows = db.execute(
        'SELECT task_id FROM completed_tasks WHERE user_id = ? ORDER BY rowid DESC LIMIT 5',
        (session['user_id'],)
    ).fetchall()
    recent_activity = []
    for row in recent_rows:
        task_id = row['task_id']
        task = task_catalog.get(task_id)
        if task:
            recent_activity.append(task)

    next_task = None
    for task_id in ordered_task_ids:
        if task_id not in completed_set:
            next_task = task_catalog.get(task_id)
            break

    photo_rows = db.execute(
        '''SELECT id, filename, uploaded_at
           FROM user_photos
           WHERE user_id = ?
           ORDER BY uploaded_at DESC, id DESC''',
        (session['user_id'],)
    ).fetchall()
    gallery_photos = [
        {
            "id": row['id'],
            "filename": row['filename'],
            "uploaded_at": row['uploaded_at'],
            "url": url_for('gallery_photo', photo_id=row['id'])
        }
        for row in photo_rows
    ]

    return render_template(
        'profile.html',
        username=user['username'],
        avatar_url=avatar_url,
        rang=rang,
        xp=xp,
        hp=hp,
        strike_curent=strike_curent,
        record_strike=record_strike,
        last_date=last_date,
        completed_tasks=completed_tasks,
        completed_count=completed_count,
        total_tasks=total_tasks,
        progress_percent=progress_percent,
        recent_activity=recent_activity,
        next_task=next_task,
        gallery_photos=gallery_photos
    )


# 2. Ruta care afișează pagina web (HTML)
@app.route('/exercices')
def exercices():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if user_needs_onboarding():
        return redirect_to_onboarding(session['user_id'], session.get('username'))
    
    db = get_db()
    user = db.execute(
        'SELECT xp, hp, strike_curent, record_strike, start_world, last_date, avatar, cooldown_until FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()
    
    xp = user['xp']
    hp = user['hp']
    strike_curent = user['strike_curent'] if user['strike_curent'] is not None else 0
    record_strike = user['record_strike'] if user['record_strike'] is not None else 0
    start_world = user['start_world'] if user['start_world'] is not None else 1
    last_date = user['last_date'] if user['last_date'] is not None else "N/A"
    avatar_url = f"/static/avatars/{user['avatar']}" if user['avatar'] else "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"
    cooldown_until = user['cooldown_until']
    cooldown_remaining = active_cooldown_seconds(cooldown_until)

    if hp <= 0 and cooldown_remaining <= 0:
        if cooldown_until:
            hp = 5
            strike_curent = 0
            cooldown_until = None
            db.execute(
                'UPDATE users SET hp = ?, strike_curent = ?, cooldown_until = NULL WHERE id = ?',
                (hp, strike_curent, session['user_id'])
            )
            db.commit()
        else:
            cooldown_until = create_cooldown()
            db.execute(
                'UPDATE users SET cooldown_until = ? WHERE id = ?',
                (cooldown_until, session['user_id'])
            )
            db.commit()
            cooldown_remaining = active_cooldown_seconds(cooldown_until)

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
        last_date=last_date,
        cooldown_until=cooldown_until,
        cooldown_remaining=cooldown_remaining
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
        user = db.execute('SELECT xp, hp, strike_curent, record_strike, cooldown_until FROM users WHERE id = ?', (user_id,)).fetchone()
        cooldown_remaining = active_cooldown_seconds(user['cooldown_until'])
        if user['hp'] is not None and user['hp'] <= 0 and cooldown_remaining <= 0:
            if user['cooldown_until']:
                db.execute(
                    'UPDATE users SET hp = ?, strike_curent = ?, cooldown_until = NULL WHERE id = ?',
                    (5, 0, user_id)
                )
                db.commit()
                user = db.execute('SELECT xp, hp, strike_curent, record_strike, cooldown_until FROM users WHERE id = ?', (user_id,)).fetchone()
            else:
                cooldown_until = create_cooldown()
                db.execute(
                    'UPDATE users SET cooldown_until = ? WHERE id = ?',
                    (cooldown_until, user_id)
                )
                db.commit()
                cooldown_remaining = active_cooldown_seconds(cooldown_until)

        if cooldown_remaining > 0:
            return jsonify({
                "error": "Pauza activă este în desfășurare.",
                "cooldown_active": True,
                "cooldown_remaining": cooldown_remaining
            }), 423
        
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
        cooldown_until = create_cooldown() if hp <= 0 else None
        db.execute('UPDATE users SET xp = ?, hp = ?, strike_curent = ?, record_strike = ?, cooldown_until = ? WHERE id = ?',
                   (xp, hp, strike_curent, record_strike, cooldown_until, user_id))
        if este_corect and task_id and not already_completed:
            db.execute(
                'INSERT OR IGNORE INTO completed_tasks (user_id, task_id) VALUES (?, ?)',
                (user_id, str(task_id))
            )
        db.commit()


        # 3. Trimitem rezultatul către frontend (browser)
        return jsonify({
            "scor": scor,               # Trimitem scorul pentru a declanșa animația
            "corect": este_corect,      # Decide dacă exercițiul devine verde/bifat
            "feedback": feedback,
            "new_xp": xp,
            "new_hp": hp,
            "strike_curent": strike_curent,
            "cooldown_until": cooldown_until,
            "cooldown_remaining": active_cooldown_seconds(cooldown_until)
        })

    except Exception as e:
        print(f"Eroare la verificare AI: {e}")
        return jsonify({"error": "Eroare la evaluarea răspunsului."}), 500


@app.route('/api/reset_lives', methods=['POST'])
def reset_lives():
    if 'user_id' not in session:
        return jsonify({"error": "Neautentificat"}), 401

    db = get_db()
    user = db.execute(
        'SELECT cooldown_until FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()
    if user and active_cooldown_seconds(user['cooldown_until']) > 0:
        return jsonify({
            "ok": False,
            "cooldown_active": True,
            "cooldown_remaining": active_cooldown_seconds(user['cooldown_until'])
        }), 423

    db.execute(
        'UPDATE users SET hp = ?, strike_curent = ?, cooldown_until = NULL WHERE id = ?',
        (5, 0, session['user_id'])
    )
    db.commit()

    return jsonify({
        "ok": True,
        "hp": 5,
        "strike_curent": 0
    })


if __name__ == "__main__":
    init_db()
    threading.Timer(1.0, open_in_chrome, args=("http://127.0.0.1:5000",)).start()
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
