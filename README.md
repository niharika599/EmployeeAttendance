# Face Recognition Door System

An automatic door access and employee attendance system using face recognition. A live camera identifies employees in real time, marks attendance automatically, and enforces access control — including a 60-day notice period when an employee resigns. Built with Flask + OpenCV + face-recognition (CNN/HOG).

---

## How It Works

1. **Register an employee** via `POST /employees` with their details and a face photo
2. The face is encoded (128-float CNN vector) and stored in the allowed set
3. A **background camera process** reads frames every 0.5 s, recognises faces, and auto-marks attendance
4. **Attendance** is recorded once per person per 5-minute window — no manual check-in needed
5. When an employee **resigns**, a 60-day notice period begins — access is revoked automatically after it ends

---

## Project Structure

```
faceRecognition/
├── main.py               # Flask app + all API routes + background threads
├── face_store.py         # Face encoding storage        → faces_db.json
├── employee_store.py     # Employee lifecycle management → employees_db.json
├── attendance_store.py   # Attendance records            → attendance_db.json
├── camera_worker.py      # Background camera thread + recognition loop
├── requirements.txt      # Python dependencies
├── README.md
└── ARCHITECTURE.md
```

---

## Setup on a Laptop

### Prerequisites
- Python 3.8+
- Built-in or USB webcam
- Windows / macOS / Linux

### 1. Install system dependencies

**Windows**
```bash
pip install cmake
```

**Ubuntu / Debian / WSL**
```bash
sudo apt update
sudo apt install cmake build-essential libopenblas-dev liblapack-dev
```

**macOS**
```bash
brew install cmake
```

### 2. Install Python packages
```bash
cd faceRecognition
pip install -r requirements.txt
```

> **Note:** `dlib` compilation takes a few minutes on first install.

### 3. Run the server
```bash
python main.py
```

### 4. Test the API
Use curl, Postman, or any HTTP client:
```
http://localhost:8000
```

### Camera index
The default camera is `0` (built-in webcam). Change it in `main.py` if needed:
```python
camera = CameraWorker(store, attendance=attendance, camera_index=1)
```

---

## Setup on Raspberry Pi

### Prerequisites
- Raspberry Pi 3B+ or newer (Pi 4 recommended)
- Raspberry Pi OS (64-bit recommended)
- USB webcam or Raspberry Pi Camera Module

### 1. Update the system
```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Install system dependencies
```bash
sudo apt install -y python3-pip cmake build-essential \
    libopenblas-dev liblapack-dev libatlas-base-dev \
    python3-opencv libhdf5-dev
```

### 3. Install Python packages
```bash
cd faceRecognition
pip3 install -r requirements.txt
```

> **Note:** `dlib` compilation on Raspberry Pi takes 10–30 minutes. This is normal.

### 4. Pi Camera Module (if not using USB webcam)
```bash
sudo raspi-config
# Interface Options → Camera → Enable
sudo reboot
pip3 install opencv-python-headless
```

### 5. Run the server
```bash
python main.py
```

Access from any device on the same network:
```
http://<raspberry-pi-ip>:8000
```

### Run on startup (optional)
```bash
sudo nano /etc/systemd/system/facedoor.service
```
```ini
[Unit]
Description=Face Recognition Door System
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/faceRecognition
ExecStart=python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable facedoor
sudo systemctl start facedoor
```

---

## API Reference

### Employee Management

#### Register a new employee
```
POST /employees
Content-Type: multipart/form-data

employee_id  : EMP001              (required)
name         : Niharika Pyla       (required)
image        : photo.jpg           (required — clear, front-facing)
email        : n@company.com       (optional)
department   : Engineering         (optional)
phone        : +91-9999999999      (optional)
designation  : Senior SWE          (optional)
```
```json
{
  "employee_id": "EMP001",
  "name": "Niharika Pyla",
  "email": "n@company.com",
  "department": "Engineering",
  "phone": "+91-9999999999",
  "designation": "Senior SWE",
  "face_id": "uuid...",
  "face_encoding_size": 128,
  "status": "active",
  "joined_at": "2026-06-02T10:00:00"
}
```

#### List employees
```
GET /employees                     ← all employees
GET /employees?status=active       ← active only
GET /employees?status=notice_period
GET /employees?status=resigned
```

#### Get one employee
```
GET /employees/{employee_id}
```

#### Resign an employee (starts 60-day notice period)
```
POST /employees/{employee_id}/resign
```
```json
{
  "message": "Niharika Pyla resignation recorded. Face access will be revoked on 2026-08-01.",
  "employee": {
    "status": "notice_period",
    "resigned_at": "2026-06-02T...",
    "notice_ends_at": "2026-08-01T...",
    ...
  }
}
```
> Face access is **not removed immediately** — the employee retains access and attendance continues to be marked during the notice period. Access is revoked automatically after 60 days.

---

### Face Utilities

#### List all registered faces
```
GET /faces
```
```json
{
  "uuid...": { "id": "uuid...", "name": "Niharika Pyla", "employee_id": "EMP001" }
}
```

#### Delete a face directly
```
DELETE /faces/{face_id}
```
> Prefer `POST /employees/:id/resign` for employee offboarding. Use this only for direct face management.

---

### Validate an Uploaded Photo
```
POST /validate
Content-Type: multipart/form-data

image : photo.jpg
```
```json
{
  "access": "granted",
  "recognized": true,
  "face_id": "uuid...",
  "name": "Niharika Pyla",
  "confidence": 0.91
}
```

---

### Real-Time Camera Status
```
GET /realtime/status
```
```json
{
  "camera_available": true,
  "face_detected": true,
  "recognized": true,
  "name": "Niharika Pyla",
  "face_id": "uuid...",
  "confidence": 0.91,
  "attendance_marked": true
}
```
> `attendance_marked: true` means a new attendance entry was just written for this frame.

---

### Attendance

#### Today's entries
```
GET /attendance/today
```

#### Daily report (one row per employee)
```
GET /attendance/report                     ← today
GET /attendance/report?date=2026-06-02     ← specific date
```
```json
[
  {
    "face_id": "uuid...",
    "name": "Niharika Pyla",
    "date": "2026-06-02",
    "check_in": "2026-06-02T09:01:12",
    "last_seen": "2026-06-02T17:45:03",
    "total_entries": 4
  }
]
```

#### Employee attendance history
```
GET /attendance/employee/{face_id}
```

#### Attendance by date
```
GET /attendance/date/2026-06-02
```

---

## Employee Status Lifecycle

```
Register  →  active  →  notice_period  →  resigned
              │               │
              │         (60 days pass)
              │               │
              │         face removed automatically
              │               │
              └───────────────┘
              attendance preserved throughout
```

---

## Raspberry Pi Hardware Wiring (optional)

| Component | GPIO Pin |
|-----------|----------|
| Servo motor (door lock) | GPIO 4 |
| Buzzer (alert) | GPIO 3 |

```python
import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BCM)
GPIO.setup(4, GPIO.OUT)
GPIO.setup(3, GPIO.OUT)

# On recognized face → open door
GPIO.output(4, GPIO.HIGH)

# On unrecognized face → sound buzzer
GPIO.output(3, GPIO.HIGH)
```

---

## Tips

- Use a clear, well-lit, front-facing photo for best recognition accuracy
- Recognition tolerance is `0.6` by default (lower = stricter). Adjust in `face_store.py`
- Attendance cooldown is `5 minutes` by default. Adjust in `attendance_store.py`:
  ```python
  DEFAULT_COOLDOWN_MINUTES = 5
  ```
- Notice period is `60 days` by default. Adjust in `employee_store.py`:
  ```python
  NOTICE_PERIOD_DAYS = 60
  ```
- Camera polls every `0.5s`. Adjust in `main.py`:
  ```python
  camera = CameraWorker(store, attendance=attendance, interval=0.5)
  ```
- All data survives server restarts — stored in `faces_db.json`, `employees_db.json`, `attendance_db.json`
