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
                
                # Check for and close any extra tabs
                try:
                    if len(driver.window_handles) > 1:
                        current_handle = driver.current_window_handle
                        for handle in driver.window_handles:
                            if handle != current_handle:
                                driver.switch_to.window(handle)
                                driver.close()
                        driver.switch_to.window(current_handle)
                except Exception as e:
                    logger.warning(f"Error cleaning up tabs on reused driver: {str(e)}")
                
                # Reset cookies and state
                try:
                    driver.delete_all_cookies()
                    driver.get("about:blank")
                except Exception as e:
                    logger.warning(f"Error resetting driver state: {str(e)}")
                    # If we can't reset, create a new one
                    try:
                        driver.quit()
                    except:
                        pass
                    return self._create_new_driver()
                    
                return driver
            
        # Create a new WebDriver if none available
        return self._create_new_driver()
    
    def _create_new_driver(self):
        """Create a new WebDriver with optimized settings"""
        logger.info("Creating new WebDriver")
        options = Options()
        
        # Window settings
        options.add_argument("--window-size=1920,1080")
        
        # Security settings
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # Performance settings
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-popup-blocking")
        options.page_load_strategy = 'eager'  # Load page faster by not waiting for all resources
        
        # Uncomment for headless mode in production
        # options.add_argument("--headless=new")  # Use the new headless mode
        
        # Additional performance optimization
        prefs = {
            "profile.default_content_setting_values.notifications": 2,  # Block notifications
            "profile.default_content_settings.popups": 0,  # Block popups
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "credentials_enable_service": False,
            "password_manager_enabled": False
        }
        options.add_experimental_option("prefs", prefs)
        
        try:
            # Try with ChromeDriverManager first
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as e:
            logger.warning(f"Failed to create WebDriver using ChromeDriverManager: {str(e)}")
            
            try:
                # Fall back to default Chrome
                driver = webdriver.Chrome(options=options)
            except Exception as e2:
                logger.error(f"Failed to create WebDriver: {str(e2)}")
                raise
        
        # Configure timeouts
        driver.set_page_load_timeout(60)  # Increase timeout for slow pages
        driver.set_script_timeout(30)
        driver.implicitly_wait(10)  # Wait for elements to be available
        
        return driver
    
    def return_driver(self, driver):
        """Return a WebDriver to the pool or quit it if pool is full"""
        if driver:
            try:
                # Clear cookies and reset state
                driver.delete_all_cookies()
                
                # Close any extra tabs
                try:
                    if len(driver.window_handles) > 1:
                        current_handle = driver.current_window_handle
                        for handle in driver.window_handles:
                            if handle != current_handle:
                                driver.switch_to.window(handle)
                                driver.close()
                        driver.switch_to.window(current_handle)
                except Exception as e:
                    logger.warning(f"Error closing extra tabs: {str(e)}")
                
                # Navigate to blank page
                try:
                    driver.get("about:blank")
                except:
                    pass
                
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
            
    def __del__(self):
        """Ensure we clean up resources when object is destroyed"""
        self.shutdown()