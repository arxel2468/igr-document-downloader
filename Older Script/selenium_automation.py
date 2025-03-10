import time
import os
import re
import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
from io import BytesIO
import shutil
import sys
import base64

# Web automation imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException, 
    TimeoutException, 
    ElementClickInterceptedException, 
    StaleElementReferenceException,
    WebDriverException
)
from webdriver_manager.chrome import ChromeDriverManager

# Image processing imports
import platform
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract

# PDF generation
import pdfkit

# Web server
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import zipfile


# Configure logging with a more detailed format and proper encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s',
    handlers=[
        logging.FileHandler("igr_automation.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)  # This will use the system's default encoding
    ]
)
logger = logging.getLogger(__name__)

# Load location data with proper error handling
try:
    with open('maharashtra_locations_final.json', 'r', encoding='utf-8') as f:
        location_data = json.load(f)
        
    # Create location data structures
    districts_data = list(location_data.keys())
    
    # Create tahsil_data dictionary
    tahsil_data = {district: list(tahsils_data.keys()) for district, tahsils_data in location_data.items()}
    
    # Create village_data dictionary
    village_data = {}
    for district, tahsils_data in location_data.items():
        for tahsil, villages in tahsils_data.items():
            village_data[tahsil] = villages
            
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.critical(f"Failed to load location data: {str(e)}")
    location_data = {}
    districts_data = []
    tahsil_data = {}
    village_data = {}


# Configure Tesseract path based on OS
def configure_tesseract():
    """Configure Tesseract path based on operating system"""
    if platform.system() == 'Windows':
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    elif platform.system() == 'Linux':
        pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
    else:  # macOS
        pytesseract.pytesseract.tesseract_cmd = "/usr/local/bin/tesseract"

configure_tesseract()


# WebDriver pool to reuse browser instances
class WebDriverPool:
    def __init__(self, max_drivers=3):
        self.max_drivers = max_drivers
        self.available_drivers = []
        self.lock = threading.Lock()
        
    def get_driver(self):
        """Get a WebDriver from the pool or create a new one"""
        with self.lock:
            if self.available_drivers:
                driver = self.available_drivers.pop()
                logger.debug("Reusing existing WebDriver")
                return driver
            
        # Create a new WebDriver if none available
        logger.debug("Creating new WebDriver")
        options = Options()
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # Uncomment for headless mode in production
        # options.add_argument("--headless")
        
        # Add performance optimization
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.page_load_strategy = 'eager'
        
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(60)
            driver.set_script_timeout(30)
            return driver
        except Exception as e:
            logger.error(f"Failed to create WebDriver: {str(e)}")
            raise
    
    def return_driver(self, driver):
        """Return a WebDriver to the pool or quit it if pool is full"""
        if driver:
            try:
                # Clear cookies and reset state
                driver.delete_all_cookies()
                
                with self.lock:
                    if len(self.available_drivers) < self.max_drivers:
                        self.available_drivers.append(driver)
                        logger.debug("Returned WebDriver to pool")
                        return
                    
                # If pool is full, quit the driver
                logger.debug("Pool full, quitting WebDriver")
                driver.quit()
            except Exception as e:
                logger.error(f"Error returning driver to pool: {str(e)}")
                try:
                    driver.quit()
                except:
                    pass
    
    def shutdown(self):
        """Quit all WebDrivers in the pool"""
        with self.lock:
            for driver in self.available_drivers:
                try:
                    driver.quit()
                except:
                    pass
            self.available_drivers.clear()


# Create a global WebDriver pool
driver_pool = WebDriverPool(max_drivers=3)


def solve_captcha_with_multiple_techniques(image_path):
    """Try multiple techniques to solve CAPTCHA with improved error handling"""
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
        },
        {
            "description": "Bilateral filter simulation",
            "preprocess": lambda img: ImageEnhance.Contrast(
                ImageEnhance.Sharpness(img.convert('L')).enhance(2)
            ).enhance(2.5).point(lambda p: p > 130 and 255)
        },
        {
            "description": "Inverted colors",
            "preprocess": lambda img: ImageOps.invert(img.convert('L'))
        }
    ]
    
    results = []
    
    try:
        img = Image.open(image_path)
    except Exception as e:
        logger.error(f"Failed to open CAPTCHA image: {str(e)}")
        return ""
    
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
            
            # Process the detected text to fix common OCR errors
            captcha_text = captcha_text.replace('O', '0').replace('I', '1').replace('L', '1')
            captcha_text = re.sub(r'[^A-Z0-9]', '', captcha_text.upper())
            
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
    try:
        return pytesseract.image_to_string(
            f"{image_path}_technique_0.png",
            config='--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        ).strip()
    except Exception as e:
        logger.error(f"Failed to get fallback CAPTCHA text: {str(e)}")
        return ""


def get_captcha_hash(image_path):
    """Generate a hash of the CAPTCHA image to detect changes."""
    try:
        with open(image_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        logger.error(f"Failed to hash CAPTCHA image: {str(e)}")
        return ""


@lru_cache(maxsize=1)
def configure_pdfkit():
    """Return the proper configuration for pdfkit based on OS with caching."""
    try:
        if platform.system() == 'Windows':
            return pdfkit.configuration(wkhtmltopdf=r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe')
        elif platform.system() == 'Linux':
            return pdfkit.configuration(wkhtmltopdf='/usr/bin/wkhtmltopdf')
        else:  # macOS
            return pdfkit.configuration(wkhtmltopdf='/usr/local/bin/wkhtmltopdf')
    except Exception as e:
        logger.error(f"Failed to configure pdfkit: {str(e)}")
        return None


def wait_for_new_tab(driver, original_handles, timeout=10):
    """Wait for a new tab to open and return its handle with improved error handling."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            current_handles = driver.window_handles
            if len(current_handles) > len(original_handles):
                # Return the new handle
                new_handles = set(current_handles) - set(original_handles)
                return list(new_handles)[0]
        except WebDriverException as e:
            logger.error(f"WebDriver error while waiting for new tab: {str(e)}")
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    raise TimeoutException("New tab did not open within the timeout period")


def solve_and_submit_captcha(driver, property_no, max_attempts=5):
    """Solves and submits the CAPTCHA with improved error handling and more retries."""
    
    # Take a screenshot of initial state
    os.makedirs("temp_captchas", exist_ok=True)
    driver.save_screenshot("temp_captchas/initial_state.png")
    
    # First check ONLY for document links, ignore RegistrationGrid
    index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
    if index_buttons:
        logger.info(f"Found {len(index_buttons)} document links already - no CAPTCHA needed")
        return True
        
    # Check for "No Records Found" message
    if "No Records Found" in driver.page_source:
        logger.info("No records found message detected initially")
        return "NO_RECORDS"
    
    # If we get here, we need to solve the CAPTCHA
    for attempt in range(max_attempts):
        try:
            logger.info(f"CAPTCHA attempt {attempt+1}/{max_attempts}")
            
            # Look for CAPTCHA element
            captcha_elements = driver.find_elements(By.ID, "imgCaptcha_new")
            if not captcha_elements:
                logger.warning("CAPTCHA element not found, checking for results anyway")
                
                # Check for document links
                index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
                if index_buttons:
                    logger.info(f"Found {len(index_buttons)} document links")
                    return True
                    
                # Check for "No Records Found" message
                if "No Records Found" in driver.page_source:
                    logger.info("No records found message detected")
                    return "NO_RECORDS"
                
                logger.warning("No CAPTCHA and no results - waiting a moment")
                time.sleep(3)
                continue
            
            # Take screenshot of CAPTCHA and get its hash
            captcha_element = captcha_elements[0]
            captcha_image_path = os.path.join("temp_captchas", f"captcha_attempt_{attempt}.png")
            captcha_element.screenshot(captcha_image_path)
            captcha_hash = get_captcha_hash(captcha_image_path)
            
            # Solve CAPTCHA
            captcha_text = solve_captcha_with_multiple_techniques(captcha_image_path)
            
            if not captcha_text:
                logger.warning(f"Empty CAPTCHA solution on attempt {attempt+1}")
                time.sleep(1)
                continue
                
            logger.info(f"CAPTCHA solution: '{captcha_text}'")
            
            # Before entering, verify CAPTCHA hasn't changed
            try:
                current_captcha_elements = driver.find_elements(By.ID, "imgCaptcha_new")
                if current_captcha_elements:
                    current_captcha = current_captcha_elements[0]
                    current_path = os.path.join("temp_captchas", f"captcha_current_{attempt}.png")
                    current_captcha.screenshot(current_path)
                    current_hash = get_captcha_hash(current_path)
                    
                    if current_hash != captcha_hash:
                        logger.info("CAPTCHA changed before entering solution, retrying...")
                        continue
            except Exception as e:
                logger.warning(f"Error checking if CAPTCHA changed: {str(e)}")
            
            # Enter property number and CAPTCHA
            try:
                property_input = driver.find_element(By.ID, "txtAttributeValue1")
                property_input.clear()
                property_input.send_keys(property_no)
                logger.info(f"Property number '{property_no}' entered")
                
                captcha_input = driver.find_element(By.ID, "txtImg1")
                captcha_input.clear()
                captcha_input.send_keys(captcha_text)
            except Exception as e:
                logger.warning(f"Error entering property number or CAPTCHA: {str(e)}")
                continue
            
            # Verify CAPTCHA hasn't changed before clicking search
            try:
                current_captcha_elements = driver.find_elements(By.ID, "imgCaptcha_new")
                if current_captcha_elements:
                    current_captcha = current_captcha_elements[0]
                    current_path = os.path.join("temp_captchas", f"captcha_before_click_{attempt}.png")
                    current_captcha.screenshot(current_path)
                    current_hash = get_captcha_hash(current_path)
                    
                    if current_hash != captcha_hash:
                        logger.info("CAPTCHA changed after entering solution but before clicking search, retrying...")
                        continue
            except Exception as e:
                logger.warning(f"Error checking if CAPTCHA changed before click: {str(e)}")
            
            # Click search button
            try:
                search_buttons = driver.find_elements(By.ID, "btnSearch_RestMaha")
                if not search_buttons:
                    logger.warning("Search button not found")
                    continue
                
                search_button = search_buttons[0]
                driver.execute_script("arguments[0].scrollIntoView(true);", search_button)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", search_button)
                logger.info("Search button clicked")
            except Exception as e:
                logger.warning(f"Error clicking search: {str(e)}")
                continue
            
            # Wait for results or new CAPTCHA
            logger.info("Waiting for results...")
            
            # Wait up to 30 seconds
            start_time = time.time()
            
            while time.time() - start_time < 30:
                # Check for document links
                index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
                if index_buttons:
                    logger.info(f"Found {len(index_buttons)} document links after {int(time.time() - start_time)} seconds")
                    return True
                
                # Check for "No Records Found"
                if "No Records Found" in driver.page_source:
                    logger.info("No records found message displayed")
                    return "NO_RECORDS"
                
                # Check if CAPTCHA changed (indicating incorrect solution)
                current_captcha_elements = driver.find_elements(By.ID, "imgCaptcha_new")
                if current_captcha_elements:
                    try:
                        current_captcha = current_captcha_elements[0]
                        current_path = os.path.join("temp_captchas", f"captcha_during_wait_{attempt}.png")
                        current_captcha.screenshot(current_path)
                        current_hash = get_captcha_hash(current_path)
                        
                        if current_hash != captcha_hash:
                            logger.info("CAPTCHA changed during wait (incorrect solution)")
                            break  # Break out of wait loop, try next CAPTCHA
                    except:
                        pass
                
                # Take progress screenshots every 5 seconds
                if int(time.time() - start_time) % 5 == 0:
                    driver.save_screenshot(f"temp_captchas/waiting_{attempt}_{int(time.time() - start_time)}.png")
                
                time.sleep(1)
            
            # After waiting, check one more time for results
            index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
            if index_buttons:
                logger.info(f"Found {len(index_buttons)} document links after wait")
                return True
                
            # Check for "No Records Found" again
            if "No Records Found" in driver.page_source:
                logger.info("No records found message detected after wait")
                return "NO_RECORDS"
                
            logger.info("No results found after this attempt, trying again")
            
        except Exception as e:
            logger.error(f"Error during CAPTCHA attempt {attempt+1}: {str(e)}")
            driver.save_screenshot(f"temp_captchas/error_captcha_{attempt+1}.png")
            
            # Even after error, check for results
            index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
            if index_buttons:
                logger.info(f"Found {len(index_buttons)} document links despite error")
                return True
            
            time.sleep(2)  # Delay before next attempt
    
    # After all attempts, check one more time for results
    index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
    if index_buttons:
        logger.info(f"Found {len(index_buttons)} document links after all attempts")
        return True
        
    # Check for "No Records Found" one final time
    if "No Records Found" in driver.page_source:
        logger.info("No records found message detected at end")
        return "NO_RECORDS"
        
    logger.error("All CAPTCHA attempts failed")
    return False


def run_automation(year, district, tahsil, village, property_no, job_id, jobs):
    """Run the automation to download documents with improved error handling and recovery."""
    
    driver = None
    jobs[job_id]["status"] = "running"
    
    # Create directories
    output_dir = jobs[job_id]["directory"]
    os.makedirs(output_dir, exist_ok=True)
    
    debug_dir = os.path.join(output_dir, "debug")
    os.makedirs(debug_dir, exist_ok=True)
    
    logger.info(f"Starting job {job_id} for property {property_no} in {village}, {tahsil}, {district} ({year})")
    
    try:
        # Get WebDriver from pool
        driver = driver_pool.get_driver()
        
        # Open Website with retry logic
        for attempt in range(3):
            try:
                driver.get("https://freesearchigrservice.maharashtra.gov.in/")
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                logger.info("Website opened successfully")
                break
            except (TimeoutException, WebDriverException) as e:
                if attempt == 2:  # Last attempt
                    raise
                logger.warning(f"Failed to load website (attempt {attempt+1}): {str(e)}")
                time.sleep(2)
        
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
        
        # Click "Rest of Maharashtra" with retry logic
        for attempt in range(3):
            try:
                rest_maha_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@id='btnOtherdistrictSearch']"))
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", rest_maha_button)
                time.sleep(0.5)  # Small delay after scrolling
                driver.execute_script("arguments[0].click();", rest_maha_button)
                logger.info("Selected 'Rest of Maharashtra'")
                
                # Wait for form to appear
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "ddlFromYear1"))
                )
                break
            except Exception as e:
                if attempt == 2:  # Last attempt
                    raise
                logger.warning(f"Failed to click 'Rest of Maharashtra' (attempt {attempt+1}): {str(e)}")
                time.sleep(2)
        
        # Take screenshot after "Rest of Maharashtra" selection
        driver.save_screenshot(os.path.join(debug_dir, "after_rest_maha.png"))
        
        # Form filling with more robust logic
        
        # Select Year
        try:
            # Wait for dropdown to be properly loaded
            WebDriverWait(driver, 10).until(
                lambda d: len(Select(d.find_element(By.ID, "ddlFromYear1")).options) > 1
            )
            
            year_dropdown = driver.find_element(By.ID, "ddlFromYear1")
            year_select = Select(year_dropdown)
            year_select.select_by_value(year)
            logger.info(f"Year {year} selected")
            time.sleep(1)  # Small delay after selection
        except Exception as e:
            logger.error(f"Failed to select year: {str(e)}")
            driver.save_screenshot(os.path.join(debug_dir, "year_select_error.png"))
            raise
        
        # Select District
        try:
            # Wait for dropdown to be properly loaded
            WebDriverWait(driver, 10).until(
                lambda d: len(Select(d.find_element(By.ID, "ddlDistrict1")).options) > 1
            )
            
            district_dropdown = driver.find_element(By.ID, "ddlDistrict1")
            district_select = Select(district_dropdown)
            district_select.select_by_visible_text(district)
            logger.info(f"District '{district}' selected")
            
            # Wait for district selection to update with verification
            WebDriverWait(driver, 10).until(
                lambda d: len(Select(d.find_element(By.ID, "ddltahsil")).options) > 1
            )
        except Exception as e:
            logger.error(f"Failed to select district: {str(e)}")
            driver.save_screenshot(os.path.join(debug_dir, "district_select_error.png"))
            raise
        
        # Select Tahsil
        try:
            # Wait for the next dropdown to become properly populated
            time.sleep(2)  # Allow time for AJAX updates
            
            tahsil_dropdown = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "ddltahsil"))
            )
            tahsil_select = Select(tahsil_dropdown)
            tahsil_select.select_by_visible_text(tahsil)
            logger.info(f"Tahsil '{tahsil}' selected")
            
            # Wait for tahsil selection to update with verification
            WebDriverWait(driver, 10).until(
                lambda d: len(Select(d.find_element(By.ID, "ddlvillage")).options) > 1
            )
        except Exception as e:
            logger.error(f"Failed to select tahsil: {str(e)}")
            driver.save_screenshot(os.path.join(debug_dir, "tahsil_select_error.png"))
            raise
        
        # Select Village
        try:
            # Wait for the next dropdown to become properly populated
            time.sleep(2)  # Allow time for AJAX updates
            
            village_dropdown = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "ddlvillage"))
            )
            village_select = Select(village_dropdown)
            village_select.select_by_visible_text(village)
            logger.info(f"Village '{village}' selected")
        except Exception as e:
            logger.error(f"Failed to select village: {str(e)}")
            driver.save_screenshot(os.path.join(debug_dir, "village_select_error.png"))
            raise
        
        # Input Property No.
        try:
            property_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "txtAttributeValue1"))
            )
            property_input.send_keys(property_no)
            logger.info(f"Property number '{property_no}' entered")
        except Exception as e:
            logger.error(f"Failed to enter property number: {str(e)}")
            driver.save_screenshot(os.path.join(debug_dir, "property_input_error.png"))
            raise
        
        # Take screenshot of form before submission
        driver.save_screenshot(os.path.join(debug_dir, "form_filled.png"))
        
        # Solve CAPTCHA with improved handling
        logger.info("Attempting to solve CAPTCHA...")
        captcha_result = solve_and_submit_captcha(driver, property_no, max_attempts=5)

        if captcha_result == "NO_RECORDS":
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["message"] = "No records found for the given criteria"
            logger.info("Job completed: No records found")
            return
        elif not captcha_result:
            error_msg = "Failed to solve CAPTCHA after multiple attempts"
            logger.error(error_msg)
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = error_msg
            driver.save_screenshot(os.path.join(debug_dir, "captcha_failed.png"))
            return

        # CAPTCHA successful - results should be visible now
        logger.info("CAPTCHA solved successfully, results should be visible")
        driver.save_screenshot(os.path.join(debug_dir, "after_captcha_success.png"))

        # Wait a moment for any final page updates
        time.sleep(3)

        # Get total number of documents - this only gets the count on the first page
        try:
            index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
            documents_per_page = len(index_buttons)
            
            # Check for pagination to determine total documents
            pagination_elements = driver.find_elements(By.XPATH, "//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page$\")]")
            
            if pagination_elements:
                # Try to find the last page number
                last_page = 1
                for page_link in pagination_elements:
                    try:
                        page_num = int(page_link.text.strip())
                        if page_num > last_page:
                            last_page = page_num
                    except (ValueError, AttributeError):
                        continue
                
                # If we found pagination, estimate total documents
                if last_page > 1:
                    logger.info(f"Found pagination with {last_page} pages")
                    # Estimate total documents (assuming all pages have the same number of documents)
                    total_documents = documents_per_page * last_page
                else:
                    total_documents = documents_per_page
            else:
                total_documents = documents_per_page
                
            logger.info(f"Estimated total of {total_documents} documents to download across all pages")
            jobs[job_id]["total_documents"] = total_documents
            
            if documents_per_page == 0:
                # If we got here with zero documents, check for "No Records Found" message
                if "No Records Found" in driver.page_source:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["message"] = "No records found for the given criteria"
                else:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["message"] = "Search completed but no documents found for download"
                return
        except Exception as e:
            logger.error(f"Error finding document links: {str(e)}")
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "Failed to find document links"
            driver.save_screenshot(os.path.join(debug_dir, "no_document_links.png"))
            return
            
        # Process documents one by one with improved handling
        successfully_downloaded = 0
        
        # Initialize current page number
        current_page = 1
        continue_pagination = True
        
        while continue_pagination:
            # Take a screenshot of the current page for debugging
            driver.save_screenshot(os.path.join(debug_dir, f"page_{current_page}_initial.png"))
            
            # Process all documents on the current page using the specific indexII$X format
            # We'll try each index from 0 to 9 (maximum 10 documents per page)
            documents_on_current_page = 0
            
            for index in range(10):  # indexII$0 through indexII$9
                # Look for the specific button with the current index
                button_xpath = f"//input[@type='button' and @value='IndexII' and contains(@onclick, 'indexII${index}')]"
                buttons = driver.find_elements(By.XPATH, button_xpath)
                
                if not buttons:
                    logger.info(f"No button found for indexII${index} on page {current_page}, moving to next index")
                    continue
                
                documents_on_current_page += 1
                doc_number = successfully_downloaded + 1
                logger.info(f"Processing document {doc_number} (page {current_page}, indexII${index})...")
                
                try:
                    # Store original window handles
                    original_handles = driver.window_handles
                    
                    # Get the button and ensure it's in view
                    button = buttons[0]
                    driver.execute_script("arguments[0].scrollIntoView(true);", button)
                    time.sleep(1)
                    
                    # Take screenshot before clicking
                    driver.save_screenshot(os.path.join(debug_dir, f"before_click_page{current_page}_index{index}.png"))
                    
                    # Click the button using JavaScript for reliability
                    driver.execute_script("arguments[0].click();", button)
                    logger.info(f"Clicked on IndexII button for document {doc_number} (indexII${index})")
                    
                    try:
                        # Wait for and switch to new tab with increased timeout
                        new_tab = wait_for_new_tab(driver, original_handles, timeout=20)
                        driver.switch_to.window(new_tab)
                        logger.info(f"Switched to new tab: {driver.current_url}")
                        
                        # Wait for content to load with retry
                        for content_attempt in range(3):
                            try:
                                WebDriverWait(driver, 15).until(
                                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                                )
                                break
                            except TimeoutException:
                                if content_attempt == 2:  # Last attempt
                                    raise
                                logger.warning(f"Content load timeout (attempt {content_attempt+1})")
                                driver.refresh()
                                time.sleep(3)
                        
                        # Take screenshot of the document
                        document_screenshot = os.path.join(output_dir, f"Document_{doc_number}_screenshot.png")
                        driver.save_screenshot(document_screenshot)
                        
                        # Save document as PDF
                        pdf_path = os.path.join(output_dir, f"Document_{doc_number}.pdf")
                        
                        try:
                            # Use printToPDF command for better PDF generation
                            pdf_options = {
                                'printBackground': True,
                                'paperWidth': 8.27,
                                'paperHeight': 11.69,
                                'marginTop': 0.4,
                                'marginBottom': 0.4,
                                'scale': 1.0
                            }
                            pdf_data = driver.execute_cdp_cmd('Page.printToPDF', pdf_options)
                            
                            with open(pdf_path, 'wb') as pdf_file:
                                pdf_file.write(base64.b64decode(pdf_data['data']))
                            
                            logger.info(f"Document {doc_number} saved as PDF")
                            
                        except Exception as pdf_error:
                            logger.warning(f"PDF generation failed: {str(pdf_error)}")
                            # Fallback to screenshot
                            driver.save_screenshot(os.path.join(output_dir, f"Document_{doc_number}.png"))
                        
                        # Mark as successfully downloaded
                        successfully_downloaded += 1
                        jobs[job_id]["downloaded_documents"] = successfully_downloaded
                        
                        # Close the document tab and switch back to results tab
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                        
                        # Wait for page to stabilize after switching
                        time.sleep(3)
                        
                    except TimeoutException:
                        logger.error(f"New tab did not open for document {doc_number} (indexII${index})")
                        driver.save_screenshot(os.path.join(debug_dir, f"tab_timeout_doc_{doc_number}_index{index}.png"))
                        
                        # Make sure we're on the original tab
                        if len(driver.window_handles) > 1:
                            driver.switch_to.window(driver.window_handles[0])
                    
                except Exception as e:
                    logger.error(f"Error processing document {doc_number} (indexII${index}): {str(e)}")
                    driver.save_screenshot(os.path.join(debug_dir, f"doc_error_{doc_number}_index{index}.png"))
                    
                    # Make sure we're on the original tab
                    if len(driver.window_handles) > 1:
                        driver.switch_to.window(driver.window_handles[0])
                
                # Small pause between documents to avoid overwhelming the server
                time.sleep(3)
            
            # Take a screenshot after processing all documents on this page
            driver.save_screenshot(os.path.join(debug_dir, f"page_{current_page}_after_all_docs.png"))
            logger.info(f"Completed processing {documents_on_current_page} documents on page {current_page}")
            
            # Check for next page link using the exact format from the website
            next_page_num = current_page + 1
            next_page_xpath = f"//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page${next_page_num}')\")]"
            
            next_page_links = driver.find_elements(By.XPATH, next_page_xpath)
            
            if next_page_links:
                try:
                    logger.info(f"Navigating to page {next_page_num}")
                    # Take screenshot before clicking next page
                    driver.save_screenshot(os.path.join(debug_dir, f"before_page_{next_page_num}.png"))
                    
                    # Click using JavaScript for reliability
                    driver.execute_script("arguments[0].click();", next_page_links[0])
                    
                    # Wait for the page to load with new document buttons
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.XPATH, "//input[@type='button' and @value='IndexII']"))
                    )
                    
                    # Increment page counter
                    current_page += 1
                    
                    # Wait for page to stabilize
                    time.sleep(5)
                    
                    # Take screenshot after page navigation
                    driver.save_screenshot(os.path.join(debug_dir, f"after_page_{current_page}.png"))
                    
                except Exception as e:
                    logger.error(f"Failed to navigate to the next page: {str(e)}")
                    driver.save_screenshot(os.path.join(debug_dir, f"page_navigation_error_{current_page}.png"))
                    continue_pagination = False
            else:
                # Try an alternative approach to find the next page link
                try:
                    # Look for any pagination links
                    pagination_links = driver.find_elements(By.XPATH, "//a[contains(@href, 'javascript:__doPostBack')]")
                    
                    # Filter for links that have the next page number
                    next_page_candidates = []
                    for link in pagination_links:
                        if link.text.strip() == str(next_page_num):
                            next_page_candidates.append(link)
                    
                    if next_page_candidates:
                        logger.info(f"Found alternative next page link to page {next_page_num}")
                        driver.execute_script("arguments[0].click();", next_page_candidates[0])
                        
                        # Wait for the page to load
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.XPATH, "//input[@type='button' and @value='IndexII']"))
                        )
                        
                        # Increment page counter
                        current_page += 1
                        
                        # Wait for page to stabilize
                        time.sleep(5)
                    else:
                        logger.info("No next page link found. Pagination complete.")
                        continue_pagination = False
                except Exception as alt_e:
                    logger.warning(f"Alternative pagination approach failed: {str(alt_e)}")
                    continue_pagination = False
        
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


if __name__ == '__main__':
    # Start the cleanup scheduler in a separate thread
    threading.Thread(target=start_cleanup_scheduler, daemon=True).start()
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)