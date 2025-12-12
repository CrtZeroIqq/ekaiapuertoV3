"""
EKAIA Puerto - RTSP Stream Manager
Handles RTSP camera streams with reconnection, buffering, and detection overlay
"""
import cv2
import numpy as np
from typing import Optional, Generator, Callable, List, Tuple
import threading
import time
from queue import Queue, Full
import logging

logger = logging.getLogger(__name__)


class RTSPStream:
    """Thread-safe RTSP stream handler with auto-reconnect and detection overlay"""

    def __init__(
        self,
        rtsp_url: str,
        name: str = "camera",
        buffer_size: int = 2,
        reconnect_delay: int = 5
    ):
        """
        Args:
            rtsp_url: RTSP URL
            name: Stream name for logging
            buffer_size: Frame buffer size (small for low latency)
            reconnect_delay: Seconds to wait before reconnect
        """
        self.rtsp_url = rtsp_url
        self.name = name
        self.buffer_size = buffer_size
        self.reconnect_delay = reconnect_delay

        self.cap: Optional[cv2.VideoCapture] = None
        self.frame_queue = Queue(maxsize=buffer_size)
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.last_frame: Optional[np.ndarray] = None
        self.last_frame_time = 0
        
        # Detection overlay data
        self.current_detections: List[dict] = []
        self.tripwire_lines: List[dict] = []
        self.detection_count: int = 0
        self.last_plate_text: Optional[str] = None
        self._overlay_lock = threading.Lock()

    def connect(self) -> bool:
        """Connect to RTSP stream"""
        try:
            self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)

            # Set buffer size to minimum for low latency
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            # TCP transport for reliability (optional)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'H264'))

            if not self.cap.isOpened():
                logger.error(f"[{self.name}] Failed to open stream")
                return False

            logger.info(f"[{self.name}] Connected to {self.rtsp_url}")
            return True

        except Exception as e:
            logger.error(f"[{self.name}] Connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from stream"""
        if self.cap:
            self.cap.release()
            self.cap = None
        logger.info(f"[{self.name}] Disconnected")

    def _read_loop(self):
        """Background thread for reading frames"""
        consecutive_failures = 0
        max_failures = 10

        while self.is_running:
            if not self.cap or not self.cap.isOpened():
                logger.warning(f"[{self.name}] Stream disconnected, reconnecting...")
                self.disconnect()
                time.sleep(self.reconnect_delay)

                if self.connect():
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        logger.error(f"[{self.name}] Max reconnection attempts reached")
                        break
                continue

            ret, frame = self.cap.read()

            if not ret:
                consecutive_failures += 1
                logger.warning(f"[{self.name}] Failed to read frame ({consecutive_failures})")

                if consecutive_failures >= max_failures:
                    logger.error(f"[{self.name}] Too many failures, reconnecting...")
                    self.disconnect()
                    consecutive_failures = 0

                time.sleep(0.1)
                continue

            consecutive_failures = 0
            self.last_frame = frame.copy()
            self.last_frame_time = time.time()

            # Put frame in queue (drop old frames if full)
            try:
                self.frame_queue.put(frame, block=False)
            except Full:
                # Remove old frame and add new one
                try:
                    self.frame_queue.get_nowait()
                    self.frame_queue.put(frame, block=False)
                except:
                    pass

    def start(self):
        """Start stream reading thread"""
        if self.is_running:
            logger.warning(f"[{self.name}] Stream already running")
            return

        if not self.connect():
            raise RuntimeError(f"Failed to connect to {self.rtsp_url}")

        self.is_running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()
        logger.info(f"[{self.name}] Stream started")

    def stop(self):
        """Stop stream reading thread"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.disconnect()
        logger.info(f"[{self.name}] Stream stopped")

    def read(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """
        Read latest frame
        Returns None if no frame available
        """
        try:
            frame = self.frame_queue.get(timeout=timeout)
            return frame
        except:
            # Return last known frame if available
            return self.last_frame

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get last captured frame (non-blocking)"""
        return self.last_frame

    def is_alive(self) -> bool:
        """Check if stream is receiving frames"""
        if not self.is_running:
            return False

        # Check if we received a frame in the last 10 seconds
        if self.last_frame_time > 0:
            age = time.time() - self.last_frame_time
            return age < 10

        return False

    # ==========================================
    # DETECTION OVERLAY METHODS
    # ==========================================
    
    def update_detections(self, detections: List[dict]):
        """
        Update current detections for overlay
        detections: list of {"bbox": [x1,y1,x2,y2], "class": str, "confidence": float, "plate_text": str|None}
        """
        with self._overlay_lock:
            self.current_detections = detections
            self.detection_count = len(detections)
            # Get last plate text
            for d in detections:
                if d.get("plate_text"):
                    self.last_plate_text = d["plate_text"]
    
    def update_tripwire_lines(self, lines: List[dict]):
        """
        Update tripwire lines for overlay
        lines: list of {"p1": (x1,y1), "p2": (x2,y2), "name": str, "direction": str}
        """
        with self._overlay_lock:
            self.tripwire_lines = lines
    
    def _draw_overlay(self, frame: np.ndarray) -> np.ndarray:
        """Draw detections and tripwire lines on frame"""
        overlay_frame = frame.copy()
        
        with self._overlay_lock:
            # Draw tripwire lines
            for line in self.tripwire_lines:
                p1 = tuple(line["p1"])
                p2 = tuple(line["p2"])
                
                # Draw thick red line
                cv2.line(overlay_frame, p1, p2, (0, 0, 255), 3)
                
                # Draw direction arrow
                mid_x = (p1[0] + p2[0]) // 2
                mid_y = (p1[1] + p2[1]) // 2
                
                direction = line.get("direction", "down")
                arrow_len = 30
                
                if direction == "down":
                    arrow_end = (mid_x, mid_y + arrow_len)
                elif direction == "up":
                    arrow_end = (mid_x, mid_y - arrow_len)
                elif direction == "right":
                    arrow_end = (mid_x + arrow_len, mid_y)
                elif direction == "left":
                    arrow_end = (mid_x - arrow_len, mid_y)
                else:
                    arrow_end = (mid_x, mid_y + arrow_len)
                
                cv2.arrowedLine(overlay_frame, (mid_x, mid_y), arrow_end, (0, 0, 255), 2, tipLength=0.4)
                
                # Label
                label = f"{line.get('name', 'tripwire')} ({direction})"
                cv2.putText(overlay_frame, label, (p1[0], p1[1] - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            
            # Draw detection boxes
            for det in self.current_detections:
                bbox = det.get("bbox", [])
                if len(bbox) != 4:
                    continue
                
                x1, y1, x2, y2 = map(int, bbox)
                conf = det.get("confidence", 0)
                cls_name = det.get("class", "object")
                plate_text = det.get("plate_text")
                
                # Color based on class
                if cls_name in ["plate", "license_plate", "patente"]:
                    color = (0, 255, 255)  # Yellow for plates
                else:
                    color = (0, 255, 0)  # Green for vehicles
                
                # Draw bounding box
                cv2.rectangle(overlay_frame, (x1, y1), (x2, y2), color, 2)
                
                # Label with class and confidence
                if plate_text:
                    label = f"{plate_text} ({conf:.0%})"
                else:
                    label = f"{cls_name} {conf:.0%}"
                
                # Background for text
                (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                cv2.rectangle(overlay_frame, (x1, y1 - text_h - 10), (x1 + text_w + 5, y1), color, -1)
                cv2.putText(overlay_frame, label, (x1 + 2, y1 - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
            
            # Status overlay (top left)
            status_text = f"Detecciones: {self.detection_count}"
            cv2.putText(overlay_frame, status_text, (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            if self.last_plate_text:
                plate_status = f"Ultima patente: {self.last_plate_text}"
                cv2.putText(overlay_frame, plate_status, (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        
        return overlay_frame

    def generate_jpeg_stream(self, quality: int = 80, with_overlay: bool = True) -> Generator[bytes, None, None]:
        """
        Generate MJPEG stream for HTTP streaming
        Yields JPEG frames with optional detection overlay
        """
        while self.is_running:
            frame = self.read(timeout=1.0)

            if frame is None:
                # Send blank frame if no data
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    blank, "No Signal", (200, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2
                )
                frame = blank
            elif with_overlay:
                # Draw detections and tripwire
                frame = self._draw_overlay(frame)

            # Encode as JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            frame_bytes = buffer.tobytes()

            # MJPEG format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')


class StreamManager:
    """Manages multiple RTSP streams"""

    def __init__(self):
        self.streams: dict[str, RTSPStream] = {}

    def add_stream(self, name: str, rtsp_url: str) -> RTSPStream:
        """Add and start a new stream"""
        if name in self.streams:
            logger.warning(f"Stream {name} already exists")
            return self.streams[name]

        stream = RTSPStream(rtsp_url, name)
        stream.start()
        self.streams[name] = stream
        return stream

    def get_stream(self, name: str) -> Optional[RTSPStream]:
        """Get stream by name"""
        return self.streams.get(name)

    def stop_all(self):
        """Stop all streams"""
        for stream in self.streams.values():
            stream.stop()
        self.streams.clear()
    
    def update_stream_detections(self, name: str, detections: List[dict]):
        """Update detections for a specific stream"""
        stream = self.get_stream(name)
        if stream:
            stream.update_detections(detections)
    
    def update_stream_tripwire(self, name: str, lines: List[dict]):
        """Update tripwire lines for a specific stream"""
        stream = self.get_stream(name)
        if stream:
            stream.update_tripwire_lines(lines)


# Global stream manager
_stream_manager = None


def get_stream_manager() -> StreamManager:
    """Get stream manager singleton"""
    global _stream_manager
    if _stream_manager is None:
        _stream_manager = StreamManager()
    return _stream_manager