import json
import os
import shutil
import tarfile
import tempfile
import sys
from pathlib import Path
from urllib.request import urlopen, urlretrieve

REPO = "LagrangeDev/Lagrange.Core"
LAGRANGE_DIR = Path("/app/lagrange")
BIN = LAGRANGE_DIR / "Lagrange.OneBot"


def get_latest_release():
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    with urlopen(url) as r:
        data = json.loads(r.read().decode())
    return data["tag_name"], data["assets"]


def download_asset(assets):
    for a in assets:
        name = a["name"]
        url = a["browser_download_url"]
        is_linux = "linux" in name.lower()
        is_x64 = "x64" in name or "x86_64" in name
        if not (is_linux and is_x64):
            continue
        if name.endswith(".tar.gz"):
            print(f"[dl] Downloading {name}...")
            tmp = tempfile.mktemp(suffix=".tar.gz")
            try:
                urlretrieve(url, tmp)
                with tarfile.open(tmp, "r:gz") as t:
                    t.extractall(path=LAGRANGE_DIR)
                for f in LAGRANGE_DIR.rglob("Lagrange.OneBot*"):
                    if f.is_file():
                        shutil.copy2(f, BIN)
                        break
            finally:
                Path(tmp).unlink(missing_ok=True)
            return True
        elif not any(name.endswith(s) for s in (".zip", ".md5", ".sha256", ".sig")):
            print(f"[dl] Downloading {name}...")
            urlretrieve(url, BIN)
            return True
    return False


def main():
    LAGRANGE_DIR.mkdir(parents=True, exist_ok=True)
    if BIN.exists():
        import subprocess
        r = subprocess.run(["file", str(BIN)], capture_output=True, text=True)
        if "ELF" in r.stdout:
            print("[dl] Lagrange.OneBot already exists, skipping")
            return
        print("[dl] Existing file is invalid, re-downloading...")
        BIN.unlink()

    try:
        tag, assets = get_latest_release()
        print(f"[dl] Latest release: {tag}")
    except Exception as e:
        print(f"[dl] Failed to fetch release info: {e}", file=sys.stderr)
        sys.exit(1)

    if not download_asset(assets):
        print("[dl] No matching linux-x64 asset found", file=sys.stderr)
        sys.exit(1)

    if not BIN.exists():
        print("[dl] Binary not found after extraction", file=sys.stderr)
        sys.exit(1)

    BIN.chmod(0o755)
    print(f"[dl] Lagrange.OneBot ready ({BIN.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
