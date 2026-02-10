import streamlit as st
import os
import time
import re
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

# --- 页面配置 ---
st.set_page_config(page_title="云端网盘搜", page_icon="☁️")
st.title("☁️ 网盘资源搜索器 (Cloud版)")

# --- 核心爬虫函数 ---
def get_driver():
    chrome_options = Options()
    
    # ------------------------------------------
    # Streamlit Cloud 部署必须的设置
    # ------------------------------------------
    chrome_options.add_argument("--headless")  # 必须无头
    chrome_options.add_argument("--no-sandbox") # 必须禁用沙盒
    chrome_options.add_argument("--disable-dev-shm-usage") # 解决内存不足
    chrome_options.add_argument("--disable-gpu")
    
    # 伪装 UA
    chrome_options.add_argument("user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1")
    chrome_options.add_argument("--window-size=375,812")
    
    # 提速设置
    prefs = {"profile.managed_default_content_settings.images": 2}
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.page_load_strategy = 'eager'

    # 使用 webdriver_manager 安装适合 Linux 的 Chromium 驱动
    return webdriver.Chrome(
        service=Service(
            ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()
        ),
        options=chrome_options
    )

def scrape_data(keyword):
    driver = None
    try:
        driver = get_driver()
        url = "http://hgm.y41566.com/app/index.html?id=test"
        driver.get(url)
        
        # 1. 等待输入框
        wait = WebDriverWait(driver, 10)
        search_input = wait.until(EC.element_to_be_clickable((By.ID, "search")))
        
        # 2. 输入
        search_input.clear()
        search_input.send_keys(keyword)
        
        # 3. 点击
        btn = driver.find_element(By.ID, "submitSearch")
        driver.execute_script("arguments[0].click();", btn)
        
        # 4. 等待结果
        try:
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "js-title")))
            time.sleep(0.5)
        except:
            return []
            
        # 5. 解析
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        results = []
        boxes = soup.find_all("div", class_="access-box")
        
        for box in boxes:
            title_tag = box.find(class_="js-title")
            if not title_tag: continue
            title = title_tag.get_text(strip=True)
            
            baidu = None
            quark = None
            
            info = box.find("div", class_="info")
            if info:
                # 获取所有文本（包含隐藏在按钮里的）
                full_text = str(info) 
                
                # 正则匹配链接
                bd = re.search(r'(https?://pan\.baidu\.com/s/[a-zA-Z0-9\-_]+)', full_text)
                if bd: baidu = bd.group(1)
                
                qk = re.search(r'(https?://pan\.quark\.cn/s/[a-zA-Z0-9\-_]+)', full_text)
                if qk: quark = qk.group(1)
            
            if baidu or quark:
                results.append({"title": title, "baidu": baidu, "quark": quark})
                
        return results
        
    except Exception as e:
        st.error(f"运行出错: {e}")
        return []
    finally:
        if driver:
            driver.quit()

# --- 界面 ---
query = st.text_input("请输入搜索关键词")
if st.button("搜索"):
    if query:
        with st.spinner("云端服务器正在搜索..."):
            data = scrape_data(query)
            if data:
                st.success(f"找到 {len(data)} 个结果")
                for item in data:
                    with st.container(border=True):
                        st.write(f"🎬 **{item['title']}**")
                        if item['baidu']: st.markdown(f"[百度网盘]({item['baidu']})")
                        if item['quark']: st.markdown(f"[夸克网盘]({item['quark']})")
            else:
                st.warning("未找到结果 (可能是云端IP被目标网站屏蔽，或者确实没资源)")
    else:
        st.warning("请输入内容")
