import os
import sqlite3
import datetime
from flask import Flask, request, jsonify, render_template
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_super_secret_key_12345'  # JWT 加密金鑰
DATABASE = os.path.join(os.path.dirname(__file__), 'landlord.db')

# ---- 資料庫初始化 ----
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # 使用者資料表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        # 出租處資料表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                type TEXT NOT NULL,
                rent INTEGER NOT NULL,
                notes TEXT,
                image_url TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        # 合約資料表 (is_active: 1=進行中, 0=歷史合約)
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
        conn.commit()

# ---- JWT 驗證裝飾器 ----
def token_required(f):
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(" ")[1]
        
        if not token:
            return jsonify({'message': '缺少 Token，請先登入！'}), 401
        
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user_id = data['user_id']
        except Exception as e:
            return jsonify({'message': 'Token 無效或已過期！'}), 401
            
        return f(current_user_id, *args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

# ---- 頁面路由 ----
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# ---- 認證 API ----
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'message': '欄位不可為空'}), 400
        
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    
    try:
        with get_db() as conn:
            conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
            conn.commit()
        return jsonify({'message': '註冊成功！'})
    except sqlite3.IntegrityError:
        return jsonify({'message': '該帳戶名稱已存在！'}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    with get_db() as conn:
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
    if user and check_password_hash(user['password'], password):
        token = jwt.encode({
            'user_id': user['id'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.config['SECRET_KEY'], algorithm="HS256")
        return jsonify({'token': token, 'username': user['username']})
        
    return jsonify({'message': '帳號或密碼錯誤！'}), 412

# ---- 出租處 API ----
@app.route('/api/properties', methods=['GET', 'POST'])
@token_required
def manage_properties(current_user_id):
    conn = get_db()
    if request.method == 'GET':
        rows = conn.execute('SELECT * FROM properties WHERE user_id = ?', (current_user_id,)).fetchall()
        return jsonify([dict(r) for r in rows])
        
    elif request.method == 'POST':
        data = request.get_json()
        pid = data.get('id') # 用於編輯判斷
        name = data.get('name')
        address = data.get('address')
        room_type = data.get('type')
        rent = data.get('rent')
        notes = data.get('notes')
        image_url = data.get('image_url', 'https://images.unsplash.com/photo-1564013799919-ab600027ffc6?auto=format&fit=crop&w=300&q=80')
        
        if pid: # 編輯資料
            conn.execute('''
                UPDATE properties SET name=?, address=?, type=?, rent=?, notes=?, image_url=? 
                WHERE id=? AND user_id=?
            ''', (name, address, room_type, rent, notes, image_url, pid, current_user_id))
        else: # 新增資料
            conn.execute('''
                INSERT INTO properties (user_id, name, address, type, rent, notes, image_url) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (current_user_id, name, address, room_type, rent, notes, image_url))
        conn.commit()
        return jsonify({'message': '儲存出租處成功！'})

# ---- 合約 API ----
@app.route('/api/contracts', methods=['GET', 'POST'])
@token_required
def manage_contracts(current_user_id):
    conn = get_db()
    if request.method == 'GET':
        # 聯集 property 的圖片與名稱
        rows = conn.execute('''
            SELECT c.*, p.name as property_name, p.image_url as property_image 
            FROM contracts c
            JOIN properties p ON c.property_id = p.id
            WHERE c.user_id = ?
        ''', (current_user_id,)).fetchall()
        return jsonify([dict(r) for r in rows])
        
    elif request.method == 'POST':
        data = request.get_json()
        cid = data.get('id')
        property_id = data.get('property_id')
        tenant_name = data.get('tenant_name')
        tenant_id_card = data.get('tenant_id_card')
        tenant_phone = data.get('tenant_phone')
        contract_period = data.get('contract_period')
        payment_status = data.get('payment_status')
        room_type = data.get('room_type')
        rent = data.get('rent')
        water = data.get('water')
        electricity = data.get('electricity')
        notes = data.get('notes')
        
        if cid: # 編輯
            conn.execute('''
                UPDATE contracts SET property_id=?, tenant_name=?, tenant_id_card=?, tenant_phone=?, 
                contract_period=?, payment_status=?, room_type=?, rent=?, water=?, electricity=?, notes=?
                WHERE id=? AND user_id=?
            ''', (property_id, tenant_name, tenant_id_card, tenant_phone, contract_period, payment_status, room_type, rent, water, electricity, notes, cid, current_user_id))
        else: # 新增
            conn.execute('''
                INSERT INTO contracts (user_id, property_id, tenant_name, tenant_id_card, tenant_phone, contract_period, payment_status, room_type, rent, water, electricity, notes, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (current_user_id, property_id, tenant_name, tenant_id_card, tenant_phone, contract_period, payment_status, room_type, rent, water, electricity, notes))
        conn.commit()
        return jsonify({'message': '儲存合約成功！'})

@app.route('/api/contracts/<int:cid>/terminate', methods=['POST'])
@token_required
def terminate_contract(current_user_id, cid):
    conn = get_db()
    conn.execute('UPDATE contracts SET is_active = 0 WHERE id = ? AND user_id = ?', (cid, current_user_id))
    conn.commit()
    return jsonify({'message': '合約已終止並移至歷史區'})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)