# Face Recognition Door System — Architecture

---

## 1. System Overview

The system is split into three independent layers that communicate through shared in-memory state and a REST API:

```
┌─────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                           │
│        Browser / Mobile App / Raspberry Pi GPIO Controller      │
└───────────────────────┬─────────────────────────────────────────┘
                        │ HTTP (REST)
┌───────────────────────▼─────────────────────────────────────────┐
│                          API LAYER                              │
│                    FastAPI Application                          │
│                                                                 │
│   POST /faces     GET /faces     DELETE /faces    POST /validate│
│   GET /realtime/status                                          │
└───────────┬───────────────────────────┬─────────────────────────┘
            │                           │
┌───────────▼──────────┐   ┌────────────▼────────────────────────┐
│    FACE STORE        │   │         CAMERA WORKER               │
│                      │   │                                     │
│  faces_db.json       │◄──│  AsyncIO Task → ThreadPoolExecutor  │
│  (128-float vectors) │   │  OpenCV → face_recognition          │
│  Thread-safe R/W     │   │  Polls every 0.5s                   │
└──────────────────────┘   └─────────────────────────────────────┘
```

---

## 2. Component Breakdown

### 2.1 API Layer — `main.py`

- Built on **FastAPI** (async WSGI via uvicorn)
- Handles file uploads (`multipart/form-data`) using `python-multipart`
- Decodes uploaded images via **Pillow** → converts to NumPy array for face_recognition
- Stateless: all state lives in FaceStore and CameraWorker
- Starts/stops CameraWorker via FastAPI `lifespan` context

```
Request → FastAPI route → decode image → face_recognition → FaceStore → JSON response
```

---

### 2.2 Face Store — `face_store.py`

Responsible for persisting and querying the allowed face set.

```
┌──────────────────────────────────────────────┐
│                  FaceStore                   │
│                                              │
│  self.faces = {                              │
│    "uuid-1": {                               │
│      "name": "Niharika",                     │
│      "encoding": [0.142, -0.089, ...]  ←── 128 floats (CNN output)
│    }                                         │
│  }                                           │
│                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │  add()   │   │ remove() │   │  find_   │ │
│  │          │   │          │   │  match() │ │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘ │
│       │              │              │        │
│       └──────────────┴──────────────┘        │
│                      │                       │
│              threading.Lock                  │
│         (guards concurrent R/W)              │
│                      │                       │
│               faces_db.json                  │
│            (persisted on disk)               │
└──────────────────────────────────────────────┘
```

**Matching algorithm:**
```
unknown_encoding  →  face_distance(all_known_encodings)
                  →  pick lowest distance
                  →  if distance <= 0.6 → match found
                  →  confidence = 1 - distance
```

---

### 2.3 Camera Worker — `camera_worker.py`

Runs as a long-lived background task. Designed to never block the API event loop.

```
FastAPI startup
     │
     ▼
asyncio.create_task(_loop)
     │
     ▼
┌────────────────────────────────────────────┐
│              _loop()  [async]              │
│                                            │
│  while running:                            │
│    │                                       │
│    ▼                                       │
│  run_in_executor(ThreadPoolExecutor)       │
│    │  (blocking work off the event loop)   │
│    ▼                                       │
│  _capture_and_recognize()  [sync/thread]   │
│    │                                       │
│    ├── cv2.VideoCapture(camera_index)      │
│    ├── face_locations(rgb, model="hog")    │
│    ├── face_encodings(rgb, locations)      │
│    └── store.find_match(encoding)          │
│    │                                       │
│    ▼                                       │
│  update self._state  (threading.Lock)      │
│    │                                       │
│    ▼                                       │
│  await asyncio.sleep(0.5)  ← 2 FPS        │
└────────────────────────────────────────────┘
```

**Why ThreadPoolExecutor?**
OpenCV and face_recognition are blocking (CPU-bound). Running them directly in an async function would freeze the event loop and stall all API requests. The executor moves the blocking work to a separate OS thread.

---

## 3. Face Recognition Pipeline

Based on the CNN + HOG approach from the paper:

```
Raw Image (from upload or camera)
     │
     ▼
┌─────────────────────────────────┐
│  Step 1: Face Detection (HOG)   │
│                                 │
│  Convert to grayscale           │
│  Compute HOG gradients          │
│  Slide detection window         │
│  Output: [(top,right,bottom,    │
│            left), ...]          │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Step 2: Face Alignment         │
│                                 │
│  Find 68 facial landmarks       │
│  (eyes, nose, mouth, chin)      │
│  Affine transform to center     │
│  eyes and mouth in fixed pos.   │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Step 3: CNN Encoding           │
│                                 │
│  Pass aligned face through      │
│  deep CNN (ResNet variant)      │
│  Output: 128-float vector       │
│  (unique face "fingerprint")    │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Step 4: Matching               │
│                                 │
│  Euclidean distance between     │
│  unknown vector and all known   │
│  vectors in FaceStore           │
│  Threshold: 0.6                 │
│  (SVM-style nearest-neighbour)  │
└─────────────────────────────────┘
```

---

## 4. Data Flow Diagrams

### 4.1 Register a Face

```
Client
  │
  │  POST /faces  (name="Niharika", image=photo.jpg)
  ▼
FastAPI
  │
  ├── Pillow: decode JPEG → RGB numpy array
  ├── face_recognition.face_locations()  → find face bounds
  ├── face_recognition.face_encodings()  → 128-float vector
  └── FaceStore.add("Niharika", encoding)
        │
        ├── assign uuid
        ├── store in self.faces dict
        └── write to faces_db.json
  │
  ▼
{ "face_id": "uuid", "name": "Niharika" }  →  Client
```

---

### 4.2 Validate an Uploaded Photo

```
Client
  │
  │  POST /validate  (image=photo.jpg)
  ▼
FastAPI
  │
  ├── decode image → numpy array
  ├── face_recognition.face_locations()
  ├── face_recognition.face_encodings()  → unknown_encoding
  └── FaceStore.find_match(unknown_encoding)
        │
        ├── compute face_distance vs all known encodings
        ├── pick closest
        └── compare against tolerance 0.6
  │
  ▼
{ "access": "granted", "name": "Niharika", "confidence": 0.91 }  →  Client
```

---

### 4.3 Real-Time Camera Flow

```
                   ┌──────────────────────────────┐
                   │      CameraWorker._loop       │
                   │                               │
  Camera ────────► │  capture frame every 0.5s     │
  (OpenCV)         │  → detect faces               │
                   │  → encode faces               │
                   │  → match against FaceStore    │
                   │  → update self._state         │
                   └──────────────────────────────┘
                                │
                                │  (shared state, thread-safe)
                                │
  Client ──── GET /realtime/status ────► FastAPI ──► return self._state
```

---

## 5. Concurrency Model

```
Main Thread (uvicorn event loop)
│
├── handles all HTTP requests (async)
├── runs CameraWorker._loop as asyncio.Task
│     │
│     └── offloads blocking I/O to ThreadPoolExecutor
│           │
│           └── Thread 1: OpenCV capture + face recognition
│
└── FaceStore shared between event loop + worker thread
      └── threading.Lock prevents race conditions
```

---

## 6. Storage Design

```
faces_db.json
{
  "<uuid>": {
    "name": "string",
    "encoding": [float × 128]   ← CNN face vector
  }
}
```

| Property | Detail |
|---|---|
| Format | JSON (human-readable, portable) |
| Location | Same directory as `main.py` |
| Written | On every add / delete |
| Read | Once at startup |
| Thread safety | `threading.Lock` in FaceStore |
| Persistence | Survives server restarts |

---

## 7. Deployment Architectures

### 7.1 Laptop (Development)

```
┌───────────────────────────────────────┐
│              Laptop                   │
│                                       │
│  ┌──────────┐     ┌─────────────────┐ │
│  │  Webcam  │────►│  Python Server  │ │
│  └──────────┘     │  uvicorn :8000  │ │
│                   └────────┬────────┘ │
│                            │          │
│                   localhost:8000/docs │
└───────────────────────────────────────┘
```

---

### 7.2 Raspberry Pi (Production Door System)

```
┌─────────────────────────────────────────────────────┐
│                   Raspberry Pi                      │
│                                                     │
│  ┌──────────┐   ┌───────────────────────────────┐  │
│  │  Camera  │──►│   Python Server  :8000        │  │
│  └──────────┘   └───────────────────────────────┘  │
│                           │                         │
│              ┌────────────┼────────────┐            │
│              ▼            ▼            ▼            │
│         GPIO 4        GPIO 3      Network           │
│        Servo Motor    Buzzer    0.0.0.0:8000        │
│        (door lock)  (alert)   (remote API access)  │
└─────────────────────────────────────────────────────┘
         │
         │  same LAN
         ▼
┌──────────────────┐
│  Phone / Laptop  │──► http://<pi-ip>:8000/docs
└──────────────────┘
```

---

## 8. Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Web framework | FastAPI | Native async, auto Swagger docs, typed |
| Face recognition | dlib CNN (128-d) | 98% accuracy, runs on Pi without GPU |
| Detection model | HOG (not CNN) | Faster on CPU, sufficient for door use |
| Storage | JSON file | No DB dependency, simple, portable |
| Concurrency | AsyncIO + ThreadPoolExecutor | Keeps API responsive while camera runs |
| Camera polling | 0.5s interval | Balances CPU load vs. responsiveness |
| Face threshold | 0.6 Euclidean distance | Default sweet spot; tunable per environment |

---

## 9. Limitations & Future Improvements

| Limitation | Improvement |
|---|---|
| Single camera only | Support multiple camera streams |
| JSON flat file | Migrate to SQLite or PostgreSQL for scale |
| No authentication on API | Add API key or OAuth2 |
| No alert on unknown face | Add email / WhatsApp notification (as in paper) |
| HOG detection misses side profiles | Switch to CNN model (`model="cnn"`) with GPU |
| No audit log | Log every access attempt with timestamp |
