"""Download Alibaba spot GPU traces and GPUCloudCompare pricing snapshots."""
import concurrent.futures
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent / "data"


def get(url):
    return urlopen(Request(url, headers={"User-Agent": "htb26-dataset-download"}), timeout=120)


def download(folder, name, url, size=None):
    target = ROOT / folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    with get(url) as response, partial.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    actual = partial.stat().st_size
    if size is not None and actual != size:
        raise ValueError(f"Size mismatch for {name}: {actual} != {size}")
    partial.replace(target)
    return {"file": name, "url": url, "bytes": actual, "sha256": digest.hexdigest()}


def main():
    api = "https://api.github.com/repos/alibaba/clusterdata/contents/cluster-trace-v2026-spot-gpu"
    with get(api) as response:
        entries = json.load(response)
    tasks = [("alibaba-2026-spot-gpu", entry["name"], entry["download_url"], entry["size"])
             for entry in entries if entry["type"] == "file"]
    tasks += [("gpucloudcompare", name, "https://gpucloudcompare.com/data/" + name, None)
              for name in ("current.json", "current.csv", "history-daily.json")]
    manifests = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [(task[0], pool.submit(download, *task)) for task in tasks]
        for folder, future in futures:
            item = future.result()
            manifests.setdefault(folder, []).append(item)
            print(f"Downloaded {folder}/{item['file']}: {item['bytes']} bytes", flush=True)
    for folder, files in manifests.items():
        metadata = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "files": files}
        if folder == "gpucloudcompare":
            metadata.update(source="https://gpucloudcompare.com/data/", license="CC-BY-4.0",
                            attribution="Source: GPU Cloud Price Index — gpucloudcompare.com (CC-BY 4.0)")
        (ROOT / folder / "download-manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
