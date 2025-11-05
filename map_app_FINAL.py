import streamlit as st
import pandas as pd
import folium
import geopy.distance 
from streamlit_folium import st_folium 
from geopy.geocoders import ArcGIS 
from folium.plugins import LocateControl, MarkerCluster
import time

# --- (新) 定義 GitHub 上的「原始資料」URL ---
# 這是根據您的倉庫名稱 'shiyuki0318/moh-counseling-map' 產生的
GITHUB_RAW_URL = "https://raw.githubusercontent.com/shiyuki0318/moh-counseling-map/main/MOHW_counseling_data_FINAL.csv"

# --- 1. 載入資料 (修改版：從 GitHub URL 讀取) ---
@st.cache_data(ttl=3600) # (新) 快取 1 小時 (3600 秒)
def load_data(url):
    """
    從 GitHub 公開 URL 讀取資料。
    ttl=3600 代表 APP 每小時會強制重新抓取一次最新資料。
    """
    try:
        df = pd.read_csv(url, encoding='utf-8-sig') # (新) 直接從 URL 讀取
        df = df.dropna(subset=['lat', 'lng'])
        # 預先處理名額，將 None 轉為 0
        df['thisWeekCount'] = pd.to_numeric(df['thisWeekCount'], errors='coerce').fillna(0).astype(int)
        return df
    except Exception as e:
        st.error(f"從 GitHub 載入資料時發生錯誤: {e}")
        st.info("請檢查 GITHUB_RAW_URL 變數是否設定正確。")
        return pd.DataFrame() 

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
st.title("🏥 公費心理諮商 - 即時地圖搜尋系統 (混合雲版)")
st.write("您可以選擇「離我最近」來搜尋，或「瀏覽全台」來查看特定縣市的資源。")

# (新) 讀取資料
df_all = load_data(GITHUB_RAW_URL)

if df_all.empty:
    st.warning("資料載入中... 如果持續顯示錯誤，請稍後再試。")
    st.stop() 
    
# --- 4. 側邊欄與篩選邏輯 ---
st.sidebar.header("Step 1: 選擇搜尋模式")
search_mode = st.sidebar.radio("您想如何搜尋？", ('離我最近', '瀏覽全台'))
st.sidebar.header("Step 2: 設定篩選條件")

df_filtered = df_all.copy() 
user_loc = None
map_center = [23.9738, 120.982] 
map_zoom = 8 

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
else: 
    st.sidebar.subheader("🌏 瀏覽全台")
    counties = ['[ 全選 ]'] + sorted(df_all['scraped_county_name'].unique())
    selected_counties = st.sidebar.multiselect("篩選縣市", counties, default=['[ 全選 ]'])
    
    if '[ 全選 ]' not in selected_counties:
        df_filtered = df_filtered[df_filtered['scraped_county_name'].isin(selected_counties)]

min_slots = st.sidebar.slider("本週至少剩餘名額", 0, 20, 1, 1)
df_filtered = df_filtered[df_filtered['thisWeekCount'] >= min_slots]
    
# --- (新) 移除「資料更新」按鈕 ---
# (雲端 App 不再需要這個功能)
st.sidebar.header("資料來源")
st.sidebar.info("本站資料由本地伺服器每日自動爬取並更新。")


# --- 5. 視覺化：在地圖上顯示結果 ---
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
    
    # --- 6. 顯示表格 (中文標題 + 隱藏索引版) ---
    st.subheader("詳細資料列表")
    
    df_display = df_filtered.copy()
    CHINESE_COLUMN_MAP = {
        'orgName': '機構名稱',
        'distance': '距離', 
        'thisWeekCount': '本週名額',
        'scraped_county_name': '縣市',
        'address': '地址',
        'phone': '聯絡電話',
        'payDetail': '自付費用',
    }
    df_display = df_display.rename(columns=CHINESE_COLUMN_MAP)
    display_columns_chinese = ['機構名稱', '本週名額', '縣市', '地址', '聯絡電話', '自付費用']

    if '距離' in df_display.columns:
        display_columns_chinese.insert(1, '距離') 
        df_display = df_display.sort_values(by='距離') 
        st.dataframe(
            df_display[display_columns_chinese],
            column_config={
                "距離": st.column_config.NumberColumn(format="%.2f km")
            },
            use_container_width=True,
            hide_index=True 
        )
    else:
        st.dataframe(
            df_display[display_columns_chinese],
            use_container_width=True,
            hide_index=True 
        )
