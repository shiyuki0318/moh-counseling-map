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
    
    # Google 搜尋只使用機構名稱
    df_merged['gmaps_query'] = df_merged['orgName'].apply(
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
        * 系統將定位並篩選出距離您 1-10 公里內的機構。
        * 您可以透過側邊欄的「距離範圍」滑桿來調整搜尋半徑。
        
        **2. 縣市瀏覽：**
        * 不要輸入任何地址，使用「選擇縣市」下拉選項瀏覽特定區域。
        
        **3. 關於定位按鈕：**
        * 您可以點擊地圖左上角的「定位按鈕」來查看您目前的所在地（藍色圓點）。
        * **注意：** 為確保地圖穩定，點擊定位按鈕或拖曳地圖**不會**改變搜尋結果，請使用「輸入地址」來進行精確篩選。
        
        **4. 篩選服務：**
        * 您可以選擇要找的服務類型，例如「心理諮商」或「通訊
