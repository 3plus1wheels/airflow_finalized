import pytesseract
import cv2
import numpy as np
import requests
from datetime import datetime
import csv
import os
import boto3
from botocore.exceptions import ClientError
import re
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


# ===== Tesseract =====
pytesseract.pytesseract.tesseract_cmd = os.getenv(
    "TESSERACT_CMD",
    "/usr/bin/tesseract"
)

# ===== URLs =====
WATERLEVEL_URL = "https://thoatnuochanoi.vn/wt/"
RAIN_URL = "https://thoatnuochanoi.vn/rain/"

# ===== CSV files =====
WATERLEVEL_CSV = "water_levels.csv"
RAIN_CSV = "rain_levels.csv"

# ===== S3 / MinIO config =====
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "manholes-data")


# ===== init selenium =====
def init_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )


# ===== OCR image value =====
def ocr_value_from_image(src):
    response = requests.get(src, timeout=20)
    response.raise_for_status()

    img_array = np.frombuffer(response.content, np.uint8)
    image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    if image is None:
        return ""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    text = pytesseract.image_to_string(
        thresh,
        config="--psm 7 -c tessedit_char_whitelist=0123456789.,"
    )

    value = text.strip().replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", value)
    return match.group(0) if match else ""


def scrape_station_data(url, data_type):
    driver = init_driver()
    driver.get(url)
    time.sleep(8)

    stations = driver.find_elements(By.CSS_SELECTOR, ".border_item")
    data = []

    for station in stations:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            name = ""
            location = ""

            try:
                name = station.find_element(By.CSS_SELECTOR, ".tentram").text.strip()
            except Exception:
                pass

            try:
                location = station.find_element(By.CSS_SELECTOR, ".diach2").text.strip()
            except Exception:
                pass

            if not name:
                lines = [
                    line.strip()
                    for line in station.text.splitlines()
                    if line.strip()
                ]
                if len(lines) >= 1:
                    name = lines[0]
                if len(lines) >= 2:
                    location = lines[1]

            value = ""
            imgs = station.find_elements(By.CSS_SELECTOR, "img")
            for img in imgs:
                src = img.get_attribute("src")
                if src:
                    value = ocr_value_from_image(src)
                    if value:
                        break

            if not name and not location and not value:
                continue

            print(timestamp, data_type, name, location, value)

            data.append([
                timestamp,
                name,
                location,
                value
            ])

        except Exception as e:
            print(f"Error scraping {data_type}:", e)

    driver.quit()
    return data


# ===== scrape waterlevel =====
def scrape_water_levels():
    return scrape_station_data(WATERLEVEL_URL, "waterlevel")


# ===== scrape rain =====
def scrape_rain_levels():
    return scrape_station_data(RAIN_URL, "rain")


# ===== scrape both =====
def scrape_all_data():
    waterlevel_data = scrape_water_levels()
    rain_data = scrape_rain_levels()

    return {
        "waterlevel": waterlevel_data,
        "rain": rain_data
    }


# ===== save one csv =====
def save_one_csv(data, file_path, header):
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for row in data:
            if isinstance(row, (list, tuple)) and len(row) == 4:
                writer.writerow(row)

    print("Saved:", file_path)
    return file_path


# ===== save both csv =====
def save_all_csv(data):
    waterlevel_data = data.get("waterlevel", [])
    rain_data = data.get("rain", [])

    waterlevel_file = save_one_csv(
        waterlevel_data,
        WATERLEVEL_CSV,
        ["Time", "Station", "Location", "WaterLevel"]
    )

    rain_file = save_one_csv(
        rain_data,
        RAIN_CSV,
        ["Time", "Station", "Location", "Rain_mm"]
    )

    return {
        "waterlevel_file": waterlevel_file,
        "rain_file": rain_file
    }


# ===== create minio client =====
def get_minio_client():
    values = {
        "MINIO_ENDPOINT": MINIO_ENDPOINT,
        "MINIO_ACCESS_KEY": MINIO_ACCESS_KEY,
        "MINIO_SECRET_KEY": MINIO_SECRET_KEY,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required MinIO environment variables: {', '.join(missing)}")

    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
    )


# ===== ensure bucket =====
def ensure_bucket(s3_client):
    try:
        s3_client.head_bucket(Bucket=BUCKET_NAME)
    except ClientError:
        s3_client.create_bucket(Bucket=BUCKET_NAME)


# ===== upload both files to same timestamp folder =====
def upload_all_to_minio(files):
    s3_client = get_minio_client()
    ensure_bucket(s3_client)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = timestamp_str

    uploaded_objects = {}

    waterlevel_file = files.get("waterlevel_file")
    rain_file = files.get("rain_file")

    if waterlevel_file:
        waterlevel_object = f"{folder_name}/waterlevel_{timestamp_str}.csv"

        s3_client.upload_file(
            waterlevel_file,
            BUCKET_NAME,
            waterlevel_object,
            ExtraArgs={"ContentType": "text/csv"}
        )

        uploaded_objects["waterlevel"] = waterlevel_object
        print("Uploaded:", waterlevel_object)

    if rain_file:
        rain_object = f"{folder_name}/rain_{timestamp_str}.csv"

        s3_client.upload_file(
            rain_file,
            BUCKET_NAME,
            rain_object,
            ExtraArgs={"ContentType": "text/csv"}
        )

        uploaded_objects["rain"] = rain_object
        print("Uploaded:", rain_object)

    return uploaded_objects


# ===== full pipeline =====
def run_pipeline():
    data = scrape_all_data()
    files = save_all_csv(data)
    uploaded = upload_all_to_minio(files)
    return uploaded


if __name__ == "__main__":
    run_pipeline()
