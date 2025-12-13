"""
Flask application with API routes - OPTIMIZED & ACCURATE VERSION
"""
from flask import Flask, Response, jsonify, request
import cv2
import mediapipe as mp
import numpy as np
import time
import json
import os
import random
import string
import requests
import certifi 
from collections import deque
from datetime import datetime
from flask_cors import CORS
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from flask_mail import Mail, Message
# [Change] Import SocketIO
from flask_socketio import SocketIO, emit 

# --- IMPORT CUSTOM AI MODULE (CRITICAL FOR ACCURACY) ---
from ai_engine import AIEngine

# --- 0. CONFIGURATION ---
load_dotenv()

app = Flask(__name__)
CORS(app)
bcrypt = Bcrypt(app)

# [Change] Initialize SocketIO with async_mode to ensure non-blocking behavior
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# --- 1. MAIL CONFIGURATION ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
mail = Mail(app)

# --- 2. DATABASE SETUP ---
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "physiocheck_db"

try:
    client = MongoClient(
        MONGO_URI, 
        serverSelectionTimeoutMS=5000, 
        tls=True,
        tlsCAFile=certifi.where(),       
        tlsAllowInvalidCertificates=True 
    )
    client.admin.command('ping') 
    db = client[DB_NAME]
    users_collection = db['users']
    otp_collection = db['otps']
    sessions_collection = db['sessions']
    print(f"✅ Connected to MongoDB Cloud: {DB_NAME}")
except Exception as e:
    print(f"⚠️ DB Error: {e}")
    db = None
    users_collection = None
    otp_collection = None
    sessions_collection = None

# Global session instance
workout_session = None

def init_session():
    """Initialize workout session logic"""
    global workout_session
    from workout_session import WorkoutSession
    workout_session = WorkoutSession()

def generate_video_frames():
    """Generator for video streaming & WebSocket Data Push"""
    from constants import WorkoutPhase
    
    if workout_session is None: return
    
    while workout_session.phase != WorkoutPhase.INACTIVE:
        # process_frame handles MediaPipe inference and UI drawing
        frame, should_continue = workout_session.process_frame() 
        
        if not should_continue or frame is None:
            break
        
        # [Critical Fix] Emit data and SLEEP to allow other requests (like Stop) to process
        socketio.emit('workout_update', workout_session.get_state_dict())
        socketio.sleep(0.01) # Yield control for 10ms

        # Encode frame
        ret, buffer = cv2.imencode('.jpg', frame)
        if ret:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

# --- 3. SOCKET EVENTS (NEW) ---

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# [Change] Socket-based Stop command (More reliable than HTTP during streaming)
@socketio.on('stop_session')
def handle_stop_session(data):
    print("Received stop command via Socket")
    global workout_session
    if not workout_session: return
    
    user_email = data.get('email')
    exercise_name = data.get('exercise', 'Freestyle')
    
    try:
        report = workout_session.get_final_report()
        workout_session.stop()
        
        if user_email and sessions_collection is not None:
            right_summary = report['summary']['RIGHT']
            left_summary = report['summary']['LEFT']
            
            session_doc = {
                'email': user_email,
                'date': datetime.now().strftime("%Y-%m-%d"),
                'timestamp': time.time(),
                'exercise': exercise_name,
                'duration': report.get('duration', 0),
                'total_reps': right_summary['total_reps'] + left_summary['total_reps'],
                'right_reps': right_summary['total_reps'],
                'left_reps': left_summary['total_reps'],
                'total_errors': right_summary['error_count'] + left_summary['error_count']
            }
            sessions_collection.insert_one(session_doc)
            print(f"💾 Saved '{exercise_name}' for {user_email}")
            
        emit('session_stopped', {'status': 'success'})
    except Exception as e:
        print(f"Error stopping session: {e}")

# --- 4. HTTP ROUTES ---

@app.route('/api/auth/send-otp', methods=['POST'])
def send_otp():
    if users_collection is None: return jsonify({'error': 'Database unavailable'}), 503
    data = request.json
    email = data.get('email')
    if users_collection.find_one({'email': email}):
        return jsonify({'error': 'Email is already registered. Please login.'}), 400
    otp = ''.join(random.choices(string.digits, k=6))
    otp_collection.update_one({'email': email}, {'$set': {'otp': otp, 'created_at': time.time()}}, upsert=True)
    try:
        msg = Message('PhysioCheck Verification Code', sender=app.config['MAIL_USERNAME'], recipients=[email])
        msg.body = f"Your verification code is: {otp}"
        mail.send(msg)
        return jsonify({'message': 'OTP sent successfully'}), 200
    except Exception as e:
        return jsonify({'error': 'Failed to send email.'}), 500

@app.route('/api/auth/signup-verify', methods=['POST'])
def signup_verify():
    if users_collection is None: return jsonify({'error': 'Database unavailable'}), 503
    data = request.json
    record = otp_collection.find_one({'email': data.get('email')})
    if not record or record['otp'] != data.get('otp'):
        return jsonify({'error': 'Invalid or expired OTP'}), 400
    hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    user = {'name': data['name'], 'email': data['email'], 'password': hashed_password, 'role': data.get('role', 'patient'), 'created_at': time.time(), 'auth_method': 'email'}
    users_collection.insert_one(user)
    otp_collection.delete_one({'email': data['email']}) 
    return jsonify({'message': 'User verified', 'user': {'name': user['name'], 'role': user['role']}}), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    if users_collection is None: return jsonify({'error': 'Database unavailable'}), 503
    data = request.json
    user = users_collection.find_one({'email': data['email']})
    if user and bcrypt.check_password_hash(user['password'], data['password']):
        return jsonify({'message': 'Login successful', 'role': user['role'], 'name': user['name'], 'email': user['email']}), 200
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/auth/google', methods=['POST'])
def google_auth():
    if users_collection is None: return jsonify({'error': 'Database unavailable'}), 503
    token = request.json.get('token')
    try:
        resp = requests.get('https://www.googleapis.com/oauth2/v1/userinfo', params={'access_token': token, 'alt': 'json'})
        if not resp.ok: return jsonify({'error': 'Invalid Google Token'}), 401
        google_user = resp.json()
        email = google_user['email']
        user = users_collection.find_one({'email': email})
        if not user:
            user = {'name': google_user['name'], 'email': email, 'password': '', 'role': 'patient', 'created_at': time.time(), 'auth_method': 'google'}
            users_collection.insert_one(user)
        return jsonify({'message': 'Google login successful', 'role': user['role'], 'name': user['name'], 'email': user['email']}), 200
    except Exception as e:
        return jsonify({'error': 'Authentication failed'}), 500

@app.route('/api/user/stats', methods=['POST'])
def get_user_stats():
    if sessions_collection is None: return jsonify({'error': 'DB Error'}), 503
    email = request.json.get('email')
    user_sessions = list(sessions_collection.find({'email': email}))
    total_reps = sum(s.get('total_reps', 0) for s in user_sessions)
    accuracy = 100
    if total_reps > 0: accuracy = max(0, 100 - int((sum(s.get('total_errors', 0) for s in user_sessions) / total_reps) * 20))
    return jsonify({'total_workouts': len(user_sessions), 'total_reps': total_reps, 'accuracy': accuracy, 'graph_data': [{'date': s.get('date'), 'reps': s.get('total_reps', 0)} for s in user_sessions[-7:]]})

@app.route('/api/user/analytics_detailed', methods=['POST'])
def get_analytics_detailed():
    if sessions_collection is None: return jsonify({'error': 'DB Error'}), 503
    return jsonify(AIEngine.get_detailed_analytics(list(sessions_collection.find({'email': request.json.get('email')}).sort('timestamp', 1))))

@app.route('/api/user/ai_prediction', methods=['POST'])
def get_ai_prediction():
    if sessions_collection is None: return jsonify({'error': 'DB Error'}), 503
    sessions = list(sessions_collection.find({'email': request.json.get('email')}).sort('timestamp', 1))
    return jsonify(AIEngine.get_recovery_prediction(sessions) if sessions else {'error': 'No data'})

@app.route('/start_tracking')
def start_tracking():
    global workout_session
    if workout_session:
        try: workout_session.stop()
        except: pass
    try:
        init_session()
        workout_session.start()
        return jsonify({'status': 'success', 'message': 'Session started'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Failed to start: {e}'}), 500

# Keep this for backward compatibility, but we use Socket for stopping now
@app.route('/stop_tracking', methods=['POST'])
def stop_tracking_http():
    global workout_session
    if not workout_session: return jsonify({'status': 'inactive'})
    try:
        workout_session.stop()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error'}), 500

@app.route('/video_feed')
def video_feed():
    return Response(generate_video_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/report_data')
def report_data():
    if workout_session: return jsonify(workout_session.get_final_report())
    return jsonify({'error': 'No session data available'})

if __name__ == '__main__':
    init_session()
    # [Critical] Use socketio.run
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)