# Copyright 2026 Dorsal Hub LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import datetime
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

try:
    from dorsal.file.utils.file_hasher import FileHasher
except ImportError as e:
    print(f"Error importing Dorsal FileHasher: {e}", file=sys.stderr)
    sys.exit(1)


def get_cpu_info() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                return val.strip()
        except Exception:
            pass
    elif platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":")[1].strip()
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        except Exception:
            pass
    return platform.processor() or "Unknown CPU"


def get_disk_info(target_dir: Path) -> str:
    if platform.system() == "Windows":
        try:
            drive = target_dir.resolve().drive.replace(":", "")
            if drive:
                ps_cmd = (
                    f"$d = Get-Disk (Get-Partition -DriveLetter '{drive}').DiskNumber; "
                    f'Write-Output "$($d.Model) ($($d.MediaType), $($d.BusType))"'
                )
                out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps_cmd], text=True).strip()
                if out:
                    return out
        except Exception:
            pass
    elif platform.system() == "Linux":
        try:
            df_out = subprocess.check_output(["df", "-P", str(target_dir)], text=True).splitlines()
            if len(df_out) > 1:
                device = df_out[1].split()[0]
                if device.startswith("/dev/"):
                    pkname = subprocess.check_output(["lsblk", "-no", "pkname", device], text=True).strip()
                    base_dev = pkname if pkname else device.split("/")[-1]
                    model = subprocess.check_output(
                        ["lsblk", "-nd", "-o", "MODEL", f"/dev/{base_dev}"], text=True
                    ).strip()
                    rota = subprocess.check_output(
                        ["lsblk", "-nd", "-o", "ROTA", f"/dev/{base_dev}"], text=True
                    ).strip()
                    tran = subprocess.check_output(
                        ["lsblk", "-nd", "-o", "TRAN", f"/dev/{base_dev}"], text=True
                    ).strip()
                    disk_type = "HDD" if rota == "1" else "SSD" if rota == "0" else "Unknown MediaType"
                    return f"{model} ({disk_type}, {tran})".strip()
        except Exception:
            pass
    return "Unknown Disk Information"


def find_files(target_dir: Path):
    """Yields absolute paths to files, ignoring symlinks and unreadable items."""
    for root, _, files in os.walk(target_dir):
        for file in files:
            file_path = Path(root) / file
            if file_path.is_symlink() or not file_path.is_file():
                continue
            try:
                size = file_path.stat().st_size
                if size > 0:
                    yield file_path, size
            except OSError:
                continue


def run_benchmark(target_dir: Path, cap_gb: float, threads: int | None) -> None:
    cap_bytes = cap_gb * 1024**3
    hasher = FileHasher()

    print("=" * 80)
    print(" DORSAL DISK I/O & HASHING BENCHMARK")
    print("=" * 80)
    print(f"Timestamp        : {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print(f"Target Directory : {target_dir.resolve()}")
    print(f"Disk Info        : {get_disk_info(target_dir)}")
    print(f"Python Version   : {platform.python_version()}")
    print(f"CPU              : {get_cpu_info()}")
    print(f"Thread Limit     : {'Auto-detect' if threads is None else threads}")
    print(f"Data Cap         : {cap_gb} GB")
    print("=" * 80 + "\n")

    total_bytes = 0
    total_hash_time = 0.0
    files_processed = 0

    print(f"Scanning '{target_dir}' and hashing files...\n")

    start_wall_time = time.perf_counter()

    for file_path, size_bytes in find_files(target_dir):
        if total_bytes >= cap_bytes:
            break

        try:
            t0 = time.perf_counter()

            hasher.hash(str(file_path), file_size=size_bytes, threads=threads)
            t1 = time.perf_counter()

            total_hash_time += t1 - t0
            total_bytes += size_bytes
            files_processed += 1

            if files_processed % 100 == 0 or size_bytes > 1024**3:
                processed_gb = total_bytes / (1024**3)
                print(f"Progress: {processed_gb:.2f} GB / {cap_gb} GB processed...", end="\r")

        except (PermissionError, OSError):
            continue

    total_wall_time = time.perf_counter() - start_wall_time
    print(" " * 60 + "\r", end="")

    if files_processed == 0:
        print("No files were processed. Ensure the directory contains readable files.")
        return

    data_gb = total_bytes / (1024**3)
    data_mb = total_bytes / (1024**2)
    avg_speed_mb = data_mb / total_hash_time if total_hash_time > 0 else 0
    fs_overhead = total_wall_time - total_hash_time

    print("--- BENCHMARK RESULTS ---")
    print(f"Files Processed  : {files_processed:,}")
    print(f"Data Processed   : {data_gb:.2f} GB")
    print(f"Pure Hash Time   : {total_hash_time:.2f} seconds")
    print(f"OS Walk Overhead : {fs_overhead:.2f} seconds")
    print(f"Total Wall Time  : {total_wall_time:.2f} seconds")
    print(f"Hashing Speed    : {avg_speed_mb:.2f} MB/s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone benchmark for Dorsal unified FileHasher.")
    parser.add_argument("target_dir", type=Path, help="The root directory containing real files to hash.")
    parser.add_argument("--cap", type=float, default=50.0, help="Maximum total data to hash in GB (default: 50.0)")
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="Max worker threads to use. Omit to auto-detect based on cores/algorithms. Set to 1 to force synchronous mode.",
    )
    args = parser.parse_args()

    if not args.target_dir.exists() or not args.target_dir.is_dir():
        print(f"Error: Target directory '{args.target_dir}' does not exist or is not a directory.")
        sys.exit(1)

    run_benchmark(target_dir=args.target_dir, cap_gb=args.cap, threads=args.threads)
