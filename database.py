import sqlite3
from datetime import datetime

DB_PATH = "anket.db"

def get_all_roles():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT id, name FROM role").fetchall()

def get_role_name(role_id):
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT name FROM role WHERE id = ?", (role_id,)).fetchone()
        return res[0] if res else "Неизвестно"

def get_role_description(role_id):
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT duties FROM role WHERE id = ?", (role_id,)).fetchone()
        return res[0] if res else "Описание не найдено."

def get_sub_roles(role_id):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT id, name FROM sub_role WHERE role_id = ?", (role_id,)).fetchall()

def get_sub_role_name(sub_role_id):
    if not sub_role_id: return None
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT name FROM sub_role WHERE id = ?", (sub_role_id,)).fetchone()
        return res[0] if res else None

def ensure_user_exists(user_id, username, first_name):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM [user] WHERE id = ?", (user_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO [user] (id, username, first_name, joined_at, banned) VALUES (?, ?, ?, ?, 0)", 
                (user_id, username, first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()

def save_application(user_id, role_id, sub_role_id, form_text):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO application (submitted, status, form, sub_role_id, user_id, role_id) VALUES (?, 0, ?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), form_text, sub_role_id, user_id, role_id)
        )
        conn.commit()

def get_new_applications():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT a.id, a.form, r.name, u.first_name, u.id, u.username, a.sub_role_id "
            "FROM application a JOIN role r ON a.role_id = r.id JOIN [user] u ON a.user_id = u.id WHERE a.status = 0"
        ).fetchall()

def update_application_status(app_id, status):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE application SET status = ? WHERE id = ?", (status, app_id))
        conn.commit()

def delete_application(app_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM application WHERE id = ?", (app_id,))
        conn.commit()

def ban_user(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE [user] SET banned = 1 WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM application WHERE user_id = ?", (user_id,))
        conn.commit()

def is_user_banned(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT banned FROM [user] WHERE id = ?", (user_id,)).fetchone()
        return bool(res[0]) if res else False

def unban_user(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE [user] SET banned = 0 WHERE id = ?", (user_id,))
        conn.commit()