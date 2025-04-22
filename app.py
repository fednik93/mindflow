from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import (
    LoginManager, UserMixin,
    login_user, login_required, logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3

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
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
      )
    ''')

    # Категории
    conn.execute('''
      CREATE TABLE IF NOT EXISTS categories (
        id    INTEGER PRIMARY KEY AUTOINCREMENT,
        name  TEXT UNIQUE NOT NULL
      )
    ''')

    # Заметки
    conn.execute('''
      CREATE TABLE IF NOT EXISTS notes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT    NOT NULL,
        content     TEXT    NOT NULL,
        date        TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id     INTEGER,
        category_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (category_id) REFERENCES categories(id)
      )
    ''')

    conn.commit()
    conn.close()

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
                conn.execute(
                    'INSERT INTO users (username,password) VALUES (?,?)',
                    (username, generate_password_hash(password))
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
      WHERE n.user_id = ?
      ORDER BY n.created_at DESC
    ''', (current_user.id,)).fetchall()
    conn.close()
    return render_template('index.html', notes=notes)

@app.route('/add', methods=['GET','POST'])
@login_required
def add():
    conn = get_db_connection()
    cats = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    if request.method == 'POST':
        title       = request.form['title'].strip()
        content     = request.form['content'].strip()
        date        = request.form['date'].strip()
        category_id = request.form.get('category_id') or None
        if not title or not content or not date:
            flash("Заполните все обязательные поля", "warning")
            conn.close()
            return redirect(url_for('add'))
        conn.execute('''
          INSERT INTO notes (title, content, date, category_id, user_id)
          VALUES (?,?,?,?,?)
        ''', (title, content, date, category_id, current_user.id))
        conn.commit()
        conn.close()
        flash("Заметка добавлена", "success")
        return redirect(url_for('index'))
    conn.close()
    return render_template('add.html', categories=cats)

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
        title       = request.form['title'].strip()
        content     = request.form['content'].strip()
        date        = request.form['date'].strip()
        category_id = request.form.get('category_id') or None
        if not title or not content or not date:
            flash("Заполните все обязательные поля", "warning")
            return redirect(url_for('edit', note_id=note_id))
        conn.execute('''
          UPDATE notes
          SET title=?, content=?, date=?, category_id=?
          WHERE id=? AND user_id=?
        ''', (title, content, date, category_id, note_id, current_user.id))
        conn.commit()
        conn.close()
        flash("Заметка обновлена", "success")
        return redirect(url_for('index'))
    conn.close()
    return render_template('edit.html', note=note, categories=cats)

@app.route('/delete/<int:note_id>', methods=['POST'])
@login_required
def delete(note_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM notes WHERE id = ? AND user_id = ?', (note_id, current_user.id))
    conn.commit()
    conn.close()
    flash("Заметка удалена", "info")
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
      SELECT id, title, date
      FROM notes
      WHERE date IS NOT NULL AND user_id = ?
    ''', (current_user.id,)).fetchall()
    conn.close()
    events = [{
        'title': row['title'],
        'start': row['date'],
        'url': url_for('edit', note_id=row['id'])
    } for row in rows]
    return render_template('calendar.html', events=events)

# === Точка входа ===
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
