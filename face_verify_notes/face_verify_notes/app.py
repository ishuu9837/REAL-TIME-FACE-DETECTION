from flask import Flask, render_template, request, jsonify, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from pymongo import MongoClient
import gridfs
import requests
import face_recognition
import numpy as np
from io import BytesIO
from PIL import Image
from bson import ObjectId
import base64
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = 'uploads/'


client = MongoClient('mongodb://localhost:27017/')
db = client['task_manager']
tasks_collection = db['tasks']
time_spent_collection = db['time_spent']
users_collection = db['users']
fs = gridfs.GridFS(db)


if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def save_image_from_base64(image_data, filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    with open(filepath, 'wb') as file:
        file.write(image_data)
    return filepath

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/loginrender')
def loginrender():
    return render_template('login.html')

@app.route('/signuprender')
def signuprender():
    return render_template('signup.html')

@app.route('/signup', methods=['POST'])
def signup():
    try:
        full_name = request.form.get('fullName')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        image_id = None

        if 'capturedImage' in request.files:
            captured_image_data = request.files['capturedImage'].read()
            if captured_image_data:
                image_filename = f"{email}_captured.jpg"
                image_filepath = save_image_from_base64(captured_image_data, image_filename)
                image_id = str(ObjectId())
                with open(image_filepath, 'rb') as file:
                    fs.put(file, filename=email, metadata={'image_id': image_id})
                os.remove(image_filepath)  

        if 'uploadedImage' in request.files:
            uploaded_file = request.files['uploadedImage']
            if uploaded_file.filename:
                filename = secure_filename(uploaded_file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                uploaded_file.save(filepath)
                image_id = str(ObjectId())
                with open(filepath, 'rb') as file:
                    fs.put(file, filename=email, metadata={'image_id': image_id})
                os.remove(filepath)  

        hashed_password = generate_password_hash(password)
        user_data = {
            'name': full_name,
            'email': email,
            'phone': phone,
            'password': hashed_password,
            'image_id': image_id
        }
        users_collection.insert_one(user_data)
        return jsonify({'success': True, 'message': 'Signup successful!'})

    except Exception as e:
        print(f"Signup Error: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email')
        login_type = data.get('loginOption')
        password = data.get('password')
        image_data = data.get('image')

        if not email or not login_type:
            return jsonify({'success': False, 'message': 'Email and login type are required.'}), 400

        user = users_collection.find_one({'email': email})

        if not user:
            return jsonify({'success': False, 'message': 'User not found. Please sign up first.'}), 404

        if login_type == 'password':
            if not password:
                return jsonify({'success': False, 'message': 'Please enter your password.'}), 400

            if check_password_hash(user['password'], password):
                session['user_email'] = email
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'message': 'Invalid password.'}), 401

        elif login_type == 'face':
            if not image_data:
                return jsonify({'success': False, 'message': 'No image provided for face login.'}), 400

            try:
                image_data = image_data.split(",")[1]
                image = Image.open(BytesIO(base64.b64decode(image_data)))
                if image.mode != 'RGB':
                    image = image.convert('RGB')

                rgb_image = np.array(image)
                captured_face_encodings = face_recognition.face_encodings(rgb_image)

                if not captured_face_encodings:
                    return jsonify({'success': False, 'message': 'No face detected in the provided image.'}), 400

                captured_face_encoding = captured_face_encodings[0]

                if user.get('image_id'):
                    stored_image_id = user['image_id']
                    file_doc = db.fs.files.find_one({"metadata.image_id": stored_image_id})
                    stored_image = fs.get(file_doc['_id']).read()
                    stored_image_pil = Image.open(BytesIO(stored_image))
                    if stored_image_pil.mode != 'RGB':
                        stored_image_pil = stored_image_pil.convert('RGB')

                    stored_image_np = np.array(stored_image_pil)
                    stored_face_encodings = face_recognition.face_encodings(stored_image_np)

                    if not stored_face_encodings:
                        return jsonify({'success': False, 'message': 'No face found in stored image.'}), 400

                    stored_face_encoding = stored_face_encodings[0]
                    matches = face_recognition.compare_faces([stored_face_encoding], captured_face_encoding)

                    if matches[0]:
                        session['user_email'] = email
                        return jsonify({'success': True})
                    else:
                        return jsonify({'success': False, 'message': 'Face not matched.'}), 401
                else:
                    return jsonify({'success': False, 'message': 'No image found for face recognition.'}), 404

            except Exception as e:
                print(f"Face Recognition Error: {e}")
                return jsonify({'success': False, 'message': 'Error processing image.'}), 500

        else:
            return jsonify({'success': False, 'message': 'Invalid login type.'}), 400

    except Exception as e:
        print(f"Login Error: {e}")
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 500

@app.route('/main')
def main():
    user_email = session.get('user_email')
    if not user_email:
        return jsonify({'success': False, 'message': 'User not logged in.'}), 401

    user = users_collection.find_one({'email': user_email})
    if not user:
        return jsonify({'success': False, 'message': 'User not found.'}), 404

    username = user.get('name', 'User')
    return render_template('main.html', user_email=user_email, username=username.title())

@app.route('/get_time_spent/<user_id>', methods=['GET'])
def get_time_spent(user_id):
    user_time = time_spent_collection.find_one({'user_id': user_id})
    if user_time:
        return jsonify({'time_spent': user_time.get('time_spent', 0)})
    return jsonify({'time_spent': 0})

@app.route('/update_time_spent', methods=['POST'])
def update_time_spent():
    data = request.get_json() 
    user_id = data.get('user_id')
    time_spent = data.get('time_spent', 0)

    if not user_id:
        return jsonify({'success': False, 'message': 'User ID is required.'}), 400

    if time_spent is None or time_spent < 0:
        return jsonify({'success': False, 'message': 'Invalid time spent'}), 400

    
    time_spent_collection.update_one(
        {'user_id': user_id},
        {'$inc': {'time_spent': time_spent}},
        upsert=True
    )

    return jsonify({'success': True})


@app.route('/create_task', methods=['POST'])
def create_task():
    data = request.get_json()
    user_id = data.get('user_id')
    title = data.get('task_name')
    description = data.get('task_description')
    deadline = data.get('task_deadline')
    created_at = data.get('created_at')

    if not user_id or not title or not description or not deadline:
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    task_id = tasks_collection.insert_one({
        'user_id': user_id,
        'title': title,
        'description': description,
        'deadline': deadline,
        'completion_status': False,
        'created_at': created_at
    }).inserted_id
    task_id=str(task_id)
    print(task_id)

    return jsonify({'success': True, 'title':title, 'task_id': task_id})

@app.route('/get_tasks/<user_id>', methods=['GET'])
def get_tasks(user_id):
    tasks = list(tasks_collection.find({'user_id': user_id,'completion_status':False}))
    for task in tasks:
        task['_id'] = str(task['_id'])
    print(tasks)
    return jsonify({'tasks': tasks})

@app.route('/mark_as_completed/<task_id>', methods=['POST'])
def mark_as_completed(task_id):
    task = tasks_collection.find_one({'_id': ObjectId(task_id)})
    print(task)

    if not task:
        print(task,"empty")
        return jsonify({'success': False, 'message': 'Task not found.'}), 404

    if task.get('completion_status'):
        return jsonify({'success': False, 'message': 'Task already completed.'}), 400

    tasks_collection.update_one(
        {'_id': ObjectId(task_id)},
        {'$set': {'completion_status': True}}
    )

    return jsonify({'success': True})

@app.route('/delete_task/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    try:
        result = tasks_collection.delete_one({'_id': ObjectId(task_id)})
        if result.deleted_count == 1:
            return jsonify({"success":True,"message": "Task deleted successfully"}), 200
        else:
            return jsonify({"success":False,"message": "Task not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/get_completed_tasks_count/<user_id>', methods=['GET'])
def get_completed_tasks_count(user_id):
    try:
        completed_count = tasks_collection.count_documents({'user_id': user_id, 'completion_status': True})
        return jsonify({"completed_count": completed_count}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')



if __name__ == '__main__':
    app.run(debug=True)
