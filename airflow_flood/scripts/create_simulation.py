import requests
import json
import time
import os
from datetime import datetime, timedelta, timezone

import fiona
import fiona.vfs

if not hasattr(fiona, 'path'):
    fiona.path = fiona.vfs


TOMORROW_API_KEY = os.getenv("TOMORROW_API_KEY", "hgLTEzBZyx08GIAkmyaYEQAcgttgamaW")
LOCATION_LAT = os.getenv("LOCATION_LAT", "21.0285")
LOCATION_LON = os.getenv("LOCATION_LON", "105.804817")


THREEDI_API_KEY = os.getenv(
    "THREEDI_API_KEY",
    "Basic X19rZXlfXzo4Vm5aeUZZVC4yOEtoWWF6YnhkS3lTREtzbEFSTjJNaFVwWUc1eXZXWA==",
)
ORG_UUID = os.getenv("ORG_UUID", "905acb81673846f3b2f970e83b3af32a")
MODEL_ID = int(os.getenv("MODEL_ID", 76591))


SIMULATION_DURATION = int(os.getenv("SIMULATION_DURATION", 7200))
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", 900))


def load_last_state(state_file_path):
    """Đọc ID saved state cũ (Nhận đường dẫn từ tham số)"""
    if os.path.exists(state_file_path):
        try:
            with open(state_file_path, "r") as f:
                return json.load(f).get("last_saved_state_id")
        except:
            return None
    return None


def save_new_state(state_file_path, state_id):
    """Lưu ID saved state mới"""
    try:

        os.makedirs(os.path.dirname(state_file_path), exist_ok=True)
        with open(state_file_path, "w") as f:
            json.dump(
                {"last_saved_state_id": state_id, "updated_at": str(datetime.now())}, f
            )
    except Exception as e:
        print(f"⚠️ Không thể lưu state file: {e}")


def get_simulation_template_id(model_id):
    """Lấy Template ID để clone settings"""
    print(f"🔍 Đang tìm Template cho Model {model_id}...")
    url = "https://api.3di.live/v3/simulation-templates/"
    params = {"simulation__threedimodel__id": model_id, "limit": 1}
    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}

    try:
        res = requests.get(url, params=params, headers=headers)
        res.raise_for_status()
        results = res.json().get("results", [])
        if results:
            t_id = results[0]["id"]
            print(f"✅ Đã tìm thấy Template ID: {t_id}")
            return t_id
        else:
            print("❌ Không tìm thấy Template nào!")
            return None
    except Exception as e:
        print(f"❌ Lỗi lấy Template: {e}")
        return None


def get_rain_forecast():
    """Lấy dữ liệu mưa Tomorrow.io"""
    print(f"📡 1. Lấy dữ liệu mưa Tomorrow.io...")
    now = datetime.now(timezone.utc)
    end_time = now + timedelta(seconds=SIMULATION_DURATION)

    url = "https://api.tomorrow.io/v4/timelines"
    params = {
        "location": f"{LOCATION_LAT},{LOCATION_LON}",
        "fields": ["precipitationIntensity"],
        "timesteps": "1h",
        "units": "metric",
        "startTime": now.isoformat().replace("+00:00", "Z"),
        "endTime": end_time.isoformat().replace("+00:00", "Z"),
        "apikey": TOMORROW_API_KEY,
    }

    try:
        res = requests.get(url, params=params)
        res.raise_for_status()
        return res.json()["data"]["timelines"][0]["intervals"]
    except Exception as e:
        print(f"❌ Lỗi Weather API: {e}")
        return None


def run_forecast_process(state_file_path):
    print(f"🚀 Bắt đầu quy trình Simulation (State: {state_file_path})")

    template_id = get_simulation_template_id(MODEL_ID)
    if not template_id:
        return None, None

    intervals = get_rain_forecast()
    if not intervals:
        print("❌ Không lấy được dữ liệu mưa. Dừng.")
        return None, None

    print("🔄 2. Xử lý dữ liệu mưa...")
    rain_values = []

    start_time_str = intervals[0]["startTime"]

    for i, interval in enumerate(intervals):

        val_mm_hr = interval["values"].get("precipitationIntensity", 0)
        rain_m_s = val_mm_hr / (1000 * 3600)

        rain_values.append([i * 3600, rain_m_s])

    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}
    base_url = "https://api.3di.live/v3"

    last_state_id = load_last_state(state_file_path)
    is_hotstart = False
    if last_state_id:
        print(f"🔗 [Hotstart] Sẽ dùng Saved State ID: {last_state_id}")
        is_hotstart = True
    else:
        print("🆕 [Coldstart] Chạy mới từ Template")

    sim_payload = {
        "template": template_id,
        "name": f"Forecast_{datetime.now().strftime('%H%M')}",
        "organisation": ORG_UUID,
        "start_datetime": start_time_str,
        "duration": SIMULATION_DURATION,
        "tags": ["airflow-forecast"],
        "clone_settings": True,
        "clone_events": False,
        "clone_initials": not is_hotstart,
    }

    if is_hotstart:
        sim_payload["initial_conditions"] = {"use_saved_state_id": last_state_id}

    print(f"🚀 3. Tạo Simulation...")
    res = requests.post(
        f"{base_url}/simulations/from-template/", json=sim_payload, headers=headers
    )
    if res.status_code != 201:
        print(f"❌ Lỗi tạo Sim: {res.text}")
        return None, None
    sim_id = res.json()["id"]
    print(f"✅ Simulation ID: {sim_id}")

    print("🌧️ 4. Nạp mưa...")
    rain_payload = {
        "values": rain_values,
        "units": "m/s",
        "interpolate": True,
        "offset": 0,
    }
    requests.post(
        f"{base_url}/simulations/{sim_id}/events/rain/timeseries",
        json=rain_payload,
        headers=headers,
    )

    print(f"💾 5. Đăng ký lưu state tại giây thứ {UPDATE_INTERVAL}...")

    expiry_date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    save_payload = {
        "name": f"RollingState_{datetime.now().strftime('%H%M')}",
        "time": UPDATE_INTERVAL,
        "expiry": expiry_date,
        "tags": ["rolling-forecast"],
    }

    future_saved_state_id = None
    save_res = requests.post(
        f"{base_url}/simulations/{sim_id}/create-saved-states/timed/",
        json=save_payload,
        headers=headers,
    )

    if save_res.status_code in [200, 201]:
        future_saved_state_id = save_res.json()["id"]
        print(f"✅ Đã đăng ký thành công (ID tương lai: {future_saved_state_id})")
    else:
        print(f"❌ Lỗi đăng ký lưu state: {save_res.text}")

    print("▶️ 6. Gửi lệnh start...")

    try:
        action_res = requests.post(
            f"{base_url}/simulations/{sim_id}/actions/",
            json={"name": "start"},
            headers=headers,
        )

        if action_res.status_code not in [200, 201]:
            print(f"❌ LỖI NGHIÊM TRỌNG: Không thể Start Simulation!")
            print(f"   Status Code: {action_res.status_code}")
            print(f"   Response: {action_res.text}")

            return None, None

    except Exception as e:
        print(f"❌ Lỗi kết nối khi gọi lệnh Start: {e}")
        return None, None

    print("⏳ 7. Đang chạy...")
    is_success = False

    while True:
        try:
            st_data = requests.get(
                f"{base_url}/simulations/{sim_id}/status", headers=headers
            ).json()
            st = st_data["name"]

            if st == "finished":
                print("\n🏁 Hoàn tất!")
                is_success = True
                break
            elif st in ["crashed", "timeout", "shut_down"]:
                print(f"\n❌ Simulation bị lỗi giữa chừng: {st}")

                return None, None

            time.sleep(10)
        except:
            time.sleep(10)

    if is_success and future_saved_state_id:

        save_new_state(state_file_path, future_saved_state_id)

        return sim_id, future_saved_state_id

    if is_success:
        return sim_id, None

    return None, None


if __name__ == "__main__":

    run_forecast_process("flood_system_state.json")
