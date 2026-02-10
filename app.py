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
st.title("☁️ 网盘资源搜索器 (Cloud版)")

# --- 核心爬虫函数 ---
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

    return webdriver.Chrome(
        service=Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()),
        options=chrome_options
    )

def extract_pwd(text_context):
    """从文本中提取提取码 (支持 : 和 ：)"""
    match = re.search(r'提取码\s*[:：]\s*([a-zA-Z0-9]{4})', text_context)
    if match:
        return match.group(1)
    return None

def scrape_data(keyword):
    driver = None
    try:
        driver = get_driver()
        url = "http://hgm.y41566.com/app/index.html?id=test"
        driver.get(url)
        
        # 1. 等待
        wait = WebDriverWait(driver, 10)
        search_input = wait.until(EC.element_to_be_clickable((By.ID, "search")))
        
        # 2. 输入
        search_input.clear()
        search_input.send_keys(keyword)
        
        # 3. 点击
        btn = driver.find_element(By.ID, "submitSearch")
        driver.execute_script("arguments[0].click();", btn)
        
        # 4. 等待 .info 出现 (只要内容出来了就行)
        try:
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "info")))
            time.sleep(0.5)
        except:
            return []
            
        # 5. 解析
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        results = []
        
        # --- 修复核心：不再遍历 box，而是遍历 info ---
        # 这样无论父级是 access-box 还是 box 都能抓到，找回丢失的数据
        infos = soup.find_all("div", class_="info")
        
        for info_div in infos:
            # 找到当前 info 的父级容器，方便找 js-title
            wrapper = info_div.parent
            
            # --- 1. 标题提取 (修复 **** 问题) ---
            title = ""
            
            # 策略A: 先在父级找 js-title (标准结构)
            title_tag = wrapper.find(class_="js-title")
            if title_tag:
                title = title_tag.get_text(strip=True)
            
            # 策略B: 如果没有 js-title，直接读取 info 里的纯文本 (非标准结构)
            if not title:
                # stripped_strings 生成器会依次给出所有非标签的文本
                for text in info_div.stripped_strings:
                    # 排除掉 "链接：" "提取码：" 这种功能性文字，剩下的长文本就是标题
                    if "链接" not in text and "提取码" not in text and len(text) > 2:
                        # 去掉两边的引号
                        title = text.strip('"').strip()
                        break
            
            if not title:
                title = "未知资源"

            # --- 2. 链接与密码提取 ---
            baidu_data = None
            quark_data = None
            
            # 获取全部文本用于正则
            visible_text = info_div.get_text(separator=" ", strip=True)
            copy_btn = info_div.find("button", class_="js-copy")
            clipboard_text = copy_btn.get("data-clipboard-text", "") if copy_btn else ""
            full_text_context = visible_text + " " + clipboard_text

            # 提取链接
            all_links = re.findall(r'(https?://(?:pan\.baidu\.com|pan\.quark\.cn|pan\.xunlei\.com)[^\s"<>]+)', full_text_context)
            
            # 提取密码
            pwd = extract_pwd(full_text_context)

            for link in all_links:
                if "baidu.com" in link:
                    # 自动拼密码
                    final_url = link
                    if pwd and "pwd=" not in link:
                        connector = "&" if "?" in link else "?"
                        final_url = f"{link}{connector}pwd={pwd}"
                    
                    baidu_data = {"url": final_url, "pwd": pwd}
                    
                elif "quark.cn" in link:
                    quark_data = {"url": link, "pwd": None}

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
                        st.markdown(f"### {item['title']}")
                        
                        cols = st.columns(2)
                        with cols[0]:
                            if item['baidu']: 
                                url = item['baidu']['url']
                                pwd = item['baidu']['pwd']
                                label = f"[百度网盘]({url})"
                                if pwd:
                                    label += f" (码: `{pwd}`)"
                                st.markdown(label)
                            else:
                                st.caption("无百度资源")

                        with cols[1]:
                            if item['quark']: 
                                st.markdown(f"[夸克网盘]({item['quark']['url']})")
                            else:
                                st.caption("无夸克资源")
            else:
                st.warning("未找到结果")
    else:
        st.warning("请输入内容")
