"""Download the VSCO 2 CE samples this kit uses and check them.

The list of files and their git blob hashes is pinned in
data/vsco2-lock.json, so every download is checked against a known file.
"""

import concurrent.futures as cf
import hashlib
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from .instruments import needed_paths
from .paths import ROOT, SAMPLES

REPO = "sgossner/VSCO-2-CE"
LOCK = ROOT / "data" / "vsco2-lock.json"
UA = "loop-bgm-kit/0.1"


def git_blob_sha(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def make_lock(tree_json: Path, commit: str):
    """Build the lock file from a saved GitHub tree listing (developer use)."""
    tree = json.loads(Path(tree_json).read_text(encoding="utf-8"))
    blobs = {x["path"]: x for x in tree["tree"] if x["type"] == "blob"}
    paths = needed_paths(list(blobs))
    files = [{"path": p, "sha": blobs[p]["sha"], "size": blobs[p]["size"]} for p in paths]
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({"repo": REPO, "commit": commit, "files": files}, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    print(f"lock: {len(files)} files, {sum(f['size'] for f in files) / 1e6:.0f} MB")


def load_lock():
    return json.loads(LOCK.read_text(encoding="utf-8"))


def local_path(repo_path: str) -> Path:
    return SAMPLES / "vsco2" / repo_path


def _download(url: str, dest: Path, sha: str, retries=3):
    # curl is used instead of urllib: on some Windows setups urllib stalls for a
    # minute per request (proxy / IPv6 lookup), while curl ships with Windows 10+.
    last = None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(retries):
        try:
            r = subprocess.run(["curl", "-sSfL", "--retry", "2", "-A", UA, "-o", str(tmp), url],
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip()[:200])
            data = tmp.read_bytes()
            if git_blob_sha(data) != sha:
                raise ValueError("hash mismatch")
            tmp.replace(dest)
            return len(data)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f"{dest.name}: {last}")


def status(names=None):
    """Return (missing, total) file entries for the given instruments."""
    lock = load_lock()
    files = lock["files"]
    if names:
        want = set(needed_paths([f["path"] for f in files], names))
        files = [f for f in files if f["path"] in want]
    missing = [f for f in files if not local_path(f["path"]).exists()]
    return missing, files


def fetch(names=None, verify=False, workers=8):
    lock = load_lock()
    missing, files = status(names)
    if verify:
        bad = []
        for f in files:
            p = local_path(f["path"])
            if p.exists() and git_blob_sha(p.read_bytes()) != f["sha"]:
                bad.append(f)
        if bad:
            print(f"壊れているファイル {len(bad)} 件を取り直します")
            for f in bad:
                local_path(f["path"]).unlink()
            missing += bad
    if not missing:
        print(f"音源はそろっています（{len(files)} ファイル）")
        return True
    total = sum(f["size"] for f in missing)
    print(f"音源をダウンロードします: {len(missing)} ファイル, {total / 1e6:.0f} MB")
    base = f"https://raw.githubusercontent.com/{lock['repo']}/{lock['commit']}/"
    done = 0
    got = 0
    errors = []
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(_download, base + urllib.parse.quote(f["path"]), local_path(f["path"]), f["sha"]): f
                for f in missing}
        for fut in cf.as_completed(futs):
            done += 1
            try:
                got += fut.result()
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
            if done % 50 == 0 or done == len(missing):
                print(f"  {done}/{len(missing)}  {got / 1e6:.0f} MB", flush=True)
    if errors:
        print(f"失敗 {len(errors)} 件（もう一度実行すると続きから取ります）:", *errors[:5], sep="\n  ")
        return False
    print("ダウンロード完了。すべてハッシュ一致")
    return True


if __name__ == "__main__":
    if sys.argv[1:2] == ["lock"]:
        make_lock(Path(sys.argv[2]), sys.argv[3])
