import os
import json
import requests
from datetime import datetime

CLIENT_ID = os.environ.get("TDX_CLIENT_ID")
CLIENT_SECRET = os.environ.get("TDX_CLIENT_SECRET")

def get_access_token():
    token_url = "https://tdx.transportdata.taiwan.gov.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    res = requests.post(token_url, headers=headers, data=data, timeout=15)
    res.raise_for_status()
    return res.json()["access_token"]

def fetch_today_hsr(token):
    # 抓取高鐵當日全線時刻表 (含臨時加班車)
    api_url = "https://tdx.transportdata.taiwan.gov.tw/api/basic/v2/Rail/THSR/DailyTimetable/Today?%24format=JSON"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    res = requests.get(api_url, headers=headers, timeout=20)
    res.raise_for_status()
    return res.json()

def parse_and_clean(raw_data):
    clean_trains = []
    for item in raw_data:
        train_info = item.get("DailyTrainInfo", {})
        train_no = train_info.get("TrainNo", "")
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

        # 自由座車廂預設 10-12，若連假公告有特別註明則擷取
        free_cars = "10-12"
        if "自由座" in note:
            free_cars = note

        clean_trains.append({
            "trainNo": train_no,
            "direction": "SOUTH" if direction_num == 0 else "NORTH",
            "start": start_station,
            "end": end_station,
            "freeCars": free_cars,
            "stops": stops
        })

    # 排序：依車次排序
    clean_trains.sort(key=lambda x: x["trainNo"])

    return {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalTrains": len(clean_trains),
        "trains": clean_trains
    }

if __name__ == "__main__":
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("請先設定環境變數 TDX_CLIENT_ID 與 TDX_CLIENT_SECRET！")

    print("正在向 TDX 申請 Access Token...")
    token = get_access_token()
    print("正在下載今日高鐵最新時刻表 (含加班車)...")
    raw = fetch_today_hsr(token)
    cleaned = parse_and_clean(raw)
    
    os.makedirs("public", exist_ok=True)
    with open("public/today_hsr.json", "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    print(f"成功處理完成！今日高鐵共 {cleaned['totalTrains']} 班次，已存至 public/today_hsr.json。")
