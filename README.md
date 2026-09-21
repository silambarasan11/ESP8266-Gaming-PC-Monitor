# ESP8266 PC Monitoring LCD

A real-time PC monitoring project that sends **CPU usage, GPU usage, FPS, and system time** from a Windows PC to an **ESP8266 NodeMCU**, then displays the values on a **16×2 I2C LCD**.

The project combines Python system monitoring, Wi-Fi/HTTP communication, ESP8266 web-server handling, and an I2C LCD.



<img width="1672" height="941" alt="image" src="https://github.com/user-attachments/assets/b3a557fa-3c04-4edc-a816-c7fe599a9e90" />


---

## Project Overview

```text
PC
 │
 ├── CPU Usage  ─────────┐
 ├── GPU Usage  ─────────┤
 ├── FPS (RTSS) ─────────┤
 └── System Time ────────┤
                         ▼
                Python Monitoring Script
                         │
                         │ HTTP GET /update
                         ▼
                  Wi-Fi Network
                         │
                         ▼
                  ESP8266 NodeMCU
                         │
                         │ I2C
                         ▼
                  16×2 I2C LCD
```

### LCD Output Format

The first row is formatted as:

```text
C 45  G 62 F144
```

The second row displays the current time centered:

```text
   03:58:42
```

---

## Hardware

- ESP8266 NodeMCU
- 16×2 LCD
- I2C LCD backpack/module
- Jumper wires
- USB power/programming connection for ESP8266

## Software

### ESP8266

- Arduino IDE
- `ESP8266WiFi.h`
- `ESP8266WebServer.h`
- `Wire.h`
- `LiquidCrystal_I2C.h`

### PC Monitoring

- Python 3
- `psutil`
- `requests`
- `pynvml`
- RTSS (RivaTuner Statistics Server) for FPS data

---

## Wiring

The project uses the LCD through its **I2C backpack**.

> Keep the physical pin positions and module arrangement consistent with the circuit diagram used for this project. Wires may be rerouted for a cleaner physical layout, but the electrical connections must remain the same.

### ESP8266 → I2C LCD

| ESP8266 Pin | I2C Module Pin | Function |
|---|---|---|
| GND | GND | Ground |
| 3V3 | VCC | Power |
| D2 | SDA | I2C Data |
| D1 | SCL | I2C Clock |

### I2C LCD Address

```text
0x27
```

### Important

The LCD is a **16×2 I2C display**, so only the four I2C backpack connections are required between the ESP8266 and the LCD module:

```text
GND
VCC
SDA
SCL
```

---

# ESP8266 Firmware

The ESP8266 connects to Wi-Fi using a static IP and provides an HTTP endpoint:

```text
/update
```

Parameters:

```text
C = CPU usage
G = GPU usage
F = FPS
T = Time
```

Example request:

```text
http://192.168.1.105/update?C=45&G=62&F=144&T=03:58:42
```

### ESP8266 Code

```cpp
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

const char* ssid = "Wifi name";
const char* password = "password";

IPAddress local_IP(192, 168, 1, 105);
IPAddress gateway(192, 168, 1, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns(8, 8, 8, 8);

LiquidCrystal_I2C lcd(0x27, 16, 2);
ESP8266WebServer server(80);

int cpu = 0;
int gpu = 0;
int fps = 0;

String timeValue = "00:00:00";

void updateDisplay() {
  lcd.clear();

  // Top row:
  // C 45  G 62 F144
  lcd.setCursor(0, 0);

  lcd.print("C ");
  lcd.print(cpu);

  lcd.print("  G ");
  lcd.print(gpu);

  lcd.print(" F");
  lcd.print(fps);

  // Bottom row: centered HH:MM:SS
  int startPos = (16 - timeValue.length()) / 2;

  lcd.setCursor(startPos, 1);
  lcd.print(timeValue);
}

void handleUpdate() {

  if (server.hasArg("C")) {
    cpu = server.arg("C").toInt();
  }

  if (server.hasArg("G")) {
    gpu = server.arg("G").toInt();
  }

  if (server.hasArg("F")) {
    fps = server.arg("F").toInt();
  }

  if (server.hasArg("T")) {
    timeValue = server.arg("T");
  }

  updateDisplay();

  server.send(200, "text/plain", "OK");
}

void handleRoot() {
  server.send(
    200,
    "text/plain",
    "ESP8266 MONITOR READY\n"
    "Use /update?C=45&G=62&F=144&T=03:58:42"
  );
}

void setup() {

  Serial.begin(115200);

  lcd.init();
  lcd.backlight();

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Connecting...");

  WiFi.config(local_IP, gateway, subnet, dns);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Ready");

  lcd.setCursor(0, 1);
  lcd.print("192.168.1.105");

  server.on("/", handleRoot);
  server.on("/update", handleUpdate);

  server.begin();

  Serial.println();
  Serial.println("ESP8266 Monitor Ready");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  server.handleClient();
}
```

---

# PC Monitoring Script

The PC-side Python program reads:

- CPU usage using `psutil`
- GPU usage using NVIDIA NVML / `pynvml`
- FPS using RTSS shared memory
- Current system time using Python `datetime`

It then sends the values to the ESP8266 every second.

## Python Dependencies

Install:

```bash
pip install psutil requests pynvml
```

RTSS must be running and actively hooking the target application/game for FPS data.

---

## PC → ESP8266 Data Flow

The Python script sends:

```text
C = CPU %
G = GPU %
F = FPS
T = HH:MM:SS
```

Using an HTTP GET request:

```python
http://192.168.1.105/update
```

Example:

```text
http://192.168.1.105/update?C=45&G=62&F=144&T=03:58:42
```

---

## Python Configuration

The monitoring script uses:

```python
ESP_IP = "192.168.1.105"
TARGET_PROCESS = ""
POLL_SECONDS = 1
REQUEST_TIMEOUT = 1.5
DEBUG = True
```

### Target Process

To monitor a specific process/game:

```python
TARGET_PROCESS = "cs2.exe"
```

Leave it empty to use the script's automatic selection logic.

---

## Python Code

```python
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
TARGET_PROCESS = ""       # e.g. "cs2.exe"
POLL_SECONDS = 1
REQUEST_TIMEOUT = 1.5
DEBUG = True
# -----------------------------------------

LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "pc_to_lcd.log"
)

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
    logging.warning(
        "NVML unavailable (%s) — GPU will read as 0.",
        e
    )


def read_gpu():
    if not NVML_OK:
        return 0

    try:
        return pynvml.nvmlDeviceGetUtilizationRates(
            _gpu_handle
        ).gpu

    except Exception as e:
        logging.warning("GPU read failed: %s", e)
        return 0


def read_cpu():
    return round(psutil.cpu_percent())


# ---------------- FPS (RTSS shared memory) ----------------

kernel32 = ctypes.windll.kernel32

FILE_MAP_READ = 0x0004
RTSS_MAP_NAME = "RTSSSharedMemoryV2"

HEADER_FMT = "<IIIIIIIII"
ENTRY_FMT = "<I260sIIIII"

ENTRY_SIZE = struct.calcsize(ENTRY_FMT)

FALLBACK_SIZE = 8192

kernel32.OpenFileMappingW.restype = ctypes.c_void_p
kernel32.OpenFileMappingW.argtypes = [
    ctypes.c_uint32,
    ctypes.c_int,
    ctypes.c_wchar_p
]

kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.MapViewOfFile.argtypes = [
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_size_t
]

kernel32.UnmapViewOfFile.restype = ctypes.c_int
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]

kernel32.CloseHandle.restype = ctypes.c_int
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

kernel32.VirtualQuery.restype = ctypes.c_size_t
kernel32.VirtualQuery.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t
]

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

    result = kernel32.VirtualQuery(
        ctypes.c_void_p(address),
        ctypes.byref(mbi),
        ctypes.sizeof(mbi)
    )

    return mbi.RegionSize if result else 0


_rtss_hmap = None
_rtss_pbuf = None
_rtss_size = 0


def _open_rtss():
    global _rtss_hmap, _rtss_pbuf, _rtss_size

    _close_rtss()

    hmap = kernel32.OpenFileMappingW(
        FILE_MAP_READ,
        False,
        RTSS_MAP_NAME
    )

    if not hmap:
        return False

    pbuf = kernel32.MapViewOfFile(
        hmap,
        FILE_MAP_READ,
        0,
        0,
        0
    )

    if not pbuf:
        kernel32.CloseHandle(hmap)
        return False

    size = _query_region_size(pbuf) or FALLBACK_SIZE

    _rtss_hmap = hmap
    _rtss_pbuf = pbuf
    _rtss_size = size

    return True


def _close_rtss():
    global _rtss_hmap, _rtss_pbuf, _rtss_size

    if _rtss_pbuf:
        kernel32.UnmapViewOfFile(_rtss_pbuf)

    if _rtss_hmap:
        kernel32.CloseHandle(_rtss_hmap)

    _rtss_hmap = None
    _rtss_pbuf = None
    _rtss_size = 0


atexit.register(_close_rtss)


def read_rtss_fps():
    global _rtss_pbuf

    if _rtss_pbuf is None:
        if not _open_rtss():
            return 0

    try:
        buf = ctypes.string_at(
            _rtss_pbuf,
            _rtss_size
        )

    except OSError:
        _close_rtss()
        return 0

    (
        _sig,
        _ver,
        app_entry_size,
        app_arr_offset,
        app_arr_size,
        *_rest
    ) = struct.unpack_from(
        HEADER_FMT,
        buf,
        0
    )

    if app_entry_size == 0 or app_arr_size == 0:
        _close_rtss()
        return 0

    best_fps = 0
    best_frames = -1

    for i in range(app_arr_size):
        offset = (
            app_arr_offset +
            i * app_entry_size
        )

        if offset + ENTRY_SIZE > len(buf):
            break

        (
            pid,
            raw_name,
            _flags,
            _t0,
            _t1,
            frames,
            frametime
        ) = struct.unpack_from(
            ENTRY_FMT,
            buf,
            offset
        )

        if pid == 0 or frametime == 0:
            continue

        name = raw_name.split(
            b"\x00",
            1
        )[0].decode(
            "mbcs",
            "ignore"
        )

        fps = round(
            1_000_000 / frametime
        )

        if TARGET_PROCESS:
            if TARGET_PROCESS.lower() in name.lower():
                return fps

        elif frames > best_frames:
            best_frames = frames
            best_fps = fps

    return best_fps


# ---------------- Push to ESP ----------------

_session = requests.Session()


def push_to_esp(cpu, gpu, fps):
    t = datetime.now().strftime("%H:%M:%S")

    try:
        _session.get(
            f"http://{ESP_IP}/update",
            params={
                "C": cpu,
                "G": gpu,
                "F": fps,
                "T": t
            },
            timeout=REQUEST_TIMEOUT
        )

        logging.info(
            "Sent -> C%s G%s F%s T%s",
            cpu,
            gpu,
            fps,
            t
        )

    except requests.RequestException as e:
        logging.warning(
            "ESP unreachable: %s",
            e
        )


if __name__ == "__main__":

    psutil.cpu_percent()

    logging.info(
        "Starting PC -> LCD bridge."
    )

    try:
        while True:

            start = time.monotonic()

            push_to_esp(
                read_cpu(),
                read_gpu(),
                read_rtss_fps()
            )

            elapsed = (
                time.monotonic() - start
            )

            time.sleep(
                max(
                    0.0,
                    POLL_SECONDS - elapsed
                )
            )

    except KeyboardInterrupt:
        logging.info(
            "Stopped by user."
        )
```

---

# Setup

## 1. Configure the ESP8266

Update:

```cpp
const char* ssid = "Wifi name";
const char* password = "password";
```

Make sure the Wi-Fi network uses the same LAN as the PC.

The configured ESP8266 address is:

```text
192.168.1.105
```

---

## 2. Upload the ESP8266 Firmware

Open the firmware in Arduino IDE and upload it to the NodeMCU ESP8266.

After booting, the LCD should show:

```text
Ready
192.168.1.105
```

---

## 3. Install Python Packages

```bash
pip install psutil requests pynvml
```

---

## 4. Start RTSS

Run RTSS and make sure its FPS overlay/shared-memory data is available for the application being monitored.

---

## 5. Run the PC Monitoring Script

```bash
python pc_to_lcd_optimized.py
```

The script polls the PC once per second and sends updated values to the ESP8266.

---

# Testing the ESP8266 Directly

Once the ESP8266 is connected to Wi-Fi, open:

```text
http://192.168.1.105/
```

The root endpoint returns:

```text
ESP8266 MONITOR READY
Use /update?C=45&G=62&F=144&T=03:58:42
```

You can test the LCD manually with:

```text
http://192.168.1.105/update?C=45&G=62&F=144&T=03:58:42
```

Expected LCD:

```text
C 45  G 62 F144
   03:58:42
```

---

# Troubleshooting

### LCD stays blank

Check:

```text
VCC
GND
SDA
SCL
```

Also verify the LCD backpack address is:

```text
0x27
```

### ESP8266 does not connect

Check the Wi-Fi SSID/password and confirm the static IP configuration does not conflict with another device.

### PC cannot reach the ESP8266

From the PC, test:

```bash
ping 192.168.1.105
```

Then open:

```text
http://192.168.1.105/
```

### GPU shows 0

Make sure NVIDIA NVML is available and that:

```bash
pip install pynvml
```

has been installed successfully.

### FPS shows 0

Make sure RTSS is running and actively providing FPS/application data.

---

# Features

- Real-time CPU monitoring
- Real-time GPU monitoring
- Real-time FPS monitoring
- Live system clock
- Wi-Fi communication
- HTTP-based data transfer
- 16×2 I2C LCD
- Static ESP8266 IP
- Lightweight one-second polling
- Python → ESP8266 → LCD pipeline

---

# Future Improvements

Possible extensions include:

- Custom LCD graphics and icons
- Temperature monitoring
- RAM utilization
- Network upload/download speed
- Disk usage
- Configurable refresh rate
- Web dashboard
- Multiple display pages
- MQTT support
- ESP8266 web configuration page

---

