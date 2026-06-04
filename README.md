# AI Tutor Linux / LinuxEdu

AI Tutor Linux este o aplicație Flask pentru învățarea comenzilor Linux prin exerciții progresive, feedback AI și funcții sociale de bază. Platforma include autentificare, onboarding cu test de nivel, hartă de exerciții, chat cu tutor AI, profil, prieteni, mesaje, clasament și panou de administrare.

## Tehnologii folosite

- Python + Flask
- PostgreSQL pe Supabase
- Render pentru deploy
- Jinja templates
- HTML, CSS și JavaScript vanilla
- Groq API pentru răspunsuri AI
- Flask-Mail pentru resetarea parolei
- `psycopg2-binary` pentru conexiunea PostgreSQL
- `pypdf` pentru încărcarea materialului PDF

## Structura proiectului

```text
.
├── app.py                         # aplicația Flask principală
├── pdf_loader.py                  # helper pentru citirea PDF-ului din data/
├── requirements.txt               # dependențe pentru deploy
├── migrate_sqlite_to_postgres.py  # script temporar de migrare date SQLite -> PostgreSQL
├── data/
│   ├── exercices.json             # structura cursului și exercițiilor
│   └── AI-tutor-linux resurse.pdf # material de suport pentru tutor
├── templates/                     # pagini Jinja
├── static/
│   ├── style.css                  # stiluri aplicație
│   ├── avatars/                   # avataruri încărcate de utilizatori
│   └── uploads/                   # fișiere încărcate de utilizatori
├── tests/                         # teste existente, de actualizat după migrarea PostgreSQL
└── docs/                          # documentație auxiliară
```

Scripturile locale precum `reset_hp.py`, `update_data.py`, `generate_qr.py` și `run_tunnel.py` sunt auxiliare și nu sunt necesare pentru runtime-ul Render.

## Funcționalități principale

- Autentificare și creare cont.
- Resetare parolă prin email.
- Onboarding cu alegere nivel sau test de plasare.
- Hartă de exerciții Linux, cu XP, HP și strike.
- Evaluare AI a răspunsurilor la exerciții.
- Chat separat cu Tutor AI.
- Profil utilizator cu progres și galerie.
- Prieteni, cereri de prietenie, mesaje private și clasament.
- Panou admin pentru gestionarea utilizatorilor.

## PostgreSQL / Supabase

Aplicația folosește PostgreSQL prin variabila de mediu:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
```

Tabelele principale sunt create automat la pornire dacă nu există:

- `users`
- `completed_tasks`
- `user_photos`
- `friend_requests`
- `friendships`
- `messages`

Pentru migrarea datelor din SQLite local către Supabase, scriptul `migrate_sqlite_to_postgres.py` poate fi rulat local după setarea `DATABASE_URL`. Scriptul păstrează ID-urile existente și actualizează secvențele PostgreSQL pentru tabelele cu `SERIAL`.

## Rulare locală

1. Creează și activează un mediu virtual.
2. Instalează dependențele:

```bash
pip install -r requirements.txt
```

3. Setează variabilele de mediu necesare, în special `DATABASE_URL`.
4. Pornește aplicația:

```bash
python app.py
```

Aplicația rulează implicit pe:

```text
http://127.0.0.1:5000
```

## Deploy pe Render

Setări recomandate:

- Build command:

```bash
pip install -r requirements.txt
```

- Start command:

```bash
gunicorn app:app
```

Variabile de mediu necesare:

```text
DATABASE_URL
```

Pentru funcții de email și AI, aplicația are nevoie și de configurările corespunzătoare pentru SMTP și Groq API. În versiunea finală, parolele și cheile API trebuie mutate în variabile de mediu, nu păstrate în cod.

## Note pentru versiunea finală

- `database.db` este doar pentru date locale vechi și nu trebuie folosit în producție.
- Uploadurile utilizatorilor din `static/avatars/` și `static/uploads/` nu ar trebui versionate în Git.
- Testele existente trebuie actualizate pentru PostgreSQL, deoarece au fost scrise inițial pentru SQLite.
