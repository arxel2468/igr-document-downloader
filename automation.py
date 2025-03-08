import os
import time
import logging
import base64
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
import pdfkit
from captcha_solver import solve_and_submit_captcha
from utils import wait_for_new_tab, configure_pdfkit

logger = logging.getLogger(__name__)

def navigate_to_next_page(driver, current_page, debug_dir):
    """
    Navigate to the next page and return True if successful, False otherwise.
    """
    try:
        # Take screenshot before navigation
        driver.save_screenshot(os.path.join(debug_dir, f"page_{current_page}_before_pagination.png"))
        
        # Find direct link to next page
        next_page_number = current_page + 1
        next_page_xpath = f"//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page${next_page_number}')\")]"
        next_page_links = driver.find_elements(By.XPATH, next_page_xpath)
        
        if next_page_links:
            link = next_page_links[0]
            logger.info(f"Found direct link to page {next_page_number}")
            
            driver.execute_script("arguments[0].scrollIntoView(true);", link)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", link)
            
            # Wait for page to refresh
            time.sleep(3)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
            )
            
            return True
        
        # Try ellipsis link if direct link not found
        ellipsis_links = driver.find_elements(By.XPATH, "//a[text()='...']")
        if ellipsis_links:
            link = ellipsis_links[0]
            logger.info("Found '...' link that might lead to more pages")
            
            driver.execute_script("arguments[0].scrollIntoView(true);", link)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", link)
            
            # Wait for page to refresh
            time.sleep(3)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
            )
            
            return True
        
        # Try any link with a higher page number
        pagination_links = driver.find_elements(By.XPATH, "//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page$\")]")
        for link in pagination_links:
            try:
                link_text = link.text.strip()
                if link_text.isdigit() and int(link_text) > current_page:
                    logger.info(f"Found link to page {link_text}")
                    
                    driver.execute_script("arguments[0].scrollIntoView(true);", link)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", link)
                    
                    # Wait for page to refresh
                    time.sleep(3)
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                    )
                    
                    return True
            except:
                continue
        
        return False
    except Exception as e:
        logger.error(f"Error in navigate_to_next_page: {e}")
        return False


def run_automation(year, district, tahsil, village, property_no, job_id, jobs, driver_pool):
    """Run the automation to download documents with improved error handling and recovery."""
    
    driver = None
    jobs[job_id]["status"] = "running"
    
    # Create directories
    output_dir = jobs[job_id]["directory"]
    os.makedirs(output_dir, exist_ok=True)
    
    debug_dir = os.path.join(output_dir, "debug")
    os.makedirs(debug_dir, exist_ok=True)
    
    # At the beginning of your function, after initializing variables:
    processed_pages = set()  # Track which pages we've already processed

    # Then, inside your main processing loop (the while loop that processes pages):
    while documents_processed < total_documents_found:
        # Check if we've already processed this page
        if current_page in processed_pages:
            logger.warning(f"Already processed page {current_page}, skipping to avoid duplicates")
            
            # Try to navigate to next page directly instead of continuing the loop
            try:
                next_page_found = navigate_to_next_page(driver, current_page, debug_dir)
                if next_page_found:
                    logger.info(f"Successfully navigated away from duplicate page")
                    # Update current_page based on new span
                    new_spans = driver.find_elements(By.XPATH, "//tr/td/span")
                    for span in new_spans:
                        if span.text.strip().isdigit():
                            current_page = int(span.text.strip())
                            logger.info(f"Now on page {current_page}")
                            break
                else:
                    logger.warning(f"Could not navigate away from duplicate page, ending processing")
                    break  # Break out of the main loop
            except Exception as e:
                logger.error(f"Error trying to navigate away from duplicate page: {e}")
                break  # Break out of the main loop
        else:
            # Mark this page as processed
            processed_pages.add(current_page)
            logger.info(f"Processing new page: {current_page}")
            
            # Continue with normal page processing...
            # ...
    
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

        # Get total number of documents
        try:
            index_buttons = driver.find_elements(By.XPATH, "//td/input[@value='IndexII']")
            total_documents = len(index_buttons)
            
            jobs[job_id]["total_documents"] = total_documents
            logger.info(f"Found {total_documents} documents to download")
            
            if total_documents == 0:
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

        # Process documents with proper pagination
        successfully_downloaded = 0
        current_page = 1
        documents_processed = 0
        total_documents_found = 0

        # First, determine total number of documents across all pages
        try:
            # Check if there's a total count displayed on the page
            count_elements = driver.find_elements(By.XPATH, "//span[contains(@id, 'lblTotalRecords')]")
            if count_elements and count_elements[0].text:
                try:
                    total_documents_found = int(count_elements[0].text.strip())
                    logger.info(f"Total documents found according to counter: {total_documents_found}")
                except ValueError:
                    logger.warning(f"Could not parse total records: {count_elements[0].text}")
            
            # Count documents on first page
            index_buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
            documents_per_page = len(index_buttons)
            
            # Check for pagination
            pagination_links = driver.find_elements(By.XPATH, "//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page$\")]")
            total_pages = len(pagination_links) + 1 if pagination_links else 1
            
            # If we couldn't get total from counter, estimate from pagination
            if not total_documents_found and total_pages > 1:
                # Assuming all pages except last have same number of items
                total_documents_found = (total_pages - 1) * documents_per_page + documents_per_page
                logger.info(f"Estimated total documents from pagination: {total_documents_found}")
            elif not total_documents_found:
                total_documents_found = documents_per_page
                logger.info(f"Using documents on first page as total: {total_documents_found}")
            
            jobs[job_id]["total_documents"] = total_documents_found
            logger.info(f"Found {total_documents_found} documents across {total_pages} pages")
            
            if total_documents_found == 0:
                jobs[job_id]["status"] = "completed"
                jobs[job_id]["message"] = "Search completed but no documents found for download"
                return
                
        except Exception as e:
            logger.error(f"Error determining total documents: {str(e)}")
            driver.save_screenshot(os.path.join(debug_dir, "pagination_error.png"))
            # Continue with what we can find on the first page
            index_buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
            total_documents_found = len(index_buttons)
            jobs[job_id]["total_documents"] = total_documents_found
            logger.info(f"Fallback: Found {total_documents_found} documents on current page")

        # Process all documents across all pages
        while documents_processed < total_documents_found:
            logger.info(f"Processing page {current_page}")
            
            # Refresh the page elements to avoid stale references
            try:
                # Wait for page to be fully loaded after any navigation
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                )
                
                # Get fresh references to IndexII buttons
                index_buttons = WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.XPATH, "//input[@value='IndexII']"))
                )
                
                if not index_buttons:
                    logger.warning(f"No IndexII buttons found on page {current_page}")
                    break
            except Exception as e:
                logger.error(f"Error finding IndexII buttons on page {current_page}: {str(e)}")
                driver.save_screenshot(os.path.join(debug_dir, f"page_{current_page}_error.png"))
                break
            
            # Process each document on the current page with retry mechanism
            for i, _ in enumerate(index_buttons):
                document_number = documents_processed + 1
                logger.info(f"Processing document {document_number}/{total_documents_found} (Page {current_page}, Item {i+1})...")
                
                # Retry mechanism for document processing
                max_attempts = 3
                document_processed = False
                
                for attempt in range(max_attempts):
                    try:
                        # Get a fresh reference to the specific button to avoid stale element
                        buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
                        if i >= len(buttons):
                            logger.error(f"Button index {i} out of range (only {len(buttons)} buttons found)")
                            break
                            
                        button = buttons[i]
                        
                        # Store original window handles
                        original_handles = driver.window_handles
                        
                        # Ensure button is in view and clickable
                        driver.execute_script("arguments[0].scrollIntoView(true);", button)
                        time.sleep(1)
                        
                        # Try to click the button using JavaScript for reliability
                        driver.execute_script("arguments[0].click();", button)
                        logger.info(f"Clicked on IndexII button for document {document_number}")
                        
                        # Wait for new tab to open with enhanced timeout and checks
                        wait_start = time.time()
                        max_wait = 15  # seconds
                        new_tab_found = False
                        
                        while time.time() - wait_start < max_wait:
                            current_handles = driver.window_handles
                            if len(current_handles) > len(original_handles):
                                new_tab_found = True
                                break
                            time.sleep(0.5)
                        
                        if not new_tab_found:
                            raise TimeoutException(f"No new tab opened after clicking for document {document_number}")
                        
                        # Find the new tab handle
                        new_tabs = [handle for handle in driver.window_handles if handle not in original_handles]
                        if not new_tabs:
                            raise Exception(f"Could not identify new tab for document {document_number}")
                        
                        # Switch to the new tab
                        driver.switch_to.window(new_tabs[0])
                        
                        # Wait for page to load with enhanced error detection
                        load_start = time.time()
                        page_loaded = False
                        
                        while time.time() - load_start < 20:  # 20 second timeout
                            try:
                                # Check if document has loaded
                                ready_state = driver.execute_script("return document.readyState")
                                if ready_state == "complete":
                                    # Additional check: make sure body element exists and has content
                                    body_content = driver.execute_script("return document.body.innerHTML.length")
                                    if body_content > 100:  # Arbitrary threshold for "has content"
                                        page_loaded = True
                                        break
                                time.sleep(1)
                            except Exception as js_error:
                                logger.warning(f"Error checking page state: {js_error}")
                                time.sleep(1)
                        
                        # Log the URL for debugging
                        try:
                            current_url = driver.current_url
                            logger.info(f"Switched to new tab: {current_url}")
                        except:
                            logger.warning("Could not get URL of new tab")
                        
                        # Force a small delay to ensure page is rendered
                        time.sleep(3)
                        
                        # Print page directly to PDF with simplified approach
                        try:
                            pdf_filename = os.path.join(output_dir, f"Document_{document_number}.pdf")
                            
                            # Use Chrome DevTools Protocol method which is working reliably
                            try:
                                logger.info("Generating PDF with Chrome DevTools Protocol...")
                                # Configure Chrome print settings
                                print_options = {
                                    'landscape': False,
                                    'displayHeaderFooter': False,
                                    'printBackground': True,
                                    'preferCSSPageSize': True,
                                    'scale': 1.0,
                                }
                                
                                # Generate PDF directly from the page
                                pdf_data = driver.execute_cdp_cmd('Page.printToPDF', print_options)
                                
                                # Save the PDF file
                                with open(pdf_filename, 'wb') as f:
                                    f.write(base64.b64decode(pdf_data['data']))
                                
                                logger.info(f"Saved PDF using CDP method: {pdf_filename}")
                                
                                # Mark as successfully downloaded
                                successfully_downloaded += 1
                                jobs[job_id]["downloaded_documents"] = successfully_downloaded
                                
                            except Exception as pdf_error:
                                logger.warning(f"PDF generation failed: {pdf_error}")
                                
                                # Take screenshot as fallback
                                screenshot_path = os.path.join(output_dir, f"Document_{document_number}.png")
                                driver.save_screenshot(screenshot_path)
                                logger.info(f"Saved screenshot as fallback: {screenshot_path}")
                                
                                # Still count it as downloaded since we got a screenshot
                                successfully_downloaded += 1
                                jobs[job_id]["downloaded_documents"] = successfully_downloaded
                            
                        except Exception as save_error:
                            logger.error(f"Failed to save document: {save_error}")
                    
                    finally:
                        # Make sure we close any new tabs and return to the main window
                        try:
                            if len(driver.window_handles) > 1:
                                # Close all tabs except the first one
                                original_handle = driver.window_handles[0]
                                for handle in driver.window_handles:
                                    if handle != original_handle:
                                        driver.switch_to.window(handle)
                                        driver.close()
                                driver.switch_to.window(original_handle)
                        except Exception as tab_error:
                            logger.error(f"Error closing tabs: {tab_error}")
                            
                            # Emergency recovery - try to get back to the main window
                            try:
                                for handle in driver.window_handles:
                                    driver.switch_to.window(handle)
                                    current_url = driver.current_url
                                    if "RegistrationGrid" in current_url:
                                        logger.info(f"Found main results page: {current_url}")
                                        break
                            except:
                                # Last resort - restart the browser
                                logger.error("Could not recover browser state, will attempt to restart")
                                try:
                                    driver.quit()
                                    driver = driver_pool.get_driver(force_new=True)
                                    # Would need to re-navigate to search results
                                    # This would be complex and might require restarting the job
                                    break
                                except:
                                    logger.critical("Failed to restart browser, job cannot continue")
                                    raise
                
                # Increment document counter even if processing failed
                documents_processed += 1
            
            # Check if we need to navigate to the next page
            if documents_processed < total_documents_found:
                try:
                    # Take a screenshot of the current page for debugging
                    driver.save_screenshot(os.path.join(debug_dir, f"page_{current_page}_before_pagination.png"))
                    
                    # Find the current page span to identify which page we're on
                    current_page_spans = driver.find_elements(By.XPATH, "//tr/td/span")
                    current_page_identified = False
                    
                    for span in current_page_spans:
                        try:
                            if span.text.strip().isdigit():
                                identified_page = int(span.text.strip())
                                logger.info(f"Found current page indicator: page {identified_page}")
                                current_page = identified_page
                                current_page_identified = True
                                break
                        except:
                            continue
                    
                    if not current_page_identified:
                        logger.warning(f"Could not identify current page from spans, assuming we're still on page {current_page}")
                    
                    # Keep track of which documents we've already processed to avoid duplicates
                    processed_document_ids = set()
                    
                    # Get the document IDs on the current page to avoid duplicates
                    try:
                        # Try to find some unique identifier for each document
                        doc_elements = driver.find_elements(By.XPATH, "//tr[.//input[@value='IndexII']]")
                        for doc_element in doc_elements:
                            try:
                                # Try to extract some unique ID from the document row
                                doc_text = doc_element.text
                                # Create a hash of the text as a simple unique ID
                                doc_id = hash(doc_text)
                                processed_document_ids.add(doc_id)
                            except:
                                pass
                        
                        logger.info(f"Tracking {len(processed_document_ids)} document IDs to avoid duplicates")
                    except Exception as id_error:
                        logger.warning(f"Could not extract document IDs: {id_error}")
                    
                    # Find all pagination links
                    pagination_links = driver.find_elements(By.XPATH, "//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page$\")]")
                    
                    # Log all pagination links for debugging
                    logger.info(f"Found {len(pagination_links)} pagination links")
                    
                    # Direct approach: Try to click the next page number
                    next_page_number = current_page + 1
                    next_page_found = False
                    
                    # Look for direct link to next page
                    next_page_xpath = f"//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page${next_page_number}')\")]"
                    next_page_links = driver.find_elements(By.XPATH, next_page_xpath)
                    
                    if next_page_links:
                        link = next_page_links[0]
                        logger.info(f"Found direct link to page {next_page_number}")
                        
                        # Take screenshot before clicking
                        driver.save_screenshot(os.path.join(debug_dir, f"before_click_page_{next_page_number}.png"))
                        
                        # Click the link with retry
                        for click_attempt in range(3):
                            try:
                                driver.execute_script("arguments[0].scrollIntoView(true);", link)
                                time.sleep(1)
                                driver.execute_script("arguments[0].click();", link)
                                
                                # Wait for page to refresh
                                time.sleep(3)
                                WebDriverWait(driver, 15).until(
                                    EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                                )
                                
                                # Take screenshot after clicking
                                driver.save_screenshot(os.path.join(debug_dir, f"after_click_page_{next_page_number}.png"))
                                
                                # Verify we actually changed pages by checking if current page span changed
                                new_current_page = None
                                new_spans = driver.find_elements(By.XPATH, "//tr/td/span")
                                for span in new_spans:
                                    if span.text.strip().isdigit():
                                        new_current_page = int(span.text.strip())
                                        break
                                
                                if new_current_page and new_current_page != current_page:
                                    current_page = new_current_page
                                    logger.info(f"Successfully navigated to page {current_page}")
                                    next_page_found = True
                                    
                                    # Verify we have new documents
                                    new_doc_elements = driver.find_elements(By.XPATH, "//tr[.//input[@value='IndexII']]")
                                    new_doc_ids = set()
                                    
                                    for doc_element in new_doc_elements:
                                        try:
                                            doc_text = doc_element.text
                                            doc_id = hash(doc_text)
                                            new_doc_ids.add(doc_id)
                                        except:
                                            pass
                                    
                                    # Check if we have any new document IDs
                                    if not processed_document_ids.intersection(new_doc_ids):
                                        logger.info(f"Verified new page has different documents")
                                    else:
                                        logger.warning(f"Some documents on new page match previously processed documents")
                                        
                                    break
                                else:
                                    logger.warning(f"Page may not have changed after click, retrying...")
                                    if click_attempt < 2:
                                        time.sleep(2)
                            except Exception as click_error:
                                logger.warning(f"Error clicking page link (attempt {click_attempt+1}): {click_error}")
                                if click_attempt < 2:
                                    time.sleep(2)
                    
                    # If direct next page link didn't work, try ellipsis link
                    if not next_page_found:
                        ellipsis_links = driver.find_elements(By.XPATH, "//a[text()='...']")
                        
                        if ellipsis_links:
                            link = ellipsis_links[0]
                            logger.info("Found '...' link that might lead to more pages")
                            
                            # Take screenshot before clicking
                            driver.save_screenshot(os.path.join(debug_dir, "before_click_ellipsis.png"))
                            
                            # Click with retry
                            for click_attempt in range(3):
                                try:
                                    driver.execute_script("arguments[0].scrollIntoView(true);", link)
                                    time.sleep(1)
                                    driver.execute_script("arguments[0].click();", link)
                                    
                                    # Wait for page to refresh
                                    time.sleep(3)
                                    WebDriverWait(driver, 15).until(
                                        EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                                    )
                                    
                                    # Take screenshot after clicking
                                    driver.save_screenshot(os.path.join(debug_dir, "after_click_ellipsis.png"))
                                    
                                    # Verify we actually changed pages
                                    new_current_page = None
                                    new_spans = driver.find_elements(By.XPATH, "//tr/td/span")
                                    for span in new_spans:
                                        if span.text.strip().isdigit():
                                            new_current_page = int(span.text.strip())
                                            break
                                    
                                    if new_current_page and new_current_page != current_page:
                                        current_page = new_current_page
                                        logger.info(f"Successfully navigated to page {current_page}")
                                        next_page_found = True
                                        
                                        # Verify we have new documents
                                        new_doc_elements = driver.find_elements(By.XPATH, "//tr[.//input[@value='IndexII']]")
                                        new_doc_ids = set()
                                        
                                        for doc_element in new_doc_elements:
                                            try:
                                                doc_text = doc_element.text
                                                doc_id = hash(doc_text)
                                                new_doc_ids.add(doc_id)
                                            except:
                                                pass
                                        
                                        # Check if we have any new document IDs
                                        if not processed_document_ids.intersection(new_doc_ids):
                                            logger.info(f"Verified new page has different documents")
                                        else:
                                            logger.warning(f"Some documents on new page match previously processed documents")
                                            
                                        break
                                    else:
                                        logger.warning(f"Page may not have changed after ellipsis click, retrying...")
                                        if click_attempt < 2:
                                            time.sleep(2)
                                except Exception as click_error:
                                    logger.warning(f"Error clicking ellipsis link (attempt {click_attempt+1}): {click_error}")
                                    if click_attempt < 2:
                                        time.sleep(2)
                    
                    # If we still haven't found the next page, try any number higher than current page
                    if not next_page_found:
                        for link in pagination_links:
                            try:
                                link_text = link.text.strip()
                                if link_text.isdigit() and int(link_text) > current_page:
                                    logger.info(f"Found link to page {link_text}")
                                    
                                    # Take screenshot before clicking
                                    driver.save_screenshot(os.path.join(debug_dir, f"before_click_any_page_{link_text}.png"))
                                    
                                    # Click with retry
                                    for click_attempt in range(3):
                                        try:
                                            driver.execute_script("arguments[0].scrollIntoView(true);", link)
                                            time.sleep(1)
                                            driver.execute_script("arguments[0].click();", link)
                                            
                                            # Wait for page to refresh
                                            time.sleep(3)
                                            WebDriverWait(driver, 15).until(
                                                EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                                            )
                                            
                                            # Take screenshot after clicking
                                            driver.save_screenshot(os.path.join(debug_dir, f"after_click_any_page_{link_text}.png"))
                                            
                                            # Verify we actually changed pages
                                            new_current_page = None
                                            new_spans = driver.find_elements(By.XPATH, "//tr/td/span")
                                            for span in new_spans:
                                                if span.text.strip().isdigit():
                                                    new_current_page = int(span.text.strip())
                                                    break
                                            
                                            if new_current_page and new_current_page != current_page:
                                                current_page = new_current_page
                                                logger.info(f"Successfully navigated to page {current_page}")
                                                next_page_found = True
                                                break
                                            else:
                                                logger.warning(f"Page may not have changed after click, retrying...")
                                                if click_attempt < 2:
                                                    time.sleep(2)
                                        except Exception as click_error:
                                            logger.warning(f"Error clicking page link (attempt {click_attempt+1}): {click_error}")
                                            if click_attempt < 2:
                                                time.sleep(2)
                                    
                                    if next_page_found:
                                        break
                            except:
                                continue
                    
                    if not next_page_found:
                        logger.warning("Could not find any way to navigate to the next page")
                        
                        # Save the pagination row HTML for debugging
                        try:
                            pagination_rows = driver.find_elements(By.XPATH, "//tr[.//span or .//a[contains(@href, 'RegistrationGrid')]]")
                            for i, row in enumerate(pagination_rows):
                                logger.info(f"Pagination row {i} HTML: {row.get_attribute('outerHTML')}")
                        except:
                            pass
                        
                        # Save page source for debugging
                        with open(os.path.join(debug_dir, f"page_{current_page}_source.html"), "w", encoding="utf-8") as f:
                            f.write(driver.page_source)
                        
                        break
                        
                except Exception as nav_error:
                    logger.warning(f"Error during pagination navigation: {nav_error}")
                    driver.save_screenshot(os.path.join(debug_dir, f"pagination_error_page_{current_page}.png"))
                    break

        # After downloading documents, update the job status
        if successfully_downloaded > total_documents_found:
            logger.warning(f"Downloaded more documents ({successfully_downloaded}) than initially estimated ({total_documents_found})")
            total_documents_found = successfully_downloaded
            jobs[job_id]["total_documents"] = total_documents_found

        # Update job status
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["message"] = f"Job completed successfully. Downloaded {successfully_downloaded}/{total_documents_found} documents."
        logger.info(f"Job completed successfully. Downloaded {successfully_downloaded}/{total_documents_found} documents.")
        logger.info(f"Job completed successfully. Downloaded {successfully_downloaded}/{total_documents_found} documents.")
        
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
        # Clean up resources regardless of success or failure
        if driver:
            try:
                # Make sure all extra tabs are closed
                if len(driver.window_handles) > 1:
                    # Keep only the first tab
                    original_handle = driver.window_handles[0]
                    for handle in driver.window_handles:
                        if handle != original_handle:
                            driver.switch_to.window(handle)
                            driver.close()
                    driver.switch_to.window(original_handle)
                
                # Return to a clean state
                driver.get("about:blank")
                
                # Return driver to the pool
                driver_pool.return_driver(driver)
                logger.info("Browser returned to pool")
                os.rmdir("__pycache__")
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {str(cleanup_error)}")
                # Try to quit the driver if returning to pool fails
                try:
                    driver.quit()
                    logger.info("Browser quit after failed return to pool")
                except:
                    logger.error("Failed to quit browser")