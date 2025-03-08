# config.py
import os
import logging
import sys
import json
import platform
from datetime import datetime

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, 'downloads')

# Ensure downloads directory exists
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Application settings
TIMEOUT = 30  # seconds
MAX_RETRIES = 3
WEBDRIVER_POOL_SIZE = 3

def setup_logging():
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(f"logs_{datetime.now().strftime('%Y%m%d')}.log"),
            logging.StreamHandler()
        ]
    )

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

# Configure paths based on OS
def get_tesseract_path():
    """Return the path to Tesseract OCR executable based on OS."""
    if platform.system() == 'Windows':
        return r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    elif platform.system() == 'Linux':
        return "/usr/bin/tesseract"
    else:  # macOS
        return "/usr/local/bin/tesseract"

def get_wkhtmltopdf_path():
    """Return the path to wkhtmltopdf executable based on OS."""
    if platform.system() == 'Windows':
        return r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
    elif platform.system() == 'Linux':
        return '/usr/bin/wkhtmltopdf'
    else:  # macOS
        return '/usr/local/bin/wkhtmltopdf'

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