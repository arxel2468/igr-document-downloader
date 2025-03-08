# main.py
import os
import threading
from app import app, start_cleanup_scheduler

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs("downloads", exist_ok=True)
    os.makedirs("temp_captchas", exist_ok=True)
    
    # Start the cleanup scheduler in a separate thread
    threading.Thread(target=start_cleanup_scheduler, daemon=True).start()
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)