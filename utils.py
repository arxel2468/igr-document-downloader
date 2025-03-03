import pytesseract
from PIL import Image
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from config import TESSERACT_PATH

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

def solve_captcha(image_path):
    """Extract text from CAPTCHA image using Tesseract OCR."""
    img = Image.open(image_path)
    captcha_text = pytesseract.image_to_string(img, config='--psm 6')
    return captcha_text.strip()

def wait_and_click(driver, xpath, timeout=10):
    """Waits for an element to be clickable and clicks it."""
    WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath))).click()
