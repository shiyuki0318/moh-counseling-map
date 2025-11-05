import pandas as pd
import time
import sys
import urllib3
import math 
from bs4 import BeautifulSoup 

# 導入 Selenium 的核心工具
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait 
from selenium.webdriver.support import expected_conditions as EC 
from selenium.webdriver.chrome.service import Service

# --- 0. 設置常量 ---
main_page_url = "https://sps.mohw.gov.tw/mhs"
OUTPUT_CSV_NAME = "MOHW_counseling_data_NEW.csv"
WAIT_TIME = 30  # 增加連線等待時間

all_institutions_data = [] 

try:
    # 2.1 啟動 Chrome (GitHub Actions 修正版)
    service = Service(executable_path="/usr/bin/chromedriver")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless') 
    options.add_argument('--no-sandbox') 
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--log-level=3') 
    
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, WAIT_TIME) 
    
    # 2.2 載入頁面
    driver.get(main_page_url)

    # --- 處理 Cookie 同意彈窗 ---
    try:
        cookie_accept_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '同意') or contains(text(), '接受')]")))
        cookie_accept_button.click()
        time.sleep(1) 
    except Exception:
        pass

    # --- 2.4 點擊「心理諮商合作機構查詢」按鈕 ---
    query_button_xpath = "//a[@class='queryServiceOrg']"
    query_button = wait.until(EC.element_to_be_clickable((By.XPATH, query_button_xpath)))
    query_button.click()
    time.sleep(2) # 等待彈出視窗完全出現

    # --- 2.5 尋找縣市下拉選單並獲取代碼 ---
    county_select_element = wait.until(EC.visibility_of_element_located((By.ID, "county")))
    county_select = Select(county_select_element)
    county_map = {option.get_attribute('value'): option.text for option in county_select.options if option.get_attribute('value')}

    # --- 2.6 尋找「查詢」按鈕 (在彈出視窗內) ---
    search_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '查詢')]")))

    # --- 3. (最終修復) 步驟三：遍歷縣市，直接爬取 HTML 表格 ---
    print("\n開始遍歷所有縣市並直接爬取 HTML 表格...")

    for county_code, county_name in county_map.items():
        print(f"  正在爬取: {county_name} (代碼: {county_code}) ...")
        
        try:
            # 選擇縣市
            county_select.select_by_value(county_code)
            time.sleep(1) 
            
            # 點擊查詢按鈕
            search_button.click()
            time.sleep(3) # 給予充足時間讓表格載入 (關鍵)

            # --- 核心邏輯：偵測總頁數 ---
            try:
                # 尋找總頁數元素 (例如: 顯示 1 到 10, 共 617 筆記錄)
                total_records_element = wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'datagrid-pager') and contains(text(), '共')]")))
                text = total_records_element.text
                import re
                total_records_match = re.search(r'共(\d+)筆', text)
                total_records = int(total_records_match.group(1)) if total_records_match else 0
            except Exception:
                total_records = 0

            if total_records == 0:
                print(f"    -> {county_name} 沒有資料或載入失敗。")
                continue

            PAGE_SIZE = 10 # 每次只顯示 10 筆
            total_pages = math.ceil(total_records / PAGE_SIZE)

            # --- 子迴圈：遍歷每一頁 ---
            current_page_data = []
            
            # 尋找下一頁按鈕 (->)
            next_page_button = driver.find_element(By.XPATH, "//span[contains(@class, 'pagination-next')]")

            for page_num in range(1, total_pages + 1):
                # 1. 爬取當前頁面資料
                table_html = driver.find_element(By.XPATH, "//table[@class='datagrid-btable']").get_attribute('outerHTML')
                soup = BeautifulSoup(table_html, 'html.parser')
                rows = soup.find_all('tr')
                
                for row in rows:
                    cols = row.find_all('td')
                    cols = [ele.text.strip() for ele in cols]
                    if len(cols) >= 10: # 確保有足夠的欄位
                        current_page_data.append({
                            'scraped_county_name': county_name,
                            'countyName': cols[0], # 縣市別
                            'orgName': cols[1],    # 機構名稱
                            'address': cols[2],    # 地址
                            'phone': cols[3],      # 聯絡電話
                            'payDetail': cols[4],  # 自付費用
                            'strTeleconsultation': cols[5], # 提供通訊服務
                            'thisWeekCount': cols[6], # 本週名額
                            # ...其他欄位略過以簡化...
                            'editDate': cols[10] # 資料更新時間
                        })

                # 2. 點擊下一頁 (如果不是最後一頁)
                if page_num < total_pages:
                    next_page_button.click()
                    time.sleep(1) # 讓表格有時間刷新

            all_institutions_data.extend(current_page_data)
            print(f"  ✅ {county_name} 爬取完畢。共 {total_records} 筆。")

        except Exception as e:
            print(f"  爬取 {county_name} 時發生錯誤: {e}")

except Exception as e:
    print(f"Selenium 執行失敗: {e}")
finally:
    if driver:
        driver.quit()
        print("\n  Selenium 瀏覽器已關閉。")


# --- 5. 儲存原始資料 ---
if not all_institutions_data:
    print("未爬取到任何機構資料。")
    sys.exit(1)
else:
    df = pd.DataFrame(all_institutions_data)
    # (最終版只需儲存，不需複雜清洗，地理編碼腳本會處理)
    df.to_csv(OUTPUT_CSV_NAME, index=False, encoding='utf-8-sig')
    print(f"\n✅ 資料已成功儲存至 '{OUTPUT_CSV_NAME}'")
    print(f"總共爬取到 {len(df)} 筆機構資料。")
