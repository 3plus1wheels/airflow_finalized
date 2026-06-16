import requests
import time
import os
from datetime import datetime, timedelta, timezone

# ==============================================================================
# CONFIG
# ==============================================================================

TOMORROW_API_KEY = os.getenv("TOMORROW_API_KEY")
LOCATION_LAT = os.getenv("LOCATION_LAT", "21.0285")
LOCATION_LON = os.getenv("LOCATION_LON", "105.804817")

THREEDI_API_KEY = os.getenv("THREEDI_API_KEY")
ORG_UUID = os.getenv("ORG_UUID")
MODEL_ID = int(os.getenv("THREEDI_MODEL_ID", "78136"))

SIMULATION_DURATION = int(os.getenv("SIMULATION_DURATION", 7200))

BASE_URL = "https://api.3di.live/v3"


# ==============================================================================
# COMMON
# ==============================================================================

def get_headers():
    api_key = THREEDI_API_KEY.strip()

    if api_key.lower().startswith("basic "):
        auth_value = api_key
    else:
        auth_value = f"Basic {api_key}"

    return {
        "Authorization": auth_value,
        "Content-Type": "application/json",
    }


# ==============================================================================
# TEMPLATE
# ==============================================================================

def get_simulation_template_id(model_id=MODEL_ID):
    print(f"🔍 Đang tìm Template cho Model {model_id}...")

    url = f"{BASE_URL}/simulation-templates/"
    params = {
        "simulation__threedimodel__id": model_id,
        "limit": 1,
    }

    try:
        res = requests.get(url, params=params, headers=get_headers())
        res.raise_for_status()

        results = res.json().get("results", [])

        if results:
            template_id = results[0]["id"]
            print(f"✅ Đã tìm thấy Template ID: {template_id}")
            return template_id

        print("❌ Không tìm thấy Template nào!")
        return None

    except Exception as e:
        print(f"❌ Lỗi lấy Template: {e}")
        return None


# ==============================================================================
# RAIN
# ==============================================================================

def get_rain_forecast():
    print("📡 1. Lấy dữ liệu mưa Tomorrow.io...")

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


def build_rain_values(intervals):
    print("🔄 2. Xử lý dữ liệu mưa...")

    rain_values = []

    for i, interval in enumerate(intervals):
        val_mm_hr = interval["values"].get("precipitationIntensity", 0)
        rain_m_s = val_mm_hr / (1000 * 3600)
        rain_values.append([i * 3600, rain_m_s])

    print(f"✅ Đã xử lý {len(rain_values)} timestep mưa")

    return rain_values


# ==============================================================================
# SIMULATION
# ==============================================================================

def create_simulation(template_id, start_time_str):
    print("🚀 3. Tạo Simulation...")

    sim_payload = {
        "template": template_id,
        "name": f"Forecast_{datetime.now().strftime('%H%M')}",
        "organisation": ORG_UUID,
        "start_datetime": start_time_str,
        "duration": SIMULATION_DURATION,
        "tags": ["airflow-forecast", "initial-wl"],
        "clone_settings": True,
        "clone_events": False,
        "clone_initials": False,
    }

    res = requests.post(
        f"{BASE_URL}/simulations/from-template/",
        json=sim_payload,
        headers=get_headers(),
    )

    if res.status_code != 201:
        print(f"❌ Lỗi tạo Sim: {res.text}")
        return None

    sim_id = res.json()["id"]
    print(f"✅ Simulation ID: {sim_id}")

    return sim_id


def apply_initial_waterlevels_to_simulation(sim_id, initial_waterlevel_resource_url):
    print("🌊 4. Apply initial water level...")

    payload = {
        "initial_waterlevel": initial_waterlevel_resource_url,
    }

    print(f"🔗 Initial WL resource: {initial_waterlevel_resource_url}")

    res = requests.post(
        f"{BASE_URL}/simulations/{sim_id}/initial/1d_water_level/file/",
        json=payload,
        headers=get_headers(),
    )

    if res.status_code not in [200, 201, 204]:
        print("❌ Lỗi apply initial water level")
        print(f"   Status Code: {res.status_code}")
        print(f"   Response: {res.text}")
        return False

    print("✅ Đã apply initial water level")
    return True


def add_rain_event(sim_id, rain_values):
    print("🌧️ 5. Nạp mưa...")

    rain_payload = {
        "values": rain_values,
        "units": "m/s",
        "interpolate": True,
        "offset": 0,
    }

    res = requests.post(
        f"{BASE_URL}/simulations/{sim_id}/events/rain/timeseries",
        json=rain_payload,
        headers=get_headers(),
    )

    if res.status_code not in [200, 201, 204]:
        print("❌ Lỗi nạp mưa")
        print(f"   Status Code: {res.status_code}")
        print(f"   Response: {res.text}")
        return False

    print("✅ Đã nạp mưa")
    return True


def start_simulation(sim_id):
    print("▶️ 6. Gửi lệnh start...")

    try:
        action_res = requests.post(
            f"{BASE_URL}/simulations/{sim_id}/actions/",
            json={"name": "start"},
            headers=get_headers(),
        )

        if action_res.status_code not in [200, 201]:
            print("❌ LỖI NGHIÊM TRỌNG: Không thể Start Simulation!")
            print(f"   Status Code: {action_res.status_code}")
            print(f"   Response: {action_res.text}")
            return False

        print("✅ Đã gửi lệnh start")
        return True

    except Exception as e:
        print(f"❌ Lỗi kết nối khi gọi lệnh Start: {e}")
        return False


def monitor_simulation(sim_id):
    print("⏳ 7. Đang chạy...")

    while True:
        try:
            st_data = requests.get(
                f"{BASE_URL}/simulations/{sim_id}/status",
                headers=get_headers(),
            ).json()

            st = st_data["name"]

            if st == "finished":
                print("\n🏁 Hoàn tất!")
                print(f"👉 Results: {BASE_URL}/simulations/{sim_id}/results")
                return True

            if st in ["crashed", "timeout", "shut_down"]:
                print(f"\n❌ Simulation bị lỗi giữa chừng: {st}")
                return False

            if st == "started":
                t = st_data.get("time", 0)
                pct = int(t / SIMULATION_DURATION * 100)
                print(f"[Run: {pct}%]", end=" ", flush=True)
            else:
                print(f"[{st}]", end=" ", flush=True)

            time.sleep(10)

        except Exception as e:
            print(f"\n⚠️ Lỗi đọc status: {e}")
            time.sleep(10)


# ==============================================================================
# AIRFLOW ENTRYPOINT
# ==============================================================================

def run_simulation(initial_waterlevel_resource_url):
    print("🚀 Bắt đầu quy trình Simulation với Initial Water Level")

    template_id = get_simulation_template_id(MODEL_ID)
    if not template_id:
        return None

    intervals = get_rain_forecast()
    if not intervals:
        print("❌ Không lấy được dữ liệu mưa. Dừng.")
        return None

    rain_values = build_rain_values(intervals)
    start_time_str = intervals[0]["startTime"]

    sim_id = create_simulation(
        template_id=template_id,
        start_time_str=start_time_str,
    )

    if not sim_id:
        return None

    if not apply_initial_waterlevels_to_simulation(
        sim_id=sim_id,
        initial_waterlevel_resource_url=initial_waterlevel_resource_url,
    ):
        return None

    if not add_rain_event(sim_id, rain_values):
        return None

    if not start_simulation(sim_id):
        return None

    if not monitor_simulation(sim_id):
        return None

    print(f"✅ Simulation hoàn tất với ID: {sim_id}")

    return sim_id


if __name__ == "__main__":
    test_initial_wl_url = os.getenv("INITIAL_WATERLEVEL_RESOURCE_URL")

    if not test_initial_wl_url:
        raise ValueError("Missing INITIAL_WATERLEVEL_RESOURCE_URL")

    run_simulation(test_initial_wl_url)