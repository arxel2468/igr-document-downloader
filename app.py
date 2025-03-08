from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import os
import re
import uuid
import time
import shutil
import threading
import logging
from io import BytesIO
import zipfile
from webdriver_pool import WebDriverPool
from automation import run_automation
from config import districts_data, tahsil_data, village_data, WEBDRIVER_POOL_SIZE

# Create global objects
logger = logging.getLogger(__name__)
driver_pool = WebDriverPool(max_drivers=WEBDRIVER_POOL_SIZE)

# Store running jobs
jobs = {}

# Flask server implementation
app = Flask(__name__)
CORS(app)

@app.route('/api/get_districts', methods=['GET'])
def get_districts():
    # These would ideally come from a database or API
    districts = districts_data
    return jsonify({"districts": districts})

@app.route('/api/get_tahsils', methods=['GET'])
def get_tahsils():
    district = request.args.get('district')
    # In production, fetch from database or the actual IGR site
    district_tahsil_data = tahsil_data
    
    # Default empty list for districts not in our mock data
    tahsils = district_tahsil_data.get(district, [])
    if not tahsils:
        logger.warning(f"No tahsil data for district: {district}")
    
    return jsonify({"tahsils": tahsils})

@app.route('/api/get_villages', methods=['GET'])
def get_villages():
    district = request.args.get('district')
    tahsil = request.args.get('tahsil')
    
    # Mock data - in production, fetch from the actual source
    tahsil_village_data = village_data
    
    # Default empty list for tahsils not in our mock data
    villages = tahsil_village_data.get(tahsil, [])
    if not villages:
        logger.warning(f"No village data for tahsil: {tahsil}")
    
    return jsonify({"villages": villages})

@app.route('/api/download_documents', methods=['POST'])
def download_documents():
    data = request.json
    year = data.get('year')
    district = data.get('district')
    tahsil = data.get('tahsil')
    village = data.get('village')
    property_no = data.get('propertyNo')
    
    # Validate inputs
    if not all([year, district, tahsil, village, property_no]):
        return jsonify({
            "status": "error",
            "message": "All fields are required"
        }), 400
    
    # Generate a unique job ID
    job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    
    # Create a folder for output based on input parameters
    folder_name = f"{year}_{district}_{tahsil}_{village}_{property_no}_{job_id}"
    # Use only alphanumeric characters and underscores for folder name
    safe_folder_name = re.sub(r'[^\w]', '_', folder_name)
    
    output_dir = os.path.join("downloads", safe_folder_name)
    os.makedirs("downloads", exist_ok=True)
    
    # Initialize job info
    jobs[job_id] = {
        "status": "starting",
        "details": {
            "year": year,
            "district": district,
            "tahsil": tahsil,
            "village": village,
            "propertyNo": property_no
        },
        "total_documents": 0,
        "downloaded_documents": 0,
        "directory": output_dir,
        "created_at": time.time()
    }
    
    # Start automation in a separate thread
    threading.Thread(
        target=run_automation,
        args=(year, district, tahsil, village, property_no, job_id, jobs, driver_pool)
    ).start()
    
    return jsonify({
        "status": "success",
        "message": "Document download job started",
        "job_id": job_id
    })

@app.route('/api/job_status/<job_id>', methods=['GET'])
def job_status(job_id):
    if job_id not in jobs:
        return jsonify({
            "status": "error",
            "message": "Job not found"
        }), 404
    
    job = jobs[job_id]
    
    response = {
        "status": job["status"],
        "details": job["details"],
        "total_documents": job["total_documents"],
        "downloaded_documents": job.get("downloaded_documents", 0),
        "created_at": job.get("created_at")
    }
    
    if "error" in job:
        response["error"] = job["error"]
    if "message" in job:
        response["message"] = job["message"]
    
    return jsonify(response)

@app.route('/api/download_results/<job_id>', methods=['GET'])
def download_results(job_id):
    if job_id not in jobs:
        return jsonify({
            "status": "error",
            "message": "Job not found"
        }), 404
    
    job = jobs[job_id]
    
    if job["status"] != "completed":
        return jsonify({
            "status": "error",
            "message": "Job not completed yet"
        }), 400
    
    directory = job["directory"]
    
    if not os.path.exists(directory):
        return jsonify({
            "status": "error",
            "message": "Directory not found"
        }), 404
    
    # Create a zip file in memory
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(directory):
            for file in files:
                # Skip debug files if they're not requested
                if 'debug' in root and not request.args.get('include_debug'):
                    continue
                
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(directory))
                zipf.write(file_path, arcname)
    
    memory_file.seek(0)
    
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"{job_id}_documents.zip"
    )

@app.route('/api/cleanup_job/<job_id>', methods=['DELETE'])
def cleanup_job(job_id):
    if job_id not in jobs:
        return jsonify({
            "status": "error",
            "message": "Job not found"
        }), 404
    
    job = jobs[job_id]
    directory = job.get("directory")
    
    # Remove files
    if directory and os.path.exists(directory):
        try:
            shutil.rmtree(directory)
            logger.info(f"Cleaned up directory for job {job_id}: {directory}")
        except Exception as e:
            logger.error(f"Failed to clean up directory {directory}: {str(e)}")
            return jsonify({
                "status": "error",
                "message": f"Failed to clean up directory: {str(e)}"
            }), 500
    
    # Remove job from dictionary
    del jobs[job_id]
    logger.info(f"Removed job {job_id} from tracking")
    
    return jsonify({
        "status": "success",
        "message": "Job and associated files cleaned up"
    })

@app.route('/api/list_jobs', methods=['GET'])
def list_jobs():
    # Get optional filters
    status_filter = request.args.get('status')
    
    jobs_list = []
    for job_id, job_info in jobs.items():
        # Apply status filter if provided
        if status_filter and job_info.get('status') != status_filter:
            continue
            
        jobs_list.append({
            "job_id": job_id,
            "status": job_info.get("status"),
            "details": job_info.get("details"),
            "total_documents": job_info.get("total_documents", 0),
            "downloaded_documents": job_info.get("downloaded_documents", 0),
            "created_at": job_info.get("created_at"),
            "has_files": os.path.exists(job_info.get("directory", "")) and 
                        len(os.listdir(job_info.get("directory", ""))) > 0
        })
    
    # Sort by creation time (newest first)
    jobs_list.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    
    return jsonify({
        "jobs": jobs_list,
        "count": len(jobs_list)
    })

@app.route('/', methods=['GET'])
def home():
    return render_template("ui.html")

# Periodic cleanup of older jobs
def cleanup_old_jobs():
    """Remove jobs and files older than 24 hours."""
    current_time = time.time()
    jobs_to_remove = []
    
    for job_id, job_info in jobs.items():
        created_at = job_info.get("created_at", 0)
        # 24 hours = 86400 seconds
        if current_time - created_at > 86400:
            directory = job_info.get("directory")
            if directory and os.path.exists(directory):
                try:
                    shutil.rmtree(directory)
                    logger.info(f"Cleaned up directory for old job {job_id}: {directory}")
                except Exception as e:
                    logger.error(f"Failed to clean up directory for old job {job_id}: {str(e)}")
            
            jobs_to_remove.append(job_id)
    
    # Remove the jobs from the dictionary
    for job_id in jobs_to_remove:
        del jobs[job_id]
        logger.info(f"Removed old job {job_id} from tracking")

# Start the cleanup thread
def start_cleanup_scheduler():
    """Run cleanup every hour."""
    while True:
        time.sleep(3600)  # 1 hour
        try:
            cleanup_old_jobs()
        except Exception as e:
            logger.error(f"Error in cleanup scheduler: {str(e)}")