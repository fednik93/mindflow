from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import (
    LoginManager, UserMixin,
    login_user, login_required, logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import pathlib
import cachecontrol
import google.auth.transport.requests
from flask import session
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # для локального теста без https
import random, string
GOOGLE_CLIENT_ID = "ТВОЙ_CLIENT_ID_ИЗ_GOOGLE"
client_secrets_file = os.path.join(pathlib.Path(__file__).parent, "credentials.json")

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

# === Инициализация приложения и логина ===
app = Flask(__name__)
app.secret_key = 'your_secret_key'

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)
login_manager.login_message = "🔒 Пожалуйста, авторизуйтесь для доступа к этой странице"
login_manager.login_message_category = "info"

# === Пользовательская модель для Flask-Login ===
class User(UserMixin):
    def __init__(self, row):
        self.id = row['id']
        self.username = row['username']
        self.first_name = row['first_name'] if 'first_name' in row.keys() else ''
        self.last_name = row['last_name'] if 'last_name' in row.keys() else ''
        self.age = row['age'] if 'age' in row.keys() else None
        self.avatar = row['avatar'] if 'avatar' in row.keys() else 'default.png'
        self.group_code = row['group_code'] if 'group_code' in row.keys() else None
def generate_group_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return User(row) if row else None

# === Работа с БД ===
def get_db_connection():
    conn = sqlite3.connect('notes.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()

    # Пользователи
    conn.execute('''
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        first_name TEXT,
        last_name TEXT,
        age INTEGER,
        avatar TEXT DEFAULT 'default.png',
        group_code TEXT
      )
    ''')
    # Категории
    conn.execute('''
      CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
      )
    ''')

    # Заметки
    conn.execute('''
      CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        date TEXT,
        start_time TEXT,
        end_time TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id INTEGER,
        category_id INTEGER,
        google_event_id TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (category_id) REFERENCES categories(id)
      )
    ''')

    # 🔥 Добавляем категории, если их ещё нет
    default_categories = ["Важные дела", "Учёба", "Работа", "Личное", "Остальное"]
    for cat in default_categories:
        try:
            conn.execute('INSERT INTO categories (name) VALUES (?)', (cat,))
        except sqlite3.IntegrityError:
            pass  # Категория уже есть — пропускаем

    conn.commit()
    conn.close()
def get_google_service():
    if 'credentials' not in session:
        return None

    creds = google.oauth2.credentials.Credentials(**session['credentials'])
    return build('calendar', 'v3', credentials=creds)

def create_google_event(title, content, date, start_time=None, end_time=None):
    service = get_google_service()
    if not service:
        return None

    event = {
        'summary': title,
        'description': content,
        'start': {
            'dateTime': f"{date}T{start_time}:00" if start_time else f"{date}T00:00:00",
            'timeZone': 'Europe/Moscow',
        },
        'end': {
            'dateTime': f"{date}T{end_time}:00" if end_time else f"{date}T23:59:00",
            'timeZone': 'Europe/Moscow',
        },
    }
    created_event = service.events().insert(calendarId='primary', body=event).execute()
    return created_event['id']

def update_google_event(event_id, title, content, date):
    service = get_google_service()
    if not service:
        return

    event = {
        'summary': title,
        'description': content,
        'start': {'date': date, 'timeZone': 'Europe/Moscow'},
        'end': {'date': date, 'timeZone': 'Europe/Moscow'}
    }
    service.events().update(calendarId='primary', eventId=event_id, body=event).execute()

def delete_google_event(event_id):
    service = get_google_service()
    if not service:
        return

    service.events().delete(calendarId='primary', eventId=event_id).execute()

# === Маршруты авторизации ===
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if not username or not password:
            flash("Заполните оба поля", "warning")
        else:
            conn = get_db_connection()
            try:
                group_code = generate_group_code()
                conn.execute(
                    'INSERT INTO users (username, password, group_code) VALUES (?, ?, ?)',
                    (username, generate_password_hash(password), group_code)
                )
                conn.commit()
                user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
                login_user(User(user))  # автоматический вход
                conn.close()
                flash("Добро пожаловать, вы успешно зарегистрированы!", "success")
                return redirect(url_for('index'))

            except sqlite3.IntegrityError:
                flash("Пользователь уже существует", "danger")
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        conn = get_db_connection()
        row = conn.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()
        conn.close()
        if row and check_password_hash(row['password'], password):
            login_user(User(row))
            return redirect(url_for('index'))
        flash("Неправильное имя или пароль", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# === CRUD категорий ===
@app.route('/categories', methods=['GET','POST'])
@login_required
def categories():
    conn = get_db_connection()
    if request.method == 'POST':
        name = request.form['name'].strip()
        if name:
            try:
                conn.execute('INSERT INTO categories (name) VALUES (?)', (name,))
                conn.commit()
            except sqlite3.IntegrityError:
                flash("Такая категория уже есть", "warning")
    cats = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return render_template('categories.html', categories=cats)

# === CRUD заметок ===
@app.route('/')
@login_required
def index():
    conn = get_db_connection()
    notes = conn.execute('''
      SELECT n.*, c.name AS category_name
      FROM notes n
      LEFT JOIN categories c ON n.category_id = c.id
      JOIN users u ON u.id = n.user_id
      WHERE u.group_code = ?
      ORDER BY n.created_at DESC
    ''', (current_user.group_code,)).fetchall()
    conn.close()
    return render_template('index.html', notes=notes)

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    conn = get_db_connection()
    cats = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()

    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        date = request.form['date'].strip()
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        category_id = request.form.get('category_id') or None

        if not title or not content or not date:
            flash("Заполните все обязательные поля", "warning")
            conn.close()
            return redirect(url_for('add'))

        google_event_id = None
        try:
            if 'credentials' in session:
                google_event_id = create_google_event(title, content, date, start_time, end_time)
        except Exception as e:
            print(f"Ошибка создания события в Google: {e}")

        conn.execute('''
          INSERT INTO notes (title, content, date, start_time, end_time, category_id, user_id, google_event_id)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (title, content, date, start_time, end_time, category_id, current_user.id, google_event_id))
        conn.commit()
        conn.close()

        flash("Заметка добавлена и синхронизирована!", "success")
        return redirect(url_for('index'))

    # ВАЖНО: передаем значения из запроса в шаблон
    date_default = request.args.get('date', '')
    start_time_default = request.args.get('start_time', '')
    end_time_default = request.args.get('end_time', '')

    conn.close()
    return render_template('add.html', categories=cats,
                            date_default=date_default,
                            start_time_default=start_time_default,
                            end_time_default=end_time_default)

@app.route('/edit/<int:note_id>', methods=['GET','POST'])
@login_required
def edit(note_id):
    conn = get_db_connection()
    note = conn.execute('SELECT * FROM notes WHERE id = ? AND user_id = ?', (note_id, current_user.id)).fetchone()
    cats = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()

    if not note:
        conn.close()
        flash("Заметка не найдена", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        date = request.form['date'].strip()
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        category_id = request.form.get('category_id') or None

        if not title or not content or not date:
            flash("Заполните все обязательные поля", "warning")
            conn.close()
            return redirect(url_for('edit', note_id=note_id))

        if note['google_event_id']:
            try:
                update_google_event(note['google_event_id'], title, content, date)
            except Exception as e:
                print(f"Ошибка обновления события в Google: {e}")

        conn.execute('''
          UPDATE notes
          SET title=?, content=?, date=?, start_time=?, end_time=?, category_id=?
          WHERE id=? AND user_id=?
        ''', (title, content, date, start_time, end_time, category_id, note_id, current_user.id))
        conn.commit()
        conn.close()

        flash("Заметка обновлена!", "success")
        return redirect(url_for('index'))

    conn.close()
    return render_template('edit.html', note=note, categories=cats)
@app.route('/delete/<int:note_id>', methods=['POST'])
@login_required
def delete(note_id):
    conn = get_db_connection()
    note = conn.execute('''
        SELECT n.user_id, n.google_event_id, u.group_code AS owner_group
        FROM notes n
        JOIN users u ON u.id = n.user_id
        WHERE n.id = ?
    ''', (note_id,)).fetchone()

    if note and (note['user_id'] == current_user.id or note['owner_group'] == current_user.group_code):
        try:
            if 'credentials' in session and note['google_event_id']:
                delete_google_event(note['google_event_id'])
        except Exception as e:
            print(f"Ошибка удаления события в Google: {e}")

        conn.execute('DELETE FROM notes WHERE id = ?', (note_id,))
        conn.commit()
        flash("Заметка удалена!", "info")
    else:
        flash("⚠️ Нет прав для удаления этой заметки", "warning")

    conn.close()
    return redirect(url_for('index'))
@app.route('/search', methods=['GET','POST'])
@login_required
def search():
    results = []
    query = ""
    if request.method == 'POST':
        query = request.form['query'].strip()
        conn = get_db_connection()
        results = conn.execute('''
          SELECT * FROM notes
          WHERE user_id = ?
            AND (title LIKE ? OR content LIKE ?)
          ORDER BY created_at DESC
        ''', (current_user.id, f'%{query}%', f'%{query}%')).fetchall()
        conn.close()
    return render_template('search.html', results=results, query=query)

@app.route('/calendar')
@login_required
def calendar_view():
    conn = get_db_connection()
    rows = conn.execute('''
      SELECT n.id, n.title, n.date, n.start_time, n.end_time, c.name AS category_name
      FROM notes n
      LEFT JOIN categories c ON n.category_id = c.id
      JOIN users u ON u.id = n.user_id
      WHERE u.group_code = ?

    ''', (current_user.group_code,)).fetchall()
    conn.close()

    # Цвета по категориям
    color_map = {
        "Важные дела": "#e74c3c",    # Красный
        "Учёба": "#3498db",          # Синий
        "Работа": "#2ecc71",         # Зелёный
        "Личное": "#e67e22",         # Оранжевый
        "Остальное": "#9b59b6",      # Фиолетовый
    }

    events = []
    for row in rows:
        start = row['date']
        end = row['date']

        if row['start_time']:
            start = f"{row['date']}T{row['start_time']}"
        if row['end_time']:
            end = f"{row['date']}T{row['end_time']}"

        events.append({
            'title': row['title'],
            'start': start,
            'end': end,
            'backgroundColor': color_map.get(row['category_name'], "#95a5a6"),  # Если категории нет, серый цвет
            'borderColor': color_map.get(row['category_name'], "#95a5a6"),
            'url': url_for('edit', note_id=row['id'])
        })

    return render_template('calendar.html', events=events)
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    if not row:
        conn.close()
        flash("Пользователь не найден", "danger")
        return redirect(url_for('index'))

    avatar = row['avatar'] or 'default.png'
    first_name = row['first_name'] or ''
    last_name = row['last_name'] or ''
    age = row['age'] or ''
    group_code = row['group_code'] or '—'

    avatars_folder = os.path.join(app.static_folder, 'avatars')
    avatars = [f for f in os.listdir(avatars_folder) if os.path.isfile(os.path.join(avatars_folder, f))]

    notes_count = conn.execute('SELECT COUNT(*) FROM notes WHERE user_id = ?', (current_user.id,)).fetchone()[0]

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'join_group':
            join_code = request.form.get('join_group').strip().upper()
            exists = conn.execute('SELECT 1 FROM users WHERE group_code = ?', (join_code,)).fetchone()
            if exists:
                conn.execute('UPDATE users SET group_code = ? WHERE id = ?', (join_code, current_user.id))
                flash('✅ Вы успешно присоединились к группе!', 'success')
            else:
                flash('❌ Группа с таким кодом не найдена', 'danger')
            conn.commit()
            conn.close()
            return redirect(url_for('profile'))

        elif action == 'leave_group':
            conn.execute('UPDATE users SET group_code = NULL WHERE id = ?', (current_user.id,))
            conn.commit()
            conn.close()
            flash('❎ Вы вышли из группы', 'info')
            return redirect(url_for('profile'))

        else:
            selected_avatar = request.form.get('avatar')
            first_name = request.form.get('first_name').strip()
            last_name = request.form.get('last_name').strip()
            age = request.form.get('age')
            conn.execute('''
              UPDATE users
              SET avatar = ?, first_name = ?, last_name = ?, age = ?
              WHERE id = ?
            ''', (selected_avatar, first_name, last_name, age, current_user.id))
            conn.commit()
            conn.close()
            flash('Профиль обновлён!', 'success')
            return redirect(url_for('profile'))

    conn.close()
    return render_template('profile.html',
                           avatar=avatar,
                           avatars=avatars,
                           group_code=group_code,
                           notes_count=notes_count,
                           first_name=first_name,
                           last_name=last_name,
                           age=age)
@app.route("/authorize")
@login_required
def authorize():
    flow = Flow.from_client_secrets_file(
        client_secrets_file=client_secrets_file,
        scopes=SCOPES,
        redirect_uri=url_for('callback', _external=True)
    )

    # Добавляем параметр prompt=select_account, чтобы всегда показывался выбор аккаунта
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='select_account'  # Добавлено для выбора аккаунта
    )

    session['state'] = state
    return redirect(authorization_url)
@app.route("/callback")
@login_required
def callback():
    flow = Flow.from_client_secrets_file(
        client_secrets_file=client_secrets_file,
        scopes=SCOPES,
        redirect_uri=url_for('callback', _external=True)
    )

    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

    flash('✅ Успешная авторизация с Google!', 'success')
    return redirect(url_for('sync_notes'))
@app.route('/sync_notes')
@login_required
def sync_notes():
    if 'credentials' not in session:
        flash('⚠️ Сначала авторизуйтесь через Google', 'warning')
        return redirect(url_for('authorize'))

    creds = google.oauth2.credentials.Credentials(**session['credentials'])
    service = build('calendar', 'v3', credentials=creds)

    conn = get_db_connection()
    notes = conn.execute('''
        SELECT n.id, n.title, n.content, n.date
        FROM notes n
        JOIN users u ON u.id = n.user_id
        WHERE u.group_code = ? AND n.date IS NOT NULL AND n.google_event_id IS NULL
        ''',
        (current_user.group_code,)
    ).fetchall()

    for note in notes:
        event = {
            'summary': note['title'],
            'description': note['content'],
            'start': {
                'date': note['date'],
                'timeZone': 'Europe/Moscow',
            },
            'end': {
                'date': note['date'],
                'timeZone': 'Europe/Moscow',
            },
        }
        try:
            created_event = service.events().insert(calendarId='primary', body=event).execute()
            event_id = created_event.get('id')

            # Сохраняем event_id обратно в базу
            conn.execute(
                'UPDATE notes SET google_event_id = ? WHERE id = ?',
                (event_id, note['id'])
            )
            conn.commit()

        except Exception as e:
            print(f"Ошибка при создании события: {e}")
            flash('❗ Произошла ошибка при синхронизации некоторых заметок', 'danger')
            conn.close()
            return redirect(url_for('index'))

    conn.close()
    flash('✅ Все новые заметки синхронизированы с Google Календарем!', 'success')
    return redirect(url_for('calendar_view'))

# === Точка входа ===
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
