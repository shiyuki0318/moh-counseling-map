"""
智能自動更新爬蟲 - 繞過雲端 IP 封鎖
策略: 使用多種方法,加入隨機延遲,模擬真人行為

安裝: pip install selenium pandas beautifulsoup4 requests
"""

import pandas as pd
import time
import sys
import urllib3
import math
import re
import random
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains

# ===== 設定 =====
main_page_url = "https://sps.mohw.gov.tw/mhs"
OUTPUT_CSV_NAME = "MOHW_counseling_data_NEW.csv"
WAIT_TIME = 30

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def random_delay(min_sec=1, max_sec=3):
    """隨機延遲,模擬真人"""
    time.sleep(random.uniform(min_sec, max_sec))

def human_like_click(driver, element):
    """模擬真人點擊 - 使用 ActionChains"""
    try:
        actions = ActionChains(driver)
        actions.move_to_element(element).pause(random.uniform(0.5, 1.5)).click().perform()
        return True
    except:
        # 降級使用 JS 點擊
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except:
            return False

def smart_scrape_county(driver, wait, county_code, county_name):
    """
    智能爬取單一縣市
    使用多種策略避免被封鎖
    """
    print(f"\n   【{county_name}】開始爬取...")
    
    try:
        # 策略 1: 模擬真人操作 - 慢慢選擇縣市
        county_select = Select(wait.until(
            EC.visibility_of_element_located((By.ID, "county"))
        ))
        
        # 隨機滾動一下 (模擬真人)
        driver.execute_script("window.scrollBy(0, 100);")
        random_delay(0.5, 1)
        
        county_select.select_by_value(county_code)
        random_delay(1, 2)
        
        # 策略 2: 找到並點擊查詢按鈕
        search_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '查詢')]"))
        )
        
        if not human_like_click(driver, search_button):
            print(f"      ⚠️ 點擊查詢按鈕失敗")
            return []
        
        random_delay(2, 4)  # 等待結果載入
        
        # 策略 3: 檢查是否有資料
        try:
            # 等待表格出現
            wait.until(EC.presence_of_element_located((By.XPATH, "//table[@class='datagrid-btable']")))
            
            # 取得總筆數
            pager_element = driver.find_element(By.XPATH, "//div[contains(@class, 'datagrid-pager')]")
            pager_text = pager_element.text
            match = re.search(r'共\s*(\d+)\s*筆', pager_text)
            total_records = int(match.group(1)) if match else 0
            
            if total_records == 0:
                print(f"      ℹ️ 無資料")
                return []
            
            PAGE_SIZE = 10
            total_pages = math.ceil(total_records / PAGE_SIZE)
            print(f"      📊 共 {total_records} 筆, {total_pages} 頁")
            
        except Exception as e:
            print(f"      ❌ 無法取得資料: {e}")
            return []
        
        # 策略 4: 逐頁爬取,但加入智能延遲
        county_data = []
        
        for page_num in range(1, min(total_pages + 1, 100)):  # 限制最多100頁,避免卡太久
            print(f"      第 {page_num}/{total_pages} 頁", end="", flush=True)
            
            try:
                # 等待表格穩定
                table = wait.until(
                    EC.presence_of_element_located((By.XPATH, "//table[@class='datagrid-btable']"))
                )
                
                # 短暫延遲,確保資料完全載入
                time.sleep(0.5)
                
                # 取得 HTML
                table_html = table.get_attribute('outerHTML')
                soup = BeautifulSoup(table_html, 'html.parser')
                
                # 解析行
                rows = soup.find_all('tr')
                page_count = 0
                
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) >= 10:
                        try:
                            # 提取純文字 (移除 HTML 標籤)
                            def get_text(index):
                                if index < len(cols):
                                    return BeautifulSoup(str(cols[index]), 'html.parser').get_text(strip=True)
                                return ''
                            
                            row_data = {
                                'scraped_county_name': county_name,
                                'countyName': get_text(0),
                                'orgName': get_text(1),
                                'phone': get_text(2),
                                'address': get_text(3),
                                'payDetail': get_text(4),
                                'thisWeekCount': get_text(5) or '0',
                                'nextWeekCount': get_text(6) or '0',
                                'next2WeekCount': get_text(7) or '0',
                                'next3WeekCount': get_text(8) or '0',
                                'editDate': get_text(9),
                                'strTeleconsultation': get_text(10) if len(cols) > 10 else ''
                            }
                            
                            # 只保存有機構名稱的資料
                            if row_data['orgName']:
                                county_data.append(row_data)
                                page_count += 1
                        except Exception as e:
                            continue
                
                print(f" → {page_count} 筆", flush=True)
                
                # 策略 5: 點擊下一頁前,隨機延遲
                if page_num < total_pages:
                    # 每爬 3 頁休息久一點
                    if page_num % 3 == 0:
                        random_delay(2, 4)
                    else:
                        random_delay(1, 2)
                    
                    try:
                        next_btn = driver.find_element(
                            By.XPATH,
                            "//div[contains(@class, 'datagrid-pager')]//a[contains(@class, 'pagination-next')]"
                        )
                        
                        # 檢查按鈕是否可點擊
                        if 'l-btn-disabled' in next_btn.get_attribute('class'):
                            print(f"      ✓ 已到最後一頁")
                            break
                        
                        if not human_like_click(driver, next_btn):
                            print(f"      ⚠️ 下一頁點擊失敗")
                            break
                        
                    except Exception as e:
                        print(f"      ⚠️ 找不到下一頁按鈕")
                        break
            
            except Exception as e:
                print(f" ❌ 錯誤: {str(e)[:50]}")
                break
        
        print(f"      ✅ {county_name} 完成, 共 {len(county_data)} 筆")
        return county_data
    
    except Exception as e:
        print(f"      ❌ {county_name} 失敗: {e}")
        return []

# ===== 主程式 =====
def main():
    all_institutions_data = []
    driver = None
    
    try:
        print("=" * 70)
        print("🚀 智能自動更新爬蟲 - 開始執行")
        print("=" * 70)
        
        # 1. 啟動瀏覽器
        print("\n【步驟 1/6】啟動瀏覽器...")
        
        service = Service(executable_path="/usr/bin/chromedriver")
        
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        
        # 重要: 加入 User-Agent 模擬真實瀏覽器
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(WAIT_TIME + 10)
        wait = WebDriverWait(driver, WAIT_TIME)
        
        print("   ✓ 瀏覽器啟動成功")
        
        # 2. 載入頁面
        print("\n【步驟 2/6】載入網頁...")
        driver.get(main_page_url)
        random_delay(2, 3)
        print("   ✓ 網頁載入完成")
        
        # 3. 處理 Cookie
        print("\n【步驟 3/6】處理 Cookie...")
        try:
            cookie_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '同意') or contains(text(), '接受')]"))
            )
            human_like_click(driver, cookie_btn)
            random_delay(1, 2)
            print("   ✓ Cookie 已處理")
        except:
            print("   ℹ️ 無 Cookie 視窗")
        
        # 4. 開啟查詢視窗
        print("\n【步驟 4/6】開啟查詢視窗...")
        query_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//a[@class='queryServiceOrg']"))
        )
        human_like_click(driver, query_button)
        random_delay(2, 3)
        print("   ✓ 查詢視窗已開啟")
        
        # 5. 取得縣市列表
        print("\n【步驟 5/6】讀取縣市列表...")
        county_select_element = wait.until(
            EC.visibility_of_element_located((By.ID, "county"))
        )
        county_select = Select(county_select_element)
        
        county_map = {}
        for option in county_select.options:
            value = option.get_attribute('value')
            text = option.text
            if value:
                county_map[value] = text
        
        print(f"   ✓ 找到 {len(county_map)} 個縣市")
        
        # 6. 開始爬取
        print("\n【步驟 6/6】開始爬取資料...")
        print("=" * 70)
        
        for idx, (county_code, county_name) in enumerate(county_map.items(), 1):
            print(f"\n進度: {idx}/{len(county_map)}")
            
            county_data = smart_scrape_county(driver, wait, county_code, county_name)
            all_institutions_data.extend(county_data)
            
            # 每爬完一個縣市,休息一下
            if idx < len(county_map):
                delay = random.uniform(3, 6)
                print(f"   💤 休息 {delay:.1f} 秒...")
                time.sleep(delay)
        
        print("\n" + "=" * 70)
        print("✅ 爬取完成!")
        print("=" * 70)
    
    except Exception as e:
        print(f"\n❌ 爬蟲執行失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        if driver:
            driver.quit()
            print("\n瀏覽器已關閉")
    
    # 7. 儲存資料
    print("\n【儲存資料】")
    
    if not all_institutions_data:
        print("❌ 未抓到任何資料")
        sys.exit(1)
    
    df = pd.DataFrame(all_institutions_data)
    
    # 去重
    original_count = len(df)
    df = df.drop_duplicates(subset=['orgName', 'address', 'phone'])
    print(f"   去重: {original_count} → {len(df)} 筆")
    
    # 清理數字欄位
    num_cols = ['thisWeekCount', 'nextWeekCount', 'next2WeekCount', 'next3WeekCount']
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    
    # 儲存
    df.to_csv(OUTPUT_CSV_NAME, index=False, encoding='utf-8-sig')
    
    print(f"\n✅ 成功!")
    print(f"   總筆數: {len(df)}")
    print(f"   檔案: {OUTPUT_CSV_NAME}")
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()
