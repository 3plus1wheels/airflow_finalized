import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import fiona
import fiona.vfs
import requests


if not hasattr(fiona, "path"):
    fiona.path = fiona.vfs


def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def redact_secret(value):
    if not value:
        return value
    return re.sub(r"apikey=[^&\s]+", "apikey=<redacted>", str(value))


TOMORROW_API_KEY = require_env("TOMORROW_API_KEY")
LOCATION_LAT = os.getenv("LOCATION_LAT", "21.0285")
LOCATION_LON = os.getenv("LOCATION_LON", "105.804817")

THREEDI_API_KEY = require_env("THREEDI_API_KEY")
ORG_UUID = require_env("ORG_UUID")
MODEL_ID = int(os.getenv("MODEL_ID") or os.getenv("THREEDI_MODEL_ID", "76591"))

SIMULATION_DURATION = int(os.getenv("SIMULATION_DURATION", 600))
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", 900))
TEST_RAIN_MM_HR = os.getenv("FLOOD_TEST_RAIN_MM_HR")


def load_last_state(state_file_path):
    if os.path.exists(state_file_path):
        try:
            with open(state_file_path, "r", encoding="utf-8") as state_file:
                return json.load(state_file).get("last_saved_state_id")
        except Exception as exc:
            print(f"Could not load state file {state_file_path}: {exc}")
    return None


def save_new_state(state_file_path, state_id):
    try:
        os.makedirs(os.path.dirname(state_file_path), exist_ok=True)
        with open(state_file_path, "w", encoding="utf-8") as state_file:
            json.dump(
                {"last_saved_state_id": state_id, "updated_at": str(datetime.now())},
                state_file,
            )
    except Exception as exc:
        print(f"Could not save state file {state_file_path}: {exc}")


def get_simulation_template_id(model_id):
    print(f"Looking for 3Di simulation template for model {model_id}...")
    url = "https://api.3di.live/v3/simulation-templates/"
    params = {"simulation__threedimodel__id": model_id, "limit": 1}
    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}

    try:
        res = requests.get(url, params=params, headers=headers)
        res.raise_for_status()
        results = res.json().get("results", [])
    except Exception as exc:
        print(f"Template lookup failed: {exc}")
        return None

    if not results:
        print("No 3Di simulation template found.")
        return None

    template_id = results[0]["id"]
    print(f"Found template ID: {template_id}")
    return template_id


def get_rain_forecast():
    print("Fetching Tomorrow.io rain forecast...")
    now = datetime.now(timezone.utc)
    forecast_window_seconds = max(SIMULATION_DURATION, 3600)
    end_time = now + timedelta(seconds=forecast_window_seconds)

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
        intervals = res.json()["data"]["timelines"][0]["intervals"]
    except Exception as exc:
        print(f"Weather API error: {redact_secret(exc)}")
        if "res" in locals():
            print(f"   Status Code: {res.status_code}")
            print(f"   Response: {redact_secret(res.text)}")
        return None

    if TEST_RAIN_MM_HR:
        test_rain = float(TEST_RAIN_MM_HR)
        print(f"Using test rainfall override: {test_rain} mm/hr")
        for interval in intervals:
            interval.setdefault("values", {})["precipitationIntensity"] = test_rain
    else:
        rain_values = [
            interval.get("values", {}).get("precipitationIntensity", 0)
            for interval in intervals
        ]
        print(f"Forecast rain intensities mm/hr: {rain_values}")

    return intervals


def create_simulation(template_id, start_time_str, is_hotstart, last_state_id):
    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}
    payload = {
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
        payload["initial_conditions"] = {"use_saved_state_id": last_state_id}

    res = requests.post(
        "https://api.3di.live/v3/simulations/from-template/",
        json=payload,
        headers=headers,
    )
    if res.status_code != 201:
        print(f"Create simulation failed: {res.status_code} {res.text}")
        return None

    sim_id = res.json()["id"]
    print(f"Created simulation ID: {sim_id}")
    return sim_id


def add_rain_timeseries(sim_id, intervals):
    rain_values = []
    for index, interval in enumerate(intervals):
        val_mm_hr = interval["values"].get("precipitationIntensity", 0)
        rain_m_s = val_mm_hr / (1000 * 3600)
        rain_values.append([index * 3600, rain_m_s])

    print(f"Uploading rain timeseries mm/hr: {[round(v[1] * 1000 * 3600, 3) for v in rain_values]}")

    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}
    payload = {
        "values": rain_values,
        "units": "m/s",
        "interpolate": True,
        "offset": 0,
    }
    res = requests.post(
        f"https://api.3di.live/v3/simulations/{sim_id}/events/rain/timeseries",
        json=payload,
        headers=headers,
    )
    if res.status_code not in [200, 201]:
        print(f"Rain timeseries upload failed: {res.status_code} {res.text}")
        return False
    return True


def register_saved_state(sim_id):
    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}
    payload = {
        "name": f"RollingState_{datetime.now().strftime('%H%M')}",
        "time": UPDATE_INTERVAL,
        "expiry": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "tags": ["rolling-forecast"],
    }
    res = requests.post(
        f"https://api.3di.live/v3/simulations/{sim_id}/create-saved-states/timed/",
        json=payload,
        headers=headers,
    )
    if res.status_code in [200, 201]:
        state_id = res.json()["id"]
        print(f"Registered future saved state ID: {state_id}")
        return state_id

    print(f"Saved state registration failed: {res.status_code} {res.text}")
    return None


def start_simulation(sim_id):
    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}
    res = requests.post(
        f"https://api.3di.live/v3/simulations/{sim_id}/actions/",
        json={"name": "start"},
        headers=headers,
    )
    if res.status_code not in [200, 201]:
        print(f"Start simulation failed: {res.status_code} {res.text}")
        return False
    return True


def wait_for_simulation(sim_id):
    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}
    while True:
        try:
            status_data = requests.get(
                f"https://api.3di.live/v3/simulations/{sim_id}/status",
                headers=headers,
            ).json()
            status_name = status_data["name"]

            if status_name == "finished":
                print("Simulation finished.")
                return True
            if status_name in ["crashed", "timeout", "shut_down"]:
                print(f"Simulation failed with status: {status_name}")
                return False
        except Exception as exc:
            print(f"Could not poll simulation status: {exc}")

        time.sleep(10)


def run_forecast_process(state_file_path):
    print(f"Starting simulation workflow. State file: {state_file_path}")

    template_id = get_simulation_template_id(MODEL_ID)
    if not template_id:
        return None, None

    intervals = get_rain_forecast()
    if not intervals:
        print("Could not fetch rain data. Stopping.")
        return None, None

    start_time_str = intervals[0]["startTime"]
    last_state_id = load_last_state(state_file_path)
    is_hotstart = bool(last_state_id)
    if is_hotstart:
        print(f"Hotstart using saved state ID: {last_state_id}")
    else:
        print("Coldstart from template.")

    sim_id = create_simulation(template_id, start_time_str, is_hotstart, last_state_id)
    if not sim_id:
        return None, None

    if not add_rain_timeseries(sim_id, intervals):
        return None, None

    future_saved_state_id = register_saved_state(sim_id)

    if not start_simulation(sim_id):
        return None, None

    if not wait_for_simulation(sim_id):
        return None, None

    if future_saved_state_id:
        save_new_state(state_file_path, future_saved_state_id)
        return sim_id, future_saved_state_id

    return sim_id, None


if __name__ == "__main__":
    run_forecast_process("flood_system_state.json")
