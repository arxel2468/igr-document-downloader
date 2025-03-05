import time
import os
import re
import json
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, ElementClickInterceptedException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
import hashlib
import pdfkit
import platform
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract
import threading
import uuid
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import zipfile
from io import BytesIO
import shutil

# Load the JSON data
with open('maharashtra_locations_final.json', 'r', encoding='utf-8') as f:
    location_data = json.load(f)
    
# Create districts list
districts_data = list(location_data.keys())

# Create tahsil_data dictionary
tahsil_data = {}
for district, tahsils_data in location_data.items():
    tahsil_data[district] = list(tahsils_data.keys())

# Create village_data dictionary
village_data = {}
for district, tahsils_data in location_data.items():
    for tahsil, villages in tahsils_data.items():
        village_data[tahsil] = villages

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("igr_automation.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configure Tesseract path based on OS
if platform.system() == 'Windows':
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
elif platform.system() == 'Linux':
    pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
else:  # macOS
    pytesseract.pytesseract.tesseract_cmd = "/usr/local/bin/tesseract"

def solve_captcha_with_multiple_techniques(image_path):
    """Try multiple techniques to solve CAPTCHA"""
    techniques = [
        {
            "description": "Standard grayscale with contrast",
            "preprocess": lambda img: ImageEnhance.Contrast(img.convert('L')).enhance(2).point(lambda p: p > 140 and 255)
        },
        {
            "description": "High contrast grayscale",
            "preprocess": lambda img: ImageEnhance.Contrast(img.convert('L')).enhance(3).point(lambda p: p > 160 and 255)
        },
        {
            "description": "Noise reduction with median filter",
            "preprocess": lambda img: ImageEnhance.Contrast(img.convert('L').filter(ImageFilter.MedianFilter(size=3))).enhance(2.5).point(lambda p: p > 150 and 255)
        },
        {
            "description": "Sharpening filter",
            "preprocess": lambda img: ImageEnhance.Contrast(img.convert('L').filter(ImageFilter.SHARPEN)).enhance(2).point(lambda p: p > 145 and 255)
        },
        {
            "description": "Adaptive thresholding",
            "preprocess": lambda img: ImageOps.autocontrast(img.convert('L'))
        }
    ]
    
    results = []
    
    img = Image.open(image_path)
    
    for i, technique in enumerate(techniques):
        try:
            # Apply the preprocessing technique
            processed_img = technique["preprocess"](img)
            
            # Save preprocessed image
            preprocessed_path = f"{image_path}_technique_{i}.png"
            processed_img.save(preprocessed_path)
            
            # OCR with specific config for CAPTCHA text
            captcha_text = pytesseract.image_to_string(
                preprocessed_path,
                config='--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
            ).strip()
            
            # Check if result looks like a valid CAPTCHA (typically 5-6 alphanumeric characters)
            if re.match(r'^[A-Z0-9]{4,6}$', captcha_text):
                logger.info(f"Technique {i}: '{technique['description']}' - Result: '{captcha_text}' (VALID FORMAT)")
                results.append(captcha_text)
            else:
                logger.info(f"Technique {i}: '{technique['description']}' - Result: '{captcha_text}' (INVALID FORMAT)")
                
        except Exception as e:
            logger.error(f"Error with technique {i}: {str(e)}")
    
    # Choose the most common result if there are multiple valid results
    if results:
        from collections import Counter
        most_common = Counter(results).most_common(1)[0][0]
        return most_common
    
    # If no valid results, return the best guess from the first technique
    return pytesseract.image_to_string(
        f"{image_path}_technique_0.png",
        config='--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    ).strip()

def get_captcha_hash(image_path):
    """Generate a hash of the CAPTCHA image to detect changes."""
    with open(image_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def configure_pdfkit():
    """Return the proper configuration for pdfkit based on OS."""
    if platform.system() == 'Windows':
        return pdfkit.configuration(wkhtmltopdf=r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe')
    elif platform.system() == 'Linux':
        return pdfkit.configuration(wkhtmltopdf='/usr/bin/wkhtmltopdf')
    else:  # macOS
        return pdfkit.configuration(wkhtmltopdf='/usr/local/bin/wkhtmltopdf')

def wait_for_new_tab(driver, original_handles, timeout=10):
    """Wait for a new tab to open and return its handle."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        current_handles = driver.window_handles
        if len(current_handles) > len(original_handles):
            # Return the new handle
            new_handles = set(current_handles) - set(original_handles)
            return list(new_handles)[0]
        time.sleep(0.5)
    raise TimeoutException("New tab did not open within the timeout period")

def solve_and_submit_captcha(driver, max_attempts=3):
    """Solves and submits the CAPTCHA, with multiple retry attempts."""
    for attempt in range(max_attempts):
        try:
            captcha_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "imgCaptcha_new"))
            )
            
            # Create a temp directory for CAPTCHA images if it doesn't exist
            os.makedirs("temp_captchas", exist_ok=True)
            
            captcha_image_path = os.path.join("temp_captchas", f"captcha_attempt_{attempt}.png")
            captcha_element.screenshot(captcha_image_path)
            
            logger.info(f"CAPTCHA attempt {attempt+1}/{max_attempts}")
            
            old_captcha_hash = get_captcha_hash(captcha_image_path)
            captcha_text = solve_captcha_with_multiple_techniques(captcha_image_path)
            
            logger.info(f"CAPTCHA solution: '{captcha_text}'")
            
            # Enter CAPTCHA and submit
            captcha_input = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "txtImg1"))
            )
            captcha_input.clear()
            captcha_input.send_keys(captcha_text)
            
            # Take screenshot before clicking search
            driver.save_screenshot(f"temp_captchas/before_search_{attempt}.png")
            
            search_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//input[@id='btnSearch_RestMaha']"))
            )
            driver.execute_script("arguments[0].click();", search_button)
            
            logger.info("Search button clicked")
            
            # Wait for either results table or error message
            try:
                WebDriverWait(driver, 15).until(
                    lambda d: EC.presence_of_element_located((By.CLASS_NAME, "RegistrationGrid"))(d) or 
                              "Invalid Verification Code" in d.page_source
                )
                
                # Check for invalid CAPTCHA message
                if "Invalid Verification Code" in driver.page_source:
                    logger.warning("Invalid CAPTCHA detected, retrying...")
                    continue
                
                # Check for results table
                if driver.find_elements(By.CLASS_NAME, "RegistrationGrid"):
                    logger.info("Search successful! Results table found.")
                    return True
                    
            except TimeoutException:
                logger.warning("No results or error message found after CAPTCHA submission")
                
            # Check if CAPTCHA has changed (indicating incorrect input)
            try:
                new_captcha = driver.find_element(By.ID, "imgCaptcha_new")
                new_captcha.screenshot(captcha_image_path)
                new_hash = get_captcha_hash(captcha_image_path)
                
                if new_hash != old_captcha_hash:
                    logger.info("CAPTCHA changed (likely incorrect), trying again")
                    continue
                    
            except NoSuchElementException:
                # If CAPTCHA is gone, maybe we're on results page
                logger.info("CAPTCHA element no longer found, checking for results")
                if "RegistrationGrid" in driver.page_source:
                    return True
            
            # Additional wait for slow servers
            time.sleep(5)
            
            # Final check for results
            if "RegistrationGrid" in driver.page_source:
                logger.info("Results found after additional wait")
                return True
                
        except Exception as e:
            logger.error(f"Error during CAPTCHA attempt {attempt+1}: {str(e)}")
            driver.save_screenshot(f"temp_captchas/error_captcha_{attempt+1}.png")
            
    logger.error("All CAPTCHA attempts failed")
    return False

def run_automation(year, district, tahsil, village, property_no, job_id, jobs):
    """Run the automation to download documents and update job status."""
    jobs[job_id]["status"] = "running"
    
    # Create directories
    output_dir = jobs[job_id]["directory"]
    os.makedirs(output_dir, exist_ok=True)
    
    debug_dir = os.path.join(output_dir, "debug")
    os.makedirs(debug_dir, exist_ok=True)
    
    print(output_dir)
    
    driver = None
    
    try:
        # Set up WebDriver
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--window-size=1920,1080")
        
        # When running in production, uncomment these
        # options.add_argument("--headless")
        # options.add_argument("--no-sandbox")
        # options.add_argument("--disable-dev-shm-usage")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(60)
        
        logger.info(f"Starting job {job_id} for property {property_no} in {village}, {tahsil}, {district} ({year})")
        
        # Open Website
        driver.get("https://freesearchigrservice.maharashtra.gov.in/")
        logger.info("Website opened")
        
        # Take screenshot of home page
        driver.save_screenshot(os.path.join(debug_dir, "homepage.png"))
        
        # Close Pop-up if present
        try:
            close_button = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "btnclose"))
            )
            close_button.click()
            logger.info("Pop-up closed")
        except (TimeoutException, NoSuchElementException):
            logger.info("No pop-up found, proceeding...")
        
        # Click "Rest of Maharashtra"
        try:
            rest_maha_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//input[@id='btnOtherdistrictSearch']"))
            )
            rest_maha_button.click()
            logger.info("Selected 'Rest of Maharashtra'")
        except Exception as e:
            logger.error(f"Failed to click 'Rest of Maharashtra': {e}")
            driver.save_screenshot(os.path.join(debug_dir, "rest_maha_error.png"))
            raise
        
        # Take screenshot after "Rest of Maharashtra" selection
        driver.save_screenshot(os.path.join(debug_dir, "after_rest_maha.png"))
        
        # Select Year
        try:
            year_dropdown = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "ddlFromYear1"))
            )
            Select(year_dropdown).select_by_value(year)
            logger.info(f"Year {year} selected")
        except Exception as e:
            logger.error(f"Failed to select year: {e}")
            driver.save_screenshot(os.path.join(debug_dir, "year_select_error.png"))
            raise
        
        # Select District
        try:
            district_dropdown = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "ddlDistrict1"))
            )
            district_select = Select(district_dropdown)
            district_select.select_by_visible_text(district)
            logger.info(f"District '{district}' selected")
            
            # Wait for district selection to update
            time.sleep(2)
        except Exception as e:
            logger.error(f"Failed to select district: {e}")
            driver.save_screenshot(os.path.join(debug_dir, "district_select_error.png"))
            raise
        
        # Select Tahsil
        try:
            # Wait for Tahsil dropdown to update
            WebDriverWait(driver, 10).until(
                lambda d: len(Select(d.find_element(By.ID, "ddltahsil")).options) > 1
            )
            
            tahsil_dropdown = driver.find_element(By.ID, "ddltahsil")
            tahsil_select = Select(tahsil_dropdown)
            tahsil_select.select_by_visible_text(tahsil)
            logger.info(f"Tahsil '{tahsil}' selected")
            
            # Wait for tahsil selection to update
            time.sleep(2)
        except Exception as e:
            logger.error(f"Failed to select tahsil: {e}")
            driver.save_screenshot(os.path.join(debug_dir, "tahsil_select_error.png"))
            raise
        
        # Select Village
        try:
            # Wait for Village dropdown to update
            WebDriverWait(driver, 10).until(
                lambda d: len(Select(d.find_element(By.ID, "ddlvillage")).options) > 1
            )
            
            village_dropdown = driver.find_element(By.ID, "ddlvillage")
            village_select = Select(village_dropdown)
            village_select.select_by_visible_text(village)
            logger.info(f"Village '{village}' selected")
        except Exception as e:
            logger.error(f"Failed to select village: {e}")
            driver.save_screenshot(os.path.join(debug_dir, "village_select_error.png"))
            raise
        
        # Input Property No.
        try:
            property_input = driver.find_element(By.ID, "txtAttributeValue1")
            property_input.send_keys(property_no)
            logger.info(f"Property number '{property_no}' entered")
        except Exception as e:
            logger.error(f"Failed to enter property number: {e}")
            driver.save_screenshot(os.path.join(debug_dir, "property_input_error.png"))
            raise
        
        # Take screenshot of form before submission
        driver.save_screenshot(os.path.join(debug_dir, "form_filled.png"))
        
        # Solve CAPTCHA
        logger.info("Attempting to solve CAPTCHA...")
        if not solve_and_submit_captcha(driver):
            error_msg = "Failed to solve CAPTCHA after multiple attempts"
            logger.error(error_msg)
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = error_msg
            driver.save_screenshot(os.path.join(debug_dir, "captcha_failed.png"))
            return
        
        # Wait for Results Table
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.ID, "RegistrationGrid"))
            )
            logger.info("Results loaded successfully!")
            
            # Take screenshot of results
            driver.save_screenshot(os.path.join(debug_dir, "results_table.png"))
        except TimeoutException:
            error_msg = "No results found or page timed out"
            logger.error(error_msg)
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = error_msg
            driver.save_screenshot(os.path.join(debug_dir, "no_results.png"))
            return
        
        # Get total number of documents
        index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
        total_documents = len(index_buttons)
        
        jobs[job_id]["total_documents"] = total_documents
        logger.info(f"Found {total_documents} documents to download")
        
        if total_documents == 0:
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["message"] = "No documents found for the given criteria"
            return
        
        # Process documents one by one
        successfully_downloaded = 0
        
        for i in range(total_documents):
            logger.info(f"Processing document {i+1}/{total_documents}...")
            
            # Re-fetch the elements to avoid stale references
            index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
            
            if not index_buttons:
                logger.warning("Index buttons no longer found, refreshing page")
                driver.refresh()
                time.sleep(5)
                
                # Re-solve CAPTCHA if needed
                if "imgCaptcha_new" in driver.page_source:
                    if not solve_and_submit_captcha(driver):
                        logger.error("Failed to re-solve CAPTCHA after page refresh")
                        break
                
                # Re-find the buttons
                index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
                if not index_buttons:
                    logger.error("Still no index buttons found after refresh")
                    break
            
            try:
                # Always click the first button (sequential processing)
                button = index_buttons[0]
                
                # Store original window handles
                original_handles = driver.window_handles
                
                # Ensure button is in view and clickable
                driver.execute_script("arguments[0].scrollIntoView(true);", button)
                time.sleep(1)
                
                # Try to click the button using JavaScript for reliability
                driver.execute_script("arguments[0].click();", button)
                logger.info(f"Clicked on IndexII button for document {i+1}")
                
                try:
                    # Wait for and switch to new tab
                    new_tab = wait_for_new_tab(driver, original_handles, timeout=15)
                    driver.switch_to.window(new_tab)
                    logger.info(f"Switched to new tab: {driver.current_url}")
                    
                    # Wait for content to load
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                    
                    # Take screenshot of the document
                    document_screenshot = os.path.join(output_dir, f"Document_{i+1}_screenshot.png")
                    driver.save_screenshot(document_screenshot)
                    
                    # Save as HTML
                    html_filename = os.path.join(output_dir, f"Document_{i+1}.html")
                    with open(html_filename, "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logger.info(f"Saved HTML: {html_filename}")
                    
                    # Convert to PDF (optional)
                    try:
                        pdf_filename = os.path.join(output_dir, f"Document_{i+1}.pdf")
                        pdfkit_config = configure_pdfkit()
                        pdfkit.from_string(driver.page_source, pdf_filename, configuration=pdfkit_config)
                        logger.info(f"Saved PDF: {pdf_filename}")
                    except Exception as pdf_error:
                        logger.error(f"Failed to create PDF: {pdf_error}")
                    
                    # Mark as successfully downloaded
                    successfully_downloaded += 1
                    jobs[job_id]["downloaded_documents"] = successfully_downloaded
                    
                    # Close the document tab and switch back to results tab
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                    
                    # Wait for page to stabilize after switching
                    time.sleep(3)
                    
                except TimeoutException:
                    logger.error(f"New tab did not open for document {i+1}")
                    driver.save_screenshot(os.path.join(debug_dir, f"tab_timeout_doc_{i+1}.png"))
                    
                    # Make sure we're on the original tab
                    if len(driver.window_handles) > 1:
                        driver.switch_to.window(driver.window_handles[0])
                
            except Exception as e:
                logger.error(f"Error processing document {i+1}: {str(e)}")
                driver.save_screenshot(os.path.join(debug_dir, f"doc_error_{i+1}.png"))
                continue
            
            # Small pause between documents to avoid overwhelming the server
            time.sleep(3)
        
        # Update job status
        if successfully_downloaded > 0:
            jobs[job_id]["status"] = "completed"
            logger.info(f"Job completed successfully. Downloaded {successfully_downloaded}/{total_documents} documents.")
        else:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "Failed to download any documents"
            logger.error("No documents were successfully downloaded")
            
            # Clean up empty output directory if no documents were downloaded
            if os.path.exists(output_dir) and not os.listdir(output_dir):
                try:
                    os.rmdir(output_dir)
                    logger.info(f"Removed empty output directory: {output_dir}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to remove empty directory: {cleanup_error}")
    
    except Exception as e:
        logger.error(f"Automation error: {str(e)}", exc_info=True)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        
        # Take final error screenshot
        if driver:
            driver.save_screenshot(os.path.join(debug_dir, "fatal_error.png"))
    
    finally:
        # Clean up
        try:
            if driver:
                driver.quit()
                logger.info("Browser closed")
        except Exception as quit_error:
            logger.error(f"Error closing browser: {str(quit_error)}")

# Flask server implementation
app = Flask(__name__)
CORS(app)

# Store running jobs
jobs = {}

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
        args=(year, district, tahsil, village, property_no, job_id, jobs)
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
    return """
    <html>
        <head>
            <title>Maharashtra IGR Document Downloader</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 0; padding: 20px; line-height: 1.6; }
                h1 { color: #333; }
                .container { max-width: 800px; margin: 0 auto; }
                .card { border: 1px solid #ddd; border-radius: 4px; padding: 20px; margin-bottom: 20px; }
                .endpoint { background-color: #f5f5f5; padding: 10px; border-radius: 4px; margin-bottom: 10px; }
                code { background-color: #f1f1f1; padding: 2px 4px; border-radius: 3px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Maharashtra IGR Document Downloader API</h1>
                
                <div class="card">
                    <h2>Available Endpoints</h2>
                    
                    <div class="endpoint">
                        <h3>GET /api/get_districts</h3>
                        <p>Returns a list of available districts</p>
                    </div>
                    
                    <div class="endpoint">
                        <h3>GET /api/get_tahsils?district={district}</h3>
                        <p>Returns tahsils for the specified district</p>
                    </div>
                    
                    <div class="endpoint">
                        <h3>GET /api/get_villages?district={district}&tahsil={tahsil}</h3>
                        <p>Returns villages for the specified tahsil</p>
                    </div>
                    
                    <div class="endpoint">
                        <h3>POST /api/download_documents</h3>
                        <p>Starts a job to download documents</p>
                        <p>Required JSON body: <code>{"year": "2023", "district": "पुणे", "tahsil": "हवेली", "village": "कोथरूड", "propertyNo": "123"}</code></p>
                    </div>
                    
                    <div class="endpoint">
                        <h3>GET /api/job_status/{job_id}</h3>
                        <p>Check status of a download job</p>
                    </div>
                    
                    <div class="endpoint">
                        <h3>GET /api/download_results/{job_id}</h3>
                        <p>Download a ZIP file with the job results</p>
                    </div>
                    
                    <div class="endpoint">
                        <h3>DELETE /api/cleanup_job/{job_id}</h3>
                        <p>Delete a job and its associated files</p>
                    </div>
                    
                    <div class="endpoint">
                        <h3>GET /api/list_jobs</h3>
                        <p>List all jobs (optional query param: <code>status</code>)</p>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """

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

# HTML frontend code
@app.route('/ui', methods=['GET'])
def ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Maharashtra IGR Document Downloader</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { padding-top: 20px; }
            .job-card { margin-bottom: 15px; }
            .loading { display: none; }
            .spinner-border { width: 1.5rem; height: 1.5rem; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="mb-4 text-center">Maharashtra IGR Document Downloader</h1>
            
            <div class="row">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">
                            <h5>New Document Search</h5>
                        </div>
                        <div class="card-body">
                            <form id="searchForm">
                                <div class="mb-3">
                                    <label for="year" class="form-label">Year</label>
                                    <select class="form-select" id="year" required>
                                        <option value="">Select Year</option>
                                    </select>
                                </div>
                                
                                <div class="mb-3">
                                    <label for="district" class="form-label">District</label>
                                    <select class="form-select" id="district" required>
                                        <option value="">Select District</option>
                                    </select>
                                </div>
                                
                                <div class="mb-3">
                                    <label for="tahsil" class="form-label">Tahsil</label>
                                    <select class="form-select" id="tahsil" required>
                                        <option value="">Select Tahsil</option>
                                    </select>
                                </div>
                                
                                <div class="mb-3">
                                    <label for="village" class="form-label">Village</label>
                                    <select class="form-select" id="village" required>
                                        <option value="">Select Village</option>
                                    </select>
                                </div>
                                
                                <div class="mb-3">
                                    <label for="propertyNo" class="form-label">Property No.</label>
                                    <input type="text" class="form-control" id="propertyNo" placeholder="Enter property number" required>
                                </div>
                                
                                <div class="d-grid">
                                    <button type="submit" class="btn btn-primary">
                                        <span class="spinner-border spinner-border-sm loading" role="status" aria-hidden="true"></span>
                                        <span class="btn-text">Download Documents</span>
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                </div>
                
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h5>Recent Jobs</h5>
                            <button type="button" class="btn btn-sm btn-outline-secondary" id="refreshJobs">
                                <span class="spinner-border spinner-border-sm loading" role="status" aria-hidden="true"></span>
                                Refresh
                            </button>
                        </div>
                        <div class="card-body">
                            <div id="jobsList">
                                <div class="text-center py-3">Loading jobs...</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            document.addEventListener('DOMContentLoaded', function() {
                // Initialize years dropdown
                const yearSelect = document.getElementById('year');
                const currentYear = new Date().getFullYear();
                for (let year = currentYear; year >= 1985; year--) {
                    const option = document.createElement('option');
                    option.value = year.toString();
                    option.textContent = year.toString();
                    yearSelect.appendChild(option);
                }
                
                // Load districts
                fetch('/api/get_districts')
                    .then(response => response.json())
                    .then(data => {
                        const districtSelect = document.getElementById('district');
                        data.districts.forEach(district => {
                            const option = document.createElement('option');
                            option.value = district;
                            option.textContent = district;
                            districtSelect.appendChild(option);
                        });
                    });
                
                // District change handler
                document.getElementById('district').addEventListener('change', function() {
                    const district = this.value;
                    if (!district) return;
                    
                    // Clear tahsil and village dropdowns
                    const tahsilSelect = document.getElementById('tahsil');
                    tahsilSelect.innerHTML = '<option value="">Select Tahsil</option>';
                    
                    const villageSelect = document.getElementById('village');
                    villageSelect.innerHTML = '<option value="">Select Village</option>';
                    
                    // Load tahsils for selected district
                    fetch(`/api/get_tahsils?district=${encodeURIComponent(district)}`)
                        .then(response => response.json())
                        .then(data => {
                            data.tahsils.forEach(tahsil => {
                                const option = document.createElement('option');
                                option.value = tahsil;
                                option.textContent = tahsil;
                                tahsilSelect.appendChild(option);
                            });
                        });
                });
                
                // Tahsil change handler
                document.getElementById('tahsil').addEventListener('change', function() {
                    const district = document.getElementById('district').value;
                    const tahsil = this.value;
                    if (!district || !tahsil) return;
                    
                    // Clear village dropdown
                    const villageSelect = document.getElementById('village');
                    villageSelect.innerHTML = '<option value="">Select Village</option>';
                    
                    // Load villages for selected tahsil
                    fetch(`/api/get_villages?district=${encodeURIComponent(district)}&tahsil=${encodeURIComponent(tahsil)}`)
                        .then(response => response.json())
                        .then(data => {
                            data.villages.forEach(village => {
                                const option = document.createElement('option');
                                option.value = village;
                                option.textContent = village;
                                villageSelect.appendChild(option);
                            });
                        });
                });
                
                // Form submission
                document.getElementById('searchForm').addEventListener('submit', function(e) {
                    e.preventDefault();
                    
                    const formData = {
                        year: document.getElementById('year').value,
                        district: document.getElementById('district').value,
                        tahsil: document.getElementById('tahsil').value,
                        village: document.getElementById('village').value,
                        propertyNo: document.getElementById('propertyNo').value
                    };
                    
                    // Show loading indicator
                    const submitBtn = this.querySelector('button[type="submit"]');
                    const loadingSpinner = submitBtn.querySelector('.loading');
                    const btnText = submitBtn.querySelector('.btn-text');
                    
                    submitBtn.disabled = true;
                    loadingSpinner.style.display = 'inline-block';
                    btnText.textContent = 'Starting Job...';
                    
                    // Submit job
                    fetch('/api/download_documents', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(formData)
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'success') {
                            alert('Job started successfully! Job ID: ' + data.job_id);
                            loadJobs(); // Refresh jobs list
                        } else {
                            alert('Error: ' + data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Error:', error);
                        alert('An unexpected error occurred. Please try again.');
                    })
                    .finally(() => {
                        // Reset button state
                        submitBtn.disabled = false;
                        loadingSpinner.style.display = 'none';
                        btnText.textContent = 'Download Documents';
                    });
                });
                
                // Load jobs list
                function loadJobs() {
                    const jobsList = document.getElementById('jobsList');
                    const refreshBtn = document.getElementById('refreshJobs');
                    const loadingSpinner = refreshBtn.querySelector('.loading');
                    
                    loadingSpinner.style.display = 'inline-block';
                    
                    fetch('/api/list_jobs')
                        .then(response => response.json())
                        .then(data => {
                            if (data.count === 0) {
                                jobsList.innerHTML = '<div class="text-center py-3">No jobs found</div>';
                                return;
                            }
                            
                            // Clear existing jobs
                            jobsList.innerHTML = '';
                            
                            // Add job cards
                            data.jobs.forEach(job => {
                                const details = job.details || {};
                                const statusBadgeClass = getStatusBadgeClass(job.status);
                                
                                const jobCard = document.createElement('div');
                                jobCard.className = 'card job-card';
                                
                                jobCard.innerHTML = `
                                    <div class="card-header d-flex justify-content-between align-items-center">
                                        <span class="badge ${statusBadgeClass}">${job.status}</span>
                                        <small>ID: ${job.job_id}</small>
                                    </div>
                                    <div class="card-body">
                                        <p class="card-text mb-1">
                                            <strong>Property:</strong> ${details.propertyNo || 'N/A'} (${details.village || 'N/A'}, ${details.tahsil || 'N/A'})
                                        </p>
                                        <p class="card-text mb-1">
                                            <strong>Year:</strong> ${details.year || 'N/A'}
                                        </p>
                                        <p class="card-text mb-2">
                                            <strong>Progress:</strong> ${job.downloaded_documents || 0}/${job.total_documents || 0} documents
                                        </p>
                                        <div class="btn-group btn-group-sm w-100">
                                            <button type="button" class="btn btn-outline-primary check-status" data-job-id="${job.job_id}">Check Status</button>
                                            ${job.status === 'completed' ? `<a href="/api/download_results/${job.job_id}" class="btn btn-success">Download</a>` : ''}
                                            <button type="button" class="btn btn-outline-danger delete-job" data-job-id="${job.job_id}">Delete</button>
                                        </div>
                                    </div>
                                `;
                                
                                jobsList.appendChild(jobCard);
                            });
                            
                            // Add event listeners to dynamic buttons
                            document.querySelectorAll('.check-status').forEach(button => {
                                button.addEventListener('click', function() {
                                    const jobId = this.getAttribute('data-job-id');
                                    checkJobStatus(jobId);
                                });
                            });
                            
                            document.querySelectorAll('.delete-job').forEach(button => {
                                button.addEventListener('click', function() {
                                    const jobId = this.getAttribute('data-job-id');
                                    deleteJob(jobId);
                                });
                            });
                        })
                        .catch(error => {
                            console.error('Error loading jobs:', error);
                            jobsList.innerHTML = '<div class="alert alert-danger">Failed to load jobs</div>';
                        })
                        .finally(() => {
                            loadingSpinner.style.display = 'none';
                        });
                }
                
                // Get appropriate badge class based on status
                function getStatusBadgeClass(status) {
                    switch (status) {
                        case 'completed':
                            return 'bg-success';
                        case 'running':
                            return 'bg-primary';
                        case 'failed':
                            return 'bg-danger';
                        case 'starting':
                            return 'bg-info';
                        default:
                            return 'bg-secondary';
                    }
                }
                
                // Check job status
                function checkJobStatus(jobId) {
                    fetch(`/api/job_status/${jobId}`)
                        .then(response => response.json())
                        .then(data => {
                            let message = `Status: ${data.status}\n`;
                            message += `Documents: ${data.downloaded_documents || 0}/${data.total_documents || 0}\n`;
                            
                            if (data.error) {
                                message += `\nError: ${data.error}`;
                            }
                            
                            alert(message);
                        })
                        .catch(error => {
                            console.error('Error checking status:', error);
                            alert('Failed to check job status');
                        });
                }
                
                // Delete job
                function deleteJob(jobId) {
                    if (!confirm('Are you sure you want to delete this job and its files?')) {
                        return;
                    }
                    
                    fetch(`/api/cleanup_job/${jobId}`, {
                        method: 'DELETE'
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'success') {
                            alert('Job deleted successfully');
                            loadJobs(); // Refresh jobs list
                        } else {
                            alert('Error: ' + data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Error deleting job:', error);
                        alert('Failed to delete job');
                    });
                }
                
                // Refresh jobs button
                document.getElementById('refreshJobs').addEventListener('click', loadJobs);
                
                // Initial load
                loadJobs();
            });
        </script>
    </body>
    </html>
    """

if __name__ == '__main__':
    # Start the cleanup scheduler in a separate thread
    threading.Thread(target=start_cleanup_scheduler, daemon=True).start()
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)

