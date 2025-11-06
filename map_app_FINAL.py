import streamlit as st
import pandas as pd
import folium
import geopy.distance 
from streamlit_folium import st_folium 
from geopy.geocoders import ArcGIS 
from folium.plugins import LocateControl, MarkerCluster
import time
import urllib.parse #導入 URL 編碼工具

# 定義 GitHub 上的「原始資料」URL
GITHUB_RAW_URL = "https://raw.githubusercontent.com/shiyuki0318/moh-counseling-map/main/MOHW_counseling_data_FINAL.csv"

# 1. 載入資料 (修改版：從 GitHub URL 讀取)
@st.cache_data(ttl=3600) # 快取 1 小時 (3600 秒)
def load_data(url):
    try:
        df = pd.read_csv(url, encoding='utf-8-sig') 
        df = df.dropna(subset=['lat', 'lng'])
        df['thisWeekCount'] = pd.to_numeric(df['thisWeekCount'], errors='coerce').fillna(0).astype(int)
        
        # 預先建立 Google Maps 搜尋連結
        # 我們將 "機構名稱" + " " + "地址" 進行 URL 編碼
        df['google_maps_query'] = (df['orgName'] + ' ' + df['address']).apply(
            lambda x: urllib.parse.quote_plus(str(x))
        )
        df['google_maps_url'] = "https://www.google.com/maps/search/?api=1&query=" + df['google_maps_query']
        
        return df
    except Exception as e:
        st.error(f"從 GitHub 載入資料時發生錯誤: {e}")
        st.info("請檢查 GITHUB_RAW_URL 變數是否設定正確。")
        return pd.DataFrame() 

# 2. 定位使用者地址 (快取)
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

# (注入 CSS 更改「網站配色」)
st.markdown(
    """
    <style>
    /* 主要標題的顏色 */
    .st-emotion-cache-10trblm { color: #2E8B57; }
    /* 側邊欄 (Sidebar) 標題的顏色 */
    .st-emotion-cache-r8a62r, .st-emotion-cache-1f2d01k { color: #2E8B57; }
    /* 側邊欄背景 (使用較淺的綠色) */
    [data-testid="stSidebar"] { background-color: #8FBC8F; }
    /* 成功訊息 (st.success) 的綠色 */
    [data-testid="stNotification"] { background-color: #DDFFDD; }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🏥 公費心理諮商 - 即時地圖搜尋系統")
st.write("您可以選擇「離我最近」來搜尋，或「瀏覽全台」來查看特定縣市的資源。")

df_all = load_data(GITHUB_RAW_URL)

if df_all.empty:
    st.warning("資料載入中... 如果持續顯示錯誤，請稍後再試。")
    st.stop() 
    
# 4. 側邊欄與篩選邏輯
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
    
st.sidebar.header("資料來源")
st.sidebar.info("本站資料為管理員手動更新(盡全力維持最新資訊)。")

# 5. 視覺化：在地圖上顯示結果
m = folium.Map(location=map_center, zoom_start=map_zoom, tiles="Cartodb Positron") 
LocateControl(auto_start=False, strings={"title": "顯示我現在的位置", "popup": "您在這裡"}).add_to(m)
marker_cluster = MarkerCluster().add_to(m)

if search_mode == '離我最近' and user_loc:
    folium.Marker(location=user_loc, popup=f"<b>您的位置</b>", icon=folium.Icon(color="red", icon="user")).add_to(m)

if df_filtered.empty:
    st.warning("在地圖範圍內找不到符合條件的診所。請調整篩選器。")
else:
    st.success(f"在地圖範圍內找到 {len(df_filtered)} 間符合條件的診所：")
    
    for idx, row in df_filtered.iterrows():
        if row['thisWeekCount'] > 0: 
            fill_color = '#3CB371'; border_color = '#2E8B57'; radius = 8 
        else: 
            fill_color = '#556B2F'; border_color = '#556B2F'; radius = 5 
        
        popup_html = f"<b>{row['orgName']}</b><hr style='margin: 3px;'>"
        if 'distance' in df_filtered.columns:
             popup_html += f"<b>距離:</b> {row['distance']:.2f} 公里<br>"
        popup_html += f"<b>本週名額:</b> <b>{int(row['thisWeekCount'])}</b><br>"
        popup_html += f"<b>地址:</b> {row['address']}<br><b>電話:</b> {row['phone']}<br>"
        
        # 加入「查看 Google 評價」的連結
        popup_html += f"<a href='{row['google_maps_url']}' target='_blank'><b>[ 點此查看 Google 評價 ]</b></a>"
        
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=radius,
            popup=folium.Popup(popup_html, max_width=300),
            color=border_color,      
            fill=True,
            fill_color=fill_color,   
            fill_opacity=0.7         
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
        'google_maps_url': 'Google 評價' # 加入評價欄位連結
    }
    df_display = df_display.rename(columns=CHINESE_COLUMN_MAP)
    # 將評價欄位加入顯示
    display_columns_chinese = ['機構名稱', '本週名額', '縣市', '地址', '聯絡電話', '自付費用', 'Google 評價']

    if '距離' in df_display.columns:
        display_columns_chinese.insert(1, '距離') 
        df_display = df_display.sort_values(by='距離') 
        
        st.dataframe(
            df_display[display_columns_chinese],
            column_config={
                "距離": st.column_config.NumberColumn(format="%.2f km"),
                # 將 'Google 評價' 欄位渲染成可點擊的連結
                "Google 評價": st.column_config.LinkColumn(
                    "Google 評價",
                    display_text="點此查看"
                )
            },
            use_container_width=True,
            hide_index=True 
        )
    else:
        st.dataframe(
            df_display[display_columns_chinese],
            column_config={
                # 將 'Google 評價' 欄位變成可點擊的連結
                "Google 評價": st.column_config.LinkColumn(
                    "Google 評價",
                    display_text="點此查看"
                )
            },
            use_container_width=True,
            hide_index=True 
        )






