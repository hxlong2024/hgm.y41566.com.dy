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
st.set_page_config(page_title="云端网盘搜", page_icon="☁️", layout="wide")
st.title("☁️ 网盘资源搜索器 (修复版)")

# --- 核心爬虫函数 ---
def get_driver():
    chrome_options = Options()
    # Streamlit Cloud 部署必须的设置
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    # 伪装 UA
    chrome_options.add_argument("user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1")
    chrome_options.add_argument("--window-size=375,812")
    # 提速设置
    prefs = {"profile.managed_default_content_settings.images": 2}
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.page_load_strategy = 'eager'

    return webdriver.Chrome(
        service=Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()),
        options=chrome_options
    )

def extract_pwd(url, text_context):
    """
    专门提取提取码的辅助函数
    """
    pwd = ""
    # 1. 检查 URL 参数
    url_pwd_match = re.search(r'[?&]pwd=([a-zA-Z0-9]+)', url)
    if url_pwd_match:
        return url_pwd_match.group(1)

    # 2. 检查文本上下文 (支持中文冒号和英文冒号)
    # 逻辑：在全部文本中找 "提取码" 后面紧跟着的 4 位字符
    # 也就是不用管它是不是紧挨着链接，只要这段话里有提取码，就抓出来
    text_pwd_match = re.search(r'提取码\s*[:：]\s*([a-zA-Z0-9]{4})', text_context)
    if text_pwd_match:
        pwd = text_pwd_match.group(1)
    
    return pwd

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
            # 只要 .info 出现就可以，因为有的结果没有 .js-title
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "info")))
            time.sleep(0.5)
        except:
            return []
            
        # 5. 解析
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        results = []
        boxes = soup.find_all("div", class_="access-box")
        
        for box in boxes:
            # --- 【修复】标题获取逻辑 ---
            title = ""
            
            # 方案A: 尝试找标准的 js-title
            title_tag = box.find(class_="js-title")
            if title_tag:
                title = title_tag.get_text(strip=True)
            
            # 方案B: 如果没有 js-title，去 info 里找第一段文本
            info_div = box.find("div", class_="info")
            if not title and info_div:
                # stripped_strings 会生成所有非标签的纯文本
                # 我们取第一个不是 "链接" 也不是 "提取码" 的文本作为标题
                for text in info_div.stripped_strings:
                    if "链接" not in text and "提取码" not in text and len(text) > 1:
                        # 去掉可能存在的引号
                        title = text.strip('"').strip()
                        break
            
            if not title:
                title = "未知资源 (点击链接查看)"

            baidu_data = None
            quark_data = None
            
            # --- 获取所有相关文本用于查找提取码 ---
            full_text_context = ""
            if info_div:
                # 可见文本
                visible_text = info_div.get_text(separator=" ", strip=True)
                # 隐藏在按钮里的文本
                copy_btn = info_div.find("button", class_="js-copy")
                clipboard_text = copy_btn.get("data-clipboard-text", "") if copy_btn else ""
                full_text_context = visible_text + " " + clipboard_text

            # --- 链接匹配 ---
            all_links = re.findall(r'(https?://(?:pan\.baidu\.com|pan\.quark\.cn|pan\.xunlei\.com)[^\s"<>]+)', full_text_context)
            
            for link in all_links:
                # 提取密码
                pwd = extract_pwd(link, full_text_context)
                
                if "baidu.com" in link:
                    # 自动把提取码拼接到 URL 后面 (如果 URL 本身没有的话)
                    final_url = link
                    if pwd and "pwd=" not in link:
                        if "?" in link:
                            final_url = f"{link}&pwd={pwd}"
                        else:
                            final_url = f"{link}?pwd={pwd}"
                    
                    baidu_data = {"url": final_url, "pwd": pwd}
                    
                elif "quark.cn" in link:
                    quark_data = {"url": link, "pwd": pwd}

            # 只有有链接才显示
            if baidu_data or quark_data:
                results.append({"title": title, "baidu": baidu_data, "quark": quark_data})
                
        return results
        
    except Exception as e:
        st.error(f"运行出错: {e}")
        return []
    finally:
        if driver:
            driver.quit()

# --- 界面 ---
query = st.text_input("请输入搜索关键词", "喜羊羊")
if st.button("搜索"):
    if query:
        with st.spinner("云端服务器正在搜索..."):
            data = scrape_data(query)
            if data:
                st.success(f"找到 {len(data)} 个结果")
                for item in data:
                    with st.container(border=True):
                        # 标题加大加粗
                        st.markdown(f"### {item['title']}")
                        
                        cols = st.columns(2)
                        with cols[0]:
                            if item['baidu']: 
                                url = item['baidu']['url']
                                pwd = item['baidu']['pwd']
                                # 按钮文案带上提取码，方便查看
                                btn_label = f"👉 百度网盘 (码: {pwd})" if pwd else "👉 百度网盘"
                                st.link_button(btn_label, url)
                            else:
                                st.caption("无百度资源")

                        with cols[1]:
                            if item['quark']: 
                                url = item['quark']['url']
                                st.link_button("👉 夸克网盘", url)
                            else:
                                st.caption("无夸克资源")
            else:
                st.warning("未找到结果")
    else:
        st.warning("请输入内容")
