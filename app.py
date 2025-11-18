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
COUNSELING_CSV = "MOHW_counseling_data_FINAL.csv"  # 「心理諮商」資料
TELEHEALTH_CSV = "MOHW_telehealth_data_FINAL.csv"  # 「通訊諮商」資料

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
    
    df_merged['gmaps_query'] = (df_merged['orgName'] + ' ' + df_merged['address']).apply(
        lambda x: urllib.parse.quote_plus(str(x))
    )
    df_merged['gmaps_url'] = "http://googleusercontent.com/maps.google.com/search/" + df_merged['gmaps_query']
    
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

# (保留) 注入 CSS 更改「網站配色」
st.markdown(
    """
    <style>
    .st-emotion-cache-10trblm { color: #2E8B57; }
    .st-emotion-cache-r8a62r, .st-emotion-cache-1f2d01k { color: #2E8B57; }
    [data-testid="stSidebar"] { background-color: #F0F8F0; }
    [data-testid="stNotification"] { background-color: #DDFFDD; }
    </style>
    """,
    unsafe_allow_html=True
)

# --- (新功能) 歡迎彈窗 (Modal) ---
if 'welcome_shown' not in st.session_state:
    with st.dialog("【 歡迎使用 - 網站提醒 】"):
        st.markdown(
            """
            歡迎使用本地圖查詢系統！
            
            **如何使用：**
            
            1.  **地址查詢 (推薦)**：
                * 在左側側邊欄的「**輸入您的地址**」中輸入完整地址。
                * 地圖將自動縮放至您的位置，並顯示最近的機構。
                * 「縣市」下拉選單將被**禁用**。
            
            2.  **縣市瀏覽**：
                * **不要**輸入任何地址。
                * 使用「**或 選擇縣市**」下拉選單瀏覽特定區域。
            
            3.  **篩選服務**：
                * 您可以選擇要找的服務類型，例如「僅限 心理諮商」或「僅限 通訊諮商」。
            
            點擊下方按鈕開始使用。
            """
        )
        if st.button("我了解了，開始使用"):
            st.session_state.welcome_shown = True # 設置標記
            st.rerun() # 重新整理頁面以關閉彈窗並載入主程式

# --- (*** 關鍵修正 ***) ---
# --- 以下所有程式碼，都必須在 else: 裡面 (往右縮排) ---
else:
    # --- 5. 載入主程式 ---
    
    st.title("🗺️ 台灣公費心理諮商 即時地圖搜尋系統")
    st.markdown("「15-45歲青壯世代心理健康支持方案」，「心理諮商」及「通訊諮商」兩項公費資源整理。")

    df_master = load_and_merge_data()

    if df_master.empty:
        st.stop() 

    # --- 6. 側邊欄 (Sidebar) 篩選器 ---
    st.sidebar.header("📍 地圖篩選器")

    service_type = st.sidebar.radio(
        "請選擇公費方案：",
        ('僅限 心理諮商 (15-45歲)', 
         '僅限 通訊諮商 (15-45歲)', 
         '兩方案皆提供 (15-45歲)', 
         '顯示所有機構'),
        index=0, 
        key='service_type'
    )

    availability_filter = st.sidebar.radio(
        "請選擇名額狀態：",
        ('顯示全部', '至少一項有名額 (OR)', '兩項同時有名額 (AND)'),
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

    if service_type == '僅限 心理諮商 (15-45歲)':
        df_filtered = df_filtered[df_filtered['is_general']]
    elif service_type == '僅限 通訊諮商 (15-45歲)':
        df_filtered = df_filtered[df_filtered['is_telehealth']]
    elif service_type == '兩方案皆提供 (15-45歲)':
        df_filtered = df_filtered[df_filtered['is_general'] & df_filtered['is_telehealth']]

    if availability_filter == '至少一項有名額 (OR)':
        if service_type == '僅限 心理諮商 (15-45歲)':
            df_filtered = df_filtered[df_filtered['general_availability'] > 0]
        elif service_type == '僅限 通訊諮商 (15-45歲)':
            df_filtered = df_filtered[df_filtered['telehealth_availability'] > 0]
        else: 
            df_filtered = df_filtered[
                (df_filtered['general_availability'] > 0) | 
                (df_filtered['telehealth_availability'] > 0)
            ]
    elif availability_filter == '兩項同時有名額 (AND
