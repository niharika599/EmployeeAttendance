# Face Recognition Door System — Architecture

---

## 1. System Overview

The system has five components communicating through shared in-memory state and a REST API, with two long-running background tasks:

```
┌──────────────────────────────────────────────────────────────────────┐
│                           CLIENT LAYER                               │
│          Browser / Mobile App / Raspberry Pi GPIO Controller         │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ HTTP (REST)
┌──────────────────────────▼───────────────────────────────────────────┐
│               API LAYER  (Flask Blueprints — api/)                   │
│                                                                      │
│  employees.py  │ POST/GET /employees  POST /employees/:id/resign     │
│  faces.py      │ GET /faces           DELETE /faces/:id              │
│  validate.py   │ POST /validate                                      │
│  realtime.py   │ GET /realtime/status                                │
│  attendance.py │ GET /attendance/today|report|employee/:id|date/:d   │
└────┬──────────────┬──────────────────┬────────────────┬──────────────┘
     │              │                  │                │
┌────▼─────┐  ┌─────▼──────┐  ┌───────▼──────┐  ┌─────▼───────────────┐
│ FACE     │  │ EMPLOYEE   │  │ ATTENDANCE   │  │ CAMERA WORKER       │
│ STORE    │◄─│ STORE      │  │ STORE        │◄─│                     │
│          │  │            │  │              │  │ daemon Thread       │
│ faces_   │  │ employees_ │  │ attendance_  │  │ time.sleep(0.5s)    │
│ db.json  │  │ db.json    │  │ db.json      │  │ Polls every 0.5s    │
└──────────┘  └────────────┘  └──────────────┘  └─────────────────────┘
                                                          ▲
                                              ┌───────────┘
                                         NOTICE CHECKER
                                         daemon Thread
                                         Runs every hour
                                         Expires notice periods
```

---

## 2. Component Breakdown

### 2.1 API Layer — Flask Blueprints + `main.py`

- Built on **Flask** (synchronous WSGI)
- Routes are split into **five Blueprints** under `api/` — one per resource
- All route handlers are plain `def` functions — no `async`
- `stores.py` holds shared singleton instances; imported by each blueprint — no circular deps
- `utils.py` holds `decode_image()` — shared by `employees.py` and `validate.py`
- `main.py` is a thin **app factory** (`create_app()`): registers blueprints and error handlers
- Centralised error handlers return consistent JSON for 400 / 404 / 405 / 500
- Starts two background daemon threads at module load:
  - `CameraWorker.start()` — live recognition loop
  - `_notice_period_checker` — hourly notice period expiry check

```
main.py  (create_app)
  ├── register api/employees.py  Blueprint
  ├── register api/faces.py      Blueprint
  ├── register api/attendance.py Blueprint
  ├── register api/validate.py   Blueprint
  ├── register api/realtime.py   Blueprint
  └── @errorhandler 400/404/405/500
```

---

### 2.2 Face Store — `face_store.py`

Lowest-level component. Stores and queries face encodings only.

```
┌──────────────────────────────────────────────────┐
│                    FaceStore                     │
│                                                  │
│  self.faces = {                                  │
│    "uuid-1": {                                   │
│      "name":        "Niharika Pyla",             │
│      "employee_id": "EMP001",                    │
│      "encoding":    [0.142, -0.089, ...]  ← 128 floats
│    }                                             │
│  }                                               │
│                                                  │
│  add(name, encoding, employee_id)                │
│  remove(face_id)         ← called by EmployeeStore
│  find_match(encoding)    ← called by CameraWorker + /validate
│  list_faces()                                    │
│                                                  │
│  threading.Lock  ──►  faces_db.json              │
└──────────────────────────────────────────────────┘
```

**Matching algorithm:**
```
unknown_encoding
  → face_distance(all known encodings)   ← Euclidean distance
  → pick minimum distance
  → if distance <= 0.6  →  match (confidence = 1 - distance)
  → else                →  no match
```

---

### 2.3 Employee Store — `employee_store.py`

Owns the full employee lifecycle. Calls FaceStore directly when revoking access.

```
┌──────────────────────────────────────────────────┐
│                  EmployeeStore                   │
│                                                  │
│  self.employees = {                              │
│    "EMP001": {                                   │
│      employee_id, name, email,                   │
│      department, phone, designation,             │
│      face_id,                                    │
│      status,          ← active | notice_period | resigned
│      joined_at,                                  │
│      resigned_at,     ← set on resign()          │
│      notice_ends_at   ← resigned_at + 60 days    │
│    }                                             │
│  }                                               │
│                                                  │
│  register(...)        ← called by POST /employees│
│  resign(employee_id)  ← sets notice_period       │
│  expire_notice_periods()  ← called hourly        │
│       └── face_store.remove(face_id)  ← auto-revoke
│  get(employee_id)                                │
│  list(status=None)                               │
│                                                  │
│  threading.Lock  ──►  employees_db.json          │
└──────────────────────────────────────────────────┘
```

**Status transitions:**
```
active  ──[resign()]──►  notice_period  ──[60 days]──►  resigned
  │                            │                            │
face active              face active                  face removed
attendance marked        attendance marked             no recognition
```

---

### 2.4 Attendance Store — `attendance_store.py`

Records every recognition event with a cooldown guard to prevent duplicates.

```
┌──────────────────────────────────────────────────┐
│                 AttendanceStore                  │
│                                                  │
│  self.records = [                                │
│    {                                             │
│      id, face_id, name,                          │
│      timestamp, date, time                       │
│    }, ...                                        │
│  ]                                               │
│                                                  │
│  mark(face_id, name, cooldown_minutes=5)         │
│    └── scan backwards for same face_id           │
│    └── skip if last entry < 5 min ago            │
│    └── else append + save                        │
│                                                  │
│  get_today()                                     │
│  get_by_date(date_str)                           │
│  get_by_employee(face_id)                        │
│  get_report(date)  ← groups by employee,         │
│                       first=check_in,            │
│                       last=last_seen             │
│                                                  │
│  threading.Lock  ──►  attendance_db.json         │
└──────────────────────────────────────────────────┘
```

---

### 2.5 Camera Worker — `camera_worker.py`

Runs as a long-lived daemon thread. Independent of the Flask request cycle.

```
Flask startup  →  threading.Thread(target=_loop, daemon=True).start()
                              │
                              ▼
                   ┌──────────────────────────┐
                   │      _loop()  [thread]   │
                   │                          │
                   │  while running:          │
                   │    _capture_and_         │
                   │    recognize()           │
                   │    │                     │
                   │    ├── cv2.VideoCapture  │
                   │    ├── face_locations    │
                   │    ├── face_encodings    │
                   │    ├── FaceStore.        │
                   │    │   find_match()      │
                   │    └── AttendanceStore.  │
                   │        mark()            │
                   │                          │
                   │    update _state         │
                   │    (threading.Lock)      │
                   │                          │
                   │    time.sleep(0.5s)      │
                   └──────────────────────────┘
```

**Why a daemon thread?**
Flask is synchronous WSGI — there is no event loop to protect. A daemon thread runs independently alongside Flask's request handling and is automatically killed when the main process exits.

---

### 2.6 Notice Period Checker — `main.py`

A plain daemon thread started at module load alongside the camera worker.

```
threading.Thread(target=_notice_period_checker, daemon=True).start()
              │
              ▼
         while True:
           EmployeeStore.expire_notice_periods()
             └── for each employee with status=notice_period:
                   if now >= notice_ends_at:
                     FaceStore.remove(face_id)
                     status = "resigned"
           time.sleep(3600)   ← check every hour
```

---

## 3. Project Layout

```
faceRecognition/
├── main.py               # App factory + blueprint registration + error handlers
├── stores.py             # Shared singletons: FaceStore, EmployeeStore,
│                         #   AttendanceStore, CameraWorker
├── utils.py              # decode_image() — Pillow → NumPy RGB array
│
├── api/                  # Flask Blueprints (one per resource)
│   ├── __init__.py
│   ├── employees.py      # /employees
│   ├── faces.py          # /faces
│   ├── attendance.py     # /attendance
│   ├── validate.py       # /validate
│   └── realtime.py       # /realtime
│
├── face_store.py         # FaceStore  →  faces_db.json
├── employee_store.py     # EmployeeStore  →  employees_db.json
├── attendance_store.py   # AttendanceStore  →  attendance_db.json
└── camera_worker.py      # CameraWorker daemon thread
```

**Dependency flow (no circular imports):**
```
api/*.py  →  stores.py  →  face_store.py
                        →  employee_store.py  →  face_store.py
                        →  attendance_store.py
                        →  camera_worker.py   →  face_store.py
                                              →  attendance_store.py
api/*.py  →  utils.py
main.py   →  api/*.py
main.py   →  stores.py
```

---

## 4. Face Recognition Pipeline  

Based on the CNN + HOG approach from the paper:

```
Raw Image (upload or camera frame)
     │
     ▼
┌─────────────────────────────────┐
│  Step 1: Face Detection (HOG)   │
│  Convert to grayscale           │
│  Compute gradient directions    │
│  Slide detection window         │
│  Output: bounding box list      │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Step 2: Face Alignment         │
│  Find 68 facial landmarks       │
│  Affine-transform image so      │
│  eyes + mouth are centred       │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Step 3: CNN Encoding           │
│  Pass aligned face through      │
│  ResNet-based CNN               │
│  Output: 128-float vector       │
│  (unique face "fingerprint")    │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Step 4: Matching               │
│  Euclidean distance vs all      │
│  known vectors in FaceStore     │
│  Threshold: 0.6                 │
│  Confidence: 1 - distance       │
└─────────────────────────────────┘
```

---

## 4. Data Flow Diagrams

### 4.1 Register a New Employee

```
Client
  │  POST /employees  (employee_id, name, image, email, dept, ...)
  ▼
Flask
  ├── Pillow: decode image → RGB numpy array
  ├── face_locations()  → detect face bounds
  ├── face_encodings()  → 128-float vector
  ├── FaceStore.add(name, encoding, employee_id)  → face_id (uuid)
  └── EmployeeStore.register(employee_id, name, face_id, ...)
        ├── check duplicate employee_id  (409 if exists, rollback face)
        └── save to employees_db.json
  │
  ▼
{ employee_id, name, face_id, face_encoding_size:128, status:"active", ... }
```

---

### 4.2 Real-Time Attendance Marking

```
Camera
  │  frame every 0.5s
  ▼
CameraWorker (background thread)
  ├── face_locations()
  ├── face_encodings()
  ├── FaceStore.find_match()
  │     └── match found: face_id="uuid", name="Niharika"
  └── AttendanceStore.mark(face_id, name)
        ├── last entry for this face < 5 min ago?  → skip
        └── else: append record, save attendance_db.json

_state = { recognized:true, name, face_id, confidence, attendance_marked:true }

GET /realtime/status  →  returns _state
```

---

### 4.3 Employee Resignation + Notice Period

```
Client
  │  POST /employees/EMP001/resign
  ▼
Flask → EmployeeStore.resign("EMP001")
  ├── status       = "notice_period"
  ├── resigned_at  = now
  ├── notice_ends_at = now + 60 days
  └── face stays in FaceStore (access continues)
  │
  ▼
{ message: "...access revoked on 2026-08-01", employee: {...} }

                    ┌─────────────────────────────┐
                    │  _notice_period_checker      │
                    │  runs every hour             │
                    │                              │
                    │  now >= notice_ends_at?      │
                    │    YES:                      │
                    │      FaceStore.remove()      │
                    │      status = "resigned"     │
                    └─────────────────────────────┘
```

---

### 4.4 Validate an Uploaded Photo

```
Client
  │  POST /validate  (image=photo.jpg)
  ▼
Flask
  ├── decode image → face_encodings()
  └── FaceStore.find_match(encoding)
        ├── match  →  { access:"granted", name, confidence }
        └── no match  →  { access:"denied" }
```

---

## 5. Concurrency Model

```
Flask main thread (WSGI)
│
├── HTTP request handlers          [def — synchronous]
│
├── CameraWorker._loop             [daemon Thread]
│     └── _capture_and_recognize  [runs directly in thread — no executor needed]
│
├── _notice_period_checker         [daemon Thread]
│     └── expire_notice_periods()  [sync, fast — in-memory scan]
│
└── Shared stores (FaceStore, EmployeeStore, AttendanceStore)
      └── threading.Lock on every read/write
          (guards against CameraWorker/NoticeChecker threads vs Flask request threads)
```

---

## 6. Storage Design

Three JSON files, each owned by one store class:

### faces_db.json
```json
{
  "<uuid>": {
    "name": "Niharika Pyla",
    "employee_id": "EMP001",
    "encoding": [0.142, -0.089, ...]
  }
}
```

### employees_db.json
```json
{
  "EMP001": {
    "employee_id": "EMP001",
    "name": "Niharika Pyla",
    "email": "n@company.com",
    "department": "Engineering",
    "phone": "+91-999...",
    "designation": "Senior SWE",
    "face_id": "<uuid>",
    "status": "notice_period",
    "joined_at": "2026-01-15T09:00:00",
    "resigned_at": "2026-06-02T10:00:00",
    "notice_ends_at": "2026-08-01T10:00:00"
  }
}
```

### attendance_db.json
```json
[
  {
    "id": "<uuid>",
    "face_id": "<uuid>",
    "name": "Niharika Pyla",
    "timestamp": "2026-06-02T09:01:12",
    "date": "2026-06-02",
    "time": "09:01:12"
  }
]
```

| Property | Detail |
|---|---|
| Format | JSON (human-readable, portable) |
| Location | Same directory as `main.py` |
| Thread safety | `threading.Lock` per store |
| Persistence | Survives server restarts |
| Ignored by git | Listed in `.gitignore` |

---

## 7. Deployment Architectures

### 7.1 Laptop (Development)

```
┌───────────────────────────────────────┐
│              Laptop                   │
│  ┌──────────┐   ┌──────────────────┐  │
│  │  Webcam  │──►│  Flask  :8000    │  │
│  └──────────┘   │  python main.py  │  │
│                 └──────────────────┘  │
│                  localhost:8000       │
└───────────────────────────────────────┘
```

### 7.2 Raspberry Pi (Production Door System)

```
┌─────────────────────────────────────────────────────┐
│                   Raspberry Pi                      │
│  ┌──────────┐   ┌───────────────────────────────┐  │
│  │  Camera  │──►│   Flask  0.0.0.0:8000         │  │
│  └──────────┘   │   python main.py              │  │
│                 └───────────────────────────────┘  │
│                           │                         │
│              ┌────────────┼────────────┐            │
│              ▼            ▼            ▼            │
│         GPIO 4        GPIO 3      Network           │
│        Servo Motor    Buzzer    0.0.0.0:8000        │
│        (door lock)  (alert)   (remote API)         │
└─────────────────────────────────────────────────────┘
         │  same LAN
         ▼
┌──────────────────┐
│  Phone / Laptop  │──► http://<pi-ip>:8000
└──────────────────┘
```

---

## 8. Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Web framework | Flask | Simple synchronous WSGI, no async complexity needed |
| Route organisation | Flask Blueprints (`api/`) | One file per resource — clean separation, easy to extend |
| Shared state | `stores.py` singletons | Single source of truth, no circular imports across blueprints |
| Shared helpers | `utils.py` | `decode_image` reused by employees + validate blueprints |
| App creation | `create_app()` factory | Testable, centralised error handlers, clean entry point |
| Route functions | `def` only | Background work runs in daemon threads, not coroutines |
| Background tasks | `threading.Thread(daemon=True)` | Camera and notice checker run independently of requests |
| Face recognition | dlib CNN (128-d) | 98% accuracy, runs on Pi without GPU |
| Detection model | HOG (not CNN) | Faster on CPU, sufficient for a door camera |
| Storage | JSON files | No DB dependency, simple, portable |
| Concurrency | threading.Thread + threading.Lock | Simpler than asyncio for CPU-bound background work |
| Camera polling | 0.5s interval | Balances CPU load vs. responsiveness |
| Face threshold | 0.6 Euclidean distance | Tunable sweet spot for accuracy vs. false positives |
| Attendance cooldown | 5 minutes | Prevents duplicate entries from continuous camera |
| Notice period | 60 days | Business rule; configurable via `NOTICE_PERIOD_DAYS` |
| Notice checker interval | 1 hour | Granularity sufficient; not day-critical |
| Atomic registration | Face + employee in one request | Prevents orphaned face records |
| Rollback on conflict | Remove face if employee_id duplicate | Keeps stores consistent |

---

## 9. Limitations & Future Improvements

| Limitation | Improvement |
|---|---|
| Single camera only | Support multiple camera streams |
| JSON flat files | Migrate to SQLite or PostgreSQL for scale |
| No API authentication | Add API key or OAuth2 |
| No alert on unknown face | Add email / WhatsApp notification |
| HOG misses side profiles | Use CNN model (`model="cnn"`) with GPU |
| Attendance not linked to employee record directly | Add `employee_id` field to attendance records |
| Notice checker runs even when no notice_period employees exist | Add early-exit when queue is empty |
| No report export | Add CSV / PDF export for attendance reports |
