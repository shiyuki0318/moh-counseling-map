import streamlit as st
import pandas as pd
import folium
import geopy.distance 
from streamlit_folium import st_folium 
from geopy.geocoders import ArcGIS 
from folium.plugins import LocateControl, MarkerCluster
import sys 
import os 
import time
import math 
import urllib3
from bs4 import BeautifulSoup 

# --- 導入 Selenium 和 Webdriver Manager ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait 
from selenium.webdriver.support import expected_conditions as EC 
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager 

# --- 0. 定義檔案名稱 ---
RAW_DATA_CSV = "MOHW_counseling_data_NEW.csv" # 爬蟲原始檔
FINAL_DATA_CSV = "MOHW_counseling_data_FINAL.csv" # 包含經緯度的最終檔

# ==============================================================================
# 
# 區塊 A：爬蟲 (Auto-Scraper)
# (這就是您成功的 Plan M 程式碼，被包成了一個函數)
#
# ==============================================================================
def run_scraper(status_placeholder):
    """
    執行「隱形」的 Selenium 爬蟲 (Plan M)，抓取最新資料。
    """
    status_placeholder.warning("STEP 1/3: 正在啟動 Selenium 爬蟲 (在背景執行，請稍候 1-2 分鐘)...")
    
    main_page_url = "https://sps.mohw.gov.tw/mhs"
    inst_api_url = "https://sps.mohw.gov.tw/mhs/Home/QueryServiceOrgJsonList" 
    all_institutions_data = [] 
    county_map = {} 
    token = ""
    driver = None 

    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        service = Service(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_argument('--headless') # (重要) 啟用 headless 模式，在背景執行
        options.add_argument('--log-level=3') 
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        driver = webdriver.Chrome(service=service, options=options)
        
        wait = WebDriverWait(driver, 10) 
        driver.get(main_page_url)
        
        # 2.3 處理 Cookie
        try:
            cookie_accept_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '同意') or contains(text(), '接受')]")))
            cookie_accept_button.click()
            time.sleep(1) 
        except Exception:
            pass # 找不到 Cookie 視窗也沒關係

        # 2.4 點擊「查詢」按鈕
        query_button_xpath = "//a[@class='queryServiceOrg']"
        query_button = wait.until(EC.element_to_be_clickable((By.XPATH, query_button_xpath)))
        query_button.click()
        time.sleep(1) 

        # 2.5 尋找 Token
        token_element = wait.until(EC.presence_of_element_located((By.NAME, "__RequestVerificationToken")))
        token = token_element.get_attribute('value')

        # 2.6 尋找縣市
        county_select_element = wait.until(EC.visibility_of_element_located((By.ID, "county")))
        county_select = Select(county_select_element)
        for option in county_select.options:
            value = option.get_attribute('value')
            name = option.text
            if value: county_map[value] = name
        
        status_placeholder.warning("STEP 1/3: 爬蟲已啟動，正在逐頁抓取資料...")

        # 3. (Plan M) 執行 JS + 處理「真實分頁」
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
        driver.set_script_timeout(30) 
        PAGE_SIZE = 10 
        
        for county_code, county_name in county_map.items():
            status_placeholder.warning(f"STEP 1/3: 正在爬取 {county_name}...")
            # 第一次請求 (偵查)
            api_response = driver.execute_async_script(js_fetch_script, inst_api_url, token, county_code, PAGE_SIZE, 1)
            total_records = api_response.get('total', 0)
            institutions_in_page = api_response.get('rows', [])
            if total_records == 0 or not institutions_in_page: continue
            
            for inst in institutions_in_page: inst['scraped_county_name'] = county_name
            all_institutions_data.extend(institutions_in_page)
            
            total_pages = math.ceil(total_records / PAGE_SIZE)
            
            # 子迴圈：爬取 Page 2 到最後一頁
            if total_pages > 1:
                for page_num in range(2, total_pages + 1):
                    api_response_page = driver.execute_async_script(js_fetch_script, inst_api_url, token, county_code, PAGE_SIZE, page_num)
                    if 'error' in api_response_page: continue 
                    institutions_in_page = api_response_page.get('rows', [])
                    for inst in institutions_in_page: inst['scraped_county_name'] = county_name
                    all_institutions_data.extend(institutions_in_page)
                    time.sleep(0.3) # 禮貌性暫停
        
        status_placeholder.success("STEP 1/3: 爬蟲執行完畢！")

    except Exception as e:
        status_placeholder.error(f"爬蟲執行失敗: {e}")
        return False
    finally:
        if driver:
            driver.quit()

    # 5. 儲存原始資料
    if not all_institutions_data:
        status_placeholder.error("爬蟲未抓到任何資料。")
        return False
        
    df = pd.DataFrame(all_institutions_data)
    df.to_csv(RAW_DATA_CSV, index=False, encoding='utf-8-sig')
    status_placeholder.success(f"STEP 1/3: 原始資料已儲存至 {RAW_DATA_CSV}")
    return True

# ==============================================================================
# 
# 區塊 B：地理編碼 (Geocoding)
# (這就是您成功的 ArcGIS v2 程式碼，被包成了一個函數)
#
# ==============================================================================
def run_geocoding(status_placeholder):
    """
    讀取 RAW_DATA_CSV，將地址轉為經緯度，儲存為 FINAL_DATA_CSV
    """
    status_placeholder.warning(f"STEP 2/3: 正在執行「地理編碼」(將地址轉為經緯度)...")
    status_placeholder.info("這一步會花 5-10 分鐘，因為免費服務有限速，請耐心等待。")
    
    try:
        df = pd.read_csv(RAW_DATA_CSV)
    except FileNotFoundError:
        status_placeholder.error(f"找不到爬蟲的原始檔 {RAW_DATA_CSV}！")
        return False

    geolocator = ArcGIS(timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=0.5, error_wait_seconds=5.0)
    
    latitudes = []
    longitudes = []
    count = 0
    total = len(df)

    for address in df['address']:
        count += 1
        if pd.isna(address) or address.strip() == "":
            latitudes.append(None)
            longitudes.append(None)
            continue

        # (新) 即時更新狀態
        status_placeholder.info(f"STEP 2/3: 正在查詢經緯度 ({count}/{total}): {address} ...")
        
        try:
            location = geocode(address)
            if location:
                latitudes.append(location.latitude)
                longitudes.append(location.longitude)
            else:
                latitudes.append(None)
                longitudes.append(None)
        except Exception:
            latitudes.append(None)
            longitudes.append(None)
    
    df['lat'] = latitudes
    df['lng'] = longitudes
    
    # (新) 清洗 HTML 標籤
    def clean_html(raw_html):
        if pd.isna(raw_html): return ""
        return BeautifulSoup(str(raw_html), 'html.parser').get_text()

    if 'orgName' in df.columns: df['orgName'] = df['orgName'].apply(clean_html)
    if 'address' in df.columns: df['address'] = df['address'].apply(clean_html)

    # 儲存最終檔案
    df.to_csv(FINAL_DATA_CSV, index=False, encoding='utf-8-sig')
    status_placeholder.success(f"STEP 2/3: 經緯度轉換完畢，已儲存至 {FINAL_DATA_CSV}")
    return True

# ==============================================================================
# 
# 區塊 C：Streamlit APP 主體 (v4 - 雙模式)
#
# ==============================================================================

# --- 1. 載入資料 (快取) ---
@st.cache_data 
def load_data(csv_file):
    try:
        df = pd.read_csv(csv_file)
        df = df.dropna(subset=['lat', 'lng'])
        # 預先處理名額，將 None 轉為 0
        df['thisWeekCount'] = pd.to_numeric(df['thisWeekCount'], errors='coerce').fillna(0).astype(int)
        # (其他名額欄位也一併處理)
        return df
    except FileNotFoundError:
        return None # (新) 找不到檔案時回傳 None
    except Exception as e:
        st.error(f"讀取資料時發生錯誤: {e}")
        return None

# --- 2. 定位使用者地址 (快取) ---
@st.cache_data 
def get_user_location(address):
    if not address: return None
    try:
        geolocator = ArcGIS(timeout=5)
        location = geolocator.geocode(address)
        if location: return (location.latitude, location.longitude)
        else: return None
    except Exception: return None

# --- 3. APP 主程式 ---
st.set_page_config(page_title="公費心理諮商地圖", layout="wide")
st.title("🏥 公費心理諮商 - 即時地圖搜尋系統 (終極版)")
st.write("您可以選擇「離我最近」來搜尋，或「瀏覽全台」來查看特定縣市的資源。")

# (新) 建立一個「狀態顯示區」，用於顯示更新進度
status_placeholder = st.empty()

# --- 檢查資料庫是否存在 ---
df_all = load_data(FINAL_DATA_CSV)

if df_all is None:
    # --- 情況 A：第一次執行，資料庫不存在 ---
    st.error(f"錯誤：找不到最終資料檔 '{FINAL_DATA_CSV}'！")
    st.warning("這可能是您第一次執行本程式。")
    if st.button("點此開始「初始化資料庫」(將執行爬蟲與地理編碼，約需 10-15 分鐘)"):
        
        # 執行爬蟲
        scraper_success = run_scraper(status_placeholder)
        
        # 如果爬蟲成功，才執行地理編碼
        if scraper_success:
            geocoding_success = run_geocoding(status_placeholder)
            
            if geocoding_success:
                status_placeholder.success("✅ 資料庫初始化完成！正在重新載入 APP...")
                time.sleep(2)
                st.rerun() # 重新整理頁面
            else:
                status_placeholder.error("❌ 地理編碼失敗，請檢查錯誤訊息。")
        else:
            status_placeholder.error("❌ 爬蟲失敗，請檢查錯誤訊息。")
else:
    # --- 情況 B：資料庫已存在，正常執行 APP ---
    
    # 3. 建立側邊欄 (Sidebar) 篩選器 ---
    st.sidebar.header("Step 1: 選擇搜尋模式")
    search_mode = st.sidebar.radio("您想如何搜尋？", ('離我最近', '瀏覽全台'))
    st.sidebar.header("Step 2: 設定篩選條件")

    df_filtered = df_all.copy() 
    user_loc = None
    map_center = [23.9738, 120.982] # 預設地圖中心 (台灣)
    map_zoom = 8 # 預設縮放 (全台灣)

    if search_mode == '離我最近':
        st.sidebar.subheader("📍 您的位置")
        user_address = st.sidebar.text_input("輸入您的地址", "臺北市中正區重慶南路一段122號")
        distance_km = st.sidebar.slider("搜尋範圍 (公里)", 1.0, 10.0, 3.0, 0.5)
        user_loc = get_user_location(user_address)
        
        if user_loc:
            st.sidebar.success(f"定位成功: {user_address}")
            map_center = [user_loc[0], user_loc[1]] 
            map_zoom = 13 
            df_filtered['distance'] = df_filtered.apply(
                lambda row: geopy.distance.great_circle(user_loc, (row['lat'], row['lng'])).km,
                axis=1
            )
            df_filtered = df_filtered[df_filtered['distance'] <= distance_km]
        else:
            st.warning("請在左側輸入有效的地址以啟用「離我最近」搜尋。")

    else: # 模式 B: 瀏覽全台
        st.sidebar.subheader("🌏 瀏覽全台")
        counties = ['[ 全選 ]'] + sorted(df_all['scraped_county_name'].unique())
        selected_counties = st.sidebar.multiselect("篩選縣市", counties, default=['[ 全選 ]'])
        
        if '[ 全選 ]' not in selected_counties:
            df_filtered = df_filtered[df_filtered['scraped_county_name'].isin(selected_counties)]

    # 通用篩選器：剩餘名額 (兩個模式共用)
    min_slots = st.sidebar.slider("本週至少剩餘名額", 0, 20, 1, 1)
    df_filtered = df_filtered[df_filtered['thisWeekCount'] >= min_slots]
        
    # 4. 資料更新功能
    st.sidebar.header("資料更新 (手動)")
    last_mod_time = os.path.getmtime(FINAL_DATA_CSV)
    st.sidebar.caption(f"資料最後更新: {time.ctime(last_mod_time)}")
    
    if st.sidebar.button("執行爬蟲，更新最新名額"):
        scraper_success = run_scraper(status_placeholder)
        if scraper_success:
            geocoding_success = run_geocoding(status_placeholder)
            if geocoding_success:
                status_placeholder.success("✅ 資料庫更新完成！正在重新載F APP...")
                st.cache_data.clear() # (重要) 清除舊的快取
                time.sleep(2)
                st.rerun() # 重新整理頁面
            else:
                status_placeholder.error("❌ 地理編碼失敗，請檢查錯誤訊息。")
        else:
            status_placeholder.error("❌ 爬蟲失敗，請檢查錯誤訊息。")

    # 5. 視覺化：在地圖上顯示結果
    m = folium.Map(location=map_center, zoom_start=map_zoom) 
    LocateControl(auto_start=False, strings={"title": "顯示我現在的位置", "popup": "您在這裡"}).add_to(m)
    marker_cluster = MarkerCluster().add_to(m)

    if search_mode == '離我最近' and user_loc:
        folium.Marker(location=user_loc, popup=f"<b>您的位置</b>", icon=folium.Icon(color="red", icon="user")).add_to(m)

    if df_filtered.empty:
        st.warning("在地圖範圍內找不到符合條件的診所。請調整篩選器。")
    else:
        st.success(f"在地圖範圍內找到 {len(df_filtered)} 間符合條件的診所：")
        
        for idx, row in df_filtered.iterrows():
            if row['thisWeekCount'] > 0: marker_color = 'green'; icon_name = 'check' 
            else: marker_color = 'blue'; icon_name = 'medkit' 
            
            popup_html = f"<b>{row['orgName']}</b><hr style='margin: 3px;'>"
            if 'distance' in df_filtered.columns:
                 popup_html += f"<b>距離:</b> {row['distance']:.2f} 公里<br>"
            popup_html += f"<b>本週名額:</b> <b>{int(row['thisWeekCount'])}</b><br><b>地址:</b> {row['address']}<br><b>電話:</b> {row['phone']}"
            
            folium.Marker(
                location=[row['lat'], row['lng']],
                popup=folium.Popup(popup_html, max_width=300),
                icon=folium.Icon(color=marker_color, icon=icon_name, prefix='fa')
            ).add_to(marker_cluster) 
            
        st_folium(m, width="100%", height=500, returned_objects=[])
        
        # 6. 顯示表格
        st.subheader("詳細資料列表")
        display_columns = ['orgName', 'thisWeekCount', 'scraped_county_name', 'address', 'phone', 'payDetail']
        if 'distance' in df_filtered.columns:
            display_columns.insert(1, 'distance') 
            st.dataframe(df_filtered.sort_values(by='distance')[display_columns].style.format({'distance': '{:.2f} km'}))
        else:
            st.dataframe(df_filtered[display_columns])