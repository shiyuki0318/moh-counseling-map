import pandas as pd
import time
import sys
import urllib3
import math 
from bs4 import BeautifulSoup 

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait 
from selenium.webdriver.support import expected_conditions as EC 
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager # 本地使用這個最方便

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

main_page_url = "https://sps.mohw.gov.tw/mhs"
inst_api_url = "https://sps.mohw.gov.tw/mhs/Home/QueryServiceOrgJsonList" 
all_institutions_data = [] 
county_map = {} 
token = ""
driver = None 

try:
    print("  [本地] 正在安裝/啟動 ChromeDriver...")
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    
    # *** (關鍵) 設為無頭模式，才不會在半夜彈出視窗 ***
    options.add_argument('--headless') 
    options.add_argument('--log-level=3')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 20) # (新) 本地也增加等待時間
    
    driver.get(main_page_url)
    print("  [本地] 頁面載入中...")

    try:
        cookie_accept_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '同意') or contains(text(), '接受')]"))
        )
        cookie_accept_button.click()
        time.sleep(1) 
    except Exception:
        pass 

    try:
        query_button_xpath = "//a[@class='queryServiceOrg']"
        query_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, query_button_xpath))
        )
        query_button.click()
        time.sleep(1) 
    except TimeoutException:
        print("錯誤：在 20 秒內找不到「心理諮商合作機構查詢」按鈕！")
        sys.exit(1)

    token_element = wait.until(EC.presence_of_element_located((By.NAME, "__RequestVerificationToken")))
    token = token_element.get_attribute('value')
    county_select_element = wait.until(EC.visibility_of_element_located((By.ID, "county")))
    county_select = Select(county_select_element)
    
    for option in county_select.options:
        value = option.get_attribute('value')
        name = option.text
        if value: county_map[value] = name
            
    print(f"  [本地] 成功取得 Token 和 {len(county_map)} 個縣市。")

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
        headers: {'X-Requested-With': 'XMLHttpRequest', 'Origin': window.location.origin, 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
        body: params.toString()
    }).then(response => response.json()).then(data => callback(data)).catch(error => callback({ 'error': error.toString() }));
    """
    
    driver.set_script_timeout(40) # (新) 增加腳本超時
    PAGE_SIZE = 10 
    
    for county_code, county_name in county_map.items():
        print(f"  [本地] 正在爬取: {county_name} ...")
        
        try:
            api_response = driver.execute_async_script(
                js_fetch_script, inst_api_url, token, county_code, PAGE_SIZE, 1 
            )
            if 'error' in api_response: raise Exception(f"JS 偵查失敗: {api_response['error']}")
            
            total_records = api_response.get('total', 0)
            institutions_in_page = api_response.get('rows', [])

            if total_records == 0 or not institutions_in_page:
                continue
            
            for inst in institutions_in_page: inst['scraped_county_name'] = county_name
            all_institutions_data.extend(institutions_in_page)
            total_pages = math.ceil(total_records / PAGE_SIZE)

            if total_pages > 1:
                for page_num in range(2, total_pages + 1):
                    api_response_page = driver.execute_async_script(
                        js_fetch_script, inst_api_url, token, county_code, PAGE_SIZE, page_num
                    )
                    if 'error' in api_response_page: continue 
                    institutions_in_page = api_response_page.get('rows', [])
                    for inst in institutions_in_page: inst['scraped_county_name'] = county_name
                    all_institutions_data.extend(institutions_in_page)
                    time.sleep(0.5) 
        except Exception as e:
            print(f"  爬取 {county_name} 時發生錯誤: {e}")
except Exception as e:
    print(f"Selenium 執行失敗: {e}")
finally:
    if driver:
        driver.quit()
        print("\n  [本地] Selenium 瀏覽器已關閉。")

if all_institutions_data:
    df = pd.DataFrame(all_institutions_data)
    df = df.drop_duplicates(subset=['orgName', 'address', 'phone'])
    
    def clean_html(raw_html):
        if pd.isna(raw_html): return ""
        return BeautifulSoup(str(raw_html), 'html.parser').get_text()

    if 'orgName' in df.columns: df['orgName'] = df['orgName'].apply(clean_html)
    if 'address' in df.columns: df['address'] = df['address'].apply(clean_html)
    
    df.to_csv("MOHW_counseling_data_NEW.csv", index=False, encoding='utf-8-sig')
    print(f"\n[本地] 資料已成功儲存至 'MOHW_counseling_data_NEW.csv'")
else:
    print("[本地] 未爬取到任何機構資料。")
    sys.exit(1)
