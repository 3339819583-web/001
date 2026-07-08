"""
浏览器远程控制 API
- 在 Kali 上运行这个服务
- 我可以向它发指令，操控你的浏览器
"""
import base64
import json
import os
import tempfile
import time
import threading
from io import BytesIO
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

app = Flask(__name__)
driver = None


def get_browser():
    """获取或创建浏览器实例"""
    global driver
    if driver is None:
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--start-maximized")
        # 如果想在无界面模式运行，取消下面注释
        # chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(options=chrome_options)
    return driver


@app.route("/open", methods=["POST"])
def open_url():
    """打开网址"""
    data = request.get_json()
    url = data.get("url", "")
    if not url:
        return jsonify({"success": False, "error": "缺少 url 参数"})

    browser = get_browser()
    browser.get(url)
    return jsonify({
        "success": True,
        "title": browser.title,
        "url": browser.current_url
    })


@app.route("/click", methods=["POST"])
def click_element():
    """点击元素（支持多种定位方式）"""
    data = request.get_json()
    by = data.get("by", "css")
    value = data.get("value", "")

    by_map = {
        "css": By.CSS_SELECTOR,
        "id": By.ID,
        "name": By.NAME,
        "class": By.CLASS_NAME,
        "tag": By.TAG_NAME,
        "link": By.LINK_TEXT,
        "xpath": By.XPATH,
    }

    browser = get_browser()
    try:
        elem = WebDriverWait(browser, 10).until(
            EC.element_to_be_clickable((by_map.get(by, By.CSS_SELECTOR), value))
        )
        elem.click()
        return jsonify({"success": True, "current_url": browser.current_url})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/type", methods=["POST"])
def type_text():
    """向输入框输入文字"""
    data = request.get_json()
    by = data.get("by", "css")
    value = data.get("value", "")
    text = data.get("text", "")

    by_map = {
        "css": By.CSS_SELECTOR,
        "id": By.ID,
        "name": By.NAME,
        "class": By.CLASS_NAME,
        "tag": By.TAG_NAME,
        "xpath": By.XPATH,
    }

    browser = get_browser()
    try:
        elem = WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((by_map.get(by, By.CSS_SELECTOR), value))
        )
        elem.clear()
        elem.send_keys(text)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/submit", methods=["POST"])
def submit_form():
    """按回车提交表单"""
    data = request.get_json()
    by = data.get("by", "css")
    value = data.get("value", "")

    by_map = {
        "css": By.CSS_SELECTOR,
        "id": By.ID,
        "name": By.NAME,
        "class": By.CLASS_NAME,
        "tag": By.TAG_NAME,
        "xpath": By.XPATH,
    }

    browser = get_browser()
    try:
        elem = WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((by_map.get(by, By.CSS_SELECTOR), value))
        )
        elem.send_keys(Keys.RETURN)
        time.sleep(1)
        return jsonify({"success": True, "current_url": browser.current_url})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/screenshot", methods=["GET"])
def take_screenshot():
    """截图并返回 base64"""
    browser = get_browser()
    try:
        png = browser.get_screenshot_as_png()
        b64 = base64.b64encode(png).decode("utf-8")
        return jsonify({
            "success": True,
            "screenshot": b64,
            "title": browser.title,
            "url": browser.current_url
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/wait", methods=["POST"])
def wait_for():
    """等待一段时间"""
    data = request.get_json()
    seconds = data.get("seconds", 2)
    time.sleep(seconds)
    return jsonify({"success": True, "waited": seconds})


@app.route("/execute", methods=["POST"])
def execute_js():
    """执行 JavaScript"""
    data = request.get_json()
    script = data.get("script", "")
    browser = get_browser()
    try:
        result = browser.execute_script(script)
        return jsonify({"success": True, "result": str(result)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/info", methods=["GET"])
def page_info():
    """获取当前页面信息"""
    browser = get_browser()
    try:
        return jsonify({
            "success": True,
            "title": browser.title,
            "url": browser.current_url,
            "cookies": browser.get_cookies()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/extract", methods=["POST"])
def extract_text():
    """提取页面文字"""
    data = request.get_json()
    by = data.get("by", "css")
    value = data.get("value", "")

    by_map = {
        "css": By.CSS_SELECTOR,
        "id": By.ID,
        "name": By.NAME,
        "class": By.CLASS_NAME,
        "tag": By.TAG_NAME,
        "xpath": By.XPATH,
    }

    browser = get_browser()
    try:
        elems = browser.find_elements(by_map.get(by, By.CSS_SELECTOR), value)
        texts = [e.text for e in elems if e.text]
        return jsonify({"success": True, "count": len(texts), "texts": texts})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/close", methods=["GET"])
def close_browser():
    """关闭浏览器"""
    global driver
    if driver:
        driver.quit()
        driver = None
        return jsonify({"success": True, "message": "浏览器已关闭"})
    return jsonify({"success": True, "message": "浏览器未打开"})


if __name__ == "__main__":
    print("=" * 55)
    print("  🤖 浏览器远程控制服务已启动")
    print("=" * 55)
    print(f"  API 地址: http://127.0.0.1:8888")
    print()
    print("  可用接口:")
    print("    POST /open       - 打开网址")
    print("    POST /click      - 点击元素")
    print("    POST /type       - 输入文字")
    print("    POST /submit     - 提交表单")
    print("    POST /extract    - 提取文字")
    print("    GET  /screenshot - 截图")
    print("    GET  /info       - 页面信息")
    print("    POST /execute    - 执行JS")
    print("    POST /wait       - 等待")
    print("    GET  /close      - 关闭浏览器")
    print()
    print("  ⚠️ 注意：浏览器窗口会在你的屏幕上弹出")
    print("=" * 55)
    app.run(host="127.0.0.1", port=8888, debug=False)
