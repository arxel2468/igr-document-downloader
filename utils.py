import time
import os
import pdfkit
import logging
from functools import lru_cache
from selenium.common.exceptions import TimeoutException, WebDriverException
from config import get_wkhtmltopdf_path

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def configure_pdfkit():
    """Return the proper configuration for pdfkit based on OS with caching."""
    try:
        return pdfkit.configuration(wkhtmltopdf=get_wkhtmltopdf_path())
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