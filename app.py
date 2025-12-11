"""
Flask application with API routes
"""
from flask import Flask, Response, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Global session instance
workout_session = None

def init_session():
    """Initialize workout session"""
    global workout_session
    from workout_session import WorkoutSession
    workout_session = WorkoutSession()

def generate_video_frames():
    """Generator for video streaming"""
    from constants import WorkoutPhase
    
    while workout_session.phase != WorkoutPhase.INACTIVE:
        frame, should_continue = workout_session.process_frame()
        
        if not should_continue or frame is None:
            break
        
        ret, buffer = cv2.imencode('.jpg', frame)
        if ret:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/start_tracking')
def start_tracking():
    """Start new workout session"""
    from constants import WorkoutPhase
    
    if workout_session and workout_session.phase != WorkoutPhase.INACTIVE:
        return jsonify({'status': 'already_active'}), 400
    
    try:
        if workout_session is None:
            init_session()
        workout_session.start()
        return jsonify({'status': 'success', 'message': 'Calibration started'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/stop_tracking')
def stop_tracking():
    """Stop current workout session"""
    if workout_session:
        workout_session.stop()
    return jsonify({'status': 'success'})

@app.route('/video_feed')
def video_feed():
    """Stream video frames"""
    return Response(generate_video_frames(), 
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/data_feed')
def data_feed():
    """Get current workout state"""
    if workout_session:
        return jsonify(workout_session.get_state_dict())
    return jsonify({'status': 'INACTIVE'})

@app.route('/report_data')
def report_data():
    """Get final session report"""
    if workout_session:
        return jsonify(workout_session.get_final_report())
    return jsonify({'error': 'No session data available'})

if __name__ == '__main__':
    import cv2  # Import here for app.py
    init_session()
    app.run(host='0.0.0.0', port=5000, debug=True)