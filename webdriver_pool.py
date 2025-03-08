import logging
import threading
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

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