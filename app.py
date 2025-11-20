import streamlit as st
import pandas as pd
import folium
import geopy.distance 
from streamlit_folium import st_folium 
from geopy.geocoders import ArcGIS 
from folium.plugins import LocateControl, MarkerCluster
import time
import urllib.parse 

# --- 1. 定義兩個 CSV 檔案路徑 ---
COUNSELING_CSV = "MOHW_counseling_data_FINAL.csv"
TELEHEALTH_CSV = "MOHW_telehealth_data_FINAL.csv"

# --- 2. 載入並合併資料 ---
@st.cache_data 
def load_and_merge_data():
    try:
        df_gen = pd.read_csv(COUNSELING_CSV) 
        df_tel = pd.read_csv(TELEHEALTH_CSV) 
    except FileNotFoundError as e:
        st.error(f"❌ 錯誤：找不到資料檔！ {e}")
        st.info(f"請確認 '{COUNSELING_CSV}' 和 '{TELEHEALTH_CSV}' 都在此 app 的資料夾中。")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"讀取資料時發生錯誤: {e}")
        return pd.DataFrame()

    df_gen['merge_key'] = df_gen['orgName'].str.strip() + df_gen['address'].str.strip()
    df_tel['merge_key'] = df_tel['orgName'].str.strip() + df_tel['address'].str.strip()
    df_gen = df_gen.add_suffix('_gen')
    df_tel = df_tel.add_suffix('_tel')

    df_merged = pd.merge(
        df_gen, df_tel, 
        left_on='merge_key_gen', right_on='merge_key_tel', 
        how='outer'
    )

    df_merged['orgName'] = df_merged['orgName_gen'].fillna(df_merged['orgName_tel'])
    df_merged['address'] = df_merged['address_gen'].fillna(df_merged['address_tel'])
    df_merged['lat'] = df_merged['lat_gen'].fillna(df_merged['lat_tel'])
    df_merged['lng'] = df_merged['lng_gen'].fillna(df_merged['lng_tel'])
    df_merged['phone'] = df_merged['phone_gen'].fillna(df_merged['phone_tel'])
    df_merged['scraped_county_name'] = df_merged['scraped_county_name_gen'].fillna(df_merged['scraped_county_name_tel'])

    df_merged['is_general'] = df_merged['merge_key_gen'].notna() 
    df_merged['is_telehealth'] = df_merged['merge_key_tel'].notna() 
    
    df_merged['general_availability'] = pd.to_numeric(df_merged['thisWeekCount_gen'], errors='coerce').fillna(0).astype(int)
    df_merged['telehealth_availability'] = pd.to_numeric(df_merged['thisWeekCount_tel'], errors='coerce').fillna(0).astype(int)

    df_merged = df_merged.dropna(subset=['lat', 'lng', 'scraped_county_name', 'orgName'])
    
    # 使用標準 Google Maps 搜尋網址
    df_merged['gmaps_query'] = (df_merged['orgName'] + ' ' + df_merged['address']).apply(
        lambda x: urllib.parse.quote_plus(str(x))
    )
    df_merged['gmaps_url'] = "https://www.google.com/maps/search/?api=1&query=" + df_merged['gmaps_query']
    
    final_columns = [
        'orgName', 'address', 'phone', 'scraped_county_name', 'lat', 'lng',
        'is_general', 'is_telehealth', 
        'general_availability', 'telehealth_availability',
        'gmaps_url' 
    ]
    df_final = df_merged[final_columns]
    return df_final

# --- 3. 定位使用者地址 (快取) ---
@st.cache_data 
def geocode_user_address(address):
    if not address: return None
    try:
        geolocator = ArcGIS(timeout=5)
        location = geolocator.geocode(address)
        return (location.latitude, location.longitude) if location else None
    except Exception as e:
        return None

# --- 4. Streamlit 應用程式主體 ---
st.set_page_config(
    page_title="台灣公費心理諮商地圖",
    page_icon="🗺️",
    layout="wide"
)

# --- Session State 初始化 (用於記錄地圖中心點) ---
if 'map_center_lat' not in st.session_state:
    st.session_state.map_center_lat = 23.9738
if 'map_center_lng' not in st.session_state:
    st.session_state.map_center_lng = 120.982
if 'map_zoom' not in st.session_state:
    st.session_state.map_zoom = 8

# (保留) 大地色系樣式
st.markdown(
    f"""
    <style>
    body, [data-testid="stAppViewContainer"] {{
        background-color: #FFFFFF; 
        color: #333333; 
    }}
    .st-emotion-cache-10trblm {{ color: #9A6852; }}
    [data-testid="stSidebar"] {{ background-color: #6D4C41; }}
    [data-testid="stSidebar"] div, 
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p {{
        color: #F5F5F5; 
    }}
    .st-emotion-cache-r8a62r, .st-emotion-cache-1f2d01k {{ 
        color: #DABEA7; 
    }}
    [data-testid="stExpander"] {{
        background-color: #F9FAFB; 
        border: 1px solid #DABEA7;
    }}
    [data-testid="stNotification"][kind="success"] {{ 
        background-color: #DABEA7; 
        color: #6D4C41; 
    }}
    [data-testid="stNotification"][kind="warning"] {{ 
        background-color: #CDA581; 
        color: #6D4C41; 
    }}
    </style>
    """,
    unsafe_allow_html=True
)

st.title(" 🧡台灣公費心理諮商 即時地圖搜尋系統🗺️  ")
st.markdown("「15-45歲青壯世代心理健康支持方案」，「 🧡心理諮商」及「📞通訊諮商」兩項公費資源整理。")

# 衛福部提醒
st.warning("【 提醒 】未來四周名額為預估，詳細資訊請聯繫合作機構實際狀況為準。")

# 歡迎提醒
with st.expander("【 歡迎使用 - 網站提醒 】 (點此收合)", expanded=True):
    st.markdown(
        """
        歡迎使用本地圖查詢系統！
        
        **🎯 兩種方式搜尋附近診所：**
        
        1.  **輸入地址搜尋**：在側邊欄輸入您的地址，精準定位。
        2.  **地圖定位/GPS搜尋**：
            * 將側邊欄模式切換為「**地圖中心/定位搜尋**」。
            * 點擊地圖左上角的 **[定位圖示]**。
            * **地圖移動後，系統會自動搜尋您所在位置方圓 1-10 公里內的診所！**
        """
    )

df_master = load_and_merge_data()
if df_master.empty:
    st.stop() 

# --- 6. 側邊欄 (Sidebar) 篩選器 ---
st.sidebar.header("📍 地圖篩選器")

# (*** 新增：搜尋模式切換 ***)
search_mode = st.sidebar.radio(
    "請選擇搜尋方式：",
    ('輸入地址', '地圖中心/定位搜尋'),
    index=0,
    help="選擇「地圖中心/定位搜尋」後，點擊地圖上的定位鈕，即可搜尋您所在位置附近的診所。"
)

user_location = None # 初始化

if search_mode == '輸入地址':
    user_address = st.sidebar.text_input(
        "輸入地址：", 
        key='user_address',
        placeholder="例如：臺北市中正區重慶南路一段122號"
    )
    if user_address:
        user_location = geocode_user_address(user_address)
        if user_location:
            # 更新地圖中心到地址位置
            st.session_state.map_center_lat = user_location[0]
            st.session_state.map_center_lng = user_location[1]
            st.session_state.map_zoom = 14
else:
    st.sidebar.info("💡 請點擊地圖左上角的 **[定位圖示]**，或直接拖曳地圖。系統將搜尋**地圖中心點**附近的診所。")
    # 在此模式下，使用當前地圖中心作為使用者位置
    user_location = (st.session_state.map_center_lat, st.session_state.map_center_lng)

# 距離滑桿
selected_distance = st.sidebar.slider(
    "距離範圍 (公里)：",
    min_value=1, max_value=10, value=5, step=1,
    help="調整搜尋半徑。"
)

st.sidebar.markdown("---")

service_type = st.sidebar.radio(
    "請選擇公費方案：",
    ('心理諮商', '通訊諮商', '兩方案皆提供', '顯示所有機構'),
    index=0, key='service_type'
)

availability_filter = st.sidebar.radio(
    "請選擇名額狀態：",
    ('顯示全部', '至少一項有名額', '兩項同時有名額'),
    key='availability'
)

county_list = ["全台灣"] + sorted(df_master['scraped_county_name'].unique().tolist())
# 只有在沒有定位且沒有輸入地址時，才啟用縣市選單
is_location_active = (user_location is not None)
selected_county = st.sidebar.selectbox(
    "或 選擇縣市：",
    county_list,
    key='county',
    disabled=is_location_active,
    help="若已使用定位或地址搜尋，此選項將被禁用。"
)

st.sidebar.header("資料來源")
st.sidebar.info("本站資料為手動更新，將盡力保持最新。")

# --- 7. 核心篩選邏輯 ---
df_filtered = df_master.copy()

# 服務類型篩選
if service_type == '心理諮商':
    df_filtered = df_filtered[df_filtered['is_general']]
elif service_type == '通訊諮商':
    df_filtered = df_filtered[df_filtered['is_telehealth']]
elif service_type == '兩方案皆提供':
    df_filtered = df_filtered[df_filtered['is_general'] & df_filtered['is_telehealth']]

# 名額狀態篩選
if availability_filter == '至少一項有名額':
    if service_type == '心理諮商':
        df_filtered = df_filtered[df_filtered['general_availability'] > 0]
    elif service_type == '通訊諮商':
        df_filtered = df_filtered[df_filtered['telehealth_availability'] > 0]
    else: 
        df_filtered = df_filtered[
            (df_filtered['general_availability'] > 0) | 
            (df_filtered['telehealth_availability'] > 0)
        ]
elif availability_filter == '兩項同時有名額':
    if service_type == '兩方案皆提供':
        df_filtered = df_filtered[
            (df_filtered['general_availability'] > 0) & 
            (df_filtered['telehealth_availability'] > 0)
        ]
    elif service_type == '心理諮商':
        df_filtered = df_filtered[df_filtered['general_availability'] > 0]
    elif service_type == '通訊諮商':
        df_filtered = df_filtered[df_filtered['telehealth_availability'] > 0]

# --- 距離篩選核心邏輯 ---
if user_location:
    # 計算距離
    df_filtered['distance'] = df_filtered.apply(
        lambda row: geopy.distance.great_circle(user_location, (row['lat'], row['lng'])).km,
        axis=1
    )
    # 篩選距離
    df_filtered = df_filtered[df_filtered['distance'] <= selected_distance]
    df_filtered = df_filtered.sort_values(by="distance")
    
    st.info(f"📍 已定位搜尋：顯示位於 **{user_location[0]:.4f}, {user_location[1]:.4f}** 周邊 **{selected_distance} 公里** 內的 **{len(df_filtered)}** 間機構。")
    
else:
    # 沒定位時，依縣市篩選
    if selected_county != "全台灣":
        df_filtered = df_filtered[df_filtered['scraped_county_name'] == selected_county]

# --- 8. 繪製地圖 ---
m = folium.Map(
    location=[st.session_state.map_center_lat, st.session_state.map_center_lng], 
    zoom_start=st.session_state.map_zoom, 
    tiles="CartoDB positron"
)

marker_cluster = MarkerCluster().add_to(m)

# 加入定位按鈕
LocateControl(
    auto_start=False,
    strings={"title": "點擊定位，搜尋附近診所"}
).add_to(m)

# 繪製標記
if df_filtered.empty:
    if user_location:
        st.warning(f"在目前位置方圓 {selected_distance} 公里內找不到符合條件的診所，請嘗試擴大距離或移動地圖。")
    else:
        st.warning("在地圖範圍內找不到符合條件的診所。請調整篩選器。")
else:
    if not user_location:
        st.success(f"在地圖範圍內找到 {len(df_filtered)} 間符合條件的診所：")
    
    for idx, row in df_filtered.iterrows():
        has_any_availability = (row['general_availability'] > 0) or (row['telehealth_availability'] > 0)
        
        if has_any_availability:
            fill_color = '#CDA581'; border_color = '#9D7553'; radius = 12; fill_opacity = 0.8
        else:
            fill_color = '#A98B73'; border_color = '#876D5A'; radius = 7; fill_opacity = 0.6
        
        gmaps_url = row['gmaps_url']
        popup_html = f"<b>{row['orgName']}</b> <a href='{gmaps_url}' target='_blank'>[Google 搜尋]</a><hr style='margin: 3px;'>"
        
        if 'distance' in df_filtered.columns:
             popup_html += f"<b>距離:</b> {row['distance']:.2f} 公里<br>"
        
        if row['is_general']:
            popup_html += f"<b>心理諮商名額:</b> <b>{int(row['general_availability'])}</b><br>"
        if row['is_telehealth']:
            popup_html += f"<b>通訊諮商名額:</b> <b>{int(row['telehealth_availability'])}</b><br>"
            
        popup_html += f"<b>地址:</b> {row['address']}<br><b>電話:</b> {row['phone']}"
        
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=radius,
            popup=folium.Popup(popup_html, max_width=300),
            color=border_color, 
            fill=True, 
            fill_color=fill_color, 
            fill_opacity=fill_opacity
        ).add_to(marker_cluster) 

# 如果是地址搜尋模式，顯示紅色標記
if search_mode == '輸入地址' and user_location:
    folium.Marker(
        location=user_location, popup="您的地址", 
        icon=folium.Icon(color="red", icon="home")
    ).add_to(m)

# --- 9. 處理地圖互動回傳 (關鍵步驟) ---
# 這裡會抓取地圖的中心點，如果地圖被拖曳或點擊定位，這裡會收到新座標
map_output = st_folium(m, width="100%", height=500)

# 如果在「地圖中心/定位搜尋」模式，且地圖中心改變了，則更新 Session State 並重新執行
if search_mode == '地圖中心/定位搜尋' and map_output and map_output['center']:
    new_lat = map_output['center']['lat']
    new_lng = map_output['center']['lng']
    new_zoom = map_output['zoom']
    
    # 檢查是否位移超過一定程度 (避免微小抖動造成無限刷新)
    if (abs(new_lat - st.session_state.map_center_lat) > 0.0001 or 
        abs(new_lng - st.session_state.map_center_lng) > 0.0001 or
        new_zoom != st.session_state.map_zoom):
        
        st.session_state.map_center_lat = new_lat
        st.session_state.map_center_lng = new_lng
        st.session_state.map_zoom = new_zoom
        st.rerun() # 重新執行以更新篩選結果

# --- 10. 顯示資料表格 ---
st.subheader("📍 機構詳細列表")

cols_to_show = ['orgName']
if 'distance' in df_filtered.columns:
    cols_to_show.append('distance')

if service_type == '心理諮商':
    cols_to_show.append('general_availability')
elif service_type == '通訊諮商':
    cols_to_show.append('telehealth_availability')
else: 
    cols_to_show.extend(['general_availability', 'telehealth_availability'])

cols_to_show.extend(['address', 'phone', 'scraped_county_name'])

st.dataframe(
    df_filtered[cols_to_show].rename(columns={
        'orgName': '機構名稱',
        'distance': '距離(km)',
        'general_availability': '心理諮商名額',
        'telehealth_availability': '通訊諮商名額',
        'address': '地址',
        'phone': '電話',
        'scraped_county_name': '縣市'
    }),
    hide_index=True,
    use_container_width=True
)

st.caption(f"資料來源：衛福部心理健康司。目前顯示 {len(df_filtered)} / 總計 {len(df_master)} 筆機構資料。")
