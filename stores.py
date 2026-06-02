from attendance_store import AttendanceStore
from camera_worker import CameraWorker
from employee_store import EmployeeStore
from face_store import FaceStore

store = FaceStore()
attendance = AttendanceStore()
employees = EmployeeStore(store)
camera = CameraWorker(store, attendance=attendance)
