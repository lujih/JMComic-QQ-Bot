import json
import shutil
import tarfile
import tempfile
import sys
from pathlib import Path
from urllib.request import urlopen, urlretrieve

REPO = "LagrangeDev/Lagrange.Core"
LAGRANGE_DIR = Path("/app/lagrange")
BIN = LAGRANGE_DIR / "Lagrange.OneBot"

# 仓库已归档，只有 nightly prerelease，无法用 /releases/latest
NIGHTLY_TAG = "nightly"
FALLBACK_URL = (
    "https://github.com/LagrangeDev/Lagrange.Core/releases/download/"
    f"{NIGHTLY_TAG}/Lagrange.OneBot_linux-x64_net9.0_SelfContained.tar.gz"
)


def get_first_release():
    url = f"https://api.github.com/repos/{REPO}/releases?per_page=1"
    with urlopen(url) as r:
        data = json.loads(r.read().decode())
    if data:
        tag = data[0]["tag_name"]
        assets = data[0]["assets"]
        return tag, assets
    return None, []


def download_asset(assets):
    for a in assets:
        name = a["name"]
        url = a["browser_download_url"]
        sl = name.lower()
        is_linux = "linux" in sl
        is_x64 = "x64" in sl or "x86_64" in sl
        if not (is_linux and is_x64):
            continue
        if name.endswith((".tar.gz", ".tgz")):
            print(f"[dl] Downloading {name}...")
            tmp = tempfile.mktemp(suffix=".tar.gz")
            try:
                urlretrieve(url, tmp)
                with tarfile.open(tmp, "r:gz") as t:
                    t.extractall(path=LAGRANGE_DIR)
                for f in LAGRANGE_DIR.rglob("Lagrange.OneBot"):
                    if f.is_file():
                        shutil.copy2(f, BIN)
                        break
                for f in LAGRANGE_DIR.rglob("Lagrange.OneBot*"):
                    if f.is_file() and f.suffix not in (".tar.gz", ".tgz"):
                        shutil.copy2(f, BIN)
                        break
            finally:
                Path(tmp).unlink(missing_ok=True)
            return BIN.exists()
        if any(name.endswith(s) for s in (".zip", ".md5", ".sha256", ".sig", ".json")):
            continue
        print(f"[dl] Downloading {name}...")
        urlretrieve(url, BIN)
        return BIN.exists()
    return False


def download_fallback():
    print(f"[dl] Fallback: downloading nightly...")
    tmp = tempfile.mktemp(suffix=".tar.gz")
    try:
        urlretrieve(FALLBACK_URL, tmp)
        with tarfile.open(tmp, "r:gz") as t:
            t.extractall(path=LAGRANGE_DIR)
        for f in LAGRANGE_DIR.rglob("Lagrange.OneBot"):
            if f.is_file():
                shutil.copy2(f, BIN)
                break
    finally:
        Path(tmp).unlink(missing_ok=True)
    return BIN.exists()


def main():
    LAGRANGE_DIR.mkdir(parents=True, exist_ok=True)

    if BIN.exists():
        import subprocess
        r = subprocess.run(["file", str(BIN)], capture_output=True, text=True)
        if "ELF" in r.stdout:
            print("[dl] Lagrange.OneBot already exists, skipping")
            return
        BIN.unlink()

    try:
        tag, assets = get_first_release()
        if tag:
            print(f"[dl] Found release: {tag}")
            if download_asset(assets):
                BIN.chmod(0o755)
                print(f"[dl] Lagrange.OneBot ready ({BIN.stat().st_size} bytes)")
                return
    except Exception as e:
        print(f"[dl] API error: {e}")

    print("[dl] API failed, trying fallback URL...")
    if download_fallback():
        BIN.chmod(0o755)
        print(f"[dl] Lagrange.OneBot ready ({BIN.stat().st_size} bytes)")
        return

    print("[dl] All download methods failed", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
