import os
import re
import time
import base64
import shutil
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    NoSuchElementException, 
    TimeoutException, 
    ElementClickInterceptedException, 
    StaleElementReferenceException,
    WebDriverException
)
from captcha_solver import solve_and_submit_captcha
from document_processor import process_all_index_buttons


logger = logging.getLogger(__name__)


def run_automation(year, district, tahsil, village, property_no, job_id, jobs, driver_pool):
    """Run the automation to download documents with improved error handling and recovery."""
    
    driver = None
    jobs[job_id]["status"] = "running"
    
    # Create directories
    output_dir = jobs[job_id]["directory"]
    os.makedirs(output_dir, exist_ok=True)
    
    debug_dir = os.path.join(output_dir, "debug")
    os.makedirs(debug_dir, exist_ok=True)
    
    # Initialize tracking variables
    successfully_downloaded = 0
    documents_processed = 0
    total_documents_found = 0
    current_page = 1
    processed_pages = set()
    max_iterations = 100  # Maximum number of loop iterations to prevent infinite loops
    loop_count = 0
    
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
        fill_form_success = fill_search_form(driver, year, district, tahsil, village, property_no, debug_dir)
        if not fill_form_success:
            raise Exception("Failed to fill search form correctly")
        
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

        # Process all documents across all pages
        processing_results = process_all_index_buttons(driver, output_dir, debug_dir, job_id, jobs)

        
        # Update job status
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["message"] = f"Job completed. Downloaded {processing_results['documents_downloaded']}/{processing_results['documents_processed']} documents."
        logger.info(f"Job completed. Downloaded {processing_results['documents_downloaded']}/{processing_results['documents_processed']} documents.")
        
    except Exception as e:
        # Main error handling for the entire function
        error_message = f"Automation failed: {str(e)}"
        logger.error(error_message)
        
        # Save screenshot if driver is available
        if driver:
            try:
                driver.save_screenshot(os.path.join(debug_dir, "automation_failure.png"))
            except:
                logger.error("Failed to save error screenshot")
        
        # Update job status
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = error_message
        
    finally:
        # Clean up resources
        if driver:
            try:
                cleanup_browser_session(driver)
                driver_pool.return_driver(driver)
                logger.info("Browser returned to pool")
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {str(cleanup_error)}")
                try:
                    driver.quit()
                    logger.info("Browser quit after failed return to pool")
                except:
                    logger.error("Failed to quit browser")
        
        # Clean up pycache
        try:
            if os.path.isdir("__pycache__"):
                shutil.rmtree("__pycache__")
        except Exception as e:
            logger.error(f"Error cleaning __pycache__: {str(e)}")


def fill_search_form(driver, year, district, tahsil, village, property_no, debug_dir):
    """Fill the search form with robust error handling."""
    try:
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
            return False
        
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
            return False
        
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
            return False
        
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
            return False
        
        # Input Property No.
        try:
            property_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "txtAttributeValue1"))
            )
            property_input.clear()  # Clear any existing text
            property_input.send_keys(property_no)
            logger.info(f"Property number '{property_no}' entered")
        except Exception as e:
            logger.error(f"Failed to enter property number: {str(e)}")
            driver.save_screenshot(os.path.join(debug_dir, "property_input_error.png"))
            return False
            
        return True
    except Exception as e:
        logger.error(f"Error filling search form: {str(e)}")
        return False



def cleanup_browser_session(driver):
    """Clean up browser session before returning to pool."""
    try:
        # Close all tabs except the first one
        if len(driver.window_handles) > 1:
            original_handle = driver.window_handles[0]
            for handle in driver.window_handles:
                if handle != original_handle:
                    try:
                        driver.switch_to.window(handle)
                        driver.close()
                    except:
                        logger.warning(f"Failed to close tab {handle}")
            
            # Switch back to original tab
            try:
                driver.switch_to.window(original_handle)
            except:
                logger.warning("Failed to switch to original tab")
        
        # Navigate to blank page to release resources
        try:
            driver.get("about:blank")
            time.sleep(1)
        except:
            logger.warning("Failed to navigate to blank page")
            
    except Exception as e:
        logger.error(f"Error during browser cleanup: {str(e)}")
        raise