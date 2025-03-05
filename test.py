import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock, mock_open
import platform
from PIL import Image
import hashlib
from io import BytesIO
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import zipfile

# Import the functions to test
import selenium_automation
from selenium_automation import (
    solve_captcha_with_multiple_techniques, get_captcha_hash,
    configure_pdfkit, wait_for_new_tab, solve_and_submit_captcha,
    run_automation, districts_data, tahsil_data, village_data
)

# Create a fixture for temporary directory
@pytest.fixture
def temp_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)

# Create a test image for CAPTCHA testing
@pytest.fixture
def test_captcha_image(temp_dir):
    img = Image.new('RGB', (150, 50), color='white')
    img_path = os.path.join(temp_dir, 'test_captcha.png')
    img.save(img_path)
    return img_path

# Test data loading
def test_location_data_loaded():
    """Test that location data is loaded correctly"""
    # Check districts are loaded
    assert len(districts_data) > 0, "No districts were loaded"
    
    # Check tahsil data is loaded
    assert len(tahsil_data) > 0, "No tahsil data was loaded"
    
    # Check village data is loaded
    assert len(village_data) > 0, "No village data was loaded"
    
    # Check relationships between data
    for district in districts_data:
        assert district in tahsil_data, f"District {district} not found in tahsil_data"
        
        for tahsil in tahsil_data[district]:
            assert tahsil in village_data, f"Tahsil {tahsil} not found in village_data"
            assert len(village_data[tahsil]) > 0, f"No villages found for tahsil {tahsil}"

# Test JSON data loading
@patch('builtins.open', new_callable=mock_open, read_data='{"District1": {"Tahsil1": ["Village1", "Village2"]}}')
def test_json_loading(mock_file):
    """Test that JSON data is loaded correctly"""
    # Re-import module to trigger JSON loading with mock data
    with patch('json.load') as mock_json_load:
        mock_json_load.return_value = {"District1": {"Tahsil1": ["Village1", "Village2"]}}
        import importlib
        importlib.reload(selenium_automation)
        
        # Check mock was called correctly
        mock_file.assert_called_once_with('maharashtra_locations_final.json', 'r', encoding='utf-8')
        
        # Check JSON was loaded
        mock_json_load.assert_called_once()

# Test the CAPTCHA hash function
def test_get_captcha_hash(test_captcha_image):
    """Test that the CAPTCHA hash function works correctly"""
    hash1 = get_captcha_hash(test_captcha_image)
    
    # Hash should be a string of length 32 (MD5)
    assert isinstance(hash1, str)
    assert len(hash1) == 32
    
    # Same image should produce same hash
    hash2 = get_captcha_hash(test_captcha_image)
    assert hash1 == hash2
    
    # Different image should produce different hash
    img = Image.new('RGB', (150, 50), color='black')
    diff_img_path = os.path.join(os.path.dirname(test_captcha_image), 'diff_captcha.png')
    img.save(diff_img_path)
    hash3 = get_captcha_hash(diff_img_path)
    assert hash1 != hash3

# Test CAPTCHA solving with mocked tesseract
@patch('pytesseract.image_to_string')
def test_solve_captcha_with_multiple_techniques(mock_image_to_string, test_captcha_image):
    """Test the CAPTCHA solving function with mocked tesseract"""
    # Mock tesseract to return a valid CAPTCHA
    mock_image_to_string.return_value = "ABC123"
    
    result = solve_captcha_with_multiple_techniques(test_captcha_image)
    
    # Check that tesseract was called at least once
    assert mock_image_to_string.called
    
    # Check the result
    assert result == "ABC123"
    
    # Test with invalid CAPTCHA format
    mock_image_to_string.return_value = "invalid"
    
    result = solve_captcha_with_multiple_techniques(test_captcha_image)
    
    # Since all techniques return invalid format, it should return the best guess
    assert result == "invalid"

# Test CAPTCHA solving with multiple valid results
@patch('pytesseract.image_to_string')
def test_solve_captcha_with_multiple_valid_results(mock_image_to_string, test_captcha_image):
    """Test CAPTCHA solving when multiple techniques return valid results"""
    # Mock tesseract to return different valid CAPTCHAs for different techniques
    # First call returns "ABC123", second "DEF456", third "ABC123" etc.
    mock_image_to_string.side_effect = ["ABC123", "DEF456", "ABC123", "GHI789", "ABC123"]
    
    # Mock re.match to make all results valid format
    with patch('re.match', return_value=True):
        result = solve_captcha_with_multiple_techniques(test_captcha_image)
    
    # Should pick the most common valid result (ABC123)
    assert result == "ABC123"

# Test CAPTCHA solving with exceptions
@patch('pytesseract.image_to_string')
@patch('PIL.Image.open')
def test_solve_captcha_with_exceptions(mock_image_open, mock_image_to_string, test_captcha_image):
    """Test CAPTCHA solving when some techniques throw exceptions"""
    # Mock image open to return a valid image
    mock_img = MagicMock()
    mock_image_open.return_value = mock_img
    
    # Mock preprocessed images to raise exception for some techniques
    mock_preprocess = MagicMock()
    mock_preprocess.save.side_effect = [None, Exception("Image processing error"), None, None, None]
    
    # Mock the preprocess lambdas to return mock_preprocess
    with patch.object(selenium_automation.ImageEnhance, 'Contrast') as mock_contrast:
        mock_contrast.return_value.enhance.return_value.point.return_value = mock_preprocess
        mock_contrast.return_value.enhance.return_value = mock_preprocess
        
        with patch.object(selenium_automation.ImageOps, 'autocontrast', return_value=mock_preprocess):
            # Mock tesseract to return a valid CAPTCHA
            mock_image_to_string.return_value = "ABC123"
            
            # Test with exception in one technique
            result = solve_captcha_with_multiple_techniques(test_captcha_image)
            
            # Should still return result from other techniques
            assert result == "ABC123"

# Test pdfkit configuration
def test_configure_pdfkit():
    """Test the pdfkit configuration function"""
    with patch('platform.system') as mock_system:
        # Test Windows configuration
        mock_system.return_value = 'Windows'
        with patch('pdfkit.configuration') as mock_config:
            configure_pdfkit()
            mock_config.assert_called_with(wkhtmltopdf=r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe')
        
        # Test Linux configuration
        mock_system.return_value = 'Linux'
        with patch('pdfkit.configuration') as mock_config:
            configure_pdfkit()
            mock_config.assert_called_with(wkhtmltopdf='/usr/bin/wkhtmltopdf')
        
        # Test macOS configuration
        mock_system.return_value = 'Darwin'
        with patch('pdfkit.configuration') as mock_config:
            configure_pdfkit()
            mock_config.assert_called_with(wkhtmltopdf='/usr/local/bin/wkhtmltopdf')

# Test wait_for_new_tab function
def test_wait_for_new_tab():
    """Test the wait_for_new_tab function"""
    # Mock WebDriver
    driver = MagicMock()
    
    # Initial window handles
    original_handles = ['window1']
    
    # Test successful case - new tab opens
    driver.window_handles = ['window1', 'window2']
    
    with patch('time.time', side_effect=[0, 1, 2]):  # Mock time.time to avoid actual waiting
        with patch('time.sleep'):  # Mock sleep to avoid actual waiting
            new_handle = wait_for_new_tab(driver, original_handles, timeout=10)
            assert new_handle == 'window2'
    
    # Test timeout case - no new tab opens
    driver.window_handles = ['window1']
    
    with patch('time.time', side_effect=[0, 11]):  # Mock time to simulate timeout
        with patch('time.sleep'):  # Mock sleep to avoid actual waiting
            with pytest.raises(TimeoutException):
                wait_for_new_tab(driver, original_handles, timeout=10)

# Test CAPTCHA solving and submission
@patch('selenium.webdriver.support.wait.WebDriverWait')
def test_solve_and_submit_captcha(mock_wait):
    """Test the solve_and_submit_captcha function"""
    # Mock WebDriver and WebDriverWait
    driver = MagicMock()
    mock_wait_instance = MagicMock()
    mock_wait.return_value = mock_wait_instance
    
    # Mock the until method to return elements
    captcha_element = MagicMock()
    captcha_input = MagicMock()
    search_button = MagicMock()
    
    # Configure mocks for successful CAPTCHA solving
    mock_wait_instance.until.side_effect = [
        captcha_element,  # First call for finding CAPTCHA image
        captcha_input,    # Second call for finding CAPTCHA input
        search_button,    # Third call for finding search button
        True              # Fourth call for waiting for results
    ]
    
    # Mock find_elements to indicate results found
    driver.find_elements.return_value = [MagicMock()]
    
    # Mock the CAPTCHA solving function
    with patch('selenium_automation.solve_captcha_with_multiple_techniques', return_value='ABC123'):
        with patch('os.makedirs'):  # Mock directory creation
            with patch('selenium_automation.get_captcha_hash', return_value='hash123'):
                # Test successful CAPTCHA solving
                result = solve_and_submit_captcha(driver)
                
                # Check that the function returned True
                assert result is True
                
                # Check that CAPTCHA text was entered
                captcha_input.clear.assert_called_once()
                captcha_input.send_keys.assert_called_once_with('ABC123')
                
                # Check that search button was clicked
                driver.execute_script.assert_called_once()

# Test CAPTCHA solving with invalid verification code
@patch('selenium.webdriver.support.wait.WebDriverWait')
def test_solve_and_submit_captcha_invalid_code(mock_wait):
    """Test CAPTCHA solving with invalid verification code"""
    # Mock WebDriver and WebDriverWait
    driver = MagicMock()
    mock_wait_instance = MagicMock()
    mock_wait.return_value = mock_wait_instance
    
    # Configure mocks for CAPTCHA solving with invalid code
    captcha_element = MagicMock()
    captcha_input = MagicMock()
    search_button = MagicMock()
    
    # First attempt: Invalid verification code
    mock_wait_instance.until.side_effect = [
        captcha_element,  # Find CAPTCHA image
        captcha_input,    # Find CAPTCHA input
        search_button,    # Find search button
        None              # Wait for results
    ]
    
    # Mock page source to simulate invalid CAPTCHA message
    driver.page_source = "Invalid Verification Code"
    
    # Second attempt: Success
    driver.find_elements.side_effect = [
        [],  # First call (no results on first attempt)
        [MagicMock()]  # Second call (results found on second attempt)
    ]
    
    # Mock the CAPTCHA solving function
    with patch('selenium_automation.solve_captcha_with_multiple_techniques', return_value='ABC123'):
        with patch('os.makedirs'):  # Mock directory creation
            with patch('selenium_automation.get_captcha_hash') as mock_hash:
                # First hash (original)
                # Second hash (changed CAPTCHA after invalid code)
                # Third hash (new attempt)
                mock_hash.side_effect = ['hash1', 'hash2', 'hash3']
                
                # Mock find_element for checking if CAPTCHA changed
                driver.find_element.return_value = captcha_element
                
                # For the second attempt, change the page source
                def update_page_source(*args, **kwargs):
                    driver.page_source = "RegistrationGrid"
                    return None
                
                # Update the side effect for the second call to until
                mock_wait_instance.until.side_effect = [
                    captcha_element,  # 1st attempt: Find CAPTCHA image
                    captcha_input,    # 1st attempt: Find CAPTCHA input
                    search_button,    # 1st attempt: Find search button
                    update_page_source,  # 1st attempt: Wait for results (invalid)
                    captcha_element,  # 2nd attempt: Find CAPTCHA image
                    captcha_input,    # 2nd attempt: Find CAPTCHA input
                    search_button,    # 2nd attempt: Find search button
                    True              # 2nd attempt: Wait for results (success)
                ]
                
                # Mock time.sleep to avoid actual waiting
                with patch('time.sleep'):
                    # Test CAPTCHA solving with retry
                    result = solve_and_submit_captcha(driver)
                    
                    # Check that the function returned True (eventually succeeds)
                    assert result is True
                    
                    # Verify that send_keys was called multiple times (for each attempt)
                    assert captcha_input.send_keys.call_count >= 2

# Test CAPTCHA solving with all attempts failing
@patch('selenium.webdriver.support.wait.WebDriverWait')
def test_solve_and_submit_captcha_all_attempts_fail(mock_wait):
    """Test CAPTCHA solving when all attempts fail"""
    # Mock WebDriver and WebDriverWait
    driver = MagicMock()
    mock_wait_instance = MagicMock()
    mock_wait.return_value = mock_wait_instance
    
    # Configure mocks for CAPTCHA solving with all attempts failing
    captcha_element = MagicMock()
    captcha_input = MagicMock()
    search_button = MagicMock()
    
    # Mock the until method to return elements but fail verification
    mock_wait_instance.until.side_effect = [
        captcha_element, captcha_input, search_button, None,  # First attempt
        captcha_element, captcha_input, search_button, None,  # Second attempt
        captcha_element, captcha_input, search_button, None   # Third attempt
    ]
    
    # Mock page source to always show invalid CAPTCHA
    driver.page_source = "Invalid Verification Code"
    
    # Mock find_elements to indicate no results found
    driver.find_elements.return_value = []
    
    # Mock the CAPTCHA solving function
    with patch('selenium_automation.solve_captcha_with_multiple_techniques', return_value='ABC123'):
        with patch('os.makedirs'):  # Mock directory creation
            with patch('selenium_automation.get_captcha_hash', return_value='hash123'):
                with patch('time.sleep'):  # Mock sleep to avoid actual waiting
                    # Test CAPTCHA solving with all attempts failing
                    result = solve_and_submit_captcha(driver, max_attempts=3)
                    
                    # Check that the function returned False (all attempts failed)
                    assert result is False
                    
                    # Verify that send_keys was called for each attempt
                    assert captcha_input.send_keys.call_count == 3

# Test CAPTCHA solving with exceptions
@patch('selenium.webdriver.support.wait.WebDriverWait')
def test_solve_and_submit_captcha_with_exceptions(mock_wait):
    """Test CAPTCHA solving when exceptions occur"""
    # Mock WebDriver and WebDriverWait
    driver = MagicMock()
    mock_wait_instance = MagicMock()
    mock_wait.return_value = mock_wait_instance
    
    # Mock the until method to raise exceptions
    mock_wait_instance.until.side_effect = [
        Exception("Element not found"),  # First attempt
        Exception("Timeout"),            # Second attempt
        Exception("Stale element")       # Third attempt
    ]
    
    # Mock the CAPTCHA solving function
    with patch('selenium_automation.solve_captcha_with_multiple_techniques', return_value='ABC123'):
        with patch('os.makedirs'):  # Mock directory creation
            with patch('selenium_automation.get_captcha_hash', return_value='hash123'):
                # Mock screenshot to avoid errors
                driver.save_screenshot = MagicMock()
                
                # Test CAPTCHA solving with exceptions
                result = solve_and_submit_captcha(driver, max_attempts=3)
                
                # Check that the function returned False (all attempts failed)
                assert result is False
                
                # Verify that screenshot was taken for each error
                assert driver.save_screenshot.call_count == 3

# Test run_automation function
@patch('selenium.webdriver.chrome.service.Service')
@patch('webdriver_manager.chrome.ChromeDriverManager')
@patch('selenium.webdriver.Chrome')
def test_run_automation(mock_chrome, mock_driver_manager, mock_service, temp_dir):
    """Test the main automation function"""
    # Mock ChromeDriverManager and Service
    mock_driver_manager.return_value.install.return_value = 'C:/webdriver/bin/chromedriver.exe'
    mock_service.return_value = 'mock_service'
    
    # Mock WebDriver
    driver_instance = MagicMock()
    mock_chrome.return_value = driver_instance
    
    # Mock WebDriverWait
    with patch('selenium.webdriver.support.wait.WebDriverWait') as mock_wait:
        mock_wait_instance = MagicMock()
        mock_wait.return_value = mock_wait_instance
        
        # Mock button elements
        close_button = MagicMock()
        mock_wait_instance.until.return_value = close_button
        
        # Mock solve_and_submit_captcha to return success
        with patch('selenium_automation.solve_and_submit_captcha', return_value=True):
            # Create a jobs dictionary
            jobs = {
                'test_job': {
                    'status': 'pending',
                    'directory': temp_dir,
                    'progress': 0,
                    'files': []
                }
            }
            
            # Run the automation
            run_automation(
                year='2023',
                district='पुणे',
                tahsil='जुन्नर',
                village='अंजनावळे',
                property_no='123',
                job_id='test_job',
                jobs=jobs
            )
            
            # Check that the driver was initialized
            mock_chrome.assert_called_once()
            
            # Check that the website was opened
            driver_instance.get.assert_called_with('https://freesearchigrservice.maharashtra.gov.in/')
            
            # Check that the job status was updated
            assert jobs['test_job']['status'] == 'running'
            
            # Check that screenshots were taken
            driver_instance.save_screenshot.assert_called()
            
            # Check that the popup was handled
            close_button.click.assert_called_once()

# Test run_automation with popup exception
@patch('selenium.webdriver.chrome.service.Service')
@patch('webdriver_manager.chrome.ChromeDriverManager')
@patch('selenium.webdriver.Chrome')
def test_run_automation_popup_exception(mock_chrome, mock_driver_manager, mock_service, temp_dir):
    """Test run_automation when popup handling throws an exception"""
    # Mock ChromeDriverManager and Service
    mock_driver_manager.return_value.install.return_value = 'C:/webdriver/bin/chromedriver.exe'
    mock_service.return_value = 'mock_service'
    
    # Mock WebDriver
    driver_instance = MagicMock()
    mock_chrome.return_value = driver_instance
    
    # Mock WebDriverWait to raise an exception for popup
    with patch('selenium.webdriver.support.wait.WebDriverWait') as mock_wait:
        mock_wait_instance = MagicMock()
        mock_wait.return_value = mock_wait_instance
        
        # Make the until method raise a TimeoutException for popup
        mock_wait_instance.until.side_effect = TimeoutException("No popup found")
        
        # Mock solve_and_submit_captcha to return success
        with patch('selenium_automation.solve_and_submit_captcha', return_value=True):
            # Create a jobs dictionary
            jobs = {
                'test_job': {
                    'status': 'pending',
                    'directory': temp_dir,
                    'progress': 0,
                    'files': []
                }
            }
            
            # Run the automation
            run_automation(
                year='2023',
                district='पुणे',
                tahsil='जुन्नर',
                village='अंजनावळे',
                property_no='123',
                job_id='test_job',
                jobs=jobs
            )
            
            # Check that the job status was updated
            assert jobs['test_job']['status'] == 'running'
            
            # Check that the website was opened
            driver_instance.get.assert_called_with('https://freesearchigrservice.maharashtra.gov.in/')
            
            # Verify that the automation continues despite popup exception
            assert mock_wait_instance.until.call_count >= 1

# Test run_automation error handling
@patch('selenium.webdriver.chrome.service.Service')
@patch('webdriver_manager.chrome.ChromeDriverManager')
@patch('selenium.webdriver.Chrome')
def test_run_automation_error_handling(mock_chrome, mock_driver_manager, mock_service, temp_dir):
    """Test error handling in the run_automation function"""
    # Mock ChromeDriverManager and Service
    mock_driver_manager.return_value.install.return_value = 'C:/webdriver/bin/chromedriver.exe'
    mock_service.return_value = 'mock_service'
    
    # Mock WebDriver
    driver_instance = MagicMock()
    mock_chrome.return_value = driver_instance
    
    # Simulate an error during execution
    driver_instance.get.side_effect = Exception("Connection error")
    
    # Create a jobs dictionary
    jobs = {
        'test_job': {
            'status': 'pending',
            'directory': temp_dir,
            'progress': 0,
            'files': []
        }
    }
    
    # Run the automation which should handle the error
    run_automation(
        year='2023',
        district='पुणे',
        tahsil='जुन्नर',
        village='अंजनावळे',
        property_no='123',
        job_id='test_job',
        jobs=jobs
    )
    
    # Check that the job status was updated to error
    assert jobs['test_job']['status'] == 'error'
    
    # Check that error message was recorded
    assert 'error_message' in jobs['test_job']
    assert 'Connection error' in jobs['test_job']['error_message']

# Test Tesseract configuration
def test_tesseract_configuration():
    """Test that Tesseract is configured correctly for different platforms"""
    with patch('platform.system') as mock_system:
        # Test Windows configuration
        mock_system.return_value = 'Windows'
        import importlib
        importlib.reload(selenium_automation)
        assert selenium_automation.pytesseract.pytesseract.tesseract_cmd == r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        
        # Test Linux configuration
        mock_system.return_value = 'Linux'
        importlib.reload(selenium_automation)
        assert selenium_automation.pytesseract.pytesseract.tesseract_cmd == "/usr/bin/tesseract"
        
        # Test macOS configuration
        mock_system.return_value = 'Darwin'
        importlib.reload(selenium_automation)
        assert selenium_automation.pytesseract.pytesseract.tesseract_cmd == "/usr/local/bin/tesseract"

# Test logging configuration
def test_logging_configuration():
    """Test that logging is configured correctly"""
    with patch('logging.FileHandler') as mock_file_handler:
        with patch('logging.StreamHandler') as mock_stream_handler:
            with patch('logging.basicConfig') as mock_basic_config:
                import importlib
                importlib.reload(selenium_automation)
                
                # Check that logging was configured
                mock_basic_config.assert_called_once()
                
                # Check that both handlers were created
                mock_file_handler.assert_called_once_with("igr_automation.log")
                mock_stream_handler.assert_called_once()

# Test directory creation in run_automation
@patch('selenium.webdriver.chrome.service.Service')
@patch('webdriver_manager.chrome.ChromeDriverManager')
@patch('selenium.webdriver.Chrome')
@patch('os.makedirs')
def test_run_automation_directory_creation(mock_makedirs, mock_chrome, mock_driver_manager, mock_service):
    """Test that directories are created in run_automation"""
    # Mock ChromeDriverManager and Service
    mock_driver_manager.return_value.install.return_value = 'C:/webdriver/bin/chromedriver.exe'
    mock_service.return_value = 'mock_service'
    
    # Mock WebDriver
    driver_instance = MagicMock()
    mock_chrome.return_value = driver_instance
    
    # Create a jobs dictionary
    jobs = {
        'test_job': {
            'status': 'pending',
            'directory': '/test/output/dir',
            'progress': 0,
            'files': []
        }
    }
    
    # Simulate an error to prevent full execution
    driver_instance.get.side_effect = Exception("Stop early")
    
    # Run the automation
    run_automation(
        year='2023',
        district='पुणे',
        tahsil='जुन्नर',
        village='अंजनावळे',
        property_no='123',
        job_id='test_job',
        jobs=jobs
    )
    
    # Check that the output directory was created
    mock_makedirs.assert_any_call('/test/output/dir', exist_ok=True)
    
    # Check that the debug directory was created
    mock_makedirs.assert_any_call('/test/output/dir/debug', exist_ok=True)

# Test Chrome options in run_automation
@patch('selenium.webdriver.chrome.service.Service')
@patch('webdriver_manager.chrome.ChromeDriverManager')
@patch('selenium.webdriver.Chrome')
@patch('selenium.webdriver.ChromeOptions')
def test_run_automation_chrome_options(mock_chrome_options, mock_chrome, mock_driver_manager, mock_service):
    """Test that Chrome options are configured correctly"""
    # Mock ChromeDriverManager and Service
    mock_driver_manager.return_value.install.return_value = 'C:/webdriver/bin/chromedriver.exe'
    mock_service.return_value = 'mock_service'
    
    # Mock Chrome options
    options_instance = MagicMock()
    mock_chrome_options.return_value = options_instance
    
    # Mock WebDriver
    driver_instance = MagicMock()
    mock_chrome.return_value = driver_instance
    
    # Simulate an error to prevent full execution
    driver_instance.get.side_effect = Exception("Stop early")
    
    # Create a jobs dictionary
    jobs = {
        'test_job': {
            'status': 'pending',
            'directory': '/test/output/dir',
            'progress': 0,
            'files': []
        }
    }
    
    # Run the automation
    run_automation(
        year='2023',
        district='पुणे',
        tahsil='जुन्नर',
        village='अंजनावळे',
        property_no='123',
        job_id='test_job',
        jobs=jobs
    )
    
    # Check that Chrome options were configured
    options_instance.add_argument.assert_any_call("--disable-popup-blocking")
    options_instance.add_argument.assert_any_call("--window-size=1920,1080")
    
    # Check that Chrome was initialized with options
    mock_chrome.assert_called_once_with(service=mock_service.return_value, options=options_instance)
    
    # Check that page load timeout was set
    driver_instance.set_page_load_timeout.assert_called_once_with(60)

# Test WebDriver cleanup in run_automation
@patch('selenium.webdriver.chrome.service.Service')
@patch('webdriver_manager.chrome.ChromeDriverManager')
@patch('selenium.webdriver.Chrome')
def test_run_automation_webdriver_cleanup(mock_chrome, mock_driver_manager, mock_service):
    """Test that WebDriver is cleaned up properly in run_automation"""
    # Mock ChromeDriverManager and Service
    mock_driver_manager.return_value.install.return_value = 'C:/webdriver/bin/chromedriver.exe'
    mock_service.return_value = 'mock_service'
    
    # Mock WebDriver
    driver_instance = MagicMock()
    mock_chrome.return_value = driver_instance
    
    # Simulate an error during execution
    driver_instance.get.side_effect = Exception("Connection error")
    
    # Create a jobs dictionary
    jobs = {
        'test_job': {
            'status': 'pending',
            'directory': '/test/output/dir',
            'progress': 0,
            'files': []
        }
    }
    
    # Run the automation which should handle the error
    run_automation(
        year='2023',
        district='पुणे',
        tahsil='जुन्नर',
        village='अंजनावळे',
        property_no='123',
        job_id='test_job',
        jobs=jobs
    )
    
    # Check that the driver was quit properly
    driver_instance.quit.assert_called_once()

# Test for Flask app setup
def test_flask_app_setup():
    """Test that Flask app is set up correctly"""
    from selenium_automation import app
    
    # Check that the app is a Flask instance
    assert app.name == 'flask_app'
    
    # Check that CORS is enabled
    assert hasattr(app, 'cors')

# Test Flask API endpoint for starting a search
def test_api_start_search():
    """Test the API endpoint for starting a search"""
    from selenium_automation import app
    
    # Create a test client
    client = app.test_client()
    
    # Mock threading.Thread to avoid actually starting a thread
    with patch('threading.Thread') as mock_thread:
        # Mock uuid.uuid4 to return a predictable value
        with patch('uuid.uuid4', return_value='test-uuid'):
            # Test the endpoint
            response = client.post('/api/search', json={
                'year': '2023',
                'district': 'पुणे',
                'tahsil': 'जुन्नर',
                'village': 'अंजनावळे',
                'property_no': '123'
            })
            
            # Check response
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'job_id' in data
            assert data['job_id'] == 'test-uuid'
            
            # Check that a thread was started
            mock_thread.assert_called_once()
            mock_thread.return_value.start.assert_called_once()

# Test Flask API endpoint for job status
def test_api_job_status():
    """Test the API endpoint for checking job status"""
    from selenium_automation import app, jobs
    
    # Create a test client
    client = app.test_client()
    
    # Add a test job to the jobs dictionary
    jobs['test-job'] = {
        'status': 'running',
        'progress': 50,
        'files': ['file1.pdf', 'file2.pdf'],
        'directory': '/test/output/dir'
    }
    
    # Test the endpoint
    response = client.get('/api/status/test-job')
    
    # Check response
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'running'
    assert data['progress'] == 50
    assert len(data['files']) == 2
    
    # Test with non-existent job
    response = client.get('/api/status/non-existent-job')
    
    # Check response
    assert response.status_code == 404
    data = json.loads(response.data)
    assert 'error' in data

# Test Flask API endpoint for downloading files
def test_api_download_files():
    """Test the API endpoint for downloading files"""
    from selenium_automation import app, jobs
    
    # Create a test client
    client = app.test_client()
    
    # Add a test job to the jobs dictionary with files
    jobs['test-job'] = {
        'status': 'completed',
        'progress': 100,
        'files': ['file1.pdf', 'file2.pdf'],
        'directory': '/test/output/dir'
    }
    
    # Mock zipfile.ZipFile to avoid actually creating a zip
    with patch('zipfile.ZipFile'):
        # Mock send_file to avoid actually sending a file
        with patch('flask.send_file') as mock_send_file:
            # Mock BytesIO to avoid actually creating a buffer
            with patch('io.BytesIO') as mock_bytesio:
                # Mock os.path.exists to simulate files existing
                with patch('os.path.exists', return_value=True):
                    # Test the endpoint
                    response = client.get('/api/download/test-job')
                    
                    # Check that send_file was called
                    mock_send_file.assert_called_once()
                    
                    # Test with non-existent job
                    response = client.get('/api/download/non-existent-job')
                    
                    # Check response
                    assert response.status_code == 404
                    data = json.loads(response.data)
                    assert 'error' in data

# Test error handling in Flask API
def test_api_error_handling():
    """Test error handling in Flask API endpoints"""
    from selenium_automation import app, jobs
    
    # Create a test client
    client = app.test_client()
    
    # Test with invalid JSON
    response = client.post('/api/search', data='invalid json')
    
    # Check response
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'error' in data
    
    # Test with missing required fields
    response = client.post('/api/search', json={
        'year': '2023',
        # Missing district, tahsil, village, property_no
    })
    
    # Check response
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'error' in data
    
    # Add a test job with error status
    jobs['error-job'] = {
        'status': 'error',
        'error_message': 'Test error message',
        'directory': '/test/output/dir'
    }
    
    # Test status endpoint with error job
    response = client.get('/api/status/error-job')
    
    # Check response
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'error'
    assert data['error_message'] == 'Test error message'

# Test integration of run_automation with Flask API
def test_api_run_automation_integration():
    """Test integration of run_automation with Flask API"""
    from selenium_automation import app, jobs
    
    # Create a test client
    client = app.test_client()
    
    # Mock run_automation to avoid actually running it
    with patch('selenium_automation.run_automation') as mock_run_automation:
        # Mock uuid.uuid4 to return a predictable value
        with patch('uuid.uuid4', return_value='test-uuid'):
            # Mock threading.Thread to execute the target function immediately
            with patch('threading.Thread', new=lambda target, args: MagicMock(
                start=lambda: target(*args)
            )):
                # Test the endpoint
                response = client.post('/api/search', json={
                    'year': '2023',
                    'district': 'पुणे',
                    'tahsil': 'जुन्नर',
                    'village': 'अंजनावळे',
                    'property_no': '123'
                })
                
                # Check that run_automation was called with correct arguments
                mock_run_automation.assert_called_once_with(
                    year='2023',
                    district='पुणे',
                    tahsil='जुन्नर',
                    village='अंजनावळे',
                    property_no='123',
                    job_id='test-uuid',
                    jobs=jobs
                )
                
                # Check that job was created
                assert 'test-uuid' in jobs