import pandas as pd
import time
import sys
import urllib3
import math 
import re 
from bs4 import BeautifulSoup 

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
WAIT_TIME = 30  

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
all_institutions_data = [] 
driver = None 

try:
    # 2.1 啟動 Chrome (GitHub Actions 終極穩定版)
    service = Service(executable_path="/usr/bin/chromedriver") 
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')     
    options.add_argument('--no-sandbox')      
    options.add_argument('--disable-dev-shm-usage') 
    options.add_argument('--disable-gpu')     
    options.add_argument('--window-size=1920,1080') 
    options.add_argument('--log-level=3') 
    
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(WAIT_TIME + 10) 
    wait = WebDriverWait(driver, WAIT_TIME) 
    
    print("  [雲端] 正在載入主頁面...")
    driver.get(main_page_url)

    try:
        cookie_accept_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '同意') or contains(text(), '接受')]"))
        )
        cookie_accept_button.click()
        time.sleep(1) 
    except Exception:
        print("  [雲端] 未發現 Cookie 視窗，繼續執行。")

    print("  [雲端] 正在點擊「機構查詢」按鈕...")
    query_button_xpath = "//a[@class='queryServiceOrg']"
    query_button = wait.until(EC.element_to_be_clickable((By.XPATH, query_button_xpath)))
    driver.execute_script("arguments[0].click();", query_button) 
    time.sleep(2) 

    print("  [雲端] 正在讀取縣市列表中...")
    county_select_element = wait.until(EC.visibility_of_element_located((By.ID, "county")))
    county_select = Select(county_select_element)
    county_map = {option.get_attribute('value'): option.text for option in county_select.options if option.get_attribute('value')}
    search_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '查詢')]")))

    print("\n[雲端] 開始遍歷所有縣市並直接爬取 HTML 表格...")

    for county_code, county_name in county_map.items():
        print(f"  [雲端] 正在爬取: {county_name} ...")
        
        try:
            county_select = Select(wait.until(EC.visibility_of_element_located((By.ID, "county"))))
            county_select.select_by_value(county_code)
            time.sleep(1) 
            
            search_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '查詢')]")))
            driver.execute_script("arguments[0].click();", search_button)
            time.sleep(3) 

            try:
                total_records_element = wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'datagrid-pager') and contains(text(), '共')]")))
                text = total_records_element.text
                total_records_match = re.search(r'共\s*(\d+)\s*筆', text) 
                total_records = int(total_records_match.group(1)) if total_records_match else 0
            except Exception:
                total_records = 0 

            if total_records == 0:
                print(f"    -> {county_name} 沒有資料。")
                continue

            PAGE_SIZE = 10 
            total_pages = math.ceil(total_records / PAGE_SIZE)
            current_county_data = []
            
            for page_num in range(1, total_pages + 1):
                print(f"    -> 正在讀取 {county_name} 第 {page_num}/{total_pages} 頁...")
                table_element = wait.until(EC.presence_of_element_located((By.XPATH, "//table[@class='datagrid-btable']")))
                table_html = table_element.get_attribute('outerHTML')
                
                soup = BeautifulSoup(table_html, 'html.parser')
                rows = soup.find_all('tr')
                
                for row in rows:
                    cols = row.find_all('td')
                    fields = [col.get('field') for col in cols if col.get('field')]
                    data = [col.get_text(strip=True) for col in cols]
                    
                    if len(data) >= 11 and 'orgName' in fields: 
                        row_data = {
                            'scraped_county_name': county_name,
                            'orgName': data[fields.index('orgName')] if 'orgName' in fields else '',
                            'address': data[fields.index('address')] if 'address' in fields else '',
                            'phone': data[fields.index('phone')] if 'phone' in fields else '',
                            'payDetail': data[fields.index('payDetail')] if 'payDetail' in fields else '',
                            'strTeleconsultation': data[fields.index('strTeleconsultation')] if 'strTeleconsultation' in fields else '',
                            'thisWeekCount': data[fields.index('thisWeekCount')] if 'thisWeekCount' in fields else '0',
                            'nextWeekCount': data[fields.index('nextWeekCount')] if 'nextWeekCount' in fields else '0',
                            'next2WeekCount': data[fields.index('next2WeekCount')] if 'next2WeekCount' in fields else '0',
                            'next3WeekCount': data[fields.index('next3WeekCount')] if 'next3WeekCount' in fields else '0',
                            'editDate': data[fields.index('editDate')] if 'editDate' in fields else ''
                        }
                        current_county_data.append(row_data)

                if page_num < total_pages:
                    next_page_button = driver.find_element(By.XPATH, "//div[contains(@class, 'datagrid-pager')]//span[contains(@class, 'pagination-next')]")
                    driver.execute_script("arguments[0].click();", next_page_button)
                    time.sleep(2.0) 

            all_institutions_data.extend(current_county_data)
            print(f"  ✅ {county_name} 爬取完畢。共 {total_records} 筆。")

        except Exception as e:
            print(f"  爬取 {county_name} 時發生錯誤: {e}")

except Exception as e:
    print(f"Selenium 執行失敗: {e}")
finally:
    if driver:
        driver.quit()
        print("\n  [雲端] Selenium 瀏覽器已關閉。")

if not all_institutions_data:
    print("未爬取到任何機構資料。")
    sys.exit(1) 
else:
    df_final = pd.DataFrame(all_institutions_data)
    df_final = df_final.drop_duplicates(subset=['orgName', 'address', 'phone'])
    
    num_cols = ['thisWeekCount', 'nextWeekCount', 'next2WeekCount', 'next3WeekCount']
    for col in num_cols:
        df_final[col] = pd.to_numeric(df_final[col], errors='coerce').fillna(0).astype(int)

    df_final.to_csv(OUTPUT_CSV_NAME, index=False, encoding='utf-8-sig')
    print(f"\n✅ [雲端] 資料已成功儲存至 '{OUTPUT_CSV_NAME}'")
    print(f"總共爬取到 {len(df_final)} 筆機構資料。")
