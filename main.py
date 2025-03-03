from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
import time
import hashlib
import os
import pdfkit
from utils import solve_captcha, wait_and_click
from config import TESSERACT_PATH

def get_captcha_hash(image_path):
    """Generate a hash of the CAPTCHA image to detect changes."""
    with open(image_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def solve_and_submit_captcha(driver):
    """Solves and submits the CAPTCHA, checking if it has changed."""
    captcha_element = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "imgCaptcha_new")))
    captcha_image_path = "captcha.png"
    captcha_element.screenshot(captcha_image_path)

    old_captcha_hash = get_captcha_hash(captcha_image_path)
    captcha_text = solve_captcha(captcha_image_path)

    print(f"Captcha Solved: {captcha_text}")

    # Enter CAPTCHA and submit
    captcha_input = driver.find_element(By.ID, "txtImg1")
    captcha_input.clear()
    captcha_input.send_keys(captcha_text)

    wait_and_click(driver, "//input[@id='btnSearch_RestMaha']")
    time.sleep(5)  # Allow time for processing

    # Check if results are loading
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CLASS_NAME, "resultTable")))
        print("Documents Loaded Successfully!")
        return True
    except TimeoutException:
        print("Results not found yet. Checking CAPTCHA state...")
        
    time.sleep(15)  # Give more time for results
    if "Please wait" in driver.page_source:
        print("Website is still processing. Waiting...")
        time.sleep(15)  # Additional wait for result processing


    # Check if CAPTCHA changed
    new_captcha_element = driver.find_element(By.ID, "imgCaptcha_new")
    new_captcha_element.screenshot(captcha_image_path)
    
    if get_captcha_hash(captcha_image_path) != old_captcha_hash:
        print("CAPTCHA changed! Retrying...")
        return solve_and_submit_captcha(driver)

    return False  # CAPTCHA didn't change, but results might still be processing


# Set up WebDriver
service = Service(ChromeDriverManager().install())
options = webdriver.ChromeOptions()
options.add_argument("--disable-popup-blocking")
driver = webdriver.Chrome(service=service, options=options)

try:
    # Open Website
    driver.get("https://freesearchigrservice.maharashtra.gov.in/")
    time.sleep(2)

    # Close Pop-up if present
    try:
        close_button = driver.find_element(By.CLASS_NAME, "btnclose")
        close_button.click()
        print("Pop-up closed.")
        time.sleep(1)
    except NoSuchElementException:
        print("No pop-up found, proceeding...")

    # Click "Rest of Maharashtra"
    wait_and_click(driver, "//input[@id='btnOtherdistrictSearch']")

    # Select Year
    WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "ddlFromYear1")))
    Select(driver.find_element(By.ID, "ddlFromYear1")).select_by_value("2024")

    # Select District
    Select(driver.find_element(By.ID, "ddlDistrict1")).select_by_visible_text("पुणे")

    # Wait for Tahsil dropdown to update and re-fetch element
    WebDriverWait(driver, 5).until(lambda d: len(Select(d.find_element(By.ID, "ddltahsil")).options) > 1)
    Select(driver.find_element(By.ID, "ddltahsil")).select_by_visible_text("मुळ्शी")

    # Wait for Village dropdown to update and re-fetch element
    WebDriverWait(driver, 5).until(lambda d: len(Select(d.find_element(By.ID, "ddlvillage")).options) > 1)
    Select(driver.find_element(By.ID, "ddlvillage")).select_by_visible_text("हिंजवडी")

    # Input Property No.
    property_input = driver.find_element(By.ID, "txtAttributeValue1")
    property_input.send_keys("1")
    # Solve CAPTCHA
    solve_and_submit_captcha(driver)

    # Wait for Results Table
    try:
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "RegistrationGrid")))
        print("Results loaded!")
        
        
    except TimeoutException:
        print("Failed to load results.")
        driver.quit()
        exit()
    
    # Find all IndexII buttons
    index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
    print(f"Found {len(index_buttons)} documents.")
    
    for i, button in enumerate(index_buttons):
        print(f"Downloading document {i+1}/{len(index_buttons)}...")
        
        before_click = len(driver.window_handles)
        driver.execute_script("arguments[0].click();", button)
        time.sleep(5)
        after_click = len(driver.window_handles)

        if before_click == after_click:
            print("New tab did not open. Possible popup blocking.")


        # Switch to the new tab
        driver.switch_to.window(driver.window_handles[-1])
        print("Switched to new tab:", driver.current_url)

        time.sleep(5)  # Increase if needed
        print("Page Source:", driver.page_source[:500])  # Print first 500 characters
        
        # Save the page
        report_filename = f"downloaded_reports/Index2_Doc_{i+1}.pdf"
        try:
            pdfkit.from_string(driver.page_source, report_filename)
            print(f"Saved: {report_filename}")
        except Exception as e:
            print("PDFKit Error:", e)


        # Close the new tab and switch back to the original tab
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        print("All documents downloaded successfully!")
        time.sleep(5)

except Exception as e:
    print("Error:", e)

finally:
    time.sleep(5)
    driver.quit()
