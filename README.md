# Face Recognition Door System

An automatic door access system using face recognition. Captures faces via camera, matches them against a registered set, and grants or denies access. Built with FastAPI + OpenCV + face-recognition (CNN/HOG).

---

## How It Works

1. Register allowed faces via the API (uploads a photo)
2. A background process continuously reads the camera and recognizes faces in real time
3. Call `/validate` with a photo or poll `/realtime/status` to check if the current face is allowed
4. Unrecognized faces are flagged as denied

---

## Project Structure

```
faceRecognition/
├── main.py            # FastAPI app + all API routes
├── face_store.py      # Face encoding storage (persisted to faces_db.json)
├── camera_worker.py   # Async background camera + recognition loop
├── requirements.txt   # Python dependencies
└── faces_db.json      # Auto-created on first face registration
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

### 3. Run the server
```bash
uvicorn main:app --reload
```

### 4. Open the API docs
```
http://localhost:8000/docs
```

### Camera index
The default camera is `0` (built-in webcam). If you have multiple cameras, change it in `main.py`:
```python
camera = CameraWorker(store, camera_index=1)  # use second camera
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
Enable the camera interface:
```bash
sudo raspi-config
# Interface Options → Camera → Enable
sudo reboot
```

Then install the picamera adapter:
```bash
pip3 install opencv-python-headless
```

### 5. Run the server
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Using `--host 0.0.0.0` lets you access the API from any device on the same network:
```
http://<raspberry-pi-ip>:8000/docs
```

### Run on startup (optional)
```bash
# Create a systemd service
sudo nano /etc/systemd/system/facedoor.service
```
```ini
[Unit]
Description=Face Recognition Door System
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/faceRecognition
ExecStart=uvicorn main:app --host 0.0.0.0 --port 8000
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

### Register a face
```
POST /faces
Content-Type: multipart/form-data

name  : "Niharika"
image : <photo file>
```
```json
{ "face_id": "a1b2c3...", "name": "Niharika" }
```

### List all allowed faces
```
GET /faces
```
```json
{
  "a1b2c3...": { "id": "a1b2c3...", "name": "Niharika" }
}
```

### Delete a face
```
DELETE /faces/{face_id}
```
```json
{ "deleted": "a1b2c3..." }
```

### Validate an uploaded photo
```
POST /validate
Content-Type: multipart/form-data

image : <photo file>
```
```json
{
  "access": "granted",
  "recognized": true,
  "face_id": "a1b2c3...",
  "name": "Niharika",
  "confidence": 0.87
}
```

### Real-time camera status
```
GET /realtime/status
```
```json
{
  "camera_available": true,
  "face_detected": true,
  "recognized": true,
  "name": "Niharika",
  "face_id": "a1b2c3...",
  "confidence": 0.91
}
```

---

## Raspberry Pi Hardware Wiring (optional)

To control a servo motor (door lock) and buzzer based on recognition results, wire them to the Pi GPIO pins and extend `camera_worker.py`:

| Component | GPIO Pin |
|-----------|----------|
| Servo motor | GPIO 4 |
| Buzzer | GPIO 3 |

```python
import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BCM)
GPIO.setup(4, GPIO.OUT)  # servo
GPIO.setup(3, GPIO.OUT)  # buzzer

# On recognized face:
GPIO.output(4, GPIO.HIGH)  # open door

# On unrecognized face:
GPIO.output(3, GPIO.HIGH)  # activate buzzer
```

---

## Tips

- Use a clear, well-lit front-facing photo for registration — accuracy improves significantly
- The recognition tolerance is `0.6` by default (lower = stricter). Adjust in `face_store.py`:
  ```python
  def find_match(self, unknown_encoding, tolerance=0.6):
  ```
- The camera polls every `0.5s`. Adjust in `main.py`:
  ```python
  camera = CameraWorker(store, interval=0.5)
  ```
- All registered faces survive server restarts — stored in `faces_db.json`
