import os
import sys
import json
import requests
from datetime import datetime

CLIENT_ID = os.environ.get("TDX_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("TDX_CLIENT_SECRET", "").strip()

def get_access_token():
    # TDX OAuth 2.0 Token 官方端點
    token_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    try:
        res = requests.post(token_url, headers=headers, data=data, timeout=15)
        if res.status_code != 200:
            print(f"[錯誤] TDX Token 申請失敗！HTTP 狀態碼: {res.status_code}")
            print(f"[詳細內容] {res.text}")
            print("請檢查 GitHub Secrets 的 TDX_CLIENT_ID 與 TDX_CLIENT_SECRET 是否正確無誤！")
            sys.exit(1)
        return res.json()["access_token"]
    except requests.exceptions.RequestException as e:
        print(f"[連線錯誤] 無法連線至 TDX 認證伺服器: {e}")
        sys.exit(1)

def fetch_today_hsr(token):
    # 抓取高鐵當日全線時刻表 (含加班車)
    api_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/THSR/DailyTimetable/Today?%24format=JSON"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    try:
        res = requests.get(api_url, headers=headers, timeout=20)
        if res.status_code != 200:
            print(f"[錯誤] 下載時刻表失敗！HTTP 狀態碼: {res.status_code}")
            print(f"[詳細內容] {res.text}")
            sys.exit(1)
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"[連線錯誤] 下載時刻表連線異常: {e}")
        sys.exit(1)

def format_car_list(car_nos):
    """
    將車廂列表轉換為易讀字串格式，例如:
    [9, 10, 11, 12] -> "9-12"
    [8, 9, 10, 11, 12] -> "8-12"
    [1, 2, 3, 8, 9, 10, 11, 12] -> "1-3, 8-12"
    """
    if not car_nos:
        return "10-12"
    try:
        nums = sorted(list(set(int(c) for c in car_nos)))
        if not nums:
            return "10-12"
        ranges = []
        start = nums[0]
        prev = nums[0]
        for n in nums[1:]:
            if n == prev + 1:
                prev = n
            else:
                ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
                start = n
                prev = n
        ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
        return ", ".join(ranges)
    except Exception:
        return "10-12"

def fetch_today_free_seating_tdx(token):
    """
    從交通部 TDX 取得當日各車次之動態自由座車廂配置
    端點: DailyFreeSeatingCar/Today
    """
    api_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/THSR/DailyFreeSeatingCar/Today?%24format=JSON"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    car_map = {}
    try:
        res = requests.get(api_url, headers=headers, timeout=20)
        if res.status_code == 200:
            data = res.json()
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("FreeSeatingCars") or data.get("Items") or []

            for item in items:
                t_no = str(item.get("TrainNo", "")).strip()
                if not t_no:
                    continue
                car_nos = item.get("FreeSeatingCarNos") or item.get("CarNos")
                if isinstance(car_nos, list):
                    car_map[t_no] = format_car_list(car_nos)
                elif isinstance(car_nos, str) and car_nos:
                    car_map[t_no] = car_nos
                elif "FreeSeatingCars" in item and isinstance(item["FreeSeatingCars"], list):
                    car_map[t_no] = format_car_list(item["FreeSeatingCars"])

            print(f"[TDX 自由座] 成功從 TDX 端點獲取 {len(car_map)} 筆車次自由座配置。")
        else:
            print(f"[TDX 自由座警告] TDX FreeSeating 端點回應 HTTP {res.status_code}")
    except Exception as e:
        print(f"[TDX 自由座異常] 連線或解析失敗: {e}")
    return car_map

def fetch_today_free_seating_thsrc_web():
    """
    從台灣高鐵官方網站查詢當日全線班次的自由座配置 (雙重備援機制)
    端點: https://www.thsrc.com.tw/TimeTable/Search
    """
    car_map = {}
    today_str = datetime.now().strftime("%Y/%m/%d")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.thsrc.com.tw/TimeTable/Search"
    }
    routes = [
        ("NanGang", "ZuoYing"),
        ("ZuoYing", "NanGang")
    ]
    for start, end in routes:
        payload = {
            "SearchType": "S",
            "Lang": "TW",
            "StartStation": start,
            "EndStation": end,
            "OutWardSearchDate": today_str,
            "OutWardSearchTime": "06:00",
            "ReturnSearchDate": today_str,
            "ReturnSearchTime": "06:00",
            "DiscountType": ""
        }
        try:
            res = requests.post("https://www.thsrc.com.tw/TimeTable/Search", data=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                items = data.get("data", {}).get("DepartureTable", {}).get("TrainItem", [])
                for item in items:
                    t_no = str(item.get("TrainNumber", "")).strip()
                    car = item.get("NonReservedCar")
                    if t_no and car:
                        car_map[t_no] = str(car).strip()
        except Exception as e:
            print(f"[高鐵官網備援警告] {start}->{end} 查詢失敗: {e}")

    print(f"[高鐵官網備援] 成功從高鐵官網獲取 {len(car_map)} 筆車次自由座配置。")
    return car_map

def get_combined_free_seating_map(token):
    """
    結合 TDX API 與高鐵官網備援資料，優先取得動態自由座資訊
    """
    tdx_map = fetch_today_free_seating_tdx(token)
    web_map = fetch_today_free_seating_thsrc_web()

    combined = {}
    # 先填入官網資料
    combined.update(web_map)
    # 再填入 TDX 資料
    for t_no, car in tdx_map.items():
        if t_no not in combined or car != "10-12":
            combined[t_no] = car

    # 若任一來源檢測出非預設 (例如 9-12, 8-12)，優先採用動態調整數值
    for t_no, car in web_map.items():
        if car != "10-12":
            combined[t_no] = car

    return combined

def parse_and_clean(raw_data, free_seating_map=None):
    if free_seating_map is None:
        free_seating_map = {}

    clean_trains = []
    dynamic_count = 0

    for item in raw_data:
        train_info = item.get("DailyTrainInfo", {})
        train_no = str(train_info.get("TrainNo", "")).strip()
        direction_num = train_info.get("Direction", 0)  # 0: 南下, 1: 北上
        start_station = train_info.get("StartingStationName", {}).get("Zh_tw", "")
        end_station = train_info.get("EndingStationName", {}).get("Zh_tw", "")
        note = train_info.get("Note", "")

        stops = []
        for stop in item.get("StopTimes", []):
            st_name = stop.get("StationName", {}).get("Zh_tw", "")
            dep_time = stop.get("DepartureTime", "")
            arr_time = stop.get("ArrivalTime", dep_time)
            stops.append({
                "station": st_name,
                "arrivalTime": arr_time,
                "departureTime": dep_time
            })

        # 優先使用動態抓取的自由座車廂資訊
        free_cars = free_seating_map.get(train_no)
        if not free_cars:
            if "自由座" in note:
                free_cars = note
            else:
                free_cars = "10-12"

        if free_cars != "10-12":
            dynamic_count += 1

        clean_trains.append({
            "trainNo": train_no,
            "direction": "SOUTH" if direction_num == 0 else "NORTH",
            "start": start_station,
            "end": end_station,
            "freeCars": free_cars,
            "stops": stops
        })

    # 排序：依車次號碼排序
    clean_trains.sort(key=lambda x: x["trainNo"])

    print(f"[資料統計] 全線共 {len(clean_trains)} 班次，其中 {dynamic_count} 班次已動態調整自由座車廂 (如 9-12、8-12)。")

    return {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalTrains": len(clean_trains),
        "trains": clean_trains
    }

if __name__ == "__main__":
    if not CLIENT_ID or not CLIENT_SECRET:
        print("[錯誤] 找不到 TDX_CLIENT_ID 或 TDX_CLIENT_SECRET 環境變數！")
        print("請確認是否已在 GitHub 儲存庫的 Settings -> Secrets and variables -> Actions 中正確填入！")
        sys.exit(1)

    print("正在向 TDX 申請 Access Token...")
    token = get_access_token()
    print("Token 申請成功！正在下載今日高鐵最新時刻表 (含加班車)...")
    raw = fetch_today_hsr(token)

    print("正在獲取當日動態自由座車廂配置 (TDX + 高鐵官網備援)...")
    free_seating_map = get_combined_free_seating_map(token)

    cleaned = parse_and_clean(raw, free_seating_map)

    os.makedirs("public", exist_ok=True)
    with open("public/today_hsr.json", "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    print(f"成功處理完成！今日高鐵共 {cleaned['totalTrains']} 班次，已存至 public/today_hsr.json。")
