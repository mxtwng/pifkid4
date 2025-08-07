import cv2
import mediapipe as mp
import numpy as np
import requests
from flask import Flask, render_template, Response, jsonify, request
import threading
import time
import json
from io import BytesIO
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, List, Tuple

# Configure logging for better debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MonitoringState(Enum):
    """
    Different states of our eye health monitoring system
    Think of this as the different 'modes' our smart table can be in
    """
    IDLE = "idle"                          # No one detected at the desk
    MONITORING = "monitoring"              # User present, counting screen time
    BREAK_NEEDED = "break_needed"          # 20 minutes up, break recommended
    ON_BREAK = "on_break"                  # User looking away, counting break time
    BREAK_COMPLETE = "break_complete"      # Break finished, ready to resume

@dataclass
class GazeData:
    """
    Structure to hold gaze analysis results
    This helps us organize all the information about where someone is looking
    """
    is_looking_at_screen: bool
    head_pose_angles: Tuple[float, float, float]  # pitch, yaw, roll
    confidence: float
    face_center: Tuple[int, int]
    timestamp: float

@dataclass
class EyeHealthSession:
    """
    Tracks a complete work session with timing and health metrics
    This is like a health report card for each work session
    """
    session_start: datetime
    total_screen_time: float
    total_break_time: float
    break_count: int
    longest_continuous_screen_time: float
    average_break_duration: float
    session_end: Optional[datetime] = None

class FirebaseCloudInterface:
    """
    Interface for cloud data storage - designed to be easily replaceable
    Think of this as a filing cabinet that lives in the cloud
    """
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.enabled = False
        
        # TODO: Initialize your Firebase connection here
        # self.firebase_app = firebase_admin.initialize_app(cred, config)
        # self.db = firestore.client()
        
    def log_session_data(self, session: EyeHealthSession):
        """Log completed session to cloud storage"""
        if not self.enabled:
            logger.info("Cloud storage disabled - would log session data")
            return
            
        # TODO: Implement Firebase/cloud logging
        # session_data = {
        #     'timestamp': session.session_start.isoformat(),
        #     'duration': session.total_screen_time,
        #     'breaks': session.break_count,
        #     # ... other metrics
        # }
        # self.db.collection('work_sessions').add(session_data)
        
    def get_user_statistics(self, user_id: str, days: int = 7):
        """Retrieve user statistics from cloud storage"""
        # TODO: Implement statistics retrieval
        return {
            'avg_daily_screen_time': 0,
            'total_breaks_taken': 0,
            'compliance_rate': 0
        }

class TableHardwareInterface:
    """
    Interface for controlling physical table components (LCD, LED, buttons)
    This is the bridge between our software and the physical world
    """
    def __init__(self, esp32_ip: str):
        self.esp32_ip = esp32_ip
        self.hardware_url = f"http://{esp32_ip}/hardware"
        
    def display_message(self, message: str, duration: int = 0):
        """
        Display message on the table's LCD screen
        duration: 0 = permanent, >0 = seconds to display
        """
        try:
            payload = {
                'action': 'display',
                'message': message,
                'duration': duration
            }
            response = requests.post(f"{self.hardware_url}/lcd", 
                                   json=payload, timeout=2)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"LCD communication error: {e}")
            return False
    
    def set_led_status(self, color: str, pattern: str = "solid"):
        """
        Control the table's status LED
        color: 'green', 'yellow', 'red', 'blue', 'off'
        pattern: 'solid', 'blink', 'pulse', 'fast_blink'
        """
        try:
            payload = {
                'action': 'led',
                'color': color,
                'pattern': pattern
            }
            response = requests.post(f"{self.hardware_url}/led", 
                                   json=payload, timeout=2)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"LED communication error: {e}")
            return False
    
    def check_button_pressed(self) -> str:
        """
        Check if any table buttons have been pressed
        Returns: 'skip', 'complete', 'none'
        """
        try:
            response = requests.get(f"{self.hardware_url}/button", timeout=1)
            if response.status_code == 200:
                data = response.json()
                return data.get('button_pressed', 'none')
        except Exception as e:
            logger.error(f"Button check error: {e}")
        return 'none'
    
    # EXTENSION POINT: Add more hardware control methods here
    def set_desk_height(self, height_cm: int):
        """Future: Control motorized desk height"""
        pass
    
    def control_ambient_lighting(self, brightness: int, temperature: int):
        """Future: Control ambient lighting based on time of day"""
        pass

class SmartWorkTableAI:
    """
    Main AI system for the smart work table
    This is the brain that coordinates everything
    """
    def __init__(self, esp32_ip="192.168.1.100"):
        # Core camera and AI setup
        self.esp32_url = f"http://{esp32_ip}/stream"
        self.capture_url = f"http://{esp32_ip}/capture"
        
        # Initialize MediaPipe components
        self.mp_face_detection = mp.solutions.face_detection
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils
        
        # Face detection for presence
        self.face_detection = self.mp_face_detection.FaceDetection(
            model_selection=0, min_detection_confidence=0.7
        )
        
        # Face mesh for detailed gaze analysis
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5
        )
        
        # Hardware and cloud interfaces
        self.hardware = TableHardwareInterface(esp32_ip)
        self.cloud = FirebaseCloudInterface()
        
        # State management
        self.current_state = MonitoringState.IDLE
        self.state_start_time = time.time()
        
        # Eye health timing variables
        self.screen_time_start = None
        self.break_start_time = None
        self.total_screen_time = 0
        self.total_break_time = 0
        self.break_count = 0
        
        # Configuration - easily adjustable for different users
        self.config = {
            'max_screen_time': 20 * 60,      # 20 minutes in seconds
            'min_break_time': 20,            # 20 seconds minimum break
            'gaze_threshold': 0.3,           # Sensitivity for gaze detection
            'presence_timeout': 30,          # Seconds before assuming user left
            'notification_duration': 300,    # 5 minutes to respond to break reminder
        }
        
        # Session tracking
        self.current_session = None
        self.session_history = []
        
        # Frame processing
        self.latest_frame = None
        self.latest_gaze_data = None
        self.processing_active = False
        self.processing_thread = None
        
        logger.info(f"Smart Work Table AI initialized for ESP32 at {esp32_ip}")
    
    def analyze_gaze_direction(self, frame, face_landmarks) -> GazeData:
        """
        Analyze where the person is looking based on facial landmarks
        This is the core intelligence that determines screen vs non-screen gaze
        """
        if not face_landmarks.multi_face_landmarks:
            return GazeData(False, (0, 0, 0), 0, (0, 0), time.time())
        
        face_3d = []
        face_2d = []
        
        # Get image dimensions
        img_h, img_w, _ = frame.shape
        
        # Extract key facial landmarks for pose estimation
        face_landmark = face_landmarks.multi_face_landmarks[0]
        
        for idx, landmark in enumerate(face_landmark.landmark):
            if idx in [33, 263, 1, 61, 291, 199]:  # Key points for head pose
                x, y = int(landmark.x * img_w), int(landmark.y * img_h)
                face_2d.append([x, y])
                face_3d.append([x, y, landmark.z])
        
        # Convert to numpy arrays
        face_2d = np.array(face_2d, dtype=np.float64)
        face_3d = np.array(face_3d, dtype=np.float64)
        
        # Camera matrix (simplified - you might want to calibrate this)
        focal_length = 1 * img_w
        cam_matrix = np.array([[focal_length, 0, img_w / 2],
                              [0, focal_length, img_h / 2],
                              [0, 0, 1]])
        
        # Distortion parameters (assume no distortion for simplicity)
        distortion_matrix = np.zeros((4, 1), dtype=np.float64)
        
        # Solve PnP to get head pose
        success, rotation_vec, translation_vec = cv2.solvePnP(
            face_3d, face_2d, cam_matrix, distortion_matrix
        )
        
        # Get rotation angles
        rotation_matrix, _ = cv2.Rodrigues(rotation_vec)
        angles, _, _, _, _, _ = cv2.RQDecomp3x3(rotation_matrix)
        
        pitch, yaw, roll = angles[0] * 360, angles[1] * 360, angles[2] * 360
        
        # Determine if looking at screen based on head pose
        # These thresholds may need adjustment based on your setup
        looking_at_screen = (
            abs(pitch) < 15 and    # Not looking too far up or down
            abs(yaw) < 20 and      # Not looking too far left or right
            abs(roll) < 15         # Head not tilted too much
        )
        
        # Calculate confidence based on how centered the gaze is
        confidence = max(0, 1 - (abs(pitch) + abs(yaw) + abs(roll)) / 100)
        
        # Get face center for visualization
        face_center = (int(np.mean(face_2d[:, 0])), int(np.mean(face_2d[:, 1])))
        
        return GazeData(
            is_looking_at_screen=looking_at_screen,
            head_pose_angles=(pitch, yaw, roll),
            confidence=confidence,
            face_center=face_center,
            timestamp=time.time()
        )
    
    def update_monitoring_state(self, gaze_data: GazeData):
        """
        Update the monitoring state machine based on current gaze analysis
        This is the decision-making center of our system
        """
        current_time = time.time()
        state_duration = current_time - self.state_start_time
        
        if self.current_state == MonitoringState.IDLE:
            if gaze_data and gaze_data.confidence > 0.5:
                self._transition_to_monitoring()
        
        elif self.current_state == MonitoringState.MONITORING:
            if not gaze_data or gaze_data.confidence < 0.3:
                # User seems to have left - wait a bit before going idle
                if state_duration > self.config['presence_timeout']:
                    self._transition_to_idle()
            
            elif gaze_data.is_looking_at_screen:
                # Continue monitoring screen time
                self.total_screen_time += 1  # Assuming ~1 second per update
                
                # Check if break is needed
                if self.total_screen_time >= self.config['max_screen_time']:
                    self._transition_to_break_needed()
            
            else:
                # User is looking away - this counts as a micro-break
                self._start_break()
        
        elif self.current_state == MonitoringState.BREAK_NEEDED:
            # Check for user input
            button_pressed = self.hardware.check_button_pressed()
            
            if button_pressed == 'skip':
                self._skip_break()
            elif button_pressed == 'complete' or gaze_data and not gaze_data.is_looking_at_screen:
                self._start_break()
            elif state_duration > self.config['notification_duration']:
                # Auto-start break if user doesn't respond
                self._start_break()
        
        elif self.current_state == MonitoringState.ON_BREAK:
            if gaze_data and not gaze_data.is_looking_at_screen:
                # Continue break
                self.total_break_time += 1
                
                if self.total_break_time >= self.config['min_break_time']:
                    self._complete_break()
            else:
                # User looked back at screen before break was complete
                if self.total_break_time >= 5:  # At least 5 seconds counts as a break attempt
                    self._complete_break()
                else:
                    self._transition_to_monitoring()
    
    def _transition_to_monitoring(self):
        """Start monitoring a new work session"""
        self.current_state = MonitoringState.MONITORING
        self.state_start_time = time.time()
        self.screen_time_start = time.time()
        
        if not self.current_session:
            self.current_session = EyeHealthSession(
                session_start=datetime.now(),
                total_screen_time=0,
                total_break_time=0,
                break_count=0,
                longest_continuous_screen_time=0,
                average_break_duration=0
            )
        
        self.hardware.set_led_status('green', 'solid')
        self.hardware.display_message("Work session started. Stay healthy!", 3)
        logger.info("Started monitoring work session")
    
    def _transition_to_break_needed(self):
        """Transition to break needed state"""
        self.current_state = MonitoringState.BREAK_NEEDED
        self.state_start_time = time.time()
        
        self.hardware.set_led_status('yellow', 'blink')
        self.hardware.display_message("Break time! Look away for 20 seconds or press skip.")
        logger.info("Break needed - 20 minutes of screen time completed")
    
    def _start_break(self):
        """Start a break period"""
        self.current_state = MonitoringState.ON_BREAK
        self.state_start_time = time.time()
        self.break_start_time = time.time()
        self.break_count += 1
        
        self.hardware.set_led_status('blue', 'pulse')
        self.hardware.display_message(f"Break in progress... {self.config['min_break_time']}s remaining")
        logger.info("Break started")
    
    def _complete_break(self):
        """Complete the break and return to monitoring"""
        self.current_state = MonitoringState.MONITORING
        self.state_start_time = time.time()
        self.total_screen_time = 0  # Reset screen time counter
        
        self.hardware.set_led_status('green', 'solid')
        self.hardware.display_message("Break complete! Back to work.", 3)
        logger.info(f"Break completed after {self.total_break_time} seconds")
    
    def _skip_break(self):
        """Skip the recommended break (not ideal, but user choice)"""
        self.current_state = MonitoringState.MONITORING
        self.state_start_time = time.time()
        self.total_screen_time = 0  # Reset but log that break was skipped
        
        self.hardware.set_led_status('red', 'fast_blink')
        self.hardware.display_message("Break skipped. Consider taking regular breaks!", 5)
        logger.warning("User skipped recommended break")
    
    def _transition_to_idle(self):
        """Return to idle state and save session data"""
        if self.current_session:
            self.current_session.session_end = datetime.now()
            self.current_session.total_screen_time = self.total_screen_time
            self.current_session.total_break_time = self.total_break_time
            self.current_session.break_count = self.break_count
            
            # Save to cloud
            self.cloud.log_session_data(self.current_session)
            self.session_history.append(self.current_session)
            self.current_session = None
        
        self.current_state = MonitoringState.IDLE
        self.state_start_time = time.time()
        
        # Reset counters
        self.total_screen_time = 0
        self.total_break_time = 0
        self.break_count = 0
        
        self.hardware.set_led_status('off')
        self.hardware.display_message("Session ended. See you later!")
        logger.info("Session ended, returned to idle state")
    
    def process_frame_with_health_monitoring(self, frame):
        """
        Main processing function that combines AI analysis with health monitoring
        This is where computer vision meets health science
        """
        if frame is None:
            return frame, None
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, _ = frame.shape
        
        # Detect faces
        face_results = self.face_detection.process(rgb_frame)
        mesh_results = self.face_mesh.process(rgb_frame)
        
        gaze_data = None
        
        if face_results.detections and mesh_results.multi_face_landmarks:
            # Analyze gaze direction
            gaze_data = self.analyze_gaze_direction(frame, mesh_results)
            
            # Draw face detection
            for detection in face_results.detections:
                bbox = detection.location_data.relative_bounding_box
                x = int(bbox.xmin * width)
                y = int(bbox.ymin * height)
                w = int(bbox.width * width)
                h = int(bbox.height * height)
                
                # Color code based on gaze direction
                color = (0, 255, 0) if gaze_data.is_looking_at_screen else (0, 165, 255)
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                
                # Display gaze information
                gaze_status = "Looking at screen" if gaze_data.is_looking_at_screen else "Looking away"
                cv2.putText(frame, gaze_status, (x, y - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                
                # Show head pose angles
                pitch, yaw, roll = gaze_data.head_pose_angles
                cv2.putText(frame, f"P:{pitch:.1f} Y:{yaw:.1f} R:{roll:.1f}", 
                           (x, y + h + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        
        # Draw health monitoring status
        self._draw_health_status_overlay(frame)
        
        # Update monitoring state
        self.update_monitoring_state(gaze_data)
        
        return frame, gaze_data
    
    def _draw_health_status_overlay(self, frame):
        """Draw health monitoring information on the frame"""
        height, width, _ = frame.shape
        
        # Status panel background
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, 10), (400, 150), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        
        # Current state
        state_color = {
            MonitoringState.IDLE: (128, 128, 128),
            MonitoringState.MONITORING: (0, 255, 0),
            MonitoringState.BREAK_NEEDED: (0, 255, 255),
            MonitoringState.ON_BREAK: (255, 0, 0),
        }.get(self.current_state, (255, 255, 255))
        
        cv2.putText(frame, f"Status: {self.current_state.value.upper()}", 
                   (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, state_color, 2)
        
        # Screen time counter
        screen_time_minutes = self.total_screen_time // 60
        screen_time_seconds = self.total_screen_time % 60
        cv2.putText(frame, f"Screen Time: {screen_time_minutes:02d}:{screen_time_seconds:02d}", 
                   (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Break counter
        cv2.putText(frame, f"Breaks Taken: {self.break_count}", 
                   (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Next break countdown
        if self.current_state == MonitoringState.MONITORING:
            time_to_break = max(0, self.config['max_screen_time'] - self.total_screen_time)
            break_minutes = time_to_break // 60
            break_seconds = time_to_break % 60
            cv2.putText(frame, f"Next Break: {break_minutes:02d}:{break_seconds:02d}", 
                       (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        
        # Break progress
        elif self.current_state == MonitoringState.ON_BREAK:
            remaining_break = max(0, self.config['min_break_time'] - self.total_break_time)
            cv2.putText(frame, f"Break Time Remaining: {remaining_break}s", 
                       (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
    
    def continuous_health_monitoring_loop(self):
        """Main processing loop with health monitoring"""
        logger.info("🏥 Starting health monitoring system...")
        last_update = time.time()
        
        while self.processing_active:
            frame = self.get_frame_from_esp32()
            
            if frame is not None:
                processed_frame, gaze_data = self.process_frame_with_health_monitoring(frame)
                self.latest_frame = processed_frame
                self.latest_gaze_data = gaze_data
                
                # Update once per second for timing accuracy
                current_time = time.time()
                if current_time - last_update >= 1.0:
                    last_update = current_time
                    # State updates happen in process_frame_with_health_monitoring
            
            time.sleep(0.1)  # 10 FPS processing rate
    
    def get_frame_from_esp32(self):
        """Get frame from ESP32 camera"""
        try:
            response = requests.get(self.capture_url, timeout=2)
            if response.status_code == 200:
                image_array = np.asarray(bytearray(response.content), dtype=np.uint8)
                frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
                return frame
            return None
        except:
            return None
    
    def start_health_monitoring(self):
        """Start the health monitoring system"""
        if not self.test_esp32_connection():
            return False
        
        self.processing_active = True
        self.processing_thread = threading.Thread(target=self.continuous_health_monitoring_loop)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        
        # Initialize hardware
        self.hardware.set_led_status('green', 'pulse')
        self.hardware.display_message("Smart Work Table AI Ready!")
        
        return True
    
    def stop_health_monitoring(self):
        """Stop the health monitoring system"""
        self.processing_active = False
        if self.processing_thread:
            self.processing_thread.join()
        
        self.hardware.set_led_status('off')
        self.hardware.display_message("System stopped.")
    
    def test_esp32_connection(self):
        """Test ESP32 connection"""
        try:
            response = requests.get(self.capture_url, timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def get_latest_frame_as_jpeg(self):
        """Get latest frame as JPEG for web streaming"""
        if self.latest_frame is not None:
            ret, jpeg = cv2.imencode('.jpg', self.latest_frame, 
                                   [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                return jpeg.tobytes()
        return None
    
    def get_health_statistics(self) -> dict:
        """Get current health monitoring statistics"""
        return {
            'current_state': self.current_state.value,
            'screen_time_seconds': self.total_screen_time,
            'break_time_seconds': self.total_break_time,
            'breaks_taken': self.break_count,
            'session_duration': time.time() - (self.screen_time_start or time.time()),
            'compliance_rate': self._calculate_compliance_rate(),
            'next_break_in': max(0, self.config['max_screen_time'] - self.total_screen_time),
            'gaze_data': {
                'looking_at_screen': self.latest_gaze_data.is_looking_at_screen if self.latest_gaze_data else False,
                'confidence': self.latest_gaze_data.confidence if self.latest_gaze_data else 0,
                'head_pose': self.latest_gaze_data.head_pose_angles if self.latest_gaze_data else (0, 0, 0)
            }
        }
    
    def _calculate_compliance_rate(self) -> float:
        """Calculate how well the user is following the 20-20-20 rule"""
        if self.total_screen_time == 0:
            return 100.0
        
        expected_breaks = self.total_screen_time // self.config['max_screen_time']
        if expected_breaks == 0:
            return 100.0
        
        return min(100.0, (self.break_count / expected_breaks) * 100)
    
    # EXTENSION POINTS - Add your custom features here!
    
    def set_user_profile(self, profile: dict):
        """Customize settings based on user profile"""
        # TODO: Implement user-specific configurations
        pass
    
    def integrate_calendar(self, calendar_events: list):
        """Adjust monitoring based on calendar events"""
        # TODO: Implement calendar integration
        pass
    
    def analyze_productivity_patterns(self):
        """Analyze work patterns and provide insights"""
        # TODO: Implement productivity analysis
        pass
    
    def environmental_adjustments(self, light_level: float, room_temp: float):
        """Adjust recommendations based on environmental factors"""
        # TODO: Implement environmental awareness
        pass


# Flask Web Application
app = Flask(__name__)
smart_table = None

@app.route('/')
def dashboard():
    """Main dashboard for the smart work table"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Smart Work Table - Eye Health Monitor</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: white;
            }
            .container { 
                max-width: 1400px; 
                margin: 0 auto; 
                padding: 20px; 
            }
            .header {
                text-align: center;
                margin-bottom: 30px;
            }
            h1 {
                font-size: 2.5rem;
                margin-bottom: 10px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            }
            .status-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }
            .status-card {
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 15px;
                padding: 25px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            }
            .video-section {
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 20px;
                text-align: center;
            }
            .video-feed {
                max-width: 100%;
                border-radius: 10px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            }
            .controls {
                display: flex;
                justify-content: center;
                gap: 15px;
                margin: 20px 0;
                flex-wrap: wrap;
            }
            .btn {
                padding: 12px 24px;
                border: none;
                border-radius: 25px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            .btn-start {
                background: linear-gradient(45deg, #4CAF50, #45a049);
                color: white;
                box-shadow: 0 4px 15px rgba(76, 175, 80, 0.3);
            }
            .btn-stop {
                background: linear-gradient(45deg, #f44336, #da190b);
                color: white;
                box-shadow: 0 4px 15px rgba(244, 67, 54, 0.3);
            }
            .btn-emergency {
                background: linear-gradient(45deg, #ff9800, #f57c00);
                color: white;
                box-shadow: 0 4px 15px rgba(255, 152, 0, 0.3);
            }
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(0,0,0,0.3);
            }
            .metric-value {
                font-size: 2.2rem;
                font-weight: bold;
                margin: 10px 0;
            }
            .metric-label {
                font-size: 0.9rem;
                opacity: 0.8;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            .state-indicator {
                display: inline-block;
                width: 12px;
                height: 12px;
                border-radius: 50%;
                margin-right: 8px;
                animation: pulse 2s infinite;
            }
            .state-idle { background: #gray; }
            .state-monitoring { background: #4CAF50; }
            .state-break-needed { background: #ff9800; }
            .state-on-break { background: #2196F3; }
            @keyframes pulse {
                0% { opacity: 1; }
                50% { opacity: 0.5; }
                100% { opacity: 1; }
            }
            .progress-bar {
                width: 100%;
                height: 8px;
                background: rgba(255,255,255,0.2);
                border-radius: 4px;
                margin: 10px 0;
                overflow: hidden;
            }
            .progress-fill {
                height: 100%;
                background: linear-gradient(90deg, #4CAF50, #8BC34A);
                transition: width 0.3s ease;
                border-radius: 4px;
            }
            .gaze-indicator {
                text-align: center;
                padding: 15px;
                margin: 10px 0;
                border-radius: 10px;
                font-weight: bold;
                transition: all 0.3s ease;
            }
            .gaze-screen {
                background: rgba(76, 175, 80, 0.3);
                border: 2px solid #4CAF50;
                color: #4CAF50;
            }
            .gaze-away {
                background: rgba(33, 150, 243, 0.3);
                border: 2px solid #2196F3;
                color: #2196F3;
            }
            .settings-panel {
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border-radius: 15px;
                padding: 25px;
                margin-top: 20px;
            }
            .setting-item {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin: 15px 0;
                padding: 10px;
                background: rgba(255, 255, 255, 0.1);
                border-radius: 8px;
            }
            .setting-input {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 5px;
                padding: 8px 12px;
                color: white;
                width: 100px;
            }
            .setting-input::placeholder { color: rgba(255, 255, 255, 0.7); }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Smart Work Table</h1>
                <p>AI-Powered Eye Health Monitoring System</p>
            </div>
            
            <div class="controls">
                <button class="btn btn-start" onclick="startMonitoring()">🚀 Start Health Monitoring</button>
                <button class="btn btn-stop" onclick="stopMonitoring()">⏹️ Stop Monitoring</button>
                <button class="btn btn-emergency" onclick="emergencyBreak()">🚨 Emergency Break</button>
            </div>
            
            <div class="status-grid">
                <div class="status-card">
                    <h3>📊 Current Status</h3>
                    <div id="currentStatus" class="metric-value">
                        <span class="state-indicator state-idle"></span>IDLE
                    </div>
                    <div class="metric-label">System State</div>
                    
                    <div id="gazeStatus" class="gaze-indicator gaze-away">
                        Looking Away
                    </div>
                </div>
                
                <div class="status-card">
                    <h3>⏱️ Screen Time</h3>
                    <div id="screenTime" class="metric-value">00:00</div>
                    <div class="metric-label">Current Session</div>
                    
                    <div class="progress-bar">
                        <div id="screenTimeProgress" class="progress-fill" style="width: 0%"></div>
                    </div>
                    <small>Next break in: <span id="nextBreak">20:00</span></small>
                </div>
                
                <div class="status-card">
                    <h3>☕ Break Stats</h3>
                    <div id="breakCount" class="metric-value">0</div>
                    <div class="metric-label">Breaks Taken Today</div>
                    
                    <div>Compliance Rate: <span id="complianceRate">100%</span></div>
                </div>
                
                <div class="status-card">
                    <h3>🎯 Gaze Analysis</h3>
                    <div id="gazeConfidence" class="metric-value">0%</div>
                    <div class="metric-label">Detection Confidence</div>
                    
                    <div style="font-size: 0.8rem; margin-top: 10px;">
                        <div>Pitch: <span id="gazePitch">0°</span></div>
                        <div>Yaw: <span id="gazeYaw">0°</span></div>
                        <div>Roll: <span id="gazeRoll">0°</span></div>
                    </div>
                </div>
            </div>
            
            <div class="video-section">
                <h3>📹 Live AI Analysis</h3>
                <img id="videoFeed" class="video-feed" src="/video_feed" alt="Camera feed loading...">
                <p><small>Camera positioned at 45° angle from left corner for optimal gaze detection</small></p>
            </div>
            
            <div class="settings-panel">
                <h3>⚙️ Configuration</h3>
                <div class="setting-item">
                    <label>Screen Time Limit (minutes):</label>
                    <input type="number" id="screenTimeLimit" class="setting-input" value="20" min="5" max="60">
                </div>
                <div class="setting-item">
                    <label>Break Duration (seconds):</label>
                    <input type="number" id="breakDuration" class="setting-input" value="20" min="10" max="120">
                </div>
                <div class="setting-item">
                    <label>Gaze Detection Sensitivity:</label>
                    <input type="range" id="gazeSensitivity" min="0.1" max="1.0" step="0.1" value="0.3" class="setting-input">
                </div>
                <button class="btn btn-start" onclick="updateSettings()">💾 Save Settings</button>
            </div>
        </div>
        
        <script>
            let isMonitoring = false;
            
            function updateDisplay() {
                fetch('/health_stats')
                    .then(response => response.json())
                    .then(data => {
                        // Update status indicator
                        const statusEl = document.getElementById('currentStatus');
                        const stateClass = `state-${data.current_state.replace('_', '-')}`;
                        statusEl.innerHTML = `<span class="state-indicator ${stateClass}"></span>${data.current_state.toUpperCase()}`;
                        
                        // Update screen time
                        const minutes = Math.floor(data.screen_time_seconds / 60);
                        const seconds = data.screen_time_seconds % 60;
                        document.getElementById('screenTime').textContent = 
                            `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
                        
                        // Update progress bar
                        const maxScreenTime = 20 * 60; // 20 minutes
                        const progressPercent = (data.screen_time_seconds / maxScreenTime) * 100;
                        document.getElementById('screenTimeProgress').style.width = `${Math.min(progressPercent, 100)}%`;
                        
                        // Update next break countdown
                        const nextBreakSeconds = data.next_break_in;
                        const nextBreakMinutes = Math.floor(nextBreakSeconds / 60);
                        const nextBreakSecsRem = nextBreakSeconds % 60;
                        document.getElementById('nextBreak').textContent = 
                            `${nextBreakMinutes.toString().padStart(2, '0')}:${nextBreakSecsRem.toString().padStart(2, '0')}`;
                        
                        // Update break stats
                        document.getElementById('breakCount').textContent = data.breaks_taken;
                        document.getElementById('complianceRate').textContent = `${data.compliance_rate.toFixed(1)}%`;
                        
                        // Update gaze analysis
                        const gazeData = data.gaze_data;
                        const gazeStatusEl = document.getElementById('gazeStatus');
                        
                        if (gazeData.looking_at_screen) {
                            gazeStatusEl.textContent = 'Looking at Screen';
                            gazeStatusEl.className = 'gaze-indicator gaze-screen';
                        } else {
                            gazeStatusEl.textContent = 'Looking Away';
                            gazeStatusEl.className = 'gaze-indicator gaze-away';
                        }
                        
                        document.getElementById('gazeConfidence').textContent = `${(gazeData.confidence * 100).toFixed(1)}%`;
                        document.getElementById('gazePitch').textContent = `${gazeData.head_pose[0].toFixed(1)}°`;
                        document.getElementById('gazeYaw').textContent = `${gazeData.head_pose[1].toFixed(1)}°`;
                        document.getElementById('gazeRoll').textContent = `${gazeData.head_pose[2].toFixed(1)}°`;
                    })
                    .catch(error => {
                        console.error('Error updating display:', error);
                    });
            }
            
            function startMonitoring() {
                fetch('/start_monitoring', {method: 'POST'})
                    .then(response => response.json())
                    .then(data => {
                        alert(data.message);
                        isMonitoring = true;
                    });
            }
            
            function stopMonitoring() {
                fetch('/stop_monitoring', {method: 'POST'})
                    .then(response => response.json())
                    .then(data => {
                        alert(data.message);
                        isMonitoring = false;
                    });
            }
            
            function emergencyBreak() {
                fetch('/emergency_break', {method: 'POST'})
                    .then(response => response.json())
                    .then(data => alert(data.message));
            }
            
            function updateSettings() {
                const settings = {
                    screen_time_limit: parseInt(document.getElementById('screenTimeLimit').value),
                    break_duration: parseInt(document.getElementById('breakDuration').value),
                    gaze_sensitivity: parseFloat(document.getElementById('gazeSensitivity').value)
                };
                
                fetch('/update_settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(settings)
                })
                .then(response => response.json())
                .then(data => alert(data.message));
            }
            
            // Update display every second
            setInterval(updateDisplay, 1000);
            updateDisplay(); // Initial update
        </script>
    </body>
    </html>
    '''

@app.route('/video_feed')
def video_feed():
    """Stream the processed video feed"""
    def generate_frames():
        while True:
            if smart_table and smart_table.processing_active:
                frame_bytes = smart_table.get_latest_frame_as_jpeg()
                if frame_bytes:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.033)  # ~30 FPS
    
    return Response(generate_frames(), 
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/health_stats')
def health_stats():
    """Get current health monitoring statistics"""
    if smart_table:
        return jsonify(smart_table.get_health_statistics())
    return jsonify({
        'current_state': 'idle',
        'screen_time_seconds': 0,
        'break_time_seconds': 0,
        'breaks_taken': 0,
        'compliance_rate': 100.0,
        'next_break_in': 1200,
        'gaze_data': {
            'looking_at_screen': False,
            'confidence': 0,
            'head_pose': (0, 0, 0)
        }
    })

@app.route('/start_monitoring', methods=['POST'])
def start_monitoring():
    """Start the health monitoring system"""
    global smart_table
    if smart_table and smart_table.start_health_monitoring():
        return jsonify({'message': 'Health monitoring started successfully!'})
    return jsonify({'message': 'Failed to start monitoring - check ESP32 connection'})

@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    """Stop the health monitoring system"""
    global smart_table
    if smart_table:
        smart_table.stop_health_monitoring()
        return jsonify({'message': 'Health monitoring stopped'})
    return jsonify({'message': 'No monitoring system running'})

@app.route('/emergency_break', methods=['POST'])
def emergency_break():
    """Force an immediate break"""
    global smart_table
    if smart_table:
        smart_table._transition_to_break_needed()
        return jsonify({'message': 'Emergency break activated!'})
    return jsonify({'message': 'No monitoring system running'})

@app.route('/update_settings', methods=['POST'])
def update_settings():
    """Update system configuration"""
    global smart_table
    if smart_table:
        settings = request.json
        smart_table.config['max_screen_time'] = settings.get('screen_time_limit', 20) * 60
        smart_table.config['min_break_time'] = settings.get('break_duration', 20)
        smart_table.config['gaze_threshold'] = settings.get('gaze_sensitivity', 0.3)
        return jsonify({'message': 'Settings updated successfully!'})
    return jsonify({'message': 'No system running'})

def main():
    """Initialize and run the Smart Work Table system"""
    global smart_table
    
    print("🏥 Smart Work Table - AI Eye Health Monitor")
    print("=" * 60)
    print("This system will help you follow the 20-20-20 rule:")
    print("Every 20 minutes, look at something 20 feet away for 20 seconds")
    print("=" * 60)
    
    # Get ESP32 IP address
    esp32_ip = input("Enter your ESP32S3 IP address (or press Enter for 192.168.1.100): ").strip()
    if not esp32_ip:
        esp32_ip = "192.168.1.100"
    
    print(f"\n📡 Connecting to ESP32 camera at {esp32_ip}...")
    print("📹 Camera should be positioned at 45° angle from left corner of table")
    print("   This angle provides optimal gaze direction detection")
    
    # Initialize the smart table system
    smart_table = SmartWorkTableAI(esp32_ip)
    
    print("\n🌐 Starting web dashboard...")
    print("📱 Open your browser and go to: http://localhost:5000")
    print("🎮 Use the dashboard to control health monitoring")
    print("💡 The system will automatically detect when you're working")
    print("🛑 Press Ctrl+C to stop the server")
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Smart Work Table...")
        if smart_table:
            smart_table.stop_health_monitoring()
        print("👋 Stay healthy! Remember the 20-20-20 rule!")

if __name__ == "__main__":
    main()
