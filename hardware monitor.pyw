"""
Optimized PC -> ESP8266 LCD bridge.
Reads CPU (psutil), GPU (NVML), and FPS (RTSS shared memory) and pushes to your NodeMCU.

Requirements:
  pip install psutil requests pynvml
  RTSS running and actively hooking your game (check its OSD is visible)

Run:
  python pc_to_lcd_optimized.py
"""

import atexit
import ctypes
import logging
import os
import struct
import time
from datetime import datetime

import psutil
import requests

# ---------------- CONFIG ----------------
ESP_IP = "192.168.1.105"
TARGET_PROCESS = ""       # e.g. "cs2.exe" — leave "" to auto-pick the busiest process
POLL_SECONDS = 1
REQUEST_TIMEOUT = 1.5
DEBUG = True
# -----------------------------------------

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_to_lcd.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------- GPU (NVML) ----------------
try:
    import pynvml
    pynvml.nvmlInit()
    _gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    atexit.register(pynvml.nvmlShutdown)
    NVML_OK = True
    logging.info("NVML initialized for GPU readings.")
except Exception as e:
    NVML_OK = False
    logging.warning("NVML unavailable (%s) — GPU will read as 0. Run: pip install pynvml", e)


def read_gpu():
    if not NVML_OK:
        return 0
    try:
        return pynvml.nvmlDeviceGetUtilizationRates(_gpu_handle).gpu
    except Exception as e:
        logging.warning("NVML read failed: %s", e)
        return 0


def read_cpu():
    return round(psutil.cpu_percent())


# ---------------- FPS (RTSS shared memory, persistent handle) ----------------
kernel32 = ctypes.windll.kernel32
FILE_MAP_READ = 0x0004
RTSS_MAP_NAME = "RTSSSharedMemoryV2"
HEADER_FMT = "<IIIIIIIII"
ENTRY_FMT = "<I260sIIIII"
ENTRY_SIZE = struct.calcsize(ENTRY_FMT)
FALLBACK_SIZE = 8192  # used only if VirtualQuery fails

# Explicit 64-bit-safe signatures — without these, ctypes assumes 32-bit return
# values and silently truncates pointers on 64-bit Windows, corrupting addresses.
kernel32.OpenFileMappingW.restype = ctypes.c_void_p
kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]

kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.MapViewOfFile.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t
]

kernel32.UnmapViewOfFile.restype = ctypes.c_int
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]

kernel32.CloseHandle.restype = ctypes.c_int
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

kernel32.VirtualQuery.restype = ctypes.c_size_t
kernel32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]

kernel32.GetLastError.restype = ctypes.c_uint32


class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_ulong),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
    ]


def _query_region_size(address):
    mbi = _MEMORY_BASIC_INFORMATION()
    result = kernel32.VirtualQuery(ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi))
    return mbi.RegionSize if result else 0


_rtss_hmap = None
_rtss_pbuf = None
_rtss_size = 0


def _open_rtss():
    global _rtss_hmap, _rtss_pbuf, _rtss_size
    _close_rtss()
    hmap = kernel32.OpenFileMappingW(FILE_MAP_READ, False, RTSS_MAP_NAME)
    if not hmap:
        logging.debug("RTSS shared memory not available (err %s)", kernel32.GetLastError())
        return False
    # size=0 maps the entire section as created by RTSS, instead of guessing a fixed size
    pbuf = kernel32.MapViewOfFile(hmap, FILE_MAP_READ, 0, 0, 0)
    if not pbuf:
        kernel32.CloseHandle(hmap)
        logging.debug("Failed to map RTSS view (err %s)", kernel32.GetLastError())
        return False
    size = _query_region_size(pbuf) or FALLBACK_SIZE
    _rtss_hmap, _rtss_pbuf, _rtss_size = hmap, pbuf, size
    logging.info("RTSS shared memory mapped (%d bytes).", size)
    return True


def _close_rtss():
    global _rtss_hmap, _rtss_pbuf, _rtss_size
    if _rtss_pbuf:
        kernel32.UnmapViewOfFile(_rtss_pbuf)
    if _rtss_hmap:
        kernel32.CloseHandle(_rtss_hmap)
    _rtss_hmap, _rtss_pbuf, _rtss_size = None, None, 0


atexit.register(_close_rtss)


def read_rtss_fps():
    global _rtss_pbuf
    if _rtss_pbuf is None:
        if not _open_rtss():
            return 0

    try:
        buf = ctypes.string_at(_rtss_pbuf, _rtss_size)
    except OSError as e:
        logging.warning("RTSS memory read failed (%s) — will reopen next cycle.", e)
        _close_rtss()
        return 0

    (_sig, _ver, app_entry_size, app_arr_offset, app_arr_size,
     *_rest) = struct.unpack_from(HEADER_FMT, buf, 0)

    if app_entry_size == 0 or app_arr_size == 0:
        # Stale/invalid mapping (e.g. RTSS restarted) — reopen next call
        _close_rtss()
        return 0

    best_fps, best_frames = 0, -1
    for i in range(app_arr_size):
        offset = app_arr_offset + i * app_entry_size
        if offset + ENTRY_SIZE > len(buf):
            break
        pid, raw_name, _flags, _t0, _t1, frames, frametime = struct.unpack_from(ENTRY_FMT, buf, offset)
        if pid == 0 or frametime == 0:
            continue
        name = raw_name.split(b"\x00", 1)[0].decode("mbcs", "ignore")
        fps = round(1_000_000 / frametime)

        if DEBUG:
            logging.debug("RTSS entry: pid=%s name=%s frames=%s fps=%s", pid, name, frames, fps)

        if TARGET_PROCESS:
            if TARGET_PROCESS.lower() in name.lower():
                return fps
        elif frames > best_frames:
            best_frames, best_fps = frames, fps

    return best_fps


# ---------------- Push to ESP ----------------
_session = requests.Session()


def push_to_esp(cpu, gpu, fps):
    t = datetime.now().strftime("%H:%M:%S")
    try:
        _session.get(
            f"http://{ESP_IP}/update",
            params={"C": cpu, "G": gpu, "F": fps, "T": t},
            timeout=REQUEST_TIMEOUT,
        )
        logging.info("Sent -> C%s G%s F%s T%s", cpu, gpu, fps, t)
    except requests.RequestException as e:
        logging.warning("ESP unreachable: %s", e)


if __name__ == "__main__":
    psutil.cpu_percent()  # warm up (first call always returns 0)
    logging.info("Starting optimized PC -> LCD bridge.")
    try:
        while True:
            start = time.monotonic()
            push_to_esp(read_cpu(), read_gpu(), read_rtss_fps())
            elapsed = time.monotonic() - start
            time.sleep(max(0.0, POLL_SECONDS - elapsed))
    except KeyboardInterrupt:
        logging.info("Stopped by user.")
