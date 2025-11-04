import pandas as pd
import time
import sys
import urllib3
import math 

# --- 導入 BeautifulSoup 用於 HTML 清洗 ---
from bs4 import BeautifulSoup 

# --- 導入 Selenium 的核心工具 ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait # 智慧等待
from selenium.webdriver.support import expected_conditions as EC # 預期條件
from selenium.webdriver.chrome.service import Service
# *** 移除 webdriver_manager 導入 ***
# from webdriver_manager.chrome import ChromeDriverManager 

# --- 0. 關閉 SSL 憑證驗證的警告訊息 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 定義網址和輸出檔案 ---
main_page_url = "https://sps.mohw.gov.tw/mhs"
inst_api_url = "https://sps.mohw.gov.tw/mhs/Home/QueryServiceOrgJsonList" 
OUTPUT_CSV_NAME = "MOHW_counseling_data_NEW.csv"

all_institutions_data = [] 

# --- 2. 步驟一和步驟二「合併」 (雲端模式) ---
print("正在啟動 Selenium 瀏覽器以取得 Token 和縣市列表...")
county_map = {} 
token = ""
driver = None 

try:
    # 2.1 啟動 Chrome (GitHub Actions 修正版)
    # 我們將 Chromedriver 路徑設定為 GitHub Actions 安裝的位置
    service = Service(executable_path="/usr/bin/chromedriver") # *** 關鍵修正 ***
    
    options = webdriver.ChromeOptions()
    # (重要) 啟用 headless 模式 (雲端環境必備)
    options.add_argument('--headless') 
    # (重要) 雲端環境所需的額外參數
    options.add_argument('--no-sandbox') 
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--log-level=3') 
    
    driver = webdriver.Chrome(service=service, options=options)
    
    wait = WebDriverWait(driver, 10) 
    
    # 2.2 載入頁面
    driver.get(main_page_url)
    print("  頁面載入中...")

    # --- 2.3 處理 Cookie 同意彈窗 (如果有的話) ---
    try:
        cookie_accept_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '同意') or contains(text(), '接受')]"))
        )
        cookie_accept_button.click()
        time.sleep(1) 
    except Exception:
        pass # 找不到 Cookie 視窗也沒關係

    # --- 2.4 點擊「心理諮商合作機構查詢」按鈕 ---
    query_button_xpath = "//a[@class='queryServiceOrg']"
    query_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, query_button_xpath))
    )
    query_button.click()
    time.sleep(1) 

    # --- 2.5 尋找 Token ---
    token_element = wait.until(
        EC.presence_of_element_located((By.NAME, "__RequestVerificationToken"))
    )
    token = token_element.get_attribute('value')

    # --- 2.6 尋找縣市下拉選單 ---
    county_select_element = wait.until(
        EC.visibility_of_element_located((By.ID, "county"))
    )
    county_select = Select(county_select_element)
    
    for option in county_select.options:
        value = option.get_attribute('value')
        name = option.text
        if value: 
            county_map[value] = name
            
    # --- 3. 步驟三：使用 Selenium 執行 JS + 處理「真實分頁」 ---
    print("\n開始(在 Selenium 中)遍歷所有縣市爬取機構資料...")

    js_fetch_script = """
    var api_url = arguments[0], token = arguments[1], county_code = arguments[2];
    var page_size = arguments[3], now_page = arguments[4];
    var callback = arguments[5];
    
    var params = new URLSearchParams();
    params.append('__RequestVerificationToken', token);
    params.append('county', county_code);
    params.append('orgName', '');
    params.append('NowPage', now_page);
    params.append('PageSize', page_size);
    params.append('FirstSearch', 'true');
    params.append('sortCol', '');
    params.append('sortMode', '');
    
    fetch(api_url, {
        method: 'POST',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': window.location.origin,
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
        },
        body: params.toString()
    })
    .then(response => response.json())
    .then(data => callback(data))
    .catch(error => callback({ 'error': error.toString() }));
    """
    
    driver.set_script_timeout(30) 
    PAGE_SIZE = 10 
    
    for county_code, county_name in county_map.items():
        print(f"  正在爬取: {county_name} (代碼: {county_code}) ...")
        
        try:
            # --- 第一次請求 (偵查) ---
            api_response = driver.execute_async_script(
                js_fetch_script, inst_api_url, token, county_code, PAGE_SIZE, 1 
            )
            
            if 'error' in api_response:
                print(f"  JS 偵查失敗: {api_response['error']}")
                continue
            
            total_records = api_response.get('total', 0)
            institutions_in_page = api_response.get('rows', [])

            if total_records == 0 or not institutions_in_page:
                continue
            
            for inst in institutions_in_page:
                inst['scraped_county_name'] = county_name
            all_institutions_data.extend(institutions_in_page)
            
            total_pages = math.ceil(total_records / PAGE_SIZE)

            # --- 子迴圈：爬取 Page 2 到最後一頁 ---
            if total_pages > 1:
                for page_num in range(2, total_pages + 1):
                    api_response_page = driver.execute_async_script(
                        js_fetch_script, inst_api_url, token, county_code, PAGE_SIZE, page_num
                    )
                    
                    if 'error' in api_response_page: continue 

                    institutions_in_page = api_response_page.get('rows', [])
                    
                    for inst in institutions_in_page:
                        inst['scraped_county_name'] = county_name
                    all_institutions_data.extend(institutions_in_page)
                    
                    time.sleep(0.3) 

        except Exception as e:
            print(f"  爬取 {county_name} 時發生未知錯誤: {e}")

except Exception as e:
    print(f"Selenium 執行失敗: {e}")
finally:
    if driver:
        driver.quit()
        print("\n  Selenium 瀏覽器已關閉。")


# --- 5. 儲存原始資料 ---
if not all_institutions_data:
    print("未爬取到任何機構資料。")
    sys.exit(1) # 退出程式碼，狀態