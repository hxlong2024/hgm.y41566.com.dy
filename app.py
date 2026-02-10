import streamlit as st
import os
import time
import re
import sqlite3
import asyncio
import httpx
import requests
import random
import string
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
# 0. 数据库管理模块
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
                platform TEXT,
                created_at TIMESTAMP
            )
        ''')
        self.conn.commit()

    def get_share(self, original_url):
        cursor = self.conn.cursor()
        cursor.execute("SELECT my_share_url FROM shares WHERE original_url = ?", (original_url,))
        result = cursor.fetchone()
        return result[0] if result else None

    def add_share(self, original_url, my_share_url, title, platform):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO shares (original_url, my_share_url, title, platform, created_at) VALUES (?, ?, ?, ?, ?)",
                (original_url, my_share_url, title, platform, datetime.now())
            )
            self.conn.commit()
        except Exception as e:
            print(f"写入失败: {e}")

db = DatabaseManager()

# ==========================================
# 1. 夸克引擎
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
        try:
            if '/s/' not in share_url: return False, "链接格式错误", None
            pwd_id = share_url.split('/s/')[-1].split('?')[0]
            
            async with httpx.AsyncClient(headers=self.headers) as client:
                r = await client.post("https://drive-pc.quark.cn/1/clouddrive/share/sharepage/token",
                                      json={"pwd_id": pwd_id, "passcode": ""}, params=self._params())
                stoken = r.json().get('data', {}).get('stoken')
                if not stoken: return False, "Cookie无效或资源失效", None

                params = self._params()
                params.update({"pwd_id": pwd_id, "stoken": stoken, "pdir_fid": "0"})
                r = await client.get("https://drive-pc.quark.cn/1/clouddrive/share/sharepage/detail", params=params)
                items = r.json().get('data', {}).get('list', [])
                if not items: return False, "内容为空", None
                
                source_fids = [i['fid'] for i in items]
                source_tokens = [i['share_fid_token'] for i in items]
                file_name = items[0]['file_name']

                save_data = {"fid_list": source_fids, "fid_token_list": source_tokens, "to_pdir_fid": "0", "pwd_id": pwd_id, "stoken": stoken, "scene": "link"}
                r = await client.post("https://drive.quark.cn/1/clouddrive/share/sharepage/save", json=save_data, params=self._params())
                if r.json().get('code') not in [0, 'OK']: return False, f"转存失败: {r.json().get('message')}", None
                
                await asyncio.sleep(1.5)
                list_params = self._params()
                list_params.update({'pdir_fid': '0', '_page': 1, '_size': 20, '_sort': 'updated_at:desc'})
                r = await client.get('https://drive-pc.quark.cn/1/clouddrive/file/sort', params=list_params)
                
                new_fid = None
                for item in r.json().get('data', {}).get('list', []):
                    if item['file_name'] == file_name:
                        new_fid = item['fid']
                        break
                if not new_fid:
                    if r.json().get('data', {}).get('list'): new_fid = r.json()['data']['list'][0]['fid']
                    else: return False, "找不到转存文件", None

                share_data = {"fid_list": [new_fid], "title": f"Share: {title}", "url_type": 1, "expired_type": 1}
                r = await client.post("https://drive-pc.quark.cn/1/clouddrive/share", json=share_data, params=self._params())
                share_res = r.json()
                
                if share_res.get('code') in [0, 'OK']: return True, "成功", share_res['data']['share_url']
                else: return False, f"分享失败: {share_res.get('message')}", None

        except Exception as e: return False, f"异常: {str(e)}", None

# ==========================================
# 2. 百度引擎
# ==========================================
class AdvancedBaiduEngine:
    def __init__(self, cookies):
        self.s = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
            'Referer': 'https://pan.baidu.com',
            'Cookie': cookies
        }
        self.bdstoken = ''

    def init_token(self):
        try:
            r = self.s.get('https://pan.baidu.com/api/gettemplatevariable', params={'fields': '["bdstoken"]'}, headers=self.headers)
            if r.json().get('errno') == 0:
                self.bdstoken = r.json()['result']['bdstoken']
                return True
            return False
        except: return False

    def save_and_share(self, share_url, pwd, title):
        try:
            if not self.bdstoken and not self.init_token(): return False, "Cookie失效", None
            m = re.search(r'baidu\.com/s/1([\w\-]+)', share_url) or re.search(r'baidu\.com/s/([\w\-]+)', share_url)
            if not m: return False, "链接错误", None
            surl = m.group(1)

            verify_params = {'surl': surl, 't': int(time.time() * 1000), 'bdstoken': self.bdstoken, 'channel': 'chunlei', 'web': 1, 'clienttype': 0}
            r = self.s.post('https://pan.baidu.com/share/verify', params=verify_params, data={'pwd': pwd, 'vcode': '', 'vcode_str': ''}, headers=self.headers)
            res_json = r.json()
            if res_json['errno'] != 0: return False, "验证失败", None
            self.headers['Cookie'] += f"; BDCLND={res_json.get('randsk')}"

            page_content = self.s.get(share_url.split('?')[0], headers=self.headers).text
            try:
                shareid = re.search(r'"shareid":(\d+?),', page_content).group(1)
                uk = re.search(r'"share_uk":"(\d+?)",', page_content).group(1)
                fs_ids = re.findall(r'"fs_id":\s*(\d+)', page_content)
                fs_ids = list(set(fs_ids))
                if not fs_ids: return False, "无文件", None
                fs_id_list_str = f"[{','.join(fs_ids)}]"
            except: return False, "页面解析失败", None

            transfer_params = {'shareid': shareid, 'from': uk, 'bdstoken': self.bdstoken}
            r = self.s.post('https://pan.baidu.com/share/transfer', params=transfer_params, data={'fsidlist': fs_id_list_str, 'path': '/'}, headers=self.headers)
            if r.json().get('errno') != 0: return False, "转存失败", None

            list_res = self.s.get('https://pan.baidu.com/api/list', params={'dir': '/', 'bdstoken': self.bdstoken, 'order': 'time', 'desc': 1}, headers=self.headers).json()
            new_fs_id = list_res['list'][0]['fs_id'] if list_res.get('list') else None
            if not new_fs_id: return False, "找不到新文件", None

            new_pwd = ''.join(random.choices(string.ascii_letters + string.digits, k=4))
            share_res = self.s.post('https://pan.baidu.com/share/set', params={'bdstoken': self.bdstoken, 'channel': 'chunlei', 'clienttype': 0, 'web': 1}, data={'period': 0, 'pwd': new_pwd, 'fid_list': f'[{new_fs_id}]', 'schannel': 4}, headers=self.headers).json()

            if share_res.get('errno') == 0: return True, "成功", f"{share_res['link']}?pwd={new_pwd}"
            else: return False, "分享失败", None
        except Exception as e: return False, f"异常: {str(e)}", None

# ==========================================
# 3. 爬虫部分
# ==========================================
st.set_page_config(page_title="资源分发平台", page_icon="🚀", layout="wide")
st.title("🚀 资源搜索 & 自动分发系统")

with st.sidebar:
    st.header("⚙️ 系统配置")
    quark_cookie = st.text_area("☁️ 夸克 Cookie", placeholder="填入 cookie...", height=100)
    baidu_cookie = st.text_area("🐻 百度 Cookie", placeholder="填入 cookie...", height=100)
    st.divider()
    st.caption("✅ 状态保存已启用 (修复按钮失效)")

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
        except: return []
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        results = []
        all_infos = soup.find_all("div", class_="info")
        
        for info_div in all_infos:
            parent_box = info_div.parent
            title = ""
            title_tag = parent_box.find(class_="js-title")
            if title_tag: title = title_tag.get_text(strip=True)
            if not title:
                for text in info_div.stripped_strings:
                    if "链接" not in text and "提取码" not in text and len(text) > 1:
                        title = text.strip('"').strip()
                        break
            if not title: title = "未知资源"
            
            baidu_data = None
            quark_data = None
            visible_text = info_div.get_text(separator=" ", strip=True)
            copy_btn = info_div.find("button", class_="js-copy")
            clipboard_text = copy_btn.get("data-clipboard-text", "") if copy_btn else ""
            full_text_context = visible_text + " " + clipboard_text
            all_links = re.findall(r'(https?://(?:pan\.baidu\.com|pan\.quark\.cn|pan\.xunlei\.com)[^\s"<>]+)', full_text_context)
            pwd = extract_pwd(full_text_context)

            for link in all_links:
                if "baidu.com" in link:
                    final_url = link
                    if pwd and "pwd=" not in link:
                        connector = "&" if "?" in link else "?"
                        final_url = f"{link}{connector}pwd={pwd}"
                    baidu_data = {"url": final_url, "pwd": pwd}
                elif "quark.cn" in link:
                    quark_data = {"url": link} 
            
            if baidu_data or quark_data:
                results.append({"title": title, "baidu": baidu_data, "quark": quark_data})
        return results
    except Exception as e:
        st.error(f"搜索出错: {e}")
        return []
    finally:
        if driver: driver.quit()

# ==========================================
# 4. 统一处理函数
# ==========================================
def handle_universal_save(original_url, title, platform, pwd=None):
    cached_link = db.get_share(original_url)
    if cached_link:
        st.toast(f"⚡️ {platform} 命中缓存！", icon="🚀")
        return cached_link
    
    success, msg, new_link = False, "", None
    if platform == "quark":
        if not quark_cookie:
            st.error("请先配置夸克 Cookie")
            return None
        engine = SimpleQuarkEngine(quark_cookie)
        try:
            success, msg, new_link = asyncio.run(engine.save_and_share(original_url, title))
        except Exception as e: msg = str(e)

    elif platform == "baidu":
        if not baidu_cookie:
            st.error("请先配置百度 Cookie")
            return None
        engine = AdvancedBaiduEngine(baidu_cookie)
        try:
            success, msg, new_link = engine.save_and_share(original_url, pwd, title)
        except Exception as e: msg = str(e)
    
    if success:
        db.add_share(original_url, new_link, title, platform)
        st.toast(f"{platform} 转存成功！", icon="✅")
        return new_link
    else:
        st.error(msg)
        return None

# ==========================================
# 5. 修复后的主界面逻辑 (使用 Session State)
# ==========================================

# 初始化 Session State
if 'search_results' not in st.session_state:
    st.session_state['search_results'] = None

col1, col2 = st.columns([4, 1])
with col1:
    query = st.text_input("🔍 搜资源", placeholder="输入电影/电视剧/动漫名称...", label_visibility="collapsed")
with col2:
    submit = st.button("全网搜索", type="primary", use_container_width=True)

# 搜索逻辑：只负责更新 Session State
if submit and query:
    with st.spinner("🕷️ 爬虫正在检索..."):
        data = scrape_data(query)
        st.session_state['search_results'] = data # 【关键】保存结果到 Session State

# 显示逻辑：从 Session State 读取数据，而不是依赖 submit 按钮状态
if st.session_state['search_results']:
    data = st.session_state['search_results']
    st.success(f"✅ 找到 {len(data)} 个资源")
    
    for idx, item in enumerate(data):
        with st.container(border=True):
            st.markdown(f"#### 🎬 {item['title']}")
            c1, c2 = st.columns(2)
            
            # --- 百度网盘 ---
            with c1:
                if item['baidu']:
                    b_url = item['baidu']['url']
                    b_pwd = item['baidu']['pwd'] or ""
                    
                    st.caption("🐻 百度网盘")
                    # 使用唯一的 key
                    if st.button("⚡ 获取下载链接", key=f"get_b_{idx}", type="secondary", use_container_width=True):
                        with st.spinner("正在转存..."):
                            final_link = handle_universal_save(b_url, item['title'], "baidu", b_pwd)
                            if final_link:
                                # 【关键】把生成的链接也存入 Session State
                                st.session_state[f"link_b_{idx}"] = final_link
                    
                    # 检查 Session State 是否有该链接
                    if f"link_b_{idx}" in st.session_state:
                        my_link = st.session_state[f"link_b_{idx}"]
                        st.markdown(f"""<div style="margin-top:5px;padding:8px;background:#fef2f2;border:1px solid #fecaca;border-radius:4px;">
                        <a href="{my_link}" target="_blank" style="color:#dc2626;font-weight:bold;text-decoration:none">👉 点击下载 (百度)</a>
                        </div>""", unsafe_allow_html=True)
                else:
                    st.caption("🐻 无百度资源")
            
            # --- 夸克网盘 ---
            with c2:
                if item['quark']:
                    q_url = item['quark']['url']
                    
                    st.caption("☁️ 夸克网盘")
                    if st.button("⚡ 获取下载链接", key=f"get_q_{idx}", type="primary", use_container_width=True):
                        with st.spinner("正在转存..."):
                            final_link = handle_universal_save(q_url, item['title'], "quark")
                            if final_link:
                                st.session_state[f"link_q_{idx}"] = final_link
                    
                    if f"link_q_{idx}" in st.session_state:
                        my_link = st.session_state[f"link_q_{idx}"]
                        st.markdown(f"""<div style="margin-top:5px;padding:8px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:4px;">
                        <a href="{my_link}" target="_blank" style="color:#0284c7;font-weight:bold;text-decoration:none">👉 点击下载 (夸克)</a>
                        </div>""", unsafe_allow_html=True)
                else:
                    st.caption("☁️ 无夸克资源")

elif submit:
    st.toast("请输入搜索关键词")
