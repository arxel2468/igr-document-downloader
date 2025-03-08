# captcha_solver.py
import os
import re
import hashlib
import logging
import time
from collections import Counter
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, WebDriverException
from config import get_tesseract_path

logger = logging.getLogger(__name__)

# Configure Tesseract path
pytesseract.pytesseract.tesseract_cmd = get_tesseract_path()

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
            