import streamlit as st
import pandas as pd
import folium
import geopy.distance 
from streamlit_folium import st_folium 
from geopy.geocoders import ArcGIS 
from folium.plugins import LocateControl, MarkerCluster
import time
import urllib.parse # Google 連結需要的工具

# (已修改) 1. 只讀取「心理諮商」CSV
COUNSELING_CSV = "MOHW_counseling_data_FINAL.csv" 

# (已修改) 2. 載入資料 (已移除所有合併邏輯)
@st.cache_data 
def load_data(file_path):
    """
    讀取「心理諮商」CSV 檔。
    """
    try:
        df = pd.read_csv(file_path)
        df = df.dropna(subset=['lat', 'lng', 'scraped_county_name', 'orgName'])
        
        # 確保名額欄位是數字
        df['thisWeekCount'] = pd.to_numeric(df['thisWeekCount'], errors='coerce').fillna(0).astype(int)

        # 建立 Google Maps 搜尋連結 (使用"名稱" + "地址")
        df['gmaps_query'] = (df['orgName'] + ' ' + df['address']).apply(
            lambda x: urllib.parse.quote_plus(str(x))
        )
        df['gmaps_url'] = "http://googleusercontent.com/maps.google.com/search/" + df['gmaps_query']
        
        return df
    except FileNotFoundError as e:
        st.error(f"❌ 錯誤：找不到資料檔！ {e}")
        st.info(f"請確認 '{file_path}' 檔案已上傳到 GitHub 倉庫中。")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"讀取資料時發生錯誤: {e}")
        return pd.DataFrame()

# --- 3. 定位使用者地址 (快取) ---
@st.cache_data 
def geocode_user_address(address):
    """將使用者輸入的地址轉換為 (緯度, 經度)"""
    if not address:
        return None
    try:
        geolocator = ArcGIS(timeout=5) 
        location = geolocator.geocode(address)
        if location:
            return (location.latitude, location.longitude)
        else:
            return None
    except Exception as e:
        return None

# --- 4. Streamlit 應用程式主體 ---
st.set_page_config(
    page_title="公費心理諮商地圖",
    page_icon="🗺️",
    layout="wide"
)

# (保留) 注入 CSS 更改「網站配色」 (您喜歡的綠色系)
st.markdown(
    """
    <style>
    /* 主要標題的顏色 */
    .st-emotion-cache-10trblm { color: #2E8B57; }
    /* 側邊欄 (Sidebar) 標題的顏色 */
    .st-emotion-cache-r8a62r, .st-emotion-cache-1f2d01k { color: #2E8B57; }
    /* 側邊欄背景 (使用較淺的綠色) */
    [data-testid="stSidebar"] { background-color: #F0F8F0; }
    /* 成功訊息 (st.success) 的綠色 */
    [data-testid="stNotification"] { background-color: #DDFFDD; }
    </style>
    """,
    unsafe_allow_html=True
)

# (已修改) 標題和說明文字
st.title("🗺️ 15-45歲青壯世代 心理健康支持方案")
st.markdown("提供「15-45歲青壯世代心理健康支持方案」公費資源，提供即時名額查詢與距離排序。")

# --- 5. 載入資料 ---
df_master = load_data(COUNSELING_CSV)

if df_master.empty:
    st.stop() # 停止執行

# --- 6. 側邊欄 (Sidebar) 篩選器 ---
st.sidebar.header("📍 地圖篩選器")

# (已修改) 篩選器 1：名額 (簡化回滑桿)
min_slots = st.sidebar.slider(
    "本週至少剩餘名額：", 
    0, 20, 1, 1, # 最小, 最大, 預設, 步伐
    key='min_slots'
)

# --- (新功能) 互斥篩選邏輯 ---

# 篩選器 2：使用者地址
user_address = st.sidebar.text_input(
    "輸入您的地址 (查詢最近距離)：", 
    key='user_address',
    placeholder="例如：臺北市中正區重慶南路一段122號"
)

# (新) 檢查地址模式是否啟用
address_mode_active = bool(user_address) # True if user typed something

# 篩選器 3：縣市
county_list = ["全台灣"] + sorted(df_master['scraped_county_name'].unique().tolist())
selected_county = st.sidebar.selectbox(
    "或 選擇縣市 (瀏覽全台)：",
    county_list,
    key='county',
    disabled=address_mode_active, # (新) 當輸入地址時，禁用此選項
    help="若您已輸入地址，此選項將被禁用。"
)

# 篩選器 4：距離滑桿
selected_distance = st.sidebar.slider(
    "距離範圍 (公里)：",
    min_value=1, max_value=10, value=10, step=1,
    disabled=not address_mode_active, # (新) 只有在輸入地址時才啟用
    help="請先輸入您的地址，才能使用此篩選器。"
)
# --- (結束) 互斥篩選邏輯 ---
    
st.sidebar.header("資料來源")
st.sidebar.info("本站資料為手動更新，將盡力保持最新。") # (使用您決定的文字)

# --- 7. 核心篩選邏輯 ---

# (A) 複製一份主資料表
df_filtered = df_master.copy()

# (B) 依「名額」篩選
df_filtered = df_filtered[df_filtered['thisWeekCount'] >= min_slots]

# (C) 依「縣市」或「地址」篩選
map_center = [23.9738, 120.982] # 預設地圖中心 (台灣)
map_zoom = 8
user_location = geocode_user_address(user_address)

if user_location:
    # (新) 進入「地址模式」 (縣市篩選器已被禁用)
    map_center = user_location
    map_zoom = 12
    # 計算距離
    df_filtered['distance'] = df_filtered.apply(
        lambda row: geopy.distance.great_circle(user_location, (row['lat'], row['lng'])).km,
        axis=1
    )
    # 根據 slider 篩選距離
    df_filtered = df_filtered[df_filtered['distance'] <= selected_distance]
    # 依距離排序
    df_filtered = df_filtered.sort_values(by="distance")
else:
    # (新) 進入「縣市模式」 (地址為空)
    if selected_county != "全台灣":
        df_filtered = df_filtered[df_filtered['scraped_county_name'] == selected_county]

# --- 8. 繪製地圖 ---
m = folium.Map(location=map_center, zoom_start=map_zoom, tiles="CartoDB positron")
marker_cluster = MarkerCluster().add_to(m)
folium.plugins.LocateControl(auto_start=False).add_to(m) # 定位使用者按鈕

if df_filtered.empty:
    st.warning("在地圖範圍內找不到符合條件的診所。請調整篩選器。")
else:
    st.success(f"在地圖範圍內找到 {len(df_filtered)} 間符合條件的診所：")
    
    for idx, row in df_filtered.iterrows():
        # (已修改) 簡化名額檢查
        has_availability = (row['thisWeekCount'] > 0)
        
        # (保留) 您的自訂顏色
        if has_availability:
            fill_color = '#3CB371'; border_color = '#2E8B57'; radius = 8
        else:
            fill_color = '#556B2F'; border_color = '#556B2F'; radius = 5
        
        gmaps_url = row['gmaps_url']
        
        # (已修改) 簡化彈出視窗 (Popup) 
        popup_html = f"<b>{row['orgName']}</b>"
        popup_html += f" <a href='{gmaps_url}' target='_blank'>[Google 搜尋]</a>"
        popup_html += f"<hr style='margin: 3px;'>"
        
        if 'distance' in df_filtered.columns:
             popup_html += f"<b>距離:</b> {row['distance']:.2f} 公里<br>"
        
        # (已修改) 只顯示「本週名額」
        popup_html += f"<b>本週名額:</b> <b>{int(row['thisWeekCount'])}</b><br>"
        popup_html += f"<b>地址:</b> {row['address']}<br><b>電話:</b> {row['phone']}"
        
        # (保留) 使用 CircleMarker 
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=radius,
            popup=folium.Popup(popup_html, max_width=300),
            color=border_color,
            fill=True,
            fill_color=fill_color,
            fill_opacity=0.7
        ).add_to(marker_cluster) 

    # 在使用者位置放一個標記
    if user_location:
        folium.Marker(
            location=user_location, 
            popup="您的位置", 
            icon=folium.Icon(color="red", icon="user")
        ).add_to(m)
        
    st_folium(m, width="100%", height=500, returned_objects=[])

# --- 9. 顯示資料表格 ---
st.subheader("📍 機構詳細列表")

# (已修改) 簡化要顯示的欄位
cols_to_show = ['orgName']
if 'distance' in df_filtered.columns:
    cols_to_show.append('distance')

cols_to_show.extend(['thisWeekCount', 'address', 'phone', 'scraped_county_name'])

# (已修改) 簡化表格的欄位名稱
st.dataframe(
    df_filtered[cols_to_show].rename(columns={
        'orgName': '機構名稱',
        'distance': '距離(km)',
        'thisWeekCount': '本週名額',
        'address': '地址',
        'phone': '電話',
        'scraped_county_name': '縣市'
    }),
    hide_index=True,
    use_container_width=True # (新) 讓表格填滿寬度
)

st.caption(f"資料來源：衛福部心理健康司。目前顯示 {len(df_filtered)} / 總計 {len(df_master)} 筆機構資料。")
