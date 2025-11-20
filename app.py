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

# --- Session State 初始化 ---
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
    /* 讓 info 提示框也變成大地色系，視覺更統一 */
    [data-testid="stNotification"][kind="info"] {{ 
        background-color: #EFEBE9; 
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
        
        **1. 地址查詢 (推薦 - 搜尋附近資源)：**
        * 在左側側邊欄的「輸入您的地址」中輸入完整地址。
        * 系統將自動定位您的位置（顯示紅色地標），並篩選出距離您 1-10 公里內的機構。
        * 您可以透過側邊欄的「距離範圍」滑桿來調整搜尋半徑。
        
        **縣市瀏覽：**
        * **2. 不要輸入任何地址。**
        * 使用「選擇縣市」下拉選項瀏覽特定區域。
        
        **3. 您也可以點擊地圖左上角的「定位按鈕」來查看您目前的所在地（藍色圓點）。**
        * 系統將自動定位您的位置（顯示紅色地標），並篩選出距離您 1-10 公里內的機構。
        
        **4. 篩選服務：**
        * 您可以選擇要找的服務類型，例如「心理諮商」或「通訊諮商」。
        """
    )

df_master = load_and_merge_data()
if df_master.empty:
    st.stop() 

# --- 6. 側邊欄 (Sidebar) 篩選器 ---
st.sidebar.header("📍 地圖篩選器")

# 模式切換
search_mode = st.sidebar.radio(
    "請選擇搜尋模式：",
    ('📍 搜尋附近資源 (地址/定位)', '🏙️ 瀏覽縣市 (區域搜尋)'),
    index=0
)

user_location = None 
address_input = ""
selected_distance = 5

if search_mode == '📍 搜尋附近資源 (地址/定位)':
    address_input = st.sidebar.text_input(
        "輸入您的地址：", 
        key='user_address',
        placeholder="輸入地址或留空使用GPS定位..."
    )
    
    selected_distance = st.sidebar.slider(
        "距離範圍 (公里)：",
        min_value=1, max_value=10, value=5, step=1
    )
    
    if address_input:
        # 情況 1: 輸入地址
        loc = geocode_user_address(address_input)
        if loc:
            user_location = loc
            st.session_state.map_center_lat = loc[0]
            st.session_state.map_center_lng = loc[1]
            st.session_state.map_zoom = 14
    else:
        # 情況 3: 沒輸入地址，使用地圖中心
        is_default_center = (st.session_state.map_center_lat == 23.9738 and st.session_state.map_center_lng == 120.982)
        if not is_default_center:
             user_location = (st.session_state.map_center_lat, st.session_state.map_center_lng)
             st.sidebar.success(f"已定位：{user_location[0]:.4f}, {user_location[1]:.4f}")
        else:
             st.sidebar.info("💡 請輸入地址，或是點擊地圖左上角的 **[定位按鈕]**。")

else:
    # 情況 2: 縣市瀏覽
    st.sidebar.info("在此模式下，將顯示所選縣市的所有機構。")

# 縣市清單
county_list = ["全台灣"] + sorted(df_master['scraped_county_name'].unique().tolist())
selected_county = st.sidebar.selectbox(
    "選擇縣市：",
    county_list,
    key='county',
    disabled=(search_mode == '📍 搜尋附近資源 (地址/定位)')
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

st.sidebar.header("資料來源")
st.sidebar.info("本站資料為手動更新，將盡力保持最新。")

# --- 7. 核心篩選邏輯 ---
df_filtered = df_master.copy()

# 服務類型
if service_type == '心理諮商':
    df_filtered = df_filtered[df_filtered['is_general']]
elif service_type == '通訊諮商':
    df_filtered = df_filtered[df_filtered['is_telehealth']]
elif service_type == '兩方案皆提供':
    df_filtered = df_filtered[df_filtered['is_general'] & df_filtered['is_telehealth']]

# 名額狀態
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

# --- 距離篩選 (改進版) ---
filter_message = ""
if search_mode == '📍 搜尋附近資源 (地址/定位)' and user_location:
    # 計算距離
    df_filtered['distance'] = df_filtered.apply(
        lambda row: geopy.distance.great_circle(user_location, (row['lat'], row['lng'])).km,
        axis=1
    )
    # 篩選距離
    df_filtered = df_filtered[df_filtered['distance'] <= selected_distance]
    df_filtered = df_filtered.sort_values(by="distance")
    
    if df_filtered.empty:
        # (關鍵) 如果找不到，顯示這則訊息，但地圖照樣畫！
        filter_message = f"🔍 在方圓 **{selected_distance} 公里** 內暫無符合條件的機構。"
        st.info(filter_message)
    else:
        filter_message = f"📍 已為您篩選：位於 **{selected_distance} 公里** 內的 **{len(df_filtered)}** 間機構。"
        st.success(filter_message)

elif search_mode == '🏙️ 瀏覽縣市 (區域搜尋)':
    if selected_county != "全台灣":
        df_filtered = df_filtered[df_filtered['scraped_county_name'] == selected_county]
        if not df_filtered.empty:
            st.success(f"在 {selected_county} 找到 {len(df_filtered)} 間符合條件的機構。")

# --- 8. 繪製地圖 ---
# (關鍵) 無論是否 filtered.empty，都繪製地圖
m = folium.Map(
    location=[st.session_state.map_center_lat, st.session_state.map_center_lng], 
    zoom_start=st.session_state.map_zoom, 
    tiles="CartoDB positron"
)

marker_cluster = MarkerCluster().add_to(m)

LocateControl(
    auto_start=False,
    strings={"title": "顯示我的位置"}
).add_to(m)

# 繪製機構標記 (如果有的話)
if not df_filtered.empty:
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

# 繪製使用者紅點 (如果有的話)
if user_location:
    folium.Marker(
        location=user_location, popup="您的位置 (搜尋中心)", 
        icon=folium.Icon(color="red", icon="home")
