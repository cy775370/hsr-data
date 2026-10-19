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
        # 轉成整數並排序
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
            # 支援 list 或 dict (含 FreeSeatingCars 或 Items)
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


# ==============================================================================
# 以下為「高鐵秒轉乘 (HSR connection)」專用之接駁時刻表與台鐵即時誤點產出邏輯
# 產出獨立檔案 public/today_feeder.json，100% 不影響原本的 public/today_hsr.json
# ==============================================================================

def normalize_st_name(name):
    if not name:
        return ""
    return str(name).replace("臺", "台").strip()

def simplify_tra_type(type_name, train_no):
    t = str(type_name)
    if "區間快" in t:
        return f"區間快 {train_no}"
    if "區間" in t:
        return f"區間 {train_no}"
    if "自強" in t or "普悠瑪" in t or "太魯閣" in t:
        return f"自強 {train_no}"
    if "莒光" in t:
        return f"莒光 {train_no}"
    return f"台鐵 {train_no}"

def fetch_tra_live_delays(token):
    """
    從 TDX 取得台鐵即時誤點資訊 (LiveBoard)
    回傳 dict: { train_no: delay_minutes }
    """
    api_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveBoard?%24format=JSON"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    delay_map = {}
    try:
        res = requests.get(api_url, headers=headers, timeout=20)
        if res.status_code == 200:
            data = res.json()
            items = data if isinstance(data, list) else data.get("LiveBoards", [])
            for item in items:
                t_no = str(item.get("TrainNo", "")).strip()
                delay = int(item.get("DelayTime", 0) or 0)
                if t_no and delay > 0:
                    delay_map[t_no] = max(delay_map.get(t_no, 0), delay)
            print(f"[台鐵即時誤點] 成功讀取 LiveBoard，共 {len(delay_map)} 班列車有誤點紀錄。")
        else:
            print(f"[台鐵即時誤點警告] HTTP {res.status_code}")
    except Exception as e:
        print(f"[台鐵即時誤點異常] {e}")
    return delay_map

def fetch_tra_daily_timetable(token):
    """
    從 TDX 取得台鐵當日全線時刻表，支援 v2 與 v3 格式
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    urls = [
        "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Today?%24format=JSON",
        "https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/Today?%24format=JSON"
    ]
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=25)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    print(f"[台鐵時刻表] 成功從 TDX v2 下載 {len(data)} 班台鐵列車。")
                    return data
                if isinstance(data, dict) and "TrainTimetables" in data:
                    items = data["TrainTimetables"]
                    print(f"[台鐵時刻表] 成功從 TDX v3 下載 {len(items)} 班台鐵列車。")
                    return items
        except Exception as e:
            print(f"[台鐵時刻表警告] 嘗試 {url} 異常: {e}")
    return []

def build_tra_feeders(tra_raw, delay_map):
    """
    篩選停靠 4 大台鐵轉乘站（六家、豐富、新烏日、沙崙）的雙向班次，並附上沿途各站停靠時刻
    """
    corridors = [
        {
            "hub": "六家",
            "routeId": "HSC_TRA_MAIN",
            "targets": ["竹中", "新莊", "千甲", "北新竹", "新竹"],
            "defaultTarget": "新竹",
            "toCityHint": "六家站月台",
            "toHsrHint": "往六家方向月台"
        },
        {
            "hub": "豐富",
            "routeId": "MLI_TRA_SOUTH",
            "targets": ["苗栗", "銅鑼", "三義"],
            "defaultTarget": "苗栗",
            "toCityHint": "豐富站南下月台",
            "toHsrHint": "北上往豐富方向月台"
        },
        {
            "hub": "豐富",
            "routeId": "MLI_TRA_NORTH",
            "targets": ["造橋", "竹南"],
            "defaultTarget": "竹南",
            "toCityHint": "豐富站北上月台",
            "toHsrHint": "南下往豐富方向月台"
        },
        {
            "hub": "新烏日",
            "routeId": "TXG_TRA_NORTH",
            "targets": ["大慶", "五權", "台中", "太原", "松竹", "豐原"],
            "defaultTarget": "台中",
            "toCityHint": "新烏日北上月台",
            "toHsrHint": "南下往新烏日月台"
        },
        {
            "hub": "新烏日",
            "routeId": "TXG_TRA_SOUTH",
            "targets": ["成功", "彰化", "員林"],
            "defaultTarget": "彰化",
            "toCityHint": "新烏日南下月台",
            "toHsrHint": "北上往新烏日月台"
        },
        {
            "hub": "沙崙",
            "routeId": "TNN_TRA_CITY",
            "targets": ["長榮大學", "仁德", "保安", "台南", "大橋", "永康", "新市", "南科", "善化"],
            "defaultTarget": "台南",
            "toCityHint": "沙崙站月台",
            "toHsrHint": "往沙崙方向月台"
        }
    ]

    feeders = []
    for item in tra_raw:
        info = item.get("DailyTrainInfo") or item.get("TrainInfo") or {}
        train_no = str(info.get("TrainNo", "")).strip()
        if not train_no:
            continue
        type_obj = info.get("TrainTypeName", {})
        type_zh = type_obj.get("Zh_tw", "區間") if isinstance(type_obj, dict) else str(type_obj)
        display_train_no = simplify_tra_type(type_zh, train_no)
        delay_min = delay_map.get(train_no, 0)

        raw_stops = item.get("StopTimes", [])
        if not raw_stops:
            continue

        # 建立有序停靠站列表
        ordered_stops = []
        stop_index_map = {}
        for idx, st in enumerate(raw_stops):
            st_name = normalize_st_name(st.get("StationName", {}).get("Zh_tw", ""))
            dep = st.get("DepartureTime", "")
            arr = st.get("ArrivalTime", dep) or dep
            dep = dep or arr
            if not st_name or not arr:
                continue
            stop_entry = {
                "station": st_name,
                "arrivalTime": arr[:5],
                "departureTime": dep[:5]
            }
            stop_index_map[st_name] = len(ordered_stops)
            ordered_stops.append(stop_entry)

        # 檢查每個轉乘走廊
        for corr in corridors:
            hub_name = corr["hub"]
            if hub_name not in stop_index_map:
                continue
            hub_idx = stop_index_map[hub_name]
            hub_stop = ordered_stops[hub_idx]

            # 找出此班車有停靠的目標端點站
            matched_targets = [t for t in corr["targets"] if t in stop_index_map]
            if not matched_targets:
                continue

            # 判斷方向：若目標站索引 > hub_idx，代表由轉乘站開往市區 (TO_CITY)
            downstream_targets = [t for t in matched_targets if stop_index_map[t] > hub_idx]
            upstream_targets = [t for t in matched_targets if stop_index_map[t] < hub_idx]

            relevant_stops = [
                ordered_stops[stop_index_map[t]] for t in matched_targets
            ] + [hub_stop]

            if downstream_targets:
                rep_target = corr["defaultTarget"] if corr["defaultTarget"] in downstream_targets else downstream_targets[-1]
                rep_stop = ordered_stops[stop_index_map[rep_target]]
                feeders.append({
                    "trainNo": display_train_no,
                    "system": "TRA",
                    "routeId": corr["routeId"],
                    "mode": "TO_CITY",
                    "originStation": hub_name,
                    "destinationStation": rep_target,
                    "departureTime": hub_stop["departureTime"],
                    "arrivalTime": rep_stop["arrivalTime"],
                    "delayMinutes": delay_min,
                    "platformHint": corr["toCityHint"],
                    "stops": relevant_stops
                })

            if upstream_targets:
                rep_origin = corr["defaultTarget"] if corr["defaultTarget"] in upstream_targets else upstream_targets[0]
                rep_stop = ordered_stops[stop_index_map[rep_origin]]
                feeders.append({
                    "trainNo": display_train_no,
                    "system": "TRA",
                    "routeId": corr["routeId"],
                    "mode": "TO_HSR",
                    "originStation": rep_origin,
                    "destinationStation": hub_name,
                    "departureTime": rep_stop["departureTime"],
                    "arrivalTime": hub_stop["arrivalTime"],
                    "delayMinutes": delay_min,
                    "platformHint": corr["toHsrHint"],
                    "stops": relevant_stops
                })

    print(f"[台鐵轉乘班次] 共整理出 {len(feeders)} 筆台鐵轉乘走廊班次。")
    return feeders

def format_hhmm(total_minutes):
    normalized = ((total_minutes % 1440) + 1440) % 1440
    return f"{normalized // 60:02d}:{normalized % 60:02d}"

def build_mrt_feeders():
    """
    產生桃園機場捷運 (A18 高鐵桃園站) 與 台中捷運綠線 (高鐵臺中站) 全日班表
    App 端會根據使用者選擇的捷運端點站 (例如 A22 老街溪、A12 機場一航廈、市政府、北屯總站) 自動換算各站車程
    """
    mrt_list = []
    for hour in range(5, 24):
        # 1. 桃園機場捷運 (每 15 分鐘一班)
        for m in [3, 18, 33, 48]:
            dep_min = hour * 60 + m
            mrt_list.append({
                "trainNo": "機捷普通車",
                "system": "TYMC",
                "routeId": "TYN_MRT_SOUTH",
                "mode": "TO_CITY",
                "originStation": "A18 高鐵桃園",
                "destinationStation": "A22 老街溪(中壢)",
                "departureTime": format_hhmm(dep_min),
                "arrivalTime": format_hhmm(dep_min + 13),
                "delayMinutes": 0,
                "platformHint": "第 2 月台 (往老街溪)",
                "headwayNote": "每 15 分鐘一班"
            })
            to_hsr_dep = hour * 60 + ((m + 5) % 60)
            mrt_list.append({
                "trainNo": "機捷普通車",
                "system": "TYMC",
                "routeId": "TYN_MRT_SOUTH",
                "mode": "TO_HSR",
                "originStation": "A22 老街溪(中壢)",
                "destinationStation": "A18 高鐵桃園",
                "departureTime": format_hhmm(to_hsr_dep),
                "arrivalTime": format_hhmm(to_hsr_dep + 13),
                "delayMinutes": 0,
                "platformHint": "第 1 月台 (往高鐵桃園/台北)",
                "headwayNote": "每 15 分鐘一班"
            })
            north_dep = hour * 60 + ((m + 7) % 60)
            mrt_list.append({
                "trainNo": "機捷普通車",
                "system": "TYMC",
                "routeId": "TYN_MRT_NORTH",
                "mode": "TO_CITY",
                "originStation": "A18 高鐵桃園",
                "destinationStation": "A13 機場二航廈",
                "departureTime": format_hhmm(north_dep),
                "arrivalTime": format_hhmm(north_dep + 14),
                "delayMinutes": 0,
                "platformHint": "第 1 月台 (往機場/台北)",
                "headwayNote": "每 15 分鐘一班"
            })
            mrt_list.append({
                "trainNo": "機捷普通車",
                "system": "TYMC",
                "routeId": "TYN_MRT_NORTH",
                "mode": "TO_HSR",
                "originStation": "A13 機場二航廈",
                "destinationStation": "A18 高鐵桃園",
                "departureTime": format_hhmm(dep_min),
                "arrivalTime": format_hhmm(dep_min + 14),
                "delayMinutes": 0,
                "platformHint": "第 2 月台 (往高鐵桃園)",
                "headwayNote": "每 15 分鐘一班"
            })

        # 2. 台中捷運綠線 (高鐵臺中站 <-> 市政府/北屯總站)
        for m in range(0, 60, 10):
            dep_min = hour * 60 + m
            mrt_list.append({
                "trainNo": "綠線往北屯總站",
                "system": "TMRT",
                "routeId": "TXG_MRT_GREEN",
                "mode": "TO_CITY",
                "originStation": "中捷高鐵臺中",
                "destinationStation": "市政府",
                "departureTime": format_hhmm(dep_min),
                "arrivalTime": format_hhmm(dep_min + 17),
                "delayMinutes": 0,
                "platformHint": "端點站第 1/2 月台",
                "headwayNote": "尖峰 6 分 / 離峰 9 分一班"
            })
            mrt_list.append({
                "trainNo": "綠線往高鐵臺中",
                "system": "TMRT",
                "routeId": "TXG_MRT_GREEN",
                "mode": "TO_HSR",
                "originStation": "市政府",
                "destinationStation": "中捷高鐵臺中",
                "departureTime": format_hhmm(dep_min + 3),
                "arrivalTime": format_hhmm(dep_min + 20),
                "delayMinutes": 0,
                "platformHint": "往高鐵臺中方向月台",
                "headwayNote": "尖峰 6 分 / 離峰 9 分一班"
            })

    return mrt_list

def build_and_save_feeder_json(token):
    print("正在下載今日台鐵時刻表與即時誤點 (供高鐵秒轉乘 App 使用)...")
    delay_map = fetch_tra_live_delays(token)
    tra_raw = fetch_tra_daily_timetable(token)
    tra_feeders = build_tra_feeders(tra_raw, delay_map) if tra_raw else []
    mrt_feeders = build_mrt_feeders()

    all_feeders = tra_feeders + mrt_feeders
    feeder_payload = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalFeeders": len(all_feeders),
        "feeders": all_feeders
    }

    os.makedirs("public", exist_ok=True)
    with open("public/today_feeder.json", "w", encoding="utf-8") as f:
        json.dump(feeder_payload, f, ensure_ascii=False, indent=2)
    print(f"成功處理完成！接駁時刻表共 {len(all_feeders)} 筆，已存至 public/today_feeder.json。")

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

    # 額外產出高鐵秒轉乘 App 使用的 public/today_feeder.json (不影響原本 today_hsr.json)
    try:
        build_and_save_feeder_json(token)
    except Exception as e:
        print(f"[接駁時刻表警告] 產出 today_feeder.json 時發生錯誤 (不影響 today_hsr.json): {e}")
