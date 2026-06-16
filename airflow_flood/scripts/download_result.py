import requests
import os
import fiona
import fiona.vfs

if not hasattr(fiona, 'path'):
    fiona.path = fiona.vfs


THREEDI_API_KEY = os.getenv("THREEDI_API_KEY")


def get_real_download_link(sim_id):
    headers = {"Authorization": THREEDI_API_KEY, "Content-Type": "application/json"}
    list_url = f"https://api.3di.live/v3/simulations/{sim_id}/results/files/"

    try:
        res = requests.get(list_url, headers=headers)
        res.raise_for_status()

        target_item = None
        for item in res.json().get("results", []):
            if item.get("filename", "").endswith(".nc"):
                target_item = item
                break

        if not target_item:
            return None, None

        file_meta_url = target_item["file"]["url"]
        res_meta = requests.get(file_meta_url, headers=headers)
        related_object_url = res_meta.json().get("related_object")

        if related_object_url:
            download_api_url = related_object_url.rstrip("/") + "/download/"
            res_dl = requests.get(download_api_url, headers=headers)
            return res_dl.json().get("get_url"), target_item["filename"]
    except Exception as e:
        print(f"❌ Error getting link: {e}")
        return None, None
    return None, None


def download_file(url, output_dir, filename):
    os.makedirs(output_dir, exist_ok=True)
    local_path = os.path.join(output_dir, filename)

    print(f"⬇️ Downloading to {local_path}...")
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return local_path
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return None


def run_download(sim_id, output_dir):
    link, filename = get_real_download_link(sim_id)
    if link:
        return download_file(link, output_dir, filename)
    else:
        print(f"❌ Could not find valid results for Sim {sim_id}")
        return None
