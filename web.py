from flask import Flask, render_template, request, redirect, url_for, abort, send_from_directory, session, jsonify
from werkzeug.utils import secure_filename
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from collections import defaultdict
from flask_socketio import SocketIO
from datetime import datetime, timedelta
from functools import wraps
import subprocess
import secrets
import base64
import socket
import time
import glob
import os
import re
import json

# =============================================
# ديكوراتور للتحقق من تسجيل الدخول
# =============================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # الصفحات المسموح بالوصول إليها بدون تسجيل دخول
        allowed_routes = ['index', 'cu', 'log', 'static']
        if request.endpoint in allowed_routes:
            if 'username' in session:
                session.pop('username', None)  # إغلاق الجلسة إذا كانت موجودة
            return f(*args, **kwargs)
            
        if 'username' not in session:
            return redirect(url_for('log'))
        return f(*args, **kwargs)
    return decorated_function

# =============================================
# دوال المساعدة
# =============================================
def get_mac(ip):
    try:
        result = subprocess.run(["arp", "-a"], capture_output=True, text=True)
        lines = result.stdout.split("\n")
        for line in lines:
            if ip in line:
                mac = line.split()[1].replace(':', '-')
                return mac.lower()
    except Exception as e:
        return "Unknown"
    return "Unknown"

def derive_key(password: bytes, salt: bytes):
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    return kdf.derive(password)

def encrypt_file(file_path, key):
    with open(file_path, "rb") as f:
        plaintext = f.read()

    iv = secrets.token_bytes(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()

    encrypted_data = iv + encryptor.tag + ciphertext

    with open(file_path + ".enc", "wb") as f:
        f.write(encrypted_data)

    os.remove(file_path)

def encrypt_folder(folder_path, extensions):
    key = derive_key(PASSWORD, SALT)
    for ext in extensions:
        for file_path in glob.glob(os.path.join(folder_path, ext)):
            encrypt_file(file_path, key)

def decrypt_file(file_path, key):
    with open(file_path, "rb") as f:
        encrypted_data = f.read()

    iv = encrypted_data[:12]
    tag = encrypted_data[12:28]
    ciphertext = encrypted_data[28:]

    cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend())
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    original_file_path = file_path.replace(".enc", "")
    with open(original_file_path, "wb") as f:
        f.write(plaintext)

    os.remove(file_path)

def decrypt_folder(folder_path, extensions):
    key = derive_key(PASSWORD, SALT)
    for ext in extensions:
        for file_path in glob.glob(os.path.join(folder_path, ext + ".enc")):
            decrypt_file(file_path, key)

def get_local_ip():
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    return local_ip

def get_available_macs():
    try:
        # أولاً: مسح الشبكة باستخدام ping لاكتشاف الأجهزة النشطة
        local_ip = get_local_ip()
        network_prefix = '.'.join(local_ip.split('.')[:3]) + '.'
        
        # مسح مجموعة من العناوين (يمكن تعديل النطاق حسب حجم شبكتك)
        for i in range(1, 255):
            ip = network_prefix + str(i)
            if ip != local_ip:  # لا نرسل ping إلى السيرفر نفسه
                try:
                    subprocess.Popen(['ping', '-n', '1', '-w', '500', ip], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE)
                except:
                    continue
        
        # الانتظار قليلاً لإنهاء عمليات ping
        time.sleep(2)
        
        # ثانياً: جلب عناوين MAC من جدول ARP
        result = subprocess.run(["arp", "-a"], capture_output=True, text=True)
        lines = result.stdout.split("\n")
        macs = set()
        
        for line in lines:
            parts = line.split()
            if len(parts) >= 3:
                mac = parts[1]
                if is_valid_mac(mac):
                    macs.add(mac)
        
        server_mac = get_server_mac()
        if server_mac:
            macs.add(server_mac)
            
        return sorted(macs)
    except Exception as e:
        print(f"Error getting MAC addresses: {e}")
        return []

def is_valid_mac(mac):
    return (len(mac) == 17 and mac.count('-') == 5 and 
            all(c in '0123456789abcdef-' for c in mac.lower()) and
            not mac.startswith(('01-', '03-', '05-', '07-', '09-', '0b-', '0d-', '0f-')) and
            mac != "ff-ff-ff-ff-ff-ff" and 
            mac != "00-00-00-00-00-00")

def get_server_mac():
    try:
        result = subprocess.run(['ipconfig', '/all'], capture_output=True, text=True)
        output = result.stdout
        mac_match = re.search(r'Physical Address[ .:]+([0-9A-Fa-f-]+)', output)
        if mac_match:
            mac = mac_match.group(1).strip()
            return mac.replace('-', ':').replace(':', '-')
        return None
    except Exception as e:
        print(f"Error getting MAC on Windows: {e}")
        return None

def load_users():
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)['users']

def get_user(username):
    users = load_users()
    for user in users:
        if user['username'].lower() == username.lower():
            return user
    return None

def log_failed_attempt(ip, mac, name, time):
    user = get_user(name)
    log_file = thief if user and user['role'] == 'member' else bad
    with open(log_file, 'a') as f:
        f.write(f"IP: {ip}, MAC: {mac}, Name: {name}\n, time {time}\n")
    encrypt_folder(FOLDER_PATH, FILE_EXTENSIONS)

# =============================================
# تهيئة التطبيق والإعدادات
# =============================================
SALT = b"RandomSaltValue1234"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
CONF_DIR = os.path.join(BASE_DIR, 'conf')

# مسارات الملفات
USERS_FILE = os.path.join(STATIC_DIR, 'users.json')
thief = os.path.join(STATIC_DIR, 'xx.txt')
bad = os.path.join(STATIC_DIR, 'x.txt')
key = os.path.join(CONF_DIR, 'dec.txt')
FOLDER_PATH = STATIC_DIR
FILE_EXTENSIONS = ["*.doc", "*.pdf", "*.txt", "*.xls", "*.xlsx","*.docx","*.json"]

# Encryption passphrase: set ONYX_KEY, or put it in conf/dec.txt (git-ignored).
if os.environ.get('ONYX_KEY'):
    PASSWORD = os.environ['ONYX_KEY'].strip().encode()
else:
    with open(key, 'r') as file:
        PASSWORD = file.read().strip().encode()

app = Flask(__name__)
socketio = SocketIO(app)
app.secret_key = os.urandom(24)  # مفتاح سري قوي للجلسات
app.config['SESSION_PERMANENT'] = False
app.permanent_session_lifetime = timedelta(minutes=30)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
VISITOR_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visitors_log.txt")
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

request_log = defaultdict(list)
REQUEST_LIMIT = 300
TIME_WINDOW = 300
messages = []

# =============================================
# مسارات التطبيق
# =============================================
@app.before_request
def simple_ids():
    ip = request.remote_addr
    current_time = time.time()
    request_log[ip] = [t for t in request_log[ip] if current_time - t < TIME_WINDOW]
    request_log[ip].append(current_time)

    if len(request_log[ip]) > REQUEST_LIMIT:
        abort(429, description="Too many requests - possible attack detected")

# إغلاق السيشن
@app.route('/logout_on_close', methods=['POST'])
def logout_on_close():
    session.pop('username', None)
    return '', 200

@app.route('/')
def index():
    if 'username' in session:
        session.pop('username', None)  # إغلاق الجلسة إذا كانت موجودة
    return render_template('index.html')

@app.route('/space', methods=['POST'])
def space():
    action = request.form.get('action')
    if action == 'custmer':
        return redirect(url_for('cu'))
    elif action == 'worker':
        return redirect(url_for('log'))

@app.route('/cu')
def cu():
    if 'username' in session:
        session.pop('username', None)  # إغلاق الجلسة إذا كانت موجودة
    return render_template('result cu.html')

@app.route('/log')
def log():
    if 'username' in session:
        session.pop('username', None)  # إغلاق الجلسة إذا كانت موجودة
    return render_template('log.html')

@app.route('/space0', methods=['POST'])
def space0():
    now = datetime.now()
    visitor_ip = request.remote_addr
    visitor_mac = get_mac(visitor_ip)
    if not is_valid_mac(visitor_mac):
        visitor_mac = get_server_mac() or "Unknown"

    current_time = now.strftime('%Y-%m-%d  %H:%M:%S')

    decrypt_folder(FOLDER_PATH, FILE_EXTENSIONS)

    with open(VISITOR_LOG_PATH, "a", encoding="utf-8") as log:
        log.write(f"IP: {visitor_ip}, MAC: {visitor_mac}, Name: {request.form.get('name')}\n, time {current_time}\n")

    name = request.form.get('name')
    password = request.form.get('password')
    code = request.form.get('code')
    user = get_user(name)

    if not user:
        log_failed_attempt(visitor_ip, visitor_mac, name, current_time)
        return render_template('result spy.html')

    if code == "high hand":
        if (user['role'] == 'member' and 
            user['password'] == password and 
            visitor_mac in user['mac_addresses']):
            session.clear()
            session['username'] = name
            return redirect(url_for('add'))
        else:
            with open(thief, 'a') as file:
                file.write(f"IP: {visitor_ip}, MAC: {visitor_mac}, Name: {name}, tried high hand\n, time {current_time}\n")
            encrypt_folder(FOLDER_PATH, FILE_EXTENSIONS)
            return render_template('result spy.html')

    if (user['password'] == password and 
        visitor_mac in user['mac_addresses']):
        session.clear()
        session['username'] = name
        if user['role'] == 'guest':
            return redirect(url_for('chg'))
        else:
            return redirect(url_for('chm'))
    else:
        log_failed_attempt(visitor_ip, visitor_mac, name, current_time)
        return render_template('result spy.html')

@app.route('/chg')
@login_required
def chg():
    return render_template('ch g.html')

@app.route('/chm')
@login_required
def chm():
    return render_template('ch m.html')

@app.route('/space1', methods=['POST'])
@login_required
def space1():
    action = request.form.get('action')
    if action == 'chat':
        return redirect(url_for('chat'))
    elif action == 'work':
        return render_template('result g.html')
    return redirect(url_for('chg'))

@app.route('/space2', methods=['POST'])
@login_required
def space2():
    action = request.form.get('action')
    if action == 'chat':
        return redirect(url_for('chat'))
    elif action == 'work':
        return render_template('result m.html')
    return redirect(url_for('chm'))

@app.route('/space3', methods=['POST'])
@login_required
def space3():
    encrypt_folder(FOLDER_PATH, FILE_EXTENSIONS)
    return redirect(url_for('log'))

@app.route('/space4', methods=['POST'])
def space4():
    return redirect(url_for('index'))

@app.route('/add')
@login_required
def add():
    available_macs = get_available_macs()
    server_mac = get_server_mac()
    return render_template('add.html', 
                         available_macs=available_macs,
                         server_mac=server_mac)

@app.route('/refresh_macs')
@login_required
def refresh_macs():
    available_macs = get_available_macs()
    server_mac = get_server_mac()
    return jsonify({
        'available_macs': available_macs,
        'server_mac': server_mac
    })

@app.route('/space5', methods=['POST'])
@login_required
def space5():
    name = request.form.get('name')
    ps = request.form.get('pw')
    mac = request.form.get('mac')
    role = request.form.get('role', 'guest')  # Default to guest if not provided

    users = load_users()
    
    # إذا كان المستخدم موجود بنفس الاسم والباسورد ولكن ماك مختلف
    same_credentials_user = next(
        (u for u in users if u['username'].lower() == name.lower() and u['password'] == ps),
        None)
    
    if same_credentials_user:
        # إضافة الماك الجديد إلى قائمة الماك ادرس للمستخدم الموجود
        if mac not in same_credentials_user['mac_addresses']:
            same_credentials_user['mac_addresses'].append(mac)
        
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"users": users}, f, ensure_ascii=False, indent=2)
        
        return redirect(url_for('index'))
    
    # التحقق من وجود مستخدم بنفس الاسم
    existing_user = next((u for u in users if u['username'].lower() == name.lower()), None)
    
    if existing_user:
        # إذا كان المستخدم موجود بنفس الاسم والباسورد والماك
        if (existing_user['password'] == ps and 
            mac in existing_user['mac_addresses']):
            available_macs = get_available_macs()
            server_mac = get_server_mac()
            return render_template('add.html', 
                                 available_macs=available_macs,
                                 server_mac=server_mac,
                                 error="User already exists with same credentials and MAC")
        
        # إذا كان المستخدم موجود بنفس الاسم فقط
        available_macs = get_available_macs()
        server_mac = get_server_mac()
        return render_template('add.html', 
                             available_macs=available_macs,
                             server_mac=server_mac,
                             error="Username already exists")
    
    # إذا كان المستخدم موجود بنفس الاسم والباسورد ولكن ماك مختلف
    same_credentials_user = next(
        (u for u in users if u['username'].lower() == name.lower() and u['password'] == ps),
        None)
    
    if same_credentials_user:
        # إضافة الماك الجديد إلى قائمة الماك ادرس للمستخدم الموجود
        if mac not in same_credentials_user['mac_addresses']:
            same_credentials_user['mac_addresses'].append(mac)
        
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"users": users}, f, ensure_ascii=False, indent=2)
        
        return redirect(url_for('index'))
    
    # إذا كان مستخدم جديد تماماً
    users.append({
        "username": name,
        "password": ps,
        "role": role,
        "mac_addresses": [mac] if mac else []
    })

    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump({"users": users}, f, ensure_ascii=False, indent=2)

    return redirect(url_for('index'))

@app.route('/chat')
@login_required
def chat():
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    username = session.get('username', 'مستخدم')
    return render_template('chat.html', messages=messages, files=files, username=username)

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))

# في web.py، تعديل دالة delete_message
@app.route('/delete_message', methods=['POST'])
@login_required
def delete_message():
    try:
        data = request.get_json()
        message_id = int(data.get('message_id'))
        current_user = session['username']
        
        global messages
        
        # البحث عن الرسالة
        message_to_delete = None
        for idx, msg in enumerate(messages):
            if msg.get('id') == message_id:
                message_to_delete = msg
                break
        
        if not message_to_delete:
            return jsonify({'success': False, 'error': 'الرسالة غير موجودة'}), 404
        
        # التحقق من الصلاحية باستخدام الحقل الصحيح
        message_sender = message_to_delete.get('user')
        if message_sender != current_user:
            return jsonify({'success': False, 'error': 'غير مصرح لك بحذف هذه الرسالة'}), 403
        
        # الحذف من القائمة
        del messages[idx]
        
        # إعلام جميع العملاء بالحذف
        socketio.emit('message_deleted', {'message_id': message_id})
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_messages')
@login_required
def get_messages():
    formatted_messages = []
    for msg in messages:
        formatted_msg = {
            'id': msg.get('id'),
            'user': msg.get('user', 'مستخدم'),
            'msg': msg.get('msg', ''),
            'timestamp': msg.get('timestamp', datetime.now().isoformat()),
            'replyTo': msg.get('replyTo'),
            'replyText': msg.get('replyText'),
            'replySender': msg.get('replySender'),
            'isFile': msg.get('isFile', False),
            'fileUrl': msg.get('fileUrl'),
            'fileName': msg.get('fileName'),
            'fileSize': msg.get('fileSize'),
            'fileType': msg.get('fileType')
        }
        formatted_messages.append(formatted_msg)
    
    return jsonify({'messages': formatted_messages})

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return "لم يتم العثور على أي ملف", 400

    file = request.files['file']

    if file.filename == '':
        return "لم يتم تحديد أي ملف", 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    file_size = os.path.getsize(file_path)
    file_type = file.content_type

    file_message = {
        'id': int(time.time() * 1000),
        'user': session.get('username', 'مستخدم'),
        'msg': f"📁 ملف: {filename}",
        'isFile': True,
        'fileUrl': f"/uploads/{filename}",
        'fileName': filename,
        'fileSize': f"{file_size / 1024:.1f} KB",
        'fileType': file_type,
        'timestamp': datetime.now().isoformat()
    }

    messages.append(file_message)
    socketio.emit('message', file_message)

    return jsonify({'success': True})

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@socketio.on('message')
def handle_message(data):
    if 'username' not in session:
        return
    
    user = session.get('username', 'مستخدم')
    msg = data.get('msg', '')
    reply_to = data.get('replyTo')
    reply_text = data.get('replyText')
    reply_sender = data.get('replySender')
    
    message_data = {
        'id': int(time.time() * 1000),
        'user': user,  # استخدام 'user' بدلاً من 'sender' لتوحيد الحقول
        'msg': msg,
        'timestamp': datetime.now().isoformat(),
        'replyTo': reply_to,
        'replyText': reply_text,
        'replySender': reply_sender,
        'isFile': False
    }
    
    messages.append(message_data)
    socketio.emit('message', message_data)

@socketio.on('delete_message')
def handle_delete_message(data):
    try:
        if 'username' not in session:
            return
            
        message_id = int(data.get('message_id'))
        current_user = session['username']
        
        global messages
        
        # البحث عن الرسالة
        message_to_delete = None
        for idx, msg in enumerate(messages):
            if msg.get('id') == message_id:
                message_to_delete = msg
                break
        
        if not message_to_delete:
            return
            
        if message_to_delete.get('user') != current_user:
            return
        
        # الحذف من القائمة
        del messages[idx]
        
        # إعلام جميع العملاء بالحذف
        socketio.emit('message_deleted', {'message_id': message_id})
        
    except Exception as e:
        print(f"Error deleting message: {e}")

if __name__ == '__main__':
    local_ip = get_local_ip()
    port = 5001
    socketio.run(app, host="0.0.0.0", port=port, debug=True, allow_unsafe_werkzeug=True)