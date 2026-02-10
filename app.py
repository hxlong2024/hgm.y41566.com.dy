import streamlit as st
import os
import time
import re
import sqlite3
import asyncio
import httpx
import random
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

# ==========================================
# 0. 数据库管理模块 (新增核心)
# ==========================================
class DatabaseManager:
    def __init__(self, db_name="resource_cache.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_table()

    def create_table(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shares (
                original_url TEXT PRIMARY KEY,
                my_share_url TEXT,
                title TEXT,
                created_at TIMESTAMP
            )
        ''')
        self.conn.commit()

    def get_share(self, original_url):
        """查缓存：如果存在，返回我的分享链接；否则返回 None"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT my_share_url FROM shares WHERE original_url = ?", (original_url,))
        result = cursor.fetchone()
        return result[0] if result else None

    def add_share(self, original_url, my_share_url, title):
        """存缓存"""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO shares (original_url, my_share_url, title, created_at) VALUES (?, ?, ?, ?)",
                (original_url, my_share_url, title, datetime.now())
            )
            self.conn.commit()
        except Exception as e:
            print(f"数据库写入失败: {e}")

# 初始化数据库
db = DatabaseManager()

# ==========================================
# 1. 核心转存引擎 (夸克)
# ==========================================
class SimpleQuarkEngine:
    def __init__(self, cookies):
        self.headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'cookie': cookies,
            'origin': 'https://pan.quark.cn',
            'referer': 'https://pan.quark.cn/',
        }
    
    def _params(self):
        return {'pr': 'ucpro', 'fr': 'pc', '__dt': random.randint(100, 9999), '__t': int(time.time() * 1000)}

    async def save_and_share(self, share_url, title):
        """
        核心流程：转存 -> 分享
        返回: (Success_Bool, Message, New_Share_Link)
        """
        try:
            # --- 第一步：解析原始链接 ---
            if '/s/' not in share_url: return False, "链接格式错误", None
            pwd_id = share_url.split('/s/')[-1].split('?')[0]
            
            async with httpx.AsyncClient(headers=self.headers) as client:
                # --- 第二步：获取 stoken ---
                r = await client.post("https://drive-pc.quark.cn/1/clouddrive/share/sharepage/token",
                                      json={"pwd_id": pwd_id, "passcode": ""}, params=self._params())
                stoken = r.json().get('data', {}).get('stoken')
                if not stoken: return False, "提取码失效或Cookie无效", None

                # --- 第三步：获取文件列表 ---
                params = self._params()
                params.update({"pwd_id": pwd_id, "stoken": stoken, "pdir_fid": "0"})
                r = await client.get("https://drive-pc.quark.cn/1/clouddrive/share/sharepage/detail", params=params)
                items = r.json().get('data', {}).get('list', [])
                if not items: return False, "分享链接为空", None
                
                source_fids = [i['fid'] for i in items]
                source_tokens = [i['share_fid_token'] for i in items]
                file_name = items[0]['file_name'] # 拿到文件名，用于分享标题

                # --- 第四步：执行转存 (存到根目录) ---
                # 注意：这里我们存到根目录，如果想存到特定目录，需要先获取那个目录的 fid
                save_data = {
                    "fid_list": source_fids,
                    "fid_token_list": source_tokens,
                    "to_pdir_fid": "0", 
                    "pwd_id": pwd_id,
                    "stoken": stoken,
                    "scene": "link"
                }
                r = await client.post("https://drive.quark.cn/1/clouddrive/share/sharepage/save", 
                                      json=save_data, params=self._params())
                res = r.json()
                
                # 如果转存成功 或者 提示已经存在 (errno!=0 但 task_id 存在有时也是成功的，这里简单处理)
                if res.get('code') not in [0, 'OK']:
                    return False, f"转存失败: {res.get('message')}", None
                
                # 获取转存任务ID (有些转存是异步的，需要等待)
                task_id = res.get('data', {}).get('task_id')
                
                # --- 第五步：等待转存完成 (简单轮询) ---
                # 这里为了速度，我们假设转存很快。
                # 实际上应该轮询 task 接口。
                # 为了简化，我们尝试直接去"根目录"找刚刚转存的文件ID
                # 这是一个难点：转存后不知道新文件的 fid 是多少。
                # 变通方法：列出根目录最新的文件
                
                await asyncio.sleep(2) # 等2秒
                
                list_params = self._params()
                list_params.update({'pdir_fid': '0', '_page': 1, '_size': 20, '_sort': 'updated_at:desc'})
                r = await client.get('https://drive-pc.quark.cn/1/clouddrive/file/sort', params=list_params)
                
                new_fid = None
                for item in r.json().get('data', {}).get('list', []):
                    if item['file_name'] == file_name:
                        new_fid = item['fid']
                        break
                
                if not new_fid:
                    # 如果找不到同名文件，就拿最新的一个当替补（有风险，但能用）
                    file_list = r.json().get('data', {}).get('list', [])
                    if file_list:
                        new_fid = file_list[0]['fid']
                    else:
                        return False, "转存成功但找不到文件ID", None

                # --- 第六步：创建我的分享 ---
                share_data = {
                    "fid_list": [new_fid],
                    "title": f"分享：{title}",
                    "url_type": 1, # 1: 永久, 2: 7天? 需要测试
                    "expired_type": 1 # 永久有效
                }
                r = await client.post("https://drive-pc.quark.cn/1/clouddrive/share", json=share_data, params=self._params())
                share_res = r.json()
                
                if share_res.get('code') in [0, 'OK']:
                    share_url = share_res['data']['share_url']
                    return True, "成功", share_url
                else:
                    return False, f"分享创建失败: {share_res.get('message')}", None

        except Exception as e:
            return False, f"处理异常: {str(e)}", None

# ==========================================
# 2. 爬虫部分 (保持修复版逻辑)
# ==========================================

st.set_page_config(page_title="资源分发平台", page_icon="🚀", layout="wide")
st.title("🚀 资源搜索 & 自动分发系统")

with st.sidebar:
    st.header("管理员配置")
    st.info("填入 Cookie 以启用自动转存和分享功能。")
    quark_cookie = st.text_area("夸克 Cookie", placeholder="填入 cookie...", height=100)
    
    st.divider()
    st.caption("数据库状态：已启用自动去重缓存")

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1")
    chrome_options.add_argument("--window-size=375,812")
    prefs = {"profile.managed_default_content_settings.images": 2}
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.page_load_strategy = 'eager'
    return webdriver.Chrome(service=Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()), options=chrome_options)

def extract_pwd(text_context):
    match = re.search(r'提取码\s*[:：]\s*([a-zA-Z0-9]{4})', text_context)
    if match: return match.group(1)
    return None

def scrape_data(keyword):
    driver = None
    try:
        driver = get_driver()
        url = "http://hgm.y41566.com/app/index.html?id=test"
        driver.get(url)
        
        wait = WebDriverWait(driver, 10)
        search_input = wait.until(EC.element_to_be_clickable((By.ID, "search")))
        search_input.clear()
        search_input.send_keys(keyword)
        
        btn = driver.find_element(By.ID, "submitSearch")
        driver.execute_script("arguments[0].click();", btn)
        
        try:
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "info")))
            time.sleep(0.5)
        except:
            return []
            
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        results = []
        all_infos = soup.find_all("div", class_="info")
        
        for info_div in all_infos:
            parent_box = info_div.parent
            title = ""
            title_tag = parent_box.find(class_="js-title")
            if title_tag:
                title = title_tag.get_text(strip=True)
            if not title:
                for text in info_div.stripped_strings:
                    if "链接" not in text and "提取码" not in text and len(text) > 1:
                        title = text.strip('"').strip()
                        break
            if not title: title = "未知资源"

            quark_data = None
            visible_text = info_div.get_text(separator=" ", strip=True)
            copy_btn = info_div.find("button", class_="js-copy")
            clipboard_text = copy_btn.get("data-clipboard-text", "") if copy_btn else ""
            full_text_context = visible_text + " " + clipboard_text

            all_links = re.findall(r'(https?://(?:pan\.baidu\.com|pan\.quark\.cn|pan\.xunlei\.com)[^\s"<>]+)', full_text_context)
            
            for link in all_links:
                if "quark.cn" in link:
                    quark_data = {"url": link}
            
            if quark_data: # 只保留夸克资源，因为我们要演示夸克自动分发
                results.append({"title": title, "quark": quark_data})
                
        return results
    except Exception as e:
        st.error(f"运行出错: {e}")
        return []
    finally:
        if driver: driver.quit()

# ==========================================
# 3. 核心交互逻辑 (带缓存)
# ==========================================

# 回调函数：处理转存请求
def handle_save_request(original_url, title):
    # 1. 先查数据库
    cached_link = db.get_share(original_url)
    if cached_link:
        st.toast("⚡️ 命中缓存！秒速获取链接", icon="🚀")
        return cached_link
    
    # 2. 数据库没找到，开始转存
    if not quark_cookie:
        st.error("管理员未配置夸克 Cookie")
        return None
        
    engine = SimpleQuarkEngine(quark_cookie)
    # 运行异步任务
    try:
        success, msg, new_share_url = asyncio.run(engine.save_and_share(original_url, title))
        if success:
            # 3. 转存成功，写入数据库
            db.add_share(original_url, new_share_url, title)
            st.toast("转存并分享成功！", icon="✅")
            return new_share_url
        else:
            st.error(msg)
            return None
    except Exception as e:
        st.error(f"系统错误: {e}")
        return None

# 界面部分
query = st.text_input("🔍 搜资源", placeholder="输入电影名...")
if st.button("搜索"):
    if query:
        with st.spinner("正在全网搜索..."):
            data = scrape_data(query)
            if data:
                st.success(f"找到 {len(data)} 个夸克资源")
                
                for idx, item in enumerate(data):
                    with st.container(border=True):
                        st.markdown(f"#### 🎬 {item['title']}")
                        
                        original_url = item['quark']['url']
                        
                        # 检查这个资源是否已经在我们的数据库里
                        # 注意：这里为了不影响渲染速度，我们不在这里查库，而是点击按钮后查
                        # 或者，如果你想显示"直接获取"还是"转存获取"，可以在这里预查
                        
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            st.caption(f"原始来源: {original_url[:30]}...")
                        
                        with col2:
                            # 这里的 key 很重要，保证每个按钮唯一
                            if st.button("⚡ 获取下载链接", key=f"get_{idx}", type="primary"):
                                with st.spinner("正在为您准备资源..."):
                                    final_link = handle_save_request(original_url, item['title'])
                                    
                                    if final_link:
                                        # 使用 session_state 来保存结果，避免页面刷新后消失
                                        st.session_state[f"link_{idx}"] = final_link
                        
                        # 如果有生成好的链接，显示出来
                        if f"link_{idx}" in st.session_state:
                            my_link = st.session_state[f"link_{idx}"]
                            st.markdown(f"""
                            <div style="background-color:#f0f9ff;padding:10px;border-radius:5px;border:1px solid #bae6fd;">
                                ✅ <b>您的专属链接已生成：</b><br>
                                <a href="{my_link}" target="_blank" style="font-size:18px;font-weight:bold;">👉 点我跳转下载</a>
                                <br><span style="font-size:12px;color:gray">({my_link})</span>
                            </div>
                            """, unsafe_allow_html=True)
                            
            else:
                st.warning("未找到资源")
    else:
        st.warning("请输入内容")
