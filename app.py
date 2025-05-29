from flask import Flask, request, jsonify, send_from_directory, abort, Response
import yt_dlp
import os
import uuid
import threading
import time
from werkzeug.utils import secure_filename

app = Flask(__name__)
DOWNLOAD_FOLDER = 'downloads'
API_KEY = 'your-secret-api-key'  # Change this to your actual API key

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

progress_dict = {}

def delete_file_later(filepath, delay=600):
    def delete():
        time.sleep(delay)
        try:
            os.remove(filepath)
        except Exception:
            pass
    threading.Thread(target=delete, daemon=True).start()

def allowed_format(fmt):
    return fmt in ['mp3', 'mp4']

@app.route('/api/download', methods=['POST'])
def download():
    # API key check
    api_key = request.headers.get('x-api-key')
    if api_key != API_KEY:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    url = data.get('url')
    fmt = data.get('format')
    quality = data.get('quality', 'best')

    if not url or not allowed_format(fmt):
        return jsonify({'error': 'Invalid URL or format'}), 400

    # Generate unique filename and progress id
    file_id = str(uuid.uuid4())
    filename = secure_filename(f'{file_id}.{fmt}')
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    progress_dict[file_id] = {'progress': 0}

    def progress_hook(d):
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
            downloaded = d.get('downloaded_bytes', 0)
            percent = int(downloaded * 100 / total)
            progress_dict[file_id]['progress'] = percent
        elif d.get('status') == 'finished':
            progress_dict[file_id]['progress'] = 100

    # yt_dlp options
    ydl_opts = {
        'outtmpl': filepath,
        'format': 'bestvideo+bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'progress_hooks': [progress_hook],
        # Add the path to your cookies file here
        'cookiefile': 'cookies.txt',  # Assumes cookies.txt is in the same directory as app.py
    }
    if fmt == 'mp3':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['outtmpl'] = filepath[:-4] + '.%(ext)s'  # Save with correct extension
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    elif fmt == 'mp4':
        if quality == 'best':
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        else:
            ydl_opts['format'] = f'bestvideo[ext=mp4][height<={quality}]+bestaudio[ext=m4a]/best[ext=mp4][height<={quality}]/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        # If mp3, find the actual output file
        if fmt == 'mp3':
            base = os.path.splitext(filepath)[0]
            mp3_path = base + '.mp3'
            if os.path.exists(mp3_path):
                filepath = mp3_path
                filename = os.path.basename(mp3_path)
            else:
                return jsonify({'error': 'MP3 file not found after conversion.'}), 500
        # Get the original title and extension
        original_title = info.get('title', 'downloaded_file')
        ext = 'mp3' if fmt == 'mp3' else 'mp4'
        user_filename = secure_filename(f"{original_title}.{ext}")
    except Exception as e:
        return jsonify({'error': f'Failed to download: {str(e)}'}), 400

    # Schedule file deletion
    delete_file_later(filepath)

    download_url = f'/api/downloaded/{filename}'
    return jsonify({'download_url': download_url, 'user_filename': user_filename, 'progress_id': file_id}), 200

@app.route('/api/progress/<progress_id>')
def progress(progress_id):
    def event_stream():
        last = -1
        while True:
            percent = progress_dict.get(progress_id, {'progress': 100})['progress']
            if percent != last:
                yield f'data: {{"progress": {percent}}}\n\n'
                last = percent
            if percent >= 100:
                break
            time.sleep(0.5)
    return Response(event_stream(), mimetype='text/event-stream')

@app.route('/api/downloaded/<filename>', methods=['GET'])
def serve_file(filename):
    # Set headers to force download and avoid preview in browser
    user_filename = request.args.get('name', filename)
    response = send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)
    response.headers['Content-Disposition'] = f'attachment; filename="{user_filename}"'
    response.headers['Content-Type'] = 'application/octet-stream'
    return response

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

if __name__ == '__main__':
    # Fallback for local testing
    app.run(host='0.0.0.0', port=5000)
