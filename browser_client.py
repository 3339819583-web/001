"""
浏览器远程操控 —— 客户端脚本
在 Kali 运行 browser_api.py 后，我可以用这个脚本来操控你的浏览器
"""
import requests
import json
import base64
from io import BytesIO

class BrowserController:
    """浏览器控制器 - 在 Claude 环境中调用"""

    def __init__(self, api_url="http://你的KaliIP:8888"):
        self.api = api_url
        self.session = requests.Session()

    def open(self, url):
        """打开网址"""
        r = self.session.post(f"{self.api}/open", json={"url": url})
        return r.json()

    def click(self, selector, by="css"):
        """点击元素"""
        r = self.session.post(f"{self.api}/click", json={"by": by, "value": selector})
        return r.json()

    def type(self, selector, text, by="css"):
        """输入文字"""
        r = self.session.post(f"{self.api}/type", json={"by": by, "value": selector, "text": text})
        return r.json()

    def submit(self, selector, by="css"):
        """按回车提交"""
        r = self.session.post(f"{self.api}/submit", json={"by": by, "value": selector})
        return r.json()

    def screenshot(self):
        """截图"""
        r = self.session.get(f"{self.api}/screenshot")
        return r.json()

    def info(self):
        """获取页面信息"""
        r = self.session.get(f"{self.api}/info")
        return r.json()

    def extract(self, selector, by="css"):
        """提取文字"""
        r = self.session.post(f"{self.api}/extract", json={"by": by, "value": selector})
        return r.json()

    def execute(self, script):
        """执行 JS"""
        r = self.session.post(f"{self.api}/execute", json={"script": script})
        return r.json()

    def wait(self, seconds=2):
        """等待"""
        r = self.session.post(f"{self.api}/wait", json={"seconds": seconds})
        return r.json()

    def close(self):
        """关闭浏览器"""
        r = self.session.get(f"{self.api}/close")
        return r.json()
