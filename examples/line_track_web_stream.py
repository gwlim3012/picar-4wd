#!/usr/bin/env python3
"""
Line tracking with a live PiCamera stream.
Requires flask:
    pip3 install flask
"""
from threading import Thread
import time
import io
from flask import Flask, Response
from picamera import PiCamera
import picar_4wd as fc

app = Flask(__name__)

# Setup camera resolution
camera = PiCamera()
camera.resolution = (640, 480)

TRACK_LINE_SPEED = 20


def generate_frames():
    stream = io.BytesIO()
    for _ in camera.capture_continuous(stream, format='jpeg', use_video_port=True):
        stream.seek(0)
        frame = stream.read()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        stream.seek(0)
        stream.truncate()


@app.route('/camera')
def camera_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


def track_line_loop():
    try:
        while True:
            gs_list = fc.get_grayscale_list()
            status = fc.get_line_status(400, gs_list)
            if status == 0:
                fc.forward(TRACK_LINE_SPEED)
            elif status == -1:
                fc.turn_left(TRACK_LINE_SPEED)
            elif status == 1:
                fc.turn_right(TRACK_LINE_SPEED)
            time.sleep(0.01)
    finally:
        fc.stop()


if __name__ == '__main__':
    t = Thread(target=track_line_loop)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=8000, threaded=True)
