import os
import time
import secrets
import sqlite3
import urllib.request
import urllib.error
import subprocess
import platform
from functools import wraps
from flask import Flask, render_template, request, redirect, session, abort, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ========== 安全加固 ==========

# [修复] 使用环境变量或随机生成的 secret_key，不硬编码
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# [修复] 设置 session 过期时间（30分钟）
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 1800  # 30 分钟
app.config["SESSION_COOKIE_SECURE"] = False      # 有 HTTPS 时设为 True
app.config["SESSION_COOKIE_HTTPONLY"] = True     # 防止 JS 读取 cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"    # 防止 CSRF 的一部分

# 上传配置
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB


# ========== SQLite 数据库 ==========

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "users.db")


def log_debug(msg):
    """打印调试信息到控制台（强制刷新）"""
    print(f"[DEBUG] {msg}", flush=True)


def init_db():
    """初始化 SQLite 数据库"""
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            phone TEXT
        )
    """)
    # 插入默认用户
    c.execute("INSERT OR IGNORE INTO users (username, password, email, phone) VALUES (?, ?, ?, ?)",
              ("admin", generate_password_hash("admin123"), "admin@example.com", "13800138000"))
    c.execute("INSERT OR IGNORE INTO users (username, password, email, phone) VALUES (?, ?, ?, ?)",
              ("alice", generate_password_hash("alice2025"), "alice@example.com", "13900139001"))
    conn.commit()
    conn.close()


# ========== 用户字典（用于登录验证，保持兼容）==========

USERS = {
    "admin": {
        "username": "admin",
        "password": generate_password_hash("admin123"),
        "role": "admin",
        "email": "admin@example.com",
        "phone": "13800138000",
        "balance": 99999
    },
    "alice": {
        "username": "alice",
        "password": generate_password_hash("alice2025"),
        "role": "user",
        "email": "alice@example.com",
        "phone": "13900139001",
        "balance": 100
    }
}


# ========== 登录限流 ==========

LOGIN_ATTEMPTS = {}  # IP -> {"count": int, "first_attempt": timestamp}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15


def check_rate_limit(ip):
    """检查 IP 是否超过登录失败次数限制"""
    now = time.time()
    if ip in LOGIN_ATTEMPTS:
        record = LOGIN_ATTEMPTS[ip]
        # 超过锁定时间则重置
        if now - record["first_attempt"] > LOGIN_LOCKOUT_MINUTES * 60:
            del LOGIN_ATTEMPTS[ip]
            return True
        if record["count"] >= MAX_LOGIN_ATTEMPTS:
            remaining = int(LOGIN_LOCKOUT_MINUTES * 60 - (now - record["first_attempt"]))
            return False, remaining
    return True, 0


def record_failed_attempt(ip):
    """记录一次登录失败"""
    now = time.time()
    if ip in LOGIN_ATTEMPTS:
        record = LOGIN_ATTEMPTS[ip]
        if now - record["first_attempt"] > LOGIN_LOCKOUT_MINUTES * 60:
            LOGIN_ATTEMPTS[ip] = {"count": 1, "first_attempt": now}
        else:
            LOGIN_ATTEMPTS[ip]["count"] += 1
    else:
        LOGIN_ATTEMPTS[ip] = {"count": 1, "first_attempt": now}


def clear_login_attempts(ip):
    """登录成功，清除失败记录"""
    if ip in LOGIN_ATTEMPTS:
        del LOGIN_ATTEMPTS[ip]


# ========== CSRF 保护 ==========

def generate_csrf_token():
    """生成 CSRF Token 并存入 session"""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


app.jinja_env.globals["csrf_token"] = generate_csrf_token


# ========== 路由 ==========


@app.route("/")
def index():
    username = session.get("username")
    user_info = None
    if username and username in USERS:
        user_info = USERS[username]
    return render_template("index.html", username=username, user=user_info)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # [修复] CSRF Token 校验
        token = request.form.get("_csrf_token", "")
        if not token or token != session.get("_csrf_token"):
            abort(403, "CSRF Token 无效，请刷新页面重试")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # [修复] 登录限流检查
        client_ip = request.remote_addr or "unknown"
        ok, remaining = check_rate_limit(client_ip)
        if not ok:
            minutes = remaining // 60
            seconds = remaining % 60
            return render_template(
                "login.html",
                error=f"登录尝试过于频繁，请等待 {minutes} 分 {seconds} 秒后再试"
            )

        # [修复] 使用 check_password_hash 比较哈希密码
        user = USERS.get(username)
        if user and check_password_hash(user["password"], password):
            session["username"] = username
            session.permanent = True  # 启用过期时间
            clear_login_attempts(client_ip)
            return redirect("/")
        else:
            record_failed_attempt(client_ip)
            return render_template("login.html", error="用户名或密码错误！")

    # GET 请求，生成 CSRF Token
    generate_csrf_token()
    success = request.args.get("success", "")
    return render_template("login.html", success=success)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()

        # [修复] 使用参数化查询，防止 SQL 注入
        sql = "INSERT INTO users (username, password, email, phone) VALUES (?, ?, ?, ?)"
        log_debug(f"执行 SQL: {sql}")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute(sql, (username, generate_password_hash(password), email, phone))
            conn.commit()
            # 同步添加到 USERS 字典（保持登录兼容）
            USERS[username] = {
                "username": username,
                "password": generate_password_hash(password),
                "role": "user",
                "email": email,
                "phone": phone,
                "balance": 0
            }
            return render_template("login.html", success="注册成功，请登录")
        except Exception as e:
            error_msg = f"注册失败：{str(e)}"
            return render_template("register.html", error=error_msg)
        finally:
            conn.close()

    return render_template("register.html")


@app.route("/search")
def search():
    keyword = request.args.get("keyword", "").strip()
    results = []
    executed_sql = ""

    if keyword:
        # [修复] 使用参数化查询和 LIKE，防止 SQL 注入
        executed_sql = "SELECT id, username, email, phone FROM users WHERE username LIKE ? OR email LIKE ?"
        log_debug(f"执行 SQL: {executed_sql}")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute(executed_sql, (f"%{keyword}%", f"%{keyword}%"))
            rows = c.fetchall()
            for row in rows:
                results.append({"id": row[0], "username": row[1], "email": row[2], "phone": row[3]})
        except Exception as e:
            log_debug(f"SQL 错误: {str(e)}")
        finally:
            conn.close()

    username = session.get("username")
    user_info = None
    if username and username in USERS:
        user_info = USERS[username]

    return render_template("index.html", username=username, user=user_info, results=results, keyword=keyword)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    """头像上传"""
    # 需要登录才能访问
    if "username" not in session:
        return redirect("/login")

    if request.method == "POST":
        file = request.files.get("file")
        if file is None or file.filename == "":
            return render_template("upload.html", error="请选择要上传的文件")

        # 原始文件名（用于提取扩展名）
        original_filename = file.filename

        # [修复] 提取文件扩展名并转小写
        ext = ""
        if "." in original_filename:
            ext = original_filename.rsplit(".", 1)[1].lower()

        # [修复] 白名单校验：只允许图片扩展名
        allowed_exts = {"jpg", "jpeg", "png", "gif"}
        if ext not in allowed_exts:
            return render_template("upload.html", error=f"不支持的文件类型 .{ext}，仅允许上传 jpg、jpeg、png、gif 格式的图片")

        # [修复] 使用 UUID 重命名文件，防止路径穿越和文件名冲突
        new_filename = f"{secrets.token_hex(16)}.{ext}"

        # [修复] 验证文件内容的真实性（检查是否为真实图片）
        file.seek(0)
        file_content = file.read(512)
        file.seek(0)

        # 检测文件魔数
        if file_content[:8] == b"\x89PNG\r\n\x1a\n":
            detected_ext = "png"
        elif file_content[:2] in (b"\xff\xd8",):
            detected_ext = "jpg"
        elif file_content[:6] in (b"GIF87a", b"GIF89a"):
            detected_ext = "gif"
        else:
            return render_template("upload.html", error="文件格式验证失败，请上传真实的图片文件")

        # [修复] 确保扩展名与文件内容一致
        if detected_ext != ext:
            return render_template("upload.html", error="文件后缀与内容不匹配，请上传正确的图片文件")

        # 确保上传目录存在
        upload_dir = os.path.join(app.root_path, "static", "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        # 保存文件
        file_path = os.path.join(upload_dir, new_filename)
        file.save(file_path)

        # [修复] 设置安全的文件权限
        os.chmod(file_path, 0o644)

        # 生成访问 URL
        file_url = url_for("static", filename=f"uploads/{new_filename}")

        return render_template("upload.html", success="上传成功！", file_url=file_url, filename=new_filename)

    return render_template("upload.html")


@app.route("/profile")
def profile():
    """个人中心"""
    if "username" not in session:
        return redirect("/login")

    current_username = session.get("username", "")

    # 获取当前登录用户的 ID
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM users WHERE username = ?", (current_username,))
        current_row = c.fetchone()
        if current_row is None:
            return redirect("/login")
        current_user_id = str(current_row[0])
    finally:
        conn.close()

    # 从 URL 参数获取 user_id，默认使用当前用户
    user_id = request.args.get("user_id", current_user_id)

    # [修复] 验证：只有管理员可以查看其他用户，普通用户只能看自己
    is_admin = USERS.get(current_username, {}).get("role") == "admin"
    if user_id != current_user_id and not is_admin:
        return render_template("profile.html", error="无权查看其他用户的资料")

    # 从数据库查询用户信息
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("SELECT id, username, email, phone FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
    finally:
        conn.close()

    if row is None:
        return render_template("profile.html", error="用户不存在")

    user_data = {
        "id": row[0],
        "username": row[1],
        "email": row[2] if row[2] else "",
        "phone": row[3] if row[3] else "",
        "role": USERS.get(row[1], {}).get("role", "user"),
        "balance": USERS.get(row[1], {}).get("balance", 0),
    }

    return render_template("profile.html", user=user_data)


@app.route("/recharge", methods=["POST"])
def recharge():
    """充值"""
    if "username" not in session:
        return redirect("/login")

    current_username = session.get("username", "")

    # 获取当前登录用户的 ID
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM users WHERE username = ?", (current_username,))
        current_row = c.fetchone()
        if current_row is None:
            return redirect("/login")
        current_user_id = str(current_row[0])
    finally:
        conn.close()

    # 从表单接收 user_id 和 amount
    user_id = request.form.get("user_id", "")

    # [修复] 只能给自己的账号充值
    if user_id != current_user_id:
        return redirect(f"/profile?user_id={current_user_id}")

    amount = request.form.get("amount", "0")

    # [修复] 检查金额必须为正数
    try:
        amount_val = float(amount)
        if amount_val <= 0:
            return redirect(f"/profile?user_id={user_id}")
    except (ValueError, TypeError):
        return redirect(f"/profile?user_id={user_id}")

    # [修复] 限制单次充值金额不超过 10000
    if amount_val > 10000:
        amount_val = 10000

    # 直接修改余额
    if current_username in USERS:
        USERS[current_username]["balance"] = USERS[current_username].get("balance", 0) + amount_val

    return redirect(f"/profile?user_id={user_id}")


@app.route("/page")
def dynamic_page():
    """动态页面加载"""
    # 从 URL 获取页面名称
    name = request.args.get("name", "")

    if not name:
        return render_template("index.html", page_content="", page_title="")

    # [修复] 白名单：只允许加载预定义的页面文件
    allowed_pages = {"help", "about"}

    # [修复] 过滤路径穿越字符和非法路径
    if not name.isalnum() or name not in allowed_pages:
        return render_template("index.html", page_content="页面不存在", page_title=name,
                               username=session.get("username"),
                               user=USERS.get(session.get("username")))

    pages_dir = os.path.join(app.root_path, "pages")
    filepath = os.path.join(pages_dir, name + ".html")
    page_content = ""
    page_title = name

    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            page_content = f.read()
    else:
        page_content = "页面不存在"

    # 获取当前用户信息显示在导航栏
    username = session.get("username")
    user_info = None
    if username and username in USERS:
        user_info = USERS[username]

    return render_template("index.html", username=username, user=user_info,
                           page_content=page_content, page_title=page_title)


@app.route("/change-password", methods=["POST"])
def change_password():
    """修改密码"""
    # 需要登录
    if "username" not in session:
        return redirect("/login")

    current_username = session.get("username", "")

    # [修复] CSRF Token 校验
    token = request.form.get("_csrf_token", "")
    if not token or token != session.get("_csrf_token"):
        abort(403, "CSRF Token 无效，请刷新页面重试")

    # 从表单获取参数
    target_username = request.form.get("username", "")
    new_password = request.form.get("new_password", "")
    old_password = request.form.get("old_password", "")

    if not target_username or not new_password:
        return redirect("/profile?user_id=" + request.form.get("user_id", ""))

    # [修复] 只能修改自己的密码
    if target_username != current_username:
        return redirect("/profile?user_id=" + request.form.get("user_id", ""))

    # [修复] 验证原密码
    user = USERS.get(current_username)
    if not user or not check_password_hash(user["password"], old_password):
        return redirect("/profile?user_id=" + request.form.get("user_id", ""))

    # 更新密码
    if target_username in USERS:
        USERS[target_username]["password"] = generate_password_hash(new_password)

        # 同步更新 SQLite 数据库
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("UPDATE users SET password = ? WHERE username = ?",
                      (generate_password_hash(new_password), target_username))
            conn.commit()
        except Exception as e:
            log_debug(f"更新数据库密码失败: {str(e)}")
        finally:
            conn.close()

    return redirect("/profile?user_id=" + request.form.get("user_id", ""))


@app.route("/fetch-url", methods=["POST"])
def fetch_url():
    """URL 抓取功能"""
    if "username" not in session:
        return redirect("/login")

    url = request.form.get("url", "")
    username = session.get("username")
    user_info = None
    if username and username in USERS:
        user_info = USERS[username]

    if not url:
        return render_template("index.html", username=username, user=user_info,
                               fetch_result="", fetch_status="", fetch_url="")

    # [修复] 只允许 http/https 协议
    if not url.startswith(("http://", "https://")):
        return render_template("index.html", username=username, user=user_info,
                               fetch_result="", fetch_status="",
                               fetch_url=url, fetch_error="只允许 http 和 https 协议")

    # [修复] 解析 URL 并检查目标 IP
    from urllib.parse import urlparse
    import socket
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        # 解析域名获取真实 IP
        ip = socket.gethostbyname(host)
    except Exception:
        return render_template("index.html", username=username, user=user_info,
                               fetch_result="", fetch_status="",
                               fetch_url=url, fetch_error="无法解析目标地址")

    # [修复] 禁止访问内网 IP
    private_ranges = [
        "127.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
        "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
        "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
        "172.30.", "172.31.", "192.168.", "169.254.", "0.",
    ]
    for private in private_ranges:
        if ip.startswith(private):
            return render_template("index.html", username=username, user=user_info,
                                   fetch_result="", fetch_status="",
                                   fetch_url=url, fetch_error="禁止访问内网地址")

    # [修复] 禁止访问本机地址（localhost）
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]"):
        return render_template("index.html", username=username, user=user_info,
                               fetch_result="", fetch_status="",
                               fetch_url=url, fetch_error="禁止访问本机地址")

    result_content = ""
    status_code = ""
    error_msg = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            status_code = f"状态码：{response.getcode()}"
            content = response.read()
            result_content = content.decode("utf-8", errors="replace")[:5000]
    except urllib.error.HTTPError as e:
        status_code = f"HTTP 错误：{e.code}"
        error_msg = str(e)
    except urllib.error.URLError as e:
        status_code = "连接失败"
        error_msg = str(e.reason)
    except Exception as e:
        status_code = "请求失败"
        error_msg = str(e)

    return render_template("index.html", username=username, user=user_info,
                           fetch_result=result_content, fetch_status=status_code,
                           fetch_url=url, fetch_error=error_msg)


@app.route("/ping", methods=["GET", "POST"])
def ping():
    """Ping 网络诊断（存在命令注入漏洞）"""
    if "username" not in session:
        return redirect("/login")

    result = ""
    error = ""
    ip_input = ""

    if request.method == "POST":
        ip_input = request.form.get("ip", "")

        # 使用 f-string 拼接命令（存在命令注入漏洞）
        command = f"ping -c 3 {ip_input}"

        try:
            # 使用 shell=True 执行命令
            result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, timeout=30).decode("utf-8", errors="replace")
        except subprocess.CalledProcessError as e:
            error = e.output.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            error = "命令执行超时"
        except Exception as e:
            error = f"执行失败：{str(e)}"

    return render_template("ping.html", result=result, error=error, ip=ip_input)


# [修复] 生产环境关闭 debug 模式，使用环境变量控制
if __name__ == "__main__":
    init_db()
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="0.0.0.0", port=5000)
