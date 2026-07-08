import os
import time
import secrets
import sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, session, abort
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


# [修复] 生产环境关闭 debug 模式，使用环境变量控制
if __name__ == "__main__":
    init_db()
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="0.0.0.0", port=5000)
