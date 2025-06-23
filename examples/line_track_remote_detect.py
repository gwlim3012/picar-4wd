#!/usr/bin/env python3
"""Line tracking with remote object detection.

This script streams camera frames from the Raspberry Pi and sends them to a
remote detection server. Line tracking continues on the Pi. When detection is
enabled and the server reports ``detected=True``, the car stops.

Use the included ``remote_detection_server.py`` on your computer. Update
``DETECT_URL`` below with the server's address and make sure it points to a
server running your trained TFLite model.
"""
import time
import io
import signal
import sys
from threading import Thread, Lock

import requests
from flask import Flask, Response, redirect, url_for
from picamera import PiCamera
import picar_4wd as fc

# Configuration
TRACK_LINE_SPEED = 20
DETECT_URL = "http://localhost:5000/detect"  # change to your PC's address

# Global state
running = True
tracking_enabled = False
detection_enabled = False
detected = False
latest_frame = None
frame_lock = Lock()

app = Flask(__name__)

# Camera setup
camera = PiCamera()
camera.resolution = (160, 120)
camera.framerate = 15
camera.vflip = True


def send_for_detection(jpeg: bytes) -> bool:
    """Send ``jpeg`` to the remote server and return detection result."""
    try:
        resp = requests.post(
            DETECT_URL,
            files={"image": ("frame.jpg", jpeg, "image/jpeg")},
            timeout=5,
        )
        data = resp.json()
        return data.get("detected", False)
    except Exception as e:
        print(f"[detect] error: {e}")
        return False


@app.route('/')
def index():
    t_state = "ON" if tracking_enabled else "OFF"
    d_state = "ON" if detection_enabled else "OFF"
    found = "YES" if detected else "NO"
    return f'''<html><head><title>Remote Detect</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>body{{background:#111;color:#fff;text-align:center;font-family:sans-serif}}
             .video{{width:560px;height:420px;margin:20px auto;border:2px solid #555}}
             img{{width:100%;height:auto}} button{{margin:5px;padding:14px 0;font-size:18px;background:#333;color:#fff;border:1px solid #aaa}}
      </style></head><body>
      <h1>PiCar Stream</h1>
      <div class="video"><img src="/camera"/></div>
      <form method="post" action="/track/start"><button>Track Start</button></form>
      <form method="post" action="/track/stop"><button>Track Stop</button></form>
      <form method="post" action="/detect/start"><button>Detect Start</button></form>
      <form method="post" action="/detect/stop"><button>Detect Stop</button></form>
      <div>Tracking: {t_state} | Detection: {d_state} | Red: {found}</div>
    </body></html>'''


@app.route('/camera')
def camera_feed():
    def stream():
        while running:
            with frame_lock:
                frame = latest_frame
            if frame:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.05)
    return Response(stream(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/track/start', methods=['POST'])
def start_track():
    global tracking_enabled
    tracking_enabled = True
    return redirect(url_for('index'))


@app.route('/track/stop', methods=['POST'])
def stop_track():
    global tracking_enabled
    tracking_enabled = False
    fc.stop()
    return redirect(url_for('index'))


@app.route('/detect/start', methods=['POST'])
def start_detect():
    global detection_enabled
    detection_enabled = True
    return redirect(url_for('index'))


@app.route('/detect/stop', methods=['POST'])
def stop_detect():
    global detection_enabled
    detection_enabled = False
    return redirect(url_for('index'))


def camera_loop():
    """Capture frames and optionally send them for detection."""
    global latest_frame, detected
    stream = io.BytesIO()
    for _ in camera.capture_continuous(stream, format='jpeg', use_video_port=True, quality=30):
        if not running:
            break
        stream.seek(0)
        jpeg = stream.read()
        with frame_lock:
            latest_frame = jpeg
        if detection_enabled:
            detected = send_for_detection(jpeg)
        else:
            detected = False
        stream.seek(0)
        stream.truncate()
        time.sleep(0.05)
    camera.close()


def track_line_loop():
    """Perform line tracking unless detection stops the car."""
    global running
    while running:
        if not tracking_enabled:
            fc.stop()
            time.sleep(0.02)
            continue
        if detection_enabled and detected:
            fc.stop()
            time.sleep(0.05)
            continue
        try:
            gs_list = fc.get_grayscale_list()
            status = fc.get_line_status(1300, gs_list)
            if status == 0:
                fc.forward(TRACK_LINE_SPEED)
            elif status == -1:
                fc.turn_left(TRACK_LINE_SPEED)
            elif status == 1:
                fc.turn_right(TRACK_LINE_SPEED)
            else:
                fc.forward(TRACK_LINE_SPEED)
        except OSError as e:
            print(f"[Line Sensor] error: {e}")
        time.sleep(0.02)
    fc.stop()


def signal_handler(sig, frame):
    global running
    running = False
    fc.stop()
    sys.exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    fc.start_speed_thread()

    Thread(target=camera_loop, daemon=True).start()
    Thread(target=track_line_loop, daemon=True).start()

    app.run(host='0.0.0.0', port=8000, threaded=True)
