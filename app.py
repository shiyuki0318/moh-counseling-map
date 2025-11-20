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

    # (保留) 已修正的 Google 連結
    df_merged['gmaps_query'] = (df_merged['orgName'] + ' ' + df_merged['address']).apply(
        lambda x: urllib.parse.quote_plus(str(x))
    )
    # 使用標準 Google Maps 搜尋網址
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

# (保留) 已修正的大地色系 + 更淺的側邊欄文字
st.markdown(
    f"""
    <style>
    /* 1. 主體背景 (白色) */
    body, [data-testid="stAppViewContainer"] {{
        background-color: #FFFFFF;
        color: #333333;
    }}
    /* 2. 主標題 (大地色系) */
    .st-emotion-cache-10trblm {{ color: #9A6852; }}
    /* 3. 側邊欄 (深棕色) */
    [data-testid="stSidebar"] {{ background-color: #6D4C41; }}
    /* 4. 側邊欄文字 (更淺的顏色) */
    [data-testid="stSidebar"] div,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p {{
        color: #F5F5F5;
    }}
    /* 5. 側邊欄標題 (淺米色) */
    .st-emotion-cache-r8a62r, .st-emotion-cache-1f2d01k {{
        color: #DABEA7;
    }}
    /* 6. 歡迎提醒 (淺色) */
    [data-testid="stExpander"] {{
        background-color: #F9FAFB;
        border: 1px solid #DABEA7;
    }}
    /* 7. 提示框 (大地色系) */
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

# 歡迎提醒 (使用 st.expander)
# (*** 關鍵修正：新增定位與距離搜尋說明 ***)
with st.expander("【 歡迎使用 - 網站提醒 】 (點此收合)", expanded=True):
    st.markdown(
        """
        歡迎使用本地圖查詢系統！

        **如何使用：**

        1.  **地址查詢 (推薦 - 搜尋附近資源)**：
            * 在左側側邊欄的「**輸入您的地址**」中輸入完整地址。
            * 系統將自動定位您的位置（顯示紅色地標），並篩選出**距離您 1-10 公里內**的機構。
            * 您可以透過側邊欄的「**距離範圍**」滑桿來調整搜尋半徑。
            * 此外，您也可以點擊地圖左上角的「定位按鈕」來查看您目前的所在地（藍色圓點）。

        2.  **縣市瀏覽**：
            * **不要**輸入任何地址。
            * 使用「**選擇縣市**」下拉選項瀏覽特定區域。

        3.  **篩選服務**：
            * 您可以選擇要找的服務類型，例如「心理諮商」或「通訊諮商」。
        """
    )


df_master = load_and_merge_data()

if df_master.empty:
    st.stop()

# --- 6. 側邊欄 (Sidebar) 篩選器 ---
st.sidebar.header("📍 地圖篩選器")

# (保留) 您的篩選器選項文字
service_type = st.sidebar.radio(
    "請選擇公費方案：",
    ('心理諮商',
     '通訊諮商',
     '兩方案皆提供',
     '顯示所有機構'),
    index=0,
    key='service_type'
)

availability_filter = st.sidebar.radio(
    "請選擇名額狀態：",
    ('顯示全部', '至少一項有名額', '兩項同時有名額'),
    key='availability'
)

user_address = st.sidebar.text_input(
    "輸入您的地址 (查詢最近距離)：",
    key='user_address',
    placeholder="例如：臺北市中正區重慶南路一段122號"
)
address_mode_active = bool(user_address)

county_list = ["全台灣"] + sorted(df_master['scraped_county_name'].unique().tolist())
selected_county = st.sidebar.selectbox(
    "或 選擇縣市 (瀏覽全台)：",
    county_list,
    key='county',
    disabled=address_mode_active,
    help="若您已輸入地址，此選項將被禁用。"
)

selected_distance = st.sidebar.slider(
    "距離範圍 (公里)：",
    min_value=1, max_value=10, value=10, step=1,
    disabled=not address_mode_active,
    help="請先輸入您的地址，才能使用此篩選器。"
)

st.sidebar.header("資料來源")
st.sidebar.info("本站資料為手動更新，將盡力保持最新。")

# --- 7. 核心篩選邏輯 ---
df_filtered = df_master.copy()

if service_type == '心理諮商':
    df_filtered = df_filtered[df_filtered['is_general']]
elif service_type == '通訊諮商':
    df_filtered = df_filtered[df_filtered['is_telehealth']]
elif service_type == '兩方案皆提供':
    df_filtered = df_filtered[df_filtered['is_general'] & df_filtered['is_telehealth']]

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

map_center = [23.9738, 120.982]
map_zoom = 8
user_location = geocode_user_address(user_address)

if user_location:
    map_center = user_location
    map_zoom = 12
    df_filtered['distance'] = df_filtered.apply(
        lambda row: geopy.distance.great_circle(user_location, (row['lat'], row['lng'])).km,
        axis=1
    )
    df_filtered = df_filtered[df_filtered['distance'] <= selected_distance]
    df_filtered = df_filtered.sort_values(by="distance")
else:
    if selected_county != "全台灣":
        df_filtered = df_filtered[df_filtered['scraped_county_name'] == selected_county]

# --- 8. 繪製地圖 ---
m = folium.Map(location=map_center, zoom_start=map_zoom, tiles="CartoDB positron")
marker_cluster = MarkerCluster().add_to(m)
folium.plugins.LocateControl(auto_start=False).add_to(m)

if df_filtered.empty:
    st.warning("在地圖範圍內找不到符合條件的診所。請調整篩選器。")
else:
    st.success(f"在地圖範圍內找到 {len(df_filtered)} 間符合條件的診所：")

    for idx, row in df_filtered.iterrows():
        has_any_availability = (row['general_availability'] > 0) or (row['telehealth_availability'] > 0)

        # (保留) 加大的標記
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

    if user_location:
        folium.Marker(
            location=user_location, popup="您的位置",
            icon=folium.Icon(color="red", icon="user")
        ).add_to(m)

    st_folium(m, width="100%", height=500, returned_objects=[])

# --- 9. 顯示資料表格 ---
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

