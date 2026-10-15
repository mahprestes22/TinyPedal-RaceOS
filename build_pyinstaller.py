"""
PyInstaller build script for TinyPedal-RaceOS
"""

import os
import shutil
import subprocess
import sys
import zipfile

from tinypedal.constant import APP, FILE

BUILD_NAME = "TinyPedal"
VERSION_TAG = f"v{APP.VERSION}-raceos.1"
DIST_DIR = os.path.abspath("dist")
APP_DIR = os.path.join(DIST_DIR, BUILD_NAME)
ZIP_NAME = f"TinyPedal-RaceOS-{VERSION_TAG}-windows.zip"
ZIP_PATH = os.path.join(DIST_DIR, ZIP_NAME)


def clean_old():
    print(f"[*] Cleaning old build artifacts...")
    for folder in ["build", os.path.join("dist", BUILD_NAME)]:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
                print(f"    Removed: {folder}")
            except Exception as e:
                print(f"    Warning: Could not remove {folder}: {e}")
    spec_file = f"{BUILD_NAME}.spec"
    if os.path.exists(spec_file):
        os.remove(spec_file)


def run_pyinstaller():
    print(f"[*] Starting PyInstaller build for {BUILD_NAME}...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        f"--name={BUILD_NAME}",
        f"--icon={FILE.IMAGE_ICON}",
        "--paths=.",
        "--paths=thirdparty",
        "--hidden-import=PySide6",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=PySide6.QtMultimedia",
        "--hidden-import=requests",
        "--hidden-import=psutil",
        "--collect-submodules=tinypedal",
        "--collect-submodules=pyLMUSharedMemory",
        "--collect-submodules=pyACCSharedMemory",
        "--collect-submodules=pyRfactor2SharedMemory",
        "run.py",
    ]
    print("    Command:", " ".join(cmd))
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"[!] PyInstaller failed with code {res.returncode}")
        sys.exit(res.returncode)
    print(f"[+] PyInstaller build complete.")


def copy_runtime_assets():
    print(f"[*] Copying runtime assets into {APP_DIR}...")
    asset_dirs = [
        "images",
        "docs",
        "settings",
        "brandlogo",
        "carsetups",
        "deltabest",
        "pacenotes",
        "trackmap",
        "tracknotes",
    ]
    for d in asset_dirs:
        src = os.path.abspath(d)
        dst = os.path.join(APP_DIR, d)
        if os.path.exists(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"    Copied directory: {d}")

    asset_files = [
        "LICENSE.txt",
        "README.md",
        "Atualizar_TinyPedal.bat",
    ]
    for f in asset_files:
        src = os.path.abspath(f)
        dst = os.path.join(APP_DIR, f)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"    Copied file: {f}")


def create_release_zip():
    print(f"[*] Creating release archive: {ZIP_NAME}...")
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(APP_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, DIST_DIR)
                zipf.write(file_path, rel_path)

    zip_size_mb = os.path.getsize(ZIP_PATH) / (1024 * 1024)
    print(f"[+] Release archive created: {ZIP_PATH} ({zip_size_mb:.2f} MB)")


def main():
    clean_old()
    run_pyinstaller()
    copy_runtime_assets()
    create_release_zip()
    print("\n" + "=" * 60)
    print(f"[SUCCESS] Standalone build complete!")
    print(f"Directory: {APP_DIR}")
    print(f"Executable: {os.path.join(APP_DIR, 'TinyPedal.exe')}")
    print(f"Release ZIP: {ZIP_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
