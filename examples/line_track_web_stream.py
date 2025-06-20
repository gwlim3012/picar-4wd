#!/usr/bin/env python3
from threading import Thread, Lock
import time
import io
from flask import Flask, Response, redirect, url_for, request
from picamera import PiCamera
import picar_4wd as fc
import signal
import sys

app = Flask(__name__)

# 전역 상태
running = True
tracking_enabled = False
latest_frame = None
frame_lock = Lock()

# 카메라 설정
camera = PiCamera()
camera.resolution = (224, 224)
camera.framerate = 10
camera.vflip = True

TRACK_LINE_SPEED = 5
# Default speed used for keyboard control. Can be adjusted with the
# 6 (increase) and 4 (decrease) keys similar to ``keyboard_control.py``.
keyboard_speed = 50

@app.route('/')
def index():
    state = "ON" if tracking_enabled else "OFF"
    return f'''
    <html>
    <head>
      <title>PiCar Camera</title>
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <style>
        body {{
            background: #111;
            color: #fff;
            font-family: sans-serif;
            margin: 0;
            padding: 0;
            text-align: center;
        }}
        .video-container {{
            width: 560px;
            height: 420px;
            margin: 20px auto;
            overflow: hidden;
            border: 2px solid #555;
        }}
        .video-container img {{
            width: 100%;
            height: auto;
            display: block;
        }}
        .button-panel {{
            width: 560px;
            margin: 30px auto;
            display: flex;
            justify-content: space-between;
        }}
        button {{
            flex: 1;
            margin: 0 15px;
            padding: 16px 0;
            font-size: 18px;
            background: #333;
            color: #fff;
            border: 1px solid #aaa;
            cursor: pointer;
        }}
        .status {{
            margin-top: 10px;
            font-size: 18px;
            color: #0f0;
        }}
      </style>      
    </head>
    <body>
      <h1>PiCar Live Stream</h1>

      <div class="video-container">
        <img src="/camera" />
      </div>

      <div class="button-panel">
        <form method="post" action="/track/start">
          <button>Start</button>
        </form>
        <form method="post" action="/track/stop">
          <button>Stop</button>
        </form>
        <form method="get" action="/keyboard">
          <button>Keyboard Control</button>
        </form>
      </div>

      <div class="status">Tracking: <b>{state}</b></div>
    </body>
    </html>
    '''

@app.route('/camera')
def camera_feed():
    def stream():
        while running:
            with frame_lock:
                if latest_frame:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + latest_frame + b'\r\n')
            time.sleep(0.1) 
    return Response(stream(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/track/start', methods=['POST'])
def start_tracking():
    global tracking_enabled
    tracking_enabled = True
    return redirect(url_for('index'))

@app.route('/track/stop', methods=['POST'])
def stop_tracking():
    global tracking_enabled
    tracking_enabled = False
    fc.stop()
    return redirect(url_for('index'))

@app.route('/keyboard')
def keyboard_page():
    global tracking_enabled
    tracking_enabled = False
    return f'''
    <html>
    <head>
      <title>Keyboard Control</title>
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <style>
        body {{background:#111;color:#fff;font-family:sans-serif;text-align:center;}}
        .video-container {{width:560px;height:420px;margin:20px auto;border:2px solid #555;overflow:hidden;}}
        .video-container img {{width:100%;display:block;}}
        button {{margin-top:20px;padding:10px 20px;font-size:18px;}}
        #speed {{margin-top:10px;font-size:18px;color:#0f0;}}
      </style>
    </head>
    <body>
      <h1>Keyboard Control Mode</h1>
      <div class="video-container"><img src="/camera" /></div>
      <p>Use W/A/S/D to move. 6 to speed up, 4 to slow down. Press Q or B to go back.</p>
      <button onclick="location.href='/'">Back</button>
      <div id="speed">Speed: {keyboard_speed}</div>
      <script>
        let speed = {keyboard_speed};
        function send(cmd){{
          fetch('/control?cmd='+cmd, {{method:'POST'}})
            .then(r => r.text())
            .then(t => {{
              if(t){{
                speed = parseInt(t);
                document.getElementById('speed').innerText = 'Speed: ' + speed;
              }}
            }});
        }}
        document.addEventListener('keydown',function(e){{
          const k=e.key;
          if(k==='w' || k==='W') send('forward');
          else if(k==='s' || k==='S') send('backward');
          else if(k==='a' || k==='A') send('left');
          else if(k==='d' || k==='D') send('right');
          else if(k==='6') send('inc');
          else if(k==='4') send('dec');
          else if(k==='q' || k==='Q' || k==='b' || k==='B') location.href='/';
        }});
        document.addEventListener('keyup',function(e){{
          if(['w','a','s','d','W','A','S','D'].includes(e.key)) send('stop');
        }});
      </script>
    </body>
    </html>
    '''

@app.route('/control', methods=['POST'])
def keyboard_control():
    """Handle keyboard control commands from the web UI."""
    global keyboard_speed
    cmd = request.args.get('cmd', '')
    if cmd == 'inc':
        if keyboard_speed <= 90:
            keyboard_speed += 10
        return str(keyboard_speed)
    elif cmd == 'dec':
        if keyboard_speed >= 20:
            keyboard_speed -= 10
        return str(keyboard_speed)
    elif cmd == 'forward':
        fc.forward(keyboard_speed)
    elif cmd == 'backward':
        fc.backward(keyboard_speed)
    elif cmd == 'left':
        fc.turn_left(keyboard_speed)
    elif cmd == 'right':
        fc.turn_right(keyboard_speed)
    else:
        fc.stop()
    return str(keyboard_speed)

def camera_loop():
    global latest_frame
    stream = io.BytesIO()
    frame_counter = 0
    for _ in camera.capture_continuous(stream, format='jpeg', use_video_port=True, quality=50):
        if not running:
            break
        frame_counter += 1
        stream.seek(0)

        # # 프레임 스킵 (3개 중 1개만 처리)
        # if frame_counter % 2 != 0:
        #     stream.truncate()
        #     continue

        frame = stream.read()
        with frame_lock:
            latest_frame = frame
        stream.seek(0)
        stream.truncate()
        time.sleep(0.05)


def track_line_loop():
    while running:
        if tracking_enabled:
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
                    # Continue moving forward if the line is temporarily lost
                    fc.forward(TRACK_LINE_SPEED)
            except OSError as e:
                print(f"[Line Sensor] error: {e}")
        else:
            fc.stop()
        time.sleep(0.02)

def signal_handler(sig, frame):
    global running
    print("SIGINT received. Exiting...")
    running = False
    fc.stop()
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    fc.start_speed_thread()

    Thread(target=camera_loop, daemon=True).start()
    Thread(target=track_line_loop, daemon=True).start()

    app.run(host='0.0.0.0', port=8000, threaded=True)