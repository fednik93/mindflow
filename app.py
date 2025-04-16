from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # для flash-сообщений

def get_db_connection():
    conn = sqlite3.connect('notes.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = get_db_connection()
    notes = conn.execute('SELECT * FROM notes ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('index.html', notes=notes)

@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        if not title or not content:
            flash("Заполните все поля!", "warning")
            return redirect(url_for('add'))
        conn = get_db_connection()
        conn.execute('INSERT INTO notes (title, content) VALUES (?, ?)', (title, content))
        conn.commit()
        conn.close()
        flash("Заметка успешно добавлена!", "success")
        return redirect(url_for('index'))
    return render_template('add.html')

@app.route('/edit/<int:note_id>', methods=['GET', 'POST'])
def edit(note_id):
    conn = get_db_connection()
    note = conn.execute('SELECT * FROM notes WHERE id = ?', (note_id,)).fetchone()
    if not note:
        flash("Заметка не найдена!", "danger")
        return redirect(url_for('index'))
    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        if not title or not content:
            flash("Заполните все поля!", "warning")
            return redirect(url_for('edit', note_id=note_id))
        conn.execute('UPDATE notes SET title = ?, content = ? WHERE id = ?', (title, content, note_id))
        conn.commit()
        conn.close()
        flash("Заметка успешно обновлена!", "success")
        return redirect(url_for('index'))
    conn.close()
    return render_template('edit.html', note=note)

@app.route('/delete/<int:note_id>', methods=['POST'])
def delete(note_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM notes WHERE id = ?', (note_id,))
    conn.commit()
    conn.close()
    flash("Заметка удалена!", "info")
    return redirect(url_for('index'))

@app.route('/search', methods=['GET', 'POST'])
def search():
    results = []
    query = ""
    if request.method == 'POST':
        query = request.form['query'].strip()
        conn = get_db_connection()
        results = conn.execute("SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? ORDER BY created_at DESC",
                              ('%' + query + '%', '%' + query + '%')).fetchall()
        conn.close()
    return render_template('search.html', results=results, query=query)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
