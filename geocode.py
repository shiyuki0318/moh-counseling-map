import pandas as pd
import time
import sys

# (修改) 導入 ArcGIS 編碼器
from geopy.geocoders import ArcGIS
from geopy.extra.rate_limiter import RateLimiter

print("=" * 60)
print("🌍 正在執行「地理編碼 (Geocoding)」任務 (v2 - 使用 ArcGIS)...")
print("=" * 60)

# --- 1. 讀取您爬好的 CSV ---
try:
    df = pd.read_csv("MOHW_counseling_data_NEW.csv")
    print(f"  成功讀取 {len(df)} 筆資料。")
except FileNotFoundError:
    print("錯誤：找不到 'MOHW_counseling_data_NEW.csv'！")
    print("請確認此 .py 檔案和您的 CSV 檔案放在同一個資料夾。")
    sys.exit()

# --- 2. (修改) 初始化 ArcGIS 地理編碼器 ---
geolocator = ArcGIS(timeout=10) # 設定 10 秒超時

# (修改) ArcGIS 服務比較快，我們可以設定 0.5 秒查詢一次
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=0.5, error_wait_seconds=5.0)
print("  地理編碼器 (ArcGIS) 已初始化 (限速 0.5 秒/次)...")


# --- 3. 定義一個函數來轉換地址 ---
def get_lat_lng(address):
    """
    傳入地址字串，回傳 (緯度, 經度)
    """
    try:
        # ArcGIS 不需要 "台灣" 前綴，它能更好地理解中文地址
        location = geocode(address) 
        if location:
            return (location.latitude, location.longitude)
        else:
            return (None, None)
    except Exception as e:
        print(f"    -> 查詢 '{address}' 時出錯: {e}")
        return (None, None)

# --- 4. 開始遍歷所有地址 ---
# (這一步會花 5-10 分鐘)
print(f"\n🚀 開始轉換 {len(df)} 筆地址 (這會需要幾分鐘，請耐心等待)...")

latitudes = []
longitudes = []
count = 0

for address in df['address']:
    count += 1
    # 檢查是否為空地址
    if pd.isna(address) or address.strip() == "":
        print(f"  ({count}/{len(df)}) [SKIPPING] - 地址為空。")
        latitudes.append(None)
        longitudes.append(None)
        continue

    print(f"  ({count}/{len(df)}) 正在查詢: {address} ...")
    lat, lng = get_lat_lng(address)
    
    if lat:
        # 這次您應該會看到成功了！
        print(f"    -> 成功: ({lat}, {lng})")
    else:
        print(f"    -> 失敗: 找不到此地址。")
        
    latitudes.append(lat)
    longitudes.append(lng)

print("\n🎉 所有地址轉換完畢！")

# --- 5. 將新欄位加回 DataFrame ---
df['lat'] = latitudes
df['lng'] = longitudes

print("\n--- 資料範例 (包含經緯度) ---")
print(df.head())

# --- 6. 儲存成最終的 CSV 檔案 ---
try:
    final_filename = "MOHW_counseling_data_FINAL.csv"
    df.to_csv(final_filename, index=False, encoding='utf-8-sig')
    print(f"\n✅ 任務完成！已儲存至 '{final_filename}'")
    print("下一步：您現在可以使用這個 FINAL.csv 來建立您的地圖系統了！")
except Exception as e:
    print(f"\n❌ 儲存 CSV 失敗: {e}")