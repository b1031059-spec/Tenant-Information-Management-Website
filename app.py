import os
import sqlite3
import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import jwt

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_super_secret_key_12345'

# 設定圖片上傳資料夾（與 app.py 同目錄下的 uploads）
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DATABASE = os.path.join(os.path.dirname(__file__), 'landlord.db')

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ---- JWT 驗證裝飾器 ----
def token_required(f):
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(" ")[1]
        if not token:
            return jsonify({'message': '缺少 Token'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user_id = data['user_id']
        except:
            return jsonify({'message': 'Token 無效或已過期'}), 401
        return f(current_user_id, *args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

# ---- 靜態圖片下載與讀取路由 ----
@app.route('/uploads/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ---- 頁面路由 ----
@app.route('/')
def index(): return render_template('index.html')

@app.route('/dashboard')
def dashboard(): return render_template('dashboard.html')

# ---- 認證 API ----
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username, password = data.get('username'), data.get('password')
    if not username or not password: return jsonify({'message': '欄位不可為空'}), 400
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
    user = get_db().execute('SELECT * FROM users WHERE username = ?', (data.get('username'),)).fetchone()
    if user and check_password_hash(user['password'], data.get('password')):
        token = jwt.encode({'user_id': user['id'], 'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)}, app.config['SECRET_KEY'], algorithm="HS256")
        return jsonify({'token': token, 'username': user['username']})
    return jsonify({'message': '帳號或密碼錯誤！'}), 412

# ---- 房屋圖片上傳 API ----
@app.route('/api/upload', methods=['POST'])
@token_required
def upload_image(current_user_id):
    if 'file' not in request.files:
        return jsonify({'message': '沒有檔案部分'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'message': '未選擇檔案'}), 400
    
    # 重新命名防重複並儲存
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    filename = secure_filename(f"{timestamp}_{file.filename}")
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    
    # 回傳可供下載下載讀取的本地網址路徑
    return jsonify({'url': f'/uploads/{filename}'})

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
        pid = data.get('id')
        name, address, r_type, rent, notes = data.get('name'), data.get('address'), data.get('type'), data.get('rent'), data.get('notes')
        image_url = data.get('image_url', 'noimage')
        
        if pid:
            conn.execute('UPDATE properties SET name=?, address=?, type=?, rent=?, notes=?, image_url=? WHERE id=? AND user_id=?', (name, address, r_type, rent, notes, image_url, pid, current_user_id))
        else:
            conn.execute('INSERT INTO properties (user_id, name, address, type, rent, notes, image_url) VALUES (?, ?, ?, ?, ?, ?, ?)', (current_user_id, name, address, r_type, rent, notes, image_url))
        conn.commit()
        return jsonify({'message': '儲存成功！'})

# ---- 合約與自動重置狀態 API ----
@app.route('/api/contracts', methods=['GET', 'POST'])
@token_required
def manage_contracts(current_user_id):
    conn = get_db()
    
    # 獲取當前環境判定時間（支援前端時空機模擬）
    mock_date = request.headers.get('X-Mock-Date')
    current_month = mock_date[:7] if mock_date else datetime.datetime.now().strftime('%Y-%m')

    if request.method == 'GET':
        # 自動檢查更新機制：如果合約目前是「本月已繳」，但歷史紀錄中完全沒有「當前月份」的繳費資料，自動強制打回紅燈
        conn.execute('''
            UPDATE contracts 
            SET payment_status = "待確認/逾期"
            WHERE user_id = ? AND is_active = 1 AND payment_status = "本月已繳"
            AND id NOT IN (
                SELECT contract_id FROM payments WHERE payment_month = ?
            )
        ''', (current_user_id, current_month))
        conn.commit()

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
        p_id, t_name, t_id, t_phone, period, status, r_type, rent, water, elect, notes = (
            data.get('property_id'), data.get('tenant_name'), data.get('tenant_id_card'), data.get('tenant_phone'),
            data.get('contract_period'), data.get('payment_status'), data.get('room_type'), data.get('rent'),
            data.get('water'), data.get('electricity'), data.get('notes')
        )
        
        if cid:
            conn.execute('''
                UPDATE contracts SET property_id=?, tenant_name=?, tenant_id_card=?, tenant_phone=?, contract_period=?, payment_status=?, room_type=?, rent=?, water=?, electricity=?, notes=?
                WHERE id=? AND user_id=?
            ''', (p_id, t_name, t_id, t_phone, period, status, r_type, rent, water, elect, notes, cid, current_user_id))
        else:
            conn.execute('''
                INSERT INTO contracts (user_id, property_id, tenant_name, tenant_id_card, tenant_phone, contract_period, payment_status, room_type, rent, water, electricity, notes, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (current_user_id, p_id, t_name, t_id, t_phone, period, status, r_type, rent, water, elect, notes))
        conn.commit()
        return jsonify({'message': '合約儲存成功！'})

@app.route('/api/contracts/<int:cid>/terminate', methods=['POST'])
@token_required
def terminate_contract(current_user_id, cid):
    conn = get_db()
    conn.execute('UPDATE contracts SET is_active = 0 WHERE id = ? AND user_id = ?', (cid, current_user_id))
    conn.commit()
    return jsonify({'message': '合約已終止'})

# ---- 需求 1：歷史繳費明細查詢與確認收租 API ----
@app.route('/api/contracts/<int:cid>/payments', methods=['GET'])
@token_required
def get_payment_history(current_user_id, cid):
    rows = get_db().execute('SELECT * FROM payments WHERE contract_id = ? ORDER BY payment_month DESC', (cid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/contracts/<int:cid>/pay_confirm', methods=['POST'])
@token_required
def confirm_rent_payment(current_user_id, cid):
    # 接收前端即時表格送出的數值
    data = request.get_json() or {}
    electricity_usage = float(data.get('electricity_usage', 0))
    water_fee = int(data.get('water_fee', 0)) # 支援動態修改的水費

    conn = get_db()
    contract = conn.execute('SELECT * FROM contracts WHERE id = ? AND user_id = ?', (cid, current_user_id)).fetchone()
    if not contract: 
        return jsonify({'message': '找不到該筆合約資訊'}), 404

    # 取得環境判定時間
    mock_date = request.headers.get('X-Mock-Date')
    current_month = mock_date[:7] if mock_date else datetime.datetime.now().strftime('%Y-%m')
    now_time = mock_date if mock_date else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 檢查是否重複建立
    existing = conn.execute('SELECT id FROM payments WHERE contract_id = ? AND payment_month = ?', (cid, current_month)).fetchone()
    if existing:
        return jsonify({'message': f'本月 ({current_month}) 已經有收租記帳紀錄！'}), 400

    base_rent = contract['rent']             # 唯讀引號資料："基本租金"
    electricity_rate = contract['electricity'] # 唯讀引號資料："電費單價"
    
    # 依據指定公式精密計算
    total_electricity_fee = electricity_rate * electricity_usage
    total_amount = int(base_rent + water_fee + total_electricity_fee)

    # 封裝結構化拆算備註
    breakdown_note = f"房租:${base_rent} + 水費:${water_fee} + 電費:${total_electricity_fee:.1f} ({electricity_usage}度×${electricity_rate})"

    # 寫入歷史流水帳
    conn.execute('''
        INSERT INTO payments (user_id, contract_id, payment_month, amount, paid_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (current_user_id, cid, current_month, total_amount, f"{now_time} ({breakdown_note})"))

    # 點亮綠燈狀態
    conn.execute('UPDATE contracts SET payment_status = "本月已繳" WHERE id = ?', (cid,))
    conn.commit()
    
    return jsonify({'message': f'成功入帳 {current_month} 月份房租！金額：${total_amount:,} NTD'})

if __name__ == '__main__':
    app.run(debug=True, port=5000)

