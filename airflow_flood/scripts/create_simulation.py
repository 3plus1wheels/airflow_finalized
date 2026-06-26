import json
import os
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


TOMORROW_API_KEY = require_env("TOMORROW_API_KEY")
LOCATION_LAT = os.getenv("LOCATION_LAT", "21.0285")
LOCATION_LON = os.getenv("LOCATION_LON", "105.804817")

THREEDI_API_KEY = require_env("THREEDI_API_KEY")
ORG_UUID = require_env("ORG_UUID")
MODEL_ID = int(os.getenv("MODEL_ID") or os.getenv("THREEDI_MODEL_ID", "76591"))

SIMULATION_DURATION = int(os.getenv("SIMULATION_DURATION", 7200))
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", 900))


def load_last_state(state_file_path):
    if os.path.exists(state_file_path):
        try:
            with open(state_file_path, "r", encoding="utf-8") as state_file:
                return json.load(state_file).get("last_saved_state_id")
        except Exception:
            return None
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
        print(f"Could not save state file: {exc}")


def get_simulation_template_id(model_id):
    print(f"Looking for template for model {model_id}...")
    url = "https://api.3di.live/v3/simulation-templates/"
    params = {"simulation__threedimodel__id": model_id, "limit": 1}
    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}

    try:
        res = requests.get(url, params=params, headers=headers)
        res.raise_for_status()
        results = res.json().get("results", [])
        if results:
            template_id = results[0]["id"]
            print(f"Found template ID: {template_id}")
            return template_id

        print("No template found.")
        return None
    except Exception as exc:
        print(f"Template lookup failed: {exc}")
        return None


def get_rain_forecast():
    print("Fetching Tomorrow.io rain forecast...")
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
    except Exception as exc:
        print(f"Weather API error: {exc}")
        return None


def run_forecast_process(state_file_path):
    print(f"Starting simulation workflow. State file: {state_file_path}")

    template_id = get_simulation_template_id(MODEL_ID)
    if not template_id:
        return None, None

    intervals = get_rain_forecast()
    if not intervals:
        print("Could not fetch rain data. Stopping.")
        return None, None

    print("Processing rain data...")
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
        print(f"Hotstart using saved state ID: {last_state_id}")
        is_hotstart = True
    else:
        print("Coldstart from template.")

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

    print("Creating simulation...")
    res = requests.post(
        f"{base_url}/simulations/from-template/", json=sim_payload, headers=headers
    )
    if res.status_code != 201:
        print(f"Create simulation failed: {res.text}")
        return None, None

    sim_id = res.json()["id"]
    print(f"Simulation ID: {sim_id}")

    print("Uploading rain timeseries...")
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

    print(f"Registering saved state at second {UPDATE_INTERVAL}...")
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
        print(f"Registered future saved state ID: {future_saved_state_id}")
    else:
        print(f"Saved state registration failed: {save_res.text}")

    print("Starting simulation...")
    try:
        action_res = requests.post(
            f"{base_url}/simulations/{sim_id}/actions/",
            json={"name": "start"},
            headers=headers,
        )

        if action_res.status_code not in [200, 201]:
            print("Could not start simulation.")
            print(f"   Status Code: {action_res.status_code}")
            print(f"   Response: {action_res.text}")
            return None, None

    except Exception as exc:
        print(f"Start simulation connection error: {exc}")
        return None, None

    print("Simulation running...")
    is_success = False

    while True:
        try:
            status_data = requests.get(
                f"{base_url}/simulations/{sim_id}/status", headers=headers
            ).json()
            status = status_data["name"]

            if status == "finished":
                print("Simulation finished.")
                is_success = True
                break
            if status in ["crashed", "timeout", "shut_down"]:
                print(f"Simulation failed with status: {status}")
                return None, None

            time.sleep(10)
        except Exception:
            time.sleep(10)

    if is_success and future_saved_state_id:
        save_new_state(state_file_path, future_saved_state_id)
        return sim_id, future_saved_state_id

    if is_success:
        return sim_id, None

    return None, None


if __name__ == "__main__":
    run_forecast_process("flood_system_state.json")
