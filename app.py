import streamlit as st
import pandas as pd
import folium
import geopy.distance 
from streamlit_folium import st_folium 
from geopy.geocoders import ArcGIS 
from folium.plugins import LocateControl, MarkerCluster
import time
import urllib.parse # Google 連結需要的工具

# --- 0. 定義檔案名稱 ---
# (新) 根據您的指正，更新檔案代表的意義
COUNSELING_CSV = "MOHW_counseling_data_FINAL.csv"  # 您的「心理諮商 (15-45歲青壯方案)」資料
TELEHEALTH_CSV = "MOHW_telehealth_data_FINAL.csv"  # 您的「通訊諮商」資料

# --- 1. 載入並「合併」資料 (核心升級) ---
@st.cache_data # 快取合併後的資料，加快載入
def load_and_merge_data():
    """
    讀取「心理諮商(青壯方案)」和「通訊諮商」兩個 CSV 檔，
    並將它們合併成一個主 DataFrame。
    """
    try:
        df_gen = pd.read_csv(COUNSELING_CSV) # "gen" = General (青壯方案)
        df_tel = pd.read_csv(TELEHEALTH_CSV) # "tel" = Telehealth
    except FileNotFoundError as e:
        st.error(f"❌ 錯誤：找不到資料檔！ {e}")
        st.info(f"請確認 '{COUNSELING_CSV}' 和 '{TELEHEALTH_CSV}' 都在此 app 的資料夾中。")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"讀取資料時發生錯誤: {e}")
        return pd.DataFrame()

    # (A) 為了安全合併，建立「唯一鍵」 (機構名稱 + 地址)
    df_gen['merge_key'] = df_gen['orgName'].str.strip() + df_gen['address'].str.strip()
    df_tel['merge_key'] = df_tel['orgName'].str.strip() + df_tel['address'].str.strip()

    # (B) 分別標記欄位，以便區分
    df_gen = df_gen.add_suffix('_gen')
    df_tel = df_tel.add_suffix('_tel')

    # (C) 執行「外部合併 (Outer Merge)」，保留所有機構
    df_merged = pd.merge(
        df_gen, 
        df_tel, 
        left_on='merge_key_gen', 
        right_on='merge_key_tel', 
        how='outer'
    )

    # (D) 整理合併後的欄位 (Coalesce)
    # - 優先使用 "青壯方案" 的資料，若為空，則用 "通訊諮商" 的
    df_merged['orgName'] = df_merged['orgName_gen'].fillna(df_merged['orgName_tel'])
    df_merged['address'] = df_merged['address_gen'].fillna(df_merged['address_tel'])
    df_merged['lat'] = df_merged['lat_gen'].fillna(df_merged['lat_tel'])
    df_merged['lng'] = df_merged['lng_gen'].fillna(df_merged['lng_tel'])
    df_merged['phone'] = df_merged['phone_gen'].fillna(df_merged['phone_tel'])
    df_merged['scraped_county_name'] = df_merged['scraped_county_name_gen'].fillna(df_merged['scraped_county_name_tel'])

    # (E) 建立新的「標籤」欄位
    df_merged['is_general'] = df_merged['merge_key_gen'].notna() # True 代表有「青壯方案」
    df_merged['is_telehealth'] = df_merged['merge_key_tel'].notna() # True 代表有「通訊諮商」
    
    # (F) 整理「名額」欄位 (將 NaN 轉為 0)
    # 青年方案的名額是 'thisWeekCount_gen'
    df_merged['general_availability'] = pd.to_numeric(df_merged['thisWeekCount_gen'], errors='coerce').fillna(0).astype(int)
    # 通訊方案的名額是 'thisWeekCount_tel'
    df_merged['telehealth_availability'] = pd.to_numeric(df_merged['thisWeekCount_tel'], errors='coerce').fillna(0).astype(int)

    # (G) 清理最終資料
    df_merged = df_merged.dropna(subset=['lat', 'lng', 'scraped_county_name', 'orgName'])
    
    # (H) 選擇我們需要的最終欄位
    final_columns = [
        'orgName', 'address', 'phone', 'scraped_county_name', 'lat', 'lng',
        'is_general', 'is_telehealth', 
        'general_availability', 'telehealth_availability'
    ]
    df_final = df_merged[final_columns]
    return df_final

# --- 2. 定位使用者地址 (快取) ---
@st.cache_data 
def geocode_user_address(address):
    """將使用者輸入的地址轉換為 (緯度, 經度)"""
    if not address:
        return None
    try:
        geolocator = ArcGIS(timeout=5) # 縮短超時
        location = geolocator.geocode(address)
        if location:
            return (location.latitude, location.longitude)
        else:
            return None
    except Exception as e:
        return None

# ==============================================================================
# 
# 區塊 B：Streamlit 應用程式主體
#
# ==============================================================================

# --- 3. 頁面設定 ---
st.set_page_config(
    page_title="台灣公費心理諮商地圖",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ 台灣公費心理諮商 即時地圖搜尋系統")
# (新) Goal 1：根據您的指正更新描述
st.markdown("整合衛福部「15-45歲青壯世代心理健康支持方案」與「通訊心理諮商方案」兩項公費資源，提供即時名額查詢與距離排序。")

# --- 4. 載入資料 ---
df_master = load_and_merge_data()

if df_master.empty:
    st.error("資料載入失敗，請檢查 CSV 檔案。")
    st.stop() # 停止執行

# --- 5. 側邊欄 (Sidebar) 篩選器 ---
st.sidebar.header("📍 地圖篩選器")

# (新) 篩選器 1：服務類型 (Goal 1 用詞修正)
service_type = st.sidebar.radio(
    "請選擇公費方案：",
    ('心理諮商 (15-45歲青壯方案)', '通訊諮商 (不限年齡)', '兩方案皆提供'),
    key='service_type'
)

# 篩選器 2：名額
availability_filter = st.sidebar.radio(
    "請選擇名額狀態：",
    ('顯示全部', 
     '至少一項有名額 (OR)', 
     '兩項同時有名額 (AND)'),
    key='availability',
    help="""
- **顯示全部**: 不論有無名額。
- **至少一項有名額 (OR)**: 
  - (若選'心理諮商') -> 顯示青壯方案名額 > 0
  - (若選'通訊諮商') -> 顯示通訊諮商名額 > 0
  - (若選'兩方案皆提供') -> 顯示青壯方案 *或* 通訊諮商名額 > 0
- **兩項同時有名額 (AND)**:
  - (若選'兩方案皆提供') -> 必須 青壯方案 *且* 通訊諮商名額 > 0
"""
)

# 篩選器 3：縣市
county_list = ["全台灣"] + sorted(df_master['scraped_county_name'].unique().tolist())
selected_county = st.sidebar.selectbox(
    "請選擇縣市：",
    county_list,
    key='county'
)

# 篩選器 4：使用者地址
user_address = st.sidebar.text_input("輸入您的地址 (查詢最近距離)：", key='user_address')

# 篩選器 5：距離滑桿 (功能已加回)
distance_disabled = not bool(user_address) 
selected_distance = st.sidebar.slider(
    "請選擇距離範圍 (公里)：",
    min_value=1,
    max_value=10,
    value=10, # 預設為 10 公里
    step=1,
    disabled=distance_disabled,
    help="請先輸入您的地址，才能使用此篩選器。"
)


# --- 6. 核心篩選邏輯 ---

# (A) 複製一份主資料表
df_filtered = df_master.copy()

# (B) 依「縣市」篩選
if selected_county != "全台灣":
    df_filtered = df_filtered[df_filtered['scraped_county_name'] == selected_county]

# (C) 依「服務類型」篩選 (Goal 1 用詞修正)
if service_type == '心理諮商 (15-45歲青壯方案)':
    df_filtered = df_filtered[df_filtered['is_general']]
elif service_type == '通訊諮商 (不限年齡)':
    df_filtered = df_filtered[df_filtered['is_telehealth']]
elif service_type == '兩方案皆提供':
    df_filtered = df_filtered[df_filtered['is_general'] & df_filtered['is_telehealth']]

# (D) 依「名額狀態」篩選 (Goal 1 用詞修正)
if availability_filter == '至少一項有名額 (OR)':
    if service_type == '心理諮商 (15-45歲青壯方案)':
        df_filtered = df_filtered[df_filtered['general_availability'] > 0]
    elif service_type == '通訊諮商 (不限年齡)':
        df_filtered = df_filtered[df_filtered['telehealth_availability'] > 0]
    elif service_type == '兩方案皆提供':
        df_filtered = df_filtered[
            (df_filtered['general_availability'] > 0) | 
            (df_filtered['telehealth_availability'] > 0)
        ]

elif availability_filter == '兩項同時有名額 (AND)':
    if service_type == '心理諮商 (15-45歲青壯方案)':
        df_filtered = df_filtered[df_filtered['general_availability'] > 0]
    elif service_type == '通訊諮商 (不限年齡)':
        df_filtered = df_filtered[df_filtered['telehealth_availability'] > 0]
    elif service_type == '兩方案皆提供':
        # 關鍵邏輯：必須 青年(gen) 且(&) 通訊(tel) 都有名額
        df_filtered = df_filtered[
            (df_filtered['general_availability'] > 0) & 
            (df_filtered['telehealth_availability'] > 0)
        ]

# --- 7. 處理使用者地址與距離計算 ---
map_center = [23.9738, 120.982] # 預設地圖中心 (台灣)
map_zoom = 8
user_location = geocode_user_address(user_address)

if user_location:
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

# --- 8. 繪製地圖 ---
m = folium.Map(location=map_center, zoom_start=map_zoom, tiles="CartoDB positron")
marker_cluster = MarkerCluster().add_to(m)
folium.plugins.LocateControl(auto_start=False).add_to(m) # 定位使用者按鈕

if df_filtered.empty:
    st.warning("在地圖範圍內找不到符合條件的診所。請調整篩選器。")
else:
    st.success(f"在地圖範圍內找到 {len(df_filtered)} 間符合條件的診所：")
    
    for idx, row in df_filtered.iterrows():
        # 檢查是否有任何名額
        has_any_availability = (row['general_availability'] > 0) or (row['telehealth_availability'] > 0)
        
        if has_any_availability:
            marker_color = 'green'; icon_name = 'check'
        else:
            marker_color = 'blue'; icon_name = 'medkit'
        
        # 建立 Google Maps 連結 (僅用名稱搜尋)
        gmaps_query = urllib.parse.quote_plus(row['orgName'])
        gmaps_url = f"https://www.google.com/maps/search/?api=1&query={gmaps_query}"
        
        # 彈出視窗 (Popup) 
        popup_html = f"<b>{row['orgName']}</b>"
        # 加入 Google 連結
        popup_html += f" <a href='{gmaps_url}' target='_blank'>[Google 搜尋]</a>"
        popup_html += f"<hr style='margin: 3px;'>"
        
        if 'distance' in df_filtered.columns:
             popup_html += f"<b>距離:</b> {row['distance']:.2f} 公里<br>"
        
        # (新) Goal 1：根據機構提供的服務來顯示名額 (用詞修正)
        if row['is_general']:
            popup_html += f"<b>青壯方案名額:</b> <b>{int(row['general_availability'])}</b><br>"
        if row['is_telehealth']:
            popup_html += f"<b>通訊諮商名額:</b> <b>{int(row['telehealth_availability'])}</b><br>"
            
        popup_html += f"<b>地址:</b> {row['address']}<br><b>電話:</b> {row['phone']}"
        
        folium.Marker(
            location=[row['lat'], row['lng']],
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color=marker_color, icon=icon_name, prefix='fa')
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

cols_to_show = ['orgName']
if 'distance' in df_filtered.columns:
    cols_to_show.append('distance')

# (新) Goal 1：根據服務類型決定要顯示哪些名額欄位 (用詞修正)
if service_type == '心理諮商 (15-45歲青壯方案)':
    cols_to_show.append('general_availability')
elif service_type == '通訊諮商 (不限年齡)':
    cols_to_show.append('telehealth_availability')
elif service_type == '兩方案皆提供':
    cols_to_show.extend(['general_availability', 'telehealth_availability'])

cols_to_show.extend(['address', 'phone', 'scraped_county_name'])

# (新) Goal 1：修正表格欄位名稱
st.dataframe(
    df_filtered[cols_to_show].rename(columns={
        'orgName': '機構名稱',
        'distance': '距離(km)',
        'general_availability': '青壯方案名額',
        'telehealth_availability': '通訊諮商名額',
        'address': '地址',
        'phone': '電話',
        'scraped_county_name': '縣市'
    }),
    hide_index=True
)

st.caption(f"資料來源：衛福部心理健康司。目前顯示 {len(df_filtered)} / 總計 {len(df_master)} 筆機構資料。")
