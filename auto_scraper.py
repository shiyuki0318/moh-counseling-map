import pandas as pd
import time
import sys
import urllib3
import math 
import re # 導入 re 用於解析頁數
from bs4 import BeautifulSoup 

# 導入 Selenium 的核心工具
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait 
from selenium.webdriver.support import expected_conditions as EC 
from selenium.webdriver.chrome.service import Service

# --- 0. 設置常量 ---
main_page_url = "https://sps.mohw.gov.tw/mhs"
OUTPUT_CSV_NAME = "MOHW_counseling_data_NEW.csv"
WAIT_TIME = 30  # 增加連線等待時間 (30秒)

# --- 關閉警告 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

all_institutions_data = [] 

try:
    # 2.1 啟動 Chrome (GitHub Actions 終極穩定版)
    # 使用系統安裝的 Chromedriver 路徑
    service = Service(executable_path="/usr/bin/chromedriver") 

    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')     # *** 使用新的無頭模式 ***
    options.add_argument('--no-sandbox')      # 雲端環境必備
    options.add_argument('--disable-dev-shm-usage') # 雲端環境必備
    options.add_argument('--disable-gpu')     # 禁用 GPU
    options.add_argument('--window-size=1920,1080') # 設置窗口大小
    options.add_argument('--log-level=3') 
    
    driver = webdriver.Chrome(service=service, options=options)
    
    # 設置頁面載入超時
    driver.set_page_load_timeout(WAIT_TIME + 10) 
    wait = WebDriverWait(driver, WAIT_TIME) 
    
    # 2.2 載入頁面
    print("  正在載入主頁面...")
    driver.get(main_page_url)

    # --- 處理 Cookie 同意彈窗 (如果有的話) ---
    try:
        cookie_accept_button = wait.until(EC.element_to_be
