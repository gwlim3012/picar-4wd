#!/usr/bin/env python3
"""Remote detection server using a TensorFlow Lite object detection model.

Run this script on your PC. The Raspberry Pi sends JPEG frames to the ``/detect``
endpoint while continuing to handle line tracking locally.  The server performs
object detection, stores an annotated JPEG for viewing and returns the
detection results as JSON.

Dependencies::

    pip install flask opencv-python numpy tflite-runtime
"""
from flask import Flask, Response, request, jsonify
import cv2
import numpy as np
from threading import Lock
import time
from tflite_runtime.interpreter import Interpreter

app = Flask(__name__)

# Path to your trained TFLite model
MODEL_PATH = "model.tflite"

# Initialize the interpreter once
interpreter = Interpreter(model_path=MODEL_PATH)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
IN_H = input_details[0]["shape"][1]
IN_W = input_details[0]["shape"][2]
IN_DTYPE = input_details[0]["dtype"]

# Latest annotated JPEG for the MJPEG stream
latest_jpeg = None
frame_lock = Lock()


def run_model(frame: np.ndarray):
    """Run the TFLite model on ``frame`` and return bounding boxes.

    The function assumes an object detection model with four outputs in the
    usual order: ``boxes``, ``classes``, ``scores`` and ``count``.  The returned
    list contains dictionaries with ``box`` coordinates in pixel space and the
    corresponding ``score``.
    """
    resized = cv2.resize(frame, (IN_W, IN_H))
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    inp = rgb.astype(IN_DTYPE)
    if IN_DTYPE == np.float32:
        inp = inp / 255.0
    inp = np.expand_dims(inp, 0)
    interpreter.set_tensor(input_details[0]['index'], inp)
    interpreter.invoke()

    boxes = interpreter.get_tensor(output_details[0]['index'])[0]
    classes = interpreter.get_tensor(output_details[1]['index'])[0]
    scores = interpreter.get_tensor(output_details[2]['index'])[0]
    count = int(interpreter.get_tensor(output_details[3]['index'])[0])

    h, w = frame.shape[:2]
    results = []
    for i in range(count):
        if scores[i] < 0.5:
            continue
        y1, x1, y2, x2 = boxes[i]
        results.append({
            "box": [int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)],
            "score": float(scores[i]),
            "class_id": int(classes[i]),
        })
    return results


@app.route('/detect', methods=['POST'])
def detect_endpoint():
    file = request.files.get("image")
    if file:
        data = np.frombuffer(file.read(), np.uint8)
    else:
        data = np.frombuffer(request.get_data(), np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"error": "decode failed"}), 400

    results = run_model(frame)
    for det in results:
        x1, y1, x2, y2 = det["box"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"{det['score']:.2f}", (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    ret, jpeg = cv2.imencode('.jpg', frame)
    if ret:
        with frame_lock:
            global latest_jpeg
            latest_jpeg = jpeg.tobytes()

    return jsonify({
        "detected": bool(results),
        "results": results,
    })


@app.route('/')
def index():
    return (
        "<html><body style='background:#111;color:#fff;text-align:center'>"
        "<h1>Detection Stream</h1>"
        "<img src='/stream'/>"
        "</body></html>"
    )


@app.route('/stream')
def stream():
    def gen():
        while True:
            with frame_lock:
                frame = latest_jpeg
            if frame:
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.05)

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
