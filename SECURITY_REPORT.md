# 用户管理系统 — 安全审计报告

**审计项目**：用户信息管理平台（Flask 应用）
**审计日期**：2026-07-07
**风险等级**：严重（初始版本存在多处高危漏洞）

---

## 一、漏洞汇总

| 编号 | 漏洞名称 | 风险等级 | CVSS 3.1 | 状态 |
|:----:|----------|:--------:|:--------:|:----:|
| V-01 | 明文密码存储 | 🔴 严重 | 9.8 | ✅ 已修复 |
| V-02 | 硬编码 Secret Key | 🔴 严重 | 9.1 | ✅ 已修复 |
| V-03 | 密码明文展示到前端 | 🔴 严重 | 8.6 | ✅ 已修复 |
| V-04 | 登录接口无限流 | 🟠 高危 | 7.5 | ✅ 已修复 |
| V-05 | 无 CSRF 保护 | 🟠 高危 | 7.1 | ✅ 已修复 |
| V-06 | Debug 模式开启 | 🟠 高危 | 7.0 | ✅ 已修复 |
| V-07 | Session 永不过期 | 🟡 中危 | 5.3 | ✅ 已修复 |
| V-08 | Session 固定攻击 | 🟡 中危 | 5.1 | ✅ 已修复 |
| V-09 | Cookie 安全属性缺失 | 🟡 中危 | 4.3 | ✅ 已修复 |
| V-10 | HTML 注释泄露凭据 | 🟡 中危 | 4.0 | ✅ 已修复 |
| V-11 | 监听所有网卡 | 🟢 低危 | 3.0 | ✅ 已修复 |
| V-12 | 无 HTTPS 加密传输 | 🟢 低危 | 3.7 | ⚠️ 需自行配置 |

---

## 二、漏洞详情

### V-01：明文密码存储（严重）

**位置**：`app.py` — USERS 字典

**问题代码**：
```python
USERS = {
    "admin": { "password": "admin123" },   # ← 明文
    "alice": { "password": "alice2025" },  # ← 明文
}
```

**风险描述**：
- 数据库泄露导致所有用户密码直接暴露
- 用户可能在多个平台复用密码，造成连锁沦陷
- 内部人员可直接查看源代码获取密码

**修复方案**：
```python
from werkzeug.security import generate_password_hash, check_password_hash

USERS = {
    "admin": { "password": generate_password_hash("admin123") },
    "alice": { "password": generate_password_hash("alice2025") },
}

# 验证时：
if user and check_password_hash(user["password"], password):
    # 登录成功
```

**攻击场景**：
```
攻击者获得源码或数据库 → 直接读取密码 → 登录其他平台横向移动
```

---

### V-02：硬编码 Secret Key（严重）

**位置**：`app.py`

**问题代码**：
```python
app.secret_key = "dev-key-2025"  # ← 硬编码且公开
```

**风险描述**：
- 攻击者可利用已知 secret_key 伪造任意用户的 session cookie
- 无需密码即可冒充任意用户登录
- 签名算法已知（itsdangerous），可直接解密和伪造

**修复方案**：
```python
import secrets
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
```

**攻击场景**：
```python
# 攻击者构造伪造 session
from flask.sessions import SecureCookieSessionInterface
# 用已知 secret_key 签名一个包含 "admin" 的 session
# 设置到浏览器后直接以管理员身份访问系统
```

---

### V-03：密码明文展示到前端（严重）

**位置**：`templates/index.html`

**问题代码**：
```html
<li><span class="label">密码：</span>{{ user.password }}</li>  <!-- 直接输出密码 -->
```

**风险描述**：
- 用户登录后密码完整显示在页面上
- 他人路过屏幕即可看到密码
- 浏览器保存页面源码即可获取密码

**修复方案**：直接移除该行。

---

### V-04：登录接口无限制（高危）

**位置**：`app.py` — login 路由

**问题代码**：
```python
@app.route("/login", methods=["POST"])
def login():
    # 无条件处理登录请求，无限尝试
```

**风险描述**：
- 攻击者可编写脚本对用户名进行字典暴力破解
- 每秒可尝试数百次，弱密码几分钟内即可破解

**修复方案**：
```python
# 内存限流记录
LOGIN_ATTEMPTS = {}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15

# 每次失败记录，超限则临时锁定
if record["count"] >= MAX_LOGIN_ATTEMPTS:
    return render_template("login.html", error="登录尝试过于频繁，请稍后再试")
```

**攻击场景**：
```
hydra -l admin -P /usr/share/wordlists/rockyou.txt http-post-form \
  "/login:username=^USER^&password=^PASS^:错误"
```

---

### V-05：无 CSRF 保护（高危）

**位置**：`templates/login.html` + `app.py`

**问题代码**：
```html
<form method="POST" action="/login">
    <!-- 没有 CSRF Token -->
```

**风险描述**：
- 攻击者可构造恶意页面，诱导用户点击后自动提交登录
- 结合 XSS 可实现完全账户接管

**修复方案**：
```python
# 后端生成 Token
def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]

app.jinja_env.globals["csrf_token"] = generate_csrf_token

# 表单增加隐藏字段
# <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">

# 后端校验
if not token or token != session.get("_csrf_token"):
    abort(403)
```

---

### V-06：Debug 模式开启（高危）

**位置**：`app.py`

**问题代码**：
```python
app.run(debug=True, host="0.0.0.0", port=5000)
```

**风险描述**：
- 访问 `/console` 可执行任意 Python 代码（需要 PIN，但已知 debug=True 时可获取）
- 报错页面泄露完整文件路径、代码片段和变量值
- 生产环境绝不应开启

**修复方案**：
```python
debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
app.run(debug=debug_mode, host="0.0.0.0", port=5000)
```

---

### V-07：Session 永不过期（中危）

**位置**：`app.py`

**问题代码**：
```python
# 使用默认 session 配置，浏览器关闭前一直有效
```

**风险描述**：
- 用户离开电脑忘记退出，他人可继续操作
- 长期未关闭的浏览器 session 可被反复利用

**修复方案**：
```python
app.config["PERMANENT_SESSION_LIFETIME"] = 1800  # 30分钟
# 登录时设置：
session.permanent = True
```

---

### V-08：Session 固定攻击（中危）

**位置**：`app.py` — login 路由

**问题代码**：
```python
# 登录成功后直接使用已有 session，不重新生成
session["username"] = username
```

**风险描述**：
- 攻击者可先获取一个 session ID，诱导用户使用该 session 登录
- 登录后攻击者可用自己的 session 直接接管账户

**修复方案**：
```python
session.regenerate()
```

---

### V-09：Cookie 安全属性缺失（中危）

**位置**：`app.py`

**问题代码**：
```python
# 使用 Flask 默认 cookie 配置
```

**风险描述**：
- 未设置 `HttpOnly`，JS 可通过 `document.cookie` 读取 session
- 未设置 `SameSite`，容易被 CSRF 利用

**修复方案**：
```python
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
```

---

### V-10：HTML 注释泄露凭据（中危）

**位置**：`templates/login.html`

**问题代码**：
```html
<!-- 调试信息 - 默认管理员账号 用户名: admin 密码: admin123 -->
```

**风险描述**：
- 查看页面源代码的任何人都能直接获得管理员账号密码
- 浏览器 F12 → Elements 即可看到

**修复方案**：删除该注释行。

---

### V-11：监听所有网卡（低危）

**位置**：`app.py`

**问题代码**：
```python
app.run(host="0.0.0.0", port=5000)
```

**风险描述**：
- 局域网内任何设备均可访问
- 若暴露在公网，任何人都可访问登录页面

**修复方案**：生产环境改为 `127.0.0.1` 或配合防火墙使用。

---

### V-12：无 HTTPS 加密传输（低危）

**位置**：全站

**风险描述**：
- 所有数据（包括密码）以明文 HTTP 传输
- 局域网内可通过 ARP 欺骗抓包获取登录凭证
- 公共 WiFi 下风险极高

**修复方案**：配置 SSL 证书启用 HTTPS。

---

## 三、风险评分汇总

```
严重:  ████████████▏  3 个
高危:  ████████████▏  3 个
中危:  ████████████▏  4 个
低危:  ████████████▏  2 个
总计:  12 个
```

---

## 四、安全建议（未实施项）

1. **HTTPS** — 使用 Let's Encrypt 免费证书或自签名证书
2. **登录验证码** — 集成 Google reCAPTCHA 或类似方案
3. **密码复杂度策略** — 要求密码 ≥8 位，包含大小写字母和数字
4. **日志审计** — 记录所有登录尝试，便于事后追溯
5. **数据库迁移** — 将 USERS 字典迁移到 SQLite/MySQL，避免硬编码
6. **XSS 防护** — 对输出做 HTML 转义（Flask 模板引擎默认已转义）
7. **CSP 头** — 添加 Content-Security-Policy 响应头
8. **安全更新** — 定期更新 Flask 和依赖库版本

---

*报告结束*
