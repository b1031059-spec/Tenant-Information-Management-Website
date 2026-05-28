import sqlite3
import os

DATABASE = os.path.join(os.path.dirname(__file__), 'landlord.db')

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # 1. 使用者資料表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        # 2. 出租處資料表 (預設圖值為 'noimage')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                type TEXT NOT NULL,
                rent INTEGER NOT NULL,
                notes TEXT,
                image_url TEXT DEFAULT 'noimage',
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        # 3. 合約資料表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                property_id INTEGER NOT NULL,
                tenant_name TEXT NOT NULL,
                tenant_id_card TEXT NOT NULL,
                tenant_phone TEXT NOT NULL,
                contract_period TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                room_type TEXT NOT NULL,
                rent INTEGER NOT NULL,
                water INTEGER NOT NULL,
                electricity INTEGER NOT NULL,
                notes TEXT,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(property_id) REFERENCES properties(id)
            )
        ''')
        # 4. 新增：合約繳費歷史紀錄表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                contract_id INTEGER NOT NULL,
                payment_month TEXT NOT NULL, -- 格式: YYYY-MM
                amount INTEGER NOT NULL,
                paid_at TEXT NOT NULL,       -- 實際按下收租的日期時間
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(contract_id) REFERENCES contracts(id)
            )
        ''')
        conn.commit()

init_db()