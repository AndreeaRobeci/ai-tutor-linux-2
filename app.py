from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, g
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from gpt4all import GPT4All
from pdf_loader import load_pdf_text
import os
import json
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

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

MODEL_PATH = os.path.join("models", "Llama-3.2-3B-Instruct-Q4_0.gguf")
model = None
model_error = None

# --- LOGICĂ BAZĂ DE DATE ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

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
            streak INTEGER DEFAULT 0, last_date TEXT)''')
        db.commit()

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
            session['username'] = user['username']
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
        db.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)', (username, email, hashed_pw))
        db.commit()
        flash('Cont creat! Te poți conecta.')
    except:
        flash('Username sau Email deja existent!')
    return redirect(url_for('login'))

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
                <h3 style="color: #1a1a2e; text-align: center;">Recuperare Parolă - AI Tutor</h3>
                <p>Salut!</p>
                <p>Apasă pe butonul de mai jos pentru a alege o parolă nouă:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="padding: 12px 20px; background-color: #8ba888; color: white; text-decoration: none; border-radius: 8px; font-weight: bold;">Resetează Parola direct aici</a>
                </div>
                <p style="font-size: 0.8em; color: #999; text-align: center; margin-top: 20px;">Link-ul expiră în 30 de minute.</p>
            </div>
            """
            
            mail.send(msg)
            flash('Ți-am trimis un mail cu instrucțiuni!')
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
        
    user_id = session['user_id']
    
    import sqlite3
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    try:
        # Acum extragem și avatarul
        cursor.execute("SELECT xp, hp, streak, last_date, avatar FROM users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
    except sqlite3.OperationalError:
        user_data = None
        
    conn.close()
    
    if user_data:
        xp = user_data[0] if user_data[0] is not None else 0
        hp = user_data[1] if user_data[1] is not None else 5
        streak = user_data[2] if user_data[2] is not None else 0
        last_date = user_data[3] if user_data[3] is not None else "N/A"
        
        # Dacă are avatar în baza de date, îi creăm calea. Dacă nu, îi punem poza default.
        avatar_db = user_data[4] if len(user_data) > 4 and user_data[4] else None
        if avatar_db:
            avatar_url = f"/static/avatars/{avatar_db}"
        else:
            avatar_url = "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"
    else:
        xp, hp, streak, last_date, avatar_url = 0, 5, 0, "N/A", "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"
        
    if xp < 50:
        rang = "🟢 Newbie Linux"
    elif xp < 150:
        rang = "🔵 Terminal Explorer"
    else:
        rang = "🟣 Script Hacker"
        
    return render_template("index.html", xp=xp, hp=hp, streak=streak, last_date=last_date, rang=rang, avatar_url=avatar_url)


@app.route("/exercices")
def exercices_page():
    # 1. Verificăm dacă utilizatorul este logat
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    # 2. Ne conectăm la baza de date pentru a lua statisticile (hp, xp, streak)
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()

    # 3. Trimitem datele către fișierul exercices.html
    return render_template("exercices.html", hp=user['hp'], xp=user['xp'], streak=user['streak'])

# 2. Ruta pentru JAVASCRIPT (Trimite datele din JSON în fundal)
@app.route('/api/exercices')
def get_exercices_data():
    import os
    import json
    json_path = os.path.join('data', 'exercices.json') # Asigură-te că folderul se numește 'data'
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)