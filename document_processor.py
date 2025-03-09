import os
import time
import logging
import hashlib
import base64
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, 
    StaleElementReferenceException, 
    WebDriverException,
    NoSuchElementException,
    ElementClickInterceptedException,
    JavascriptException
)

logger = logging.getLogger(__name__)

def process_index_button(driver, button, document_number, output_dir, debug_dir):
    """Simplified and more reliable approach to process IndexII buttons"""
    original_handles = driver.window_handles
    original_url = driver.current_url
    
    try:
        # Extract onclick attribute for direct JavaScript execution
        onclick = button.get_attribute("onclick")
        match = re.search(r"__doPostBack\('([^']+)',\s*'([^']+)'\)", onclick)
        
        if match:
            target, argument = match.groups()
            logger.info(f"Clicking IndexII button for doc {document_number} using __doPostBack")
            
            # Execute JavaScript directly - most reliable for ASP.NET
            driver.execute_script(f"__doPostBack('{target}', '{argument}')")
            
            # Wait briefly for any new tab or page change
            time.sleep(3)
            
            # Check if new tab opened
            new_handles = driver.window_handles
            if len(new_handles) > len(original_handles):
                # Switch to new tab
                new_handle = [h for h in new_handles if h not in original_handles][0]
                driver.switch_to.window(new_handle)
                
                # Wait for document to load
                try:
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                    time.sleep(2)  # Additional wait for stability
                    
                    # Save document as PDF
                    pdf_path = os.path.join(output_dir, f"Document-{document_number}.pdf")
                    
                    try:
                        # Use printToPDF command for better PDF generation
                        pdf_options = {
                            'printBackground': True,
                            'paperWidth': 8.27,
                            'paperHeight': 11.69,
                            'marginTop': 0.4,
                            'marginBottom': 0.4,
                            'scale': 1.0
                        }
                        pdf_data = driver.execute_cdp_cmd('Page.printToPDF', pdf_options)
                        
                        with open(pdf_path, 'wb') as pdf_file:
                            pdf_file.write(base64.b64decode(pdf_data['data']))
                        
                        logger.info(f"Document {document_number} saved as PDF")
                        
                    except Exception as pdf_error:
                        logger.warning(f"PDF generation failed: {str(pdf_error)}")
                        # Fallback to screenshot
                        driver.save_screenshot(os.path.join(output_dir, f"Document-{document_number}.png"))
                        
                except Exception as e:
                    logger.error(f"Error loading document: {str(e)}")
                    
                # Close tab and return to original
                driver.close()
                driver.switch_to.window(original_handles[0])
                return True
                
            # Check if page changed without opening a new tab
            elif driver.current_url != original_url or "IndexII" not in driver.page_source:
                logger.info(f"Page changed for document {document_number} (no new tab)")
                
                # Save current page as document
                pdf_path = os.path.join(output_dir, f"Document-{document_number}.pdf")
                
                try:
                    # Use printToPDF command
                    pdf_options = {
                        'printBackground': True,
                        'paperWidth': 8.27,
                        'paperHeight': 11.69,
                        'marginTop': 0.4,
                        'marginBottom': 0.4,
                        'scale': 1.0
                    }
                    pdf_data = driver.execute_cdp_cmd('Page.printToPDF', pdf_options)
                    
                    with open(pdf_path, 'wb') as pdf_file:
                        pdf_file.write(base64.b64decode(pdf_data['data']))
                    
                    logger.info(f"Document {document_number} saved as PDF")
                    
                except Exception as pdf_error:
                    logger.warning(f"PDF generation failed: {str(pdf_error)}")
                    # Fallback to screenshot
                    driver.save_screenshot(os.path.join(output_dir, f"Document-{document_number}.png"))
                
                # Navigate back
                driver.back()
                time.sleep(3)
                
                # Verify we're back on results page
                if "IndexII" not in driver.page_source:
                    logger.warning("Back navigation didn't return to results, refreshing")
                    driver.refresh()
                    time.sleep(3)
                
                return True
            
            else:
                logger.warning(f"Click had no effect for document {document_number}")
                return False
        
        else:
            # Fallback to regular click if no __doPostBack
            logger.warning("No __doPostBack found in onclick, using regular click")
            button.click()
            time.sleep(3)
            
            # Similar checks as above for new tab or page change
            # (Code omitted for brevity)
            
    except Exception as e:
        logger.error(f"Error processing document {document_number}: {str(e)}")
        return False

def process_all_index_buttons(driver, output_dir, debug_dir, job_id=None, jobs=None):
    """
    Process all IndexII buttons across all pages with robust pagination handling.
    
    Args:
        driver: WebDriver instance
        output_dir: Directory to save processed document data
        debug_dir: Directory for debug screenshots and logs
        job_id: Optional job ID for tracking in jobs dictionary
        jobs: Optional jobs dictionary for status updates
    
    Returns:
        dict: Processing summary
    """
    # Ensure directories exist
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(debug_dir, exist_ok=True)
    
    # Initialize tracking variables
    processed_document_hashes = set()
    processed_button_identifiers = set()  # Track by indexII$N identifier
    documents_processed = 0
    documents_downloaded = 0
    current_page = get_current_page_number(driver) or 1
    processed_pages = set()
    max_iterations = 200  # Increased safety limit
    page_retry_limit = 3  # Max retries per page
    last_page_source_hash = None  # To detect page content changes
    
    # Create log file for this run
    log_path = os.path.join(debug_dir, f"processing_log_{time.strftime('%Y%m%d_%H%M%S')}.txt")
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"Starting document processing at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Save initial page source for debugging
    with open(os.path.join(debug_dir, "initial_page_source.html"), "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    
    # Take screenshot of initial page
    driver.save_screenshot(os.path.join(debug_dir, "initial_page.png"))
    
    # Main processing loop
    iteration = 0
    while iteration < max_iterations:
        logger.info(f"Processing iteration {iteration+1}, page {current_page}")
        
        # Check if page has been processed too many times (possible loop)
        page_process_count = sum(1 for p in processed_pages if p == current_page)
        if page_process_count >= page_retry_limit:
            logger.warning(f"Page {current_page} has been processed {page_process_count} times. Moving to next page to avoid loop.")
            if not navigate_to_next_page(driver, current_page, debug_dir):
                logger.warning("Failed to navigate to next page. Exiting loop.")
                break
            current_page = get_current_page_number(driver) or (current_page + 1)
            continue
        
        # Take screenshot for debugging
        driver.save_screenshot(os.path.join(debug_dir, f"page_{current_page}_iteration_{iteration+1}.png"))
        
        # Check if page content has changed (detect stuck state)
        current_page_source = driver.page_source
        current_page_hash = hashlib.md5(current_page_source.encode()).hexdigest()
        
        if current_page_hash == last_page_source_hash and iteration > 0:
            logger.warning("Page content hasn't changed. Possible stuck state detected.")
            
            # Try to refresh the page and check for IndexII buttons
            driver.refresh()
            time.sleep(3)
            
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                )
            except TimeoutException:
                logger.warning("No IndexII buttons found after refresh. Trying to navigate to next page.")
                if not navigate_to_next_page(driver, current_page, debug_dir):
                    logger.warning("Failed to navigate after refresh. Exiting loop.")
                    break
                current_page = get_current_page_number(driver) or (current_page + 1)
                iteration += 1
                continue
        
        last_page_source_hash = current_page_hash
        
        # Verify we're on the results page
        if not verify_results_page(driver):
            logger.warning(f"Not on results page at iteration {iteration+1}. Attempting to recover.")
            
            # Try to go back or refresh
            try:
                driver.back()
                time.sleep(2)
                if not verify_results_page(driver):
                    logger.warning("Still not on results page after back. Refreshing.")
                    driver.refresh()
                    time.sleep(3)
                    
                    # Wait for IndexII buttons to appear
                    try:
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                        )
                    except TimeoutException:
                        logger.error("Could not recover to results page. Exiting loop.")
                        break
            except Exception as e:
                logger.error(f"Error attempting to recover to results page: {str(e)}")
                break
        
        # Process all documents on current page
        page_results = process_page_documents(
            driver, current_page, output_dir, debug_dir, 
            processed_document_hashes, processed_button_identifiers,
            documents_processed
        )
        
        # Mark page as processed
        processed_pages.add(current_page)
        documents_processed += page_results['processed']
        documents_downloaded += page_results['downloaded']
        
        logger.info(f"Completed processing page {current_page}: {page_results['processed']} processed, {page_results['downloaded']} downloaded")
        
        # Update job status if tracking enabled
        if job_id and jobs:
            jobs[job_id]["processed_documents"] = documents_processed
            jobs[job_id]["downloaded_documents"] = documents_downloaded
        
        # Log progress
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"Page {current_page}: Processed {page_results['processed']}, Downloaded {page_results['downloaded']}\n")
        
        # Save page source for debugging
        with open(os.path.join(debug_dir, f"page_{current_page}_source.html"), "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        
        # Take screenshot after processing
        driver.save_screenshot(os.path.join(debug_dir, f"page_{current_page}_after_processing.png"))
        
        # Try to navigate to next page with adaptive delay
        navigation_success = navigate_to_next_page(driver, current_page, debug_dir)
        
        if navigation_success:
            # Get the new page number
            new_page = get_current_page_number(driver)
            if new_page is not None and new_page != current_page:
                logger.info(f"Successfully navigated to page {new_page}")
                current_page = new_page
            else:
                logger.warning(f"Navigation seemed successful but page number didn't change from {current_page}")
                # Try to infer page number from URL or other elements
                current_page += 1  # Assume we moved to next page if navigation was successful
        else:
            logger.info("Failed to navigate to next page. Assuming all pages processed.")
            break
        
        iteration += 1
        
        # Add adaptive delay between pages to avoid getting stuck
        adaptive_delay = min(3 + (page_results['processed'] * 0.2), 7)  # 3-7 seconds based on page complexity
        logger.info(f"Waiting {adaptive_delay:.1f} seconds before processing next page")
        time.sleep(adaptive_delay)
    
    # Final summary
    summary = {
        "pages_processed": len(processed_pages),
        "documents_processed": documents_processed,
        "documents_downloaded": documents_downloaded,
        "processed_pages": sorted(list(processed_pages))
    }
    
    logger.info(f"Processing complete. Summary: {summary}")
    
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\nProcessing complete at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"Pages processed: {summary['pages_processed']}\n")
        log_file.write(f"Documents processed: {documents_processed}\n")
        log_file.write(f"Documents downloaded: {documents_downloaded}\n")
    
    return summary

def navigate_to_next_page(driver, current_page, debug_dir):
    """More reliable pagination handling"""
    next_page = current_page + 1
    
    try:
        # Take screenshot before navigation
        driver.save_screenshot(os.path.join(debug_dir, f"before_navigate_page_{next_page}.png"))
        
        # First check if there's a direct link to the next page
        next_links = driver.find_elements(
            By.XPATH, 
            f"//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page$\") and text()='{next_page}']"
        )
        
        if next_links:
            # Extract the __doPostBack parameters
            href = next_links[0].get_attribute("href")
            match = re.search(r"javascript:__doPostBack\('([^']+)',\s*'([^']+)'\)", href)
            
            if match:
                target, argument = match.groups()
                logger.info(f"Navigating to page {next_page} using __doPostBack")
                
                # Scroll to pagination area
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                # Execute JavaScript directly
                driver.execute_script(f"__doPostBack('{target}', '{argument}')")
                
                # Wait for page to load
                time.sleep(3)
                
                # Verify page changed by checking for IndexII buttons
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                    )
                    
                    # Take screenshot after navigation
                    driver.save_screenshot(os.path.join(debug_dir, f"after_navigate_page_{next_page}.png"))
                    
                    # Verify page number changed
                    new_page = get_current_page_number(driver)
                    if new_page is not None and new_page != current_page:
                        logger.info(f"Successfully navigated to page {new_page}")
                        return True
                    else:
                        logger.warning(f"Page number didn't change after navigation (still {current_page})")
                        # Continue anyway as the content might have changed
                        return True
                        
                except TimeoutException:
                    logger.warning("No IndexII buttons found after navigation")
                    return False
        
        # If no direct link to next page, try ellipsis (...) links
        ellipsis_links = driver.find_elements(
            By.XPATH, 
            "//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page$\") and text()='...']"
        )
        
        if ellipsis_links:
            # Usually the last ellipsis link points forward
            ellipsis = ellipsis_links[-1]
            href = ellipsis.get_attribute("href")
            
            # Extract the page number from the ellipsis link
            match = re.search(r"Page\$(\d+)", href)
            if match:
                page_num = match.group(1)
                logger.info(f"Using ellipsis to navigate to page set {page_num}")
                
                # Execute JavaScript directly
                driver.execute_script(f"__doPostBack('RegistrationGrid','Page${page_num}')")
                
                # Wait for page to load
                time.sleep(3)
                
                # Verify page changed
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                    )
                    
                    # Take screenshot after navigation
                    driver.save_screenshot(os.path.join(debug_dir, f"after_ellipsis_navigate.png"))
                    
                    # Check if page number changed
                    new_page = get_current_page_number(driver)
                    if new_page is not None and new_page != current_page:
                        logger.info(f"Successfully navigated to page {new_page} via ellipsis")
                        return True
                    else:
                        logger.warning("Page number didn't change after ellipsis navigation")
                        # Continue anyway as the content might have changed
                        return True
                        
                except TimeoutException:
                    logger.warning("No IndexII buttons found after ellipsis navigation")
                    return False
        
        # If we get here, there are no more pages
        logger.info(f"No navigation options found for page {next_page} - likely at last page")
        return False
        
    except Exception as e:
        logger.error(f"Error navigating to next page: {str(e)}")
        driver.save_screenshot(os.path.join(debug_dir, f"navigation_error_page_{current_page}.png"))
        return False

def click_page_link_safely(driver, link, target_page, debug_dir):
    """
    Safely click a page navigation link with multiple fallback strategies.
    
    Args:
        driver: WebDriver instance
        link: The link element to click
        target_page: Target page number or None for ellipsis
        debug_dir: Directory for debug screenshots
    
    Returns:
        bool: True if navigation was successful, False otherwise
    """
    page_desc = str(target_page) if target_page else "ellipsis"
    
    # Strategy 1: Extract href and use JavaScript directly
    try:
        href = link.get_attribute("href")
        if href and "javascript:__doPostBack" in href:
            # Extract the page parameter
            match = re.search(r"Page\$(\d+)", href)
            if match:
                page_num = match.group(1)
                logger.info(f"Using direct JavaScript for page {page_num}")
                
                # Take screenshot before action
                driver.save_screenshot(os.path.join(debug_dir, f"before_js_navigation_{page_desc}.png"))
                
                # Scroll to make navigation controls visible
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                # Use direct JavaScript call
                driver.execute_script(f"__doPostBack('RegistrationGrid','Page${page_num}')")
                
                # Wait for page to load
                wait_result = wait_for_page_load(driver, 20)
                
                # Verify navigation
                return verify_navigation_success(driver, debug_dir)
    except Exception as e:
        logger.warning(f"JavaScript navigation failed: {str(e)}")
    
    # Strategy 2: Use JavaScript click
    try:
        logger.info(f"Using JavaScript click for {page_desc}")
        
        # Take screenshot before action
        driver.save_screenshot(os.path.join(debug_dir, f"before_js_click_{page_desc}.png"))
        
        # Scroll link into view
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link)
        time.sleep(1)
        
        # JavaScript click
        driver.execute_script("arguments[0].click();", link)
        
        # Wait for page to load
        wait_result = wait_for_page_load(driver, 20)
        
        # Verify navigation
        return verify_navigation_success(driver, debug_dir)
    except Exception as e:
        logger.warning(f"JavaScript click failed: {str(e)}")
    
    # Strategy 3: Direct click
    try:
        logger.info(f"Using direct click for {page_desc}")
        
        # Take screenshot before action
        driver.save_screenshot(os.path.join(debug_dir, f"before_direct_click_{page_desc}.png"))
        
        # Scroll link into view
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link)
        time.sleep(1)
        
        # Direct click
        link.click()
        
        # Wait for page to load
        wait_result = wait_for_page_load(driver, 20)
        
        # Verify navigation
        return verify_navigation_success(driver, debug_dir)
    except Exception as e:
        logger.warning(f"Direct click failed: {str(e)}")
    
    # Strategy 4: ActionChains
    try:
        logger.info(f"Using ActionChains for {page_desc}")
        
        # Take screenshot before action
        driver.save_screenshot(os.path.join(debug_dir, f"before_action_chains_{page_desc}.png"))
        
        # Scroll link into view
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link)
        time.sleep(1)
        
        # ActionChains click
        ActionChains(driver).move_to_element(link).click().perform()
        
        # Wait for page to load
        wait_result = wait_for_page_load(driver, 20)
        
        # Verify navigation
        return verify_navigation_success(driver, debug_dir)
    except Exception as e:
        logger.warning(f"ActionChains click failed: {str(e)}")
    
    logger.warning(f"All click strategies failed for {page_desc}")
    return False

def verify_results_page(driver):
    """
    Verify that the current page is a results page with IndexII buttons.
    
    Args:
        driver: WebDriver instance
    
    Returns:
        bool: True if on results page, False otherwise
    """
    try:
        # Check for the presence of IndexII buttons
        index_buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
        
        # Check for the registration grid which contains the results
        grid = driver.find_elements(By.ID, "RegistrationGrid")
        
        # Consider it a results page if it has at least one IndexII button and the grid
        is_results_page = len(index_buttons) > 0 and len(grid) > 0
        
        if is_results_page:
            logger.info(f"Verified current page is a results page with {len(index_buttons)} IndexII buttons")
        else:
            logger.warning(
                f"Current page doesn't appear to be a results page. "
                f"IndexII buttons: {len(index_buttons)}, Grid: {len(grid)}"
            )
            
            # Take a screenshot for debugging
            try:
                debug_dir = os.path.dirname(driver.get_screenshot_as_file("temp.png"))
                if debug_dir:
                    driver.save_screenshot(os.path.join(debug_dir, "not_results_page.png"))
                    os.remove(os.path.join(debug_dir, "temp.png"))
            except:
                pass
        
        return is_results_page
    
    except Exception as e:
        logger.error(f"Error verifying results page: {str(e)}")
        return False

def wait_for_page_load(driver, timeout=20):
    """
    Wait for page to load after navigation.
    
    Args:
        driver: WebDriver instance
        timeout: Maximum wait time in seconds
    
    Returns:
        bool: True if page loaded successfully, False otherwise
    """
    try:
        # Wait for document to be ready
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        
        # Wait for IndexII buttons to appear
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
        )
        
        # Add a small delay to ensure page is fully loaded
        time.sleep(2)
        
        return True
    except Exception as e:
        logger.warning(f"Wait for page load failed: {str(e)}")
        return False

def verify_navigation_success(driver, debug_dir):
    """
    Verify that navigation was successful by checking for IndexII buttons
    and taking a screenshot.
    
    Args:
        driver: WebDriver instance
        debug_dir: Directory for debug screenshots
    
    Returns:
        bool: True if navigation was successful, False otherwise
    """
    try:
        # Take screenshot after navigation
        driver.save_screenshot(os.path.join(debug_dir, "after_navigation.png"))
        
        # Check for IndexII buttons
        buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
        if len(buttons) > 0:
            logger.info(f"Navigation successful, found {len(buttons)} IndexII buttons")
            return True
        else:
            logger.warning("Navigation may have failed, no IndexII buttons found")
            
            # Try refreshing once before declaring failure
            driver.refresh()
            time.sleep(3)
            
            # Check again after refresh
            buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
            if len(buttons) > 0:
                logger.info(f"Navigation successful after refresh, found {len(buttons)} IndexII buttons")
                return True
            else:
                logger.warning("Navigation failed, no IndexII buttons found after refresh")
                return False
    except Exception as e:
        logger.warning(f"Error verifying navigation: {str(e)}")
        return False

def process_page_documents(driver, page_number, output_dir, debug_dir, processed_document_hashes, 
                           processed_button_identifiers, documents_processed_so_far):
    """
    Process all IndexII buttons on the current page.
    
    Args:
        driver: WebDriver instance
        page_number: Current page number
        output_dir: Directory to save processed document data
        debug_dir: Directory for debug screenshots and logs
        processed_document_hashes: Set of already processed document hashes
        processed_button_identifiers: Set of already processed button identifiers
        documents_processed_so_far: Count of documents processed before this page
    
    Returns:
        dict: Results of processing this page
    """
    page_dir = os.path.join(debug_dir, f"page_{page_number}")
    os.makedirs(page_dir, exist_ok=True)
    
    page_processed = 0
    page_downloaded = 0
    
    try:
        # Wait for page to load properly
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
            )
        except TimeoutException:
            logger.warning(f"No IndexII buttons found on page {page_number}")
            driver.save_screenshot(os.path.join(page_dir, "no_index_buttons.png"))
            return {"processed": 0, "downloaded": 0}
        
        # Get all IndexII buttons
        buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
        
        # Create button identifiers that include the page number to ensure uniqueness across pages
        buttons_with_ids = []
        for i, button in enumerate(buttons):
            try:
                # Extract the button index from onclick attribute
                onclick = button.get_attribute("onclick")
                if onclick:
                    match = re.search(r"indexII\$(\d+)", onclick)
                    if match:
                        # Create a page-specific button ID
                        button_id = f"page_{page_number}_indexII_{match.group(1)}"
                        buttons_with_ids.append((button, button_id))
                    else:
                        # Fallback to position-based ID with page number
                        buttons_with_ids.append((button, f"page_{page_number}_position_{i}"))
                else:
                    # Fallback to position-based ID with page number
                    buttons_with_ids.append((button, f"page_{page_number}_position_{i}"))
            except Exception as e:
                logger.warning(f"Error extracting button ID: {str(e)}")
                # Fallback to position-based ID with page number
                buttons_with_ids.append((button, f"page_{page_number}_position_{i}"))
        
        logger.info(f"Found {len(buttons_with_ids)} IndexII buttons on page {page_number}")
        
        # Process each button one at a time
        for i, (button, button_id) in enumerate(buttons_with_ids):
            try:
                # Skip if already processed by ID
                if button_id in processed_button_identifiers:
                    logger.info(f"Skipping document with ID {button_id} on page {page_number} - already processed")
                    continue
                
                # Calculate document number for file naming - unique number for each document
                document_number = documents_processed_so_far + page_processed + 1
                logger.info(f"Processing document {document_number} (Page {page_number}, ID {button_id})")
                
                # Process this document with multiple retries
                success = False
                for retry in range(3):  # Try up to 3 times
                    try:
                        # Process this document
                        result = process_single_document(driver, button, document_number, output_dir, page_dir)
                        if result:
                            success = True
                            break
                        else:
                            logger.warning(f"Failed to process document {document_number} (attempt {retry+1})")
                            
                            # If failed, check if we're still on results page
                            if not verify_results_page(driver):
                                logger.warning("Not on results page after failed attempt. Navigating back.")
                                driver.back()
                                time.sleep(2)
                                
                                if not verify_results_page(driver):
                                    logger.warning("Still not on results page. Refreshing.")
                                    driver.refresh()
                                    time.sleep(3)
                                
                                # Wait for page to load
                                wait_for_page_load(driver, 15)
                            
                            # Re-find the buttons after refresh
                            buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
                            
                            # Try to find the button with similar position
                            if i < len(buttons):
                                button = buttons[i]
                            else:
                                logger.warning(f"Button index {i} out of range after refresh")
                                break
                    except StaleElementReferenceException:
                        logger.warning(f"Stale element on retry {retry+1}")
                        if retry < 2:  # Don't refresh on last attempt
                            driver.refresh()
                            time.sleep(3)
                            wait_for_page_load(driver, 15)
                            
                            # Re-find the buttons after refresh
                            buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
                            if i < len(buttons):
                                button = buttons[i]
                            else:
                                logger.warning(f"Button index {i} out of range after refresh")
                                break
                    except Exception as e:
                        logger.error(f"Error on retry {retry+1}: {str(e)}")
                        if retry < 2:  # Don't refresh on last attempt
                            driver.refresh()
                            time.sleep(3)
                            wait_for_page_load(driver, 15)
                
                # Mark as processed regardless of success
                processed_button_identifiers.add(button_id)
                page_processed += 1
                
                if success:
                    page_downloaded += 1
                
                # Make sure we're back on the results page
                if not verify_results_page(driver):
                    logger.warning("Not on results page after processing document, navigating back")
                    
                    # Try to go back
                    driver.back()
                    time.sleep(2)
                    
                    # If still not on results page, refresh
                    if not verify_results_page(driver):
                        logger.warning("Still not on results page after back, refreshing")
                        driver.refresh()
                        time.sleep(3)
                        
                        # Wait for page to load
                        wait_for_page_load(driver, 15)
                
                # Add dynamic delay based on success
                delay = 2 if success else 3  # Longer delay if there was an issue
                time.sleep(delay)
            
            except Exception as e:
                logger.error(f"Error processing document with ID {button_id} on page {page_number}: {str(e)}")
                # Take error screenshot
                driver.save_screenshot(os.path.join(page_dir, f"error_button_{button_id}.png"))
                
                # Try to recover
                try:
                    if not verify_results_page(driver):
                        driver.back()
                        time.sleep(2)
                    
                    if not verify_results_page(driver):
                        driver.refresh()
                        time.sleep(3)
                    
                    # Wait for page to load
                    wait_for_page_load(driver, 15)
                except Exception as recovery_error:
                    logger.error(f"Failed to recover after document error: {str(recovery_error)}")
                    break
    
    except Exception as e:
        logger.error(f"Error processing page {page_number}: {str(e)}")
        # Take error screenshot
        driver.save_screenshot(os.path.join(page_dir, "page_error.png"))
    
    return {
        "processed": page_processed,
        "downloaded": page_downloaded
    }

def process_single_document(driver, button, document_number, output_dir, debug_dir):
    """
    Process a single document.
    
    Args:
        driver: WebDriver instance
        button: The IndexII button element to click
        document_number: Document number for naming
        output_dir: Directory to save document
        debug_dir: Directory for debug files
    
    Returns:
        bool: True if document was successfully processed, False otherwise
    """
    # Store original window handles
    original_handles = driver.window_handles
    original_handle = driver.current_window_handle
    
    try:
        # Take screenshot before clicking
        driver.save_screenshot(os.path.join(debug_dir, f"before_click_doc_{document_number}.png"))
        
        # Scroll to button to ensure it's visible
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        time.sleep(1)
        
        # Get button identifier for better logging
        button_id = "unknown"
        try:
            onclick = button.get_attribute("onclick")
            if onclick:
                match = re.search(r"indexII\$(\d+)", onclick)
                if match:
                    button_id = f"indexII${match.group(1)}"
        except:
            pass
        
        logger.info(f"Clicking IndexII button (ID: {button_id}) for document {document_number}")
        
        # Try multiple click methods for reliability
        click_successful = False
        
        # Method 1: Direct JavaScript execution via onclick attribute
        try:
            onclick = button.get_attribute("onclick")
            if onclick and "__doPostBack" in onclick:
                # Extract parameters
                match = re.search(r"__doPostBack\('([^']+)',\s*'([^']+)'\)", onclick)
                if match:
                    target = match.group(1)
                    argument = match.group(2)
                    logger.info(f"Using direct JavaScript __doPostBack with params: {target}, {argument}")
                    
                    driver.execute_script(f"__doPostBack('{target}', '{argument}')")
                    time.sleep(3)
                    
                    if len(driver.window_handles) > len(original_handles) or "IndexII" not in driver.page_source:
                        click_successful = True
        except Exception as e:
            logger.warning(f"Direct JavaScript execution failed: {str(e)}")
        
        # Method 2: JavaScript click
        if not click_successful:
            try:
                logger.info("Using JavaScript click")
                driver.execute_script("arguments[0].click();", button)
                time.sleep(3)
                
                if len(driver.window_handles) > len(original_handles) or "IndexII" not in driver.page_source:
                    click_successful = True
            except Exception as e:
                logger.warning(f"JavaScript click failed: {str(e)}")
        
        # Method 3: Native click
        if not click_successful:
            try:
                logger.info("Using native click")
                button.click()
                time.sleep(3)
                
                if len(driver.window_handles) > len(original_handles) or "IndexII" not in driver.page_source:
                    click_successful = True
            except Exception as e:
                logger.warning(f"Native click failed: {str(e)}")
        
        # Method 4: ActionChains
        if not click_successful:
            try:
                logger.info("Using ActionChains")
                ActionChains(driver).move_to_element(button).click().perform()
                time.sleep(3)
                
                if len(driver.window_handles) > len(original_handles) or "IndexII" not in driver.page_source:
                    click_successful = True
            except Exception as e:
                logger.warning(f"ActionChains click failed: {str(e)}")
        
        if not click_successful:
            logger.warning(f"All click methods failed for document {document_number}")
            return False
        
        # Check if new tab opened
        new_handles = driver.window_handles
        
        # Case 1: New tab opened
        if len(new_handles) > len(original_handles):
            logger.info(f"New tab opened for document {document_number}")
            
            # Switch to new tab
            new_handle = [h for h in new_handles if h not in original_handles][0]
            driver.switch_to.window(new_handle)
            
            # Wait for document to load
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # Additional wait for page to stabilize
                time.sleep(2)
                
                # Take screenshot of document
                driver.save_screenshot(os.path.join(debug_dir, f"document_{document_number}.png"))
                
                # Generate PDF file with proper naming
                pdf_path = os.path.join(output_dir, f"Document-{document_number}.pdf")
                
                try:
                    # Configure PDF options
                    pdf_options = {
                        'landscape': False,
                        'printBackground': True,
                        'paperWidth': 8.27,  # A4 width in inches
                        'paperHeight': 11.69,  # A4 height in inches
                        'marginTop': 0.4,
                        'marginBottom': 0.4,
                        'marginLeft': 0.4,
                        'marginRight': 0.4,
                        'scale': 1.0
                    }
                    
                    # Generate PDF
                    pdf_data = driver.execute_cdp_cmd('Page.printToPDF', pdf_options)
                    
                    # Save PDF
                    with open(pdf_path, 'wb') as pdf_file:
                        pdf_file.write(base64.b64decode(pdf_data['data']))
                    
                    logger.info(f"Document PDF saved to {pdf_path}")
                    success = True
                except Exception as pdf_error:
                    logger.warning(f"Could not generate PDF: {str(pdf_error)}")
                    
                    # Fallback to screenshot
                    screenshot_path = os.path.join(output_dir, f"Document-{document_number}.png")
                    driver.save_screenshot(screenshot_path)
                    logger.info(f"Saved screenshot as fallback to {screenshot_path}")
                    success = True
            
            except Exception as load_error:
                logger.error(f"Error waiting for document to load: {str(load_error)}")
                success = False
            
            # Close tab and switch back to original
            try:
                driver.close()
                driver.switch_to.window(original_handle)
            except Exception as e:
                logger.error(f"Error closing tab: {str(e)}")
                # Try to recover by switching to original handle
                try:
                    for handle in driver.window_handles:
                        if handle == original_handle:
                            driver.switch_to.window(handle)
                            break
                except Exception as switch_error:
                    logger.error(f"Error switching back to original handle: {str(switch_error)}")
            
            return success
        
        # Case 2: No new tab, but page changed
        elif "IndexII" not in driver.page_source:
            logger.info(f"Page content changed for document {document_number} (no new tab)")
            
            # Take screenshot of document
            driver.save_screenshot(os.path.join(debug_dir, f"document_{document_number}.png"))
            
            # Generate PDF file with proper naming
            pdf_path = os.path.join(output_dir, f"Document-{document_number}.pdf")
            
            try:
                # Configure PDF options
                pdf_options = {
                    'landscape': False,
                    'printBackground': True,
                    'paperWidth': 8.27,  # A4 width in inches
                    'paperHeight': 11.69,  # A4 height in inches
                    'marginTop': 0.4,
                    'marginBottom': 0.4,
                    'marginLeft': 0.4,
                    'marginRight': 0.4,
                    'scale': 1.0
                }
                
                # Generate PDF
                pdf_data = driver.execute_cdp_cmd('Page.printToPDF', pdf_options)
                
                # Save PDF
                with open(pdf_path, 'wb') as pdf_file:
                    pdf_file.write(base64.b64decode(pdf_data['data']))
                
                logger.info(f"Document PDF saved to {pdf_path}")
                success = True
            except Exception as pdf_error:
                logger.warning(f"Could not generate PDF: {str(pdf_error)}")
                
                # Fallback to screenshot
                screenshot_path = os.path.join(output_dir, f"Document-{document_number}.png")
                driver.save_screenshot(screenshot_path)
                logger.info(f"Saved screenshot as fallback to {screenshot_path}")
                success = True
            
            # Navigate back to results
            try:
                driver.back()
                time.sleep(2)
                
                # Check if we're back on results page
                if not verify_results_page(driver):
                    logger.warning("Back navigation didn't return to results page, refreshing")
                    driver.refresh()
                    time.sleep(3)
                    wait_for_page_load(driver, 15)
            except Exception as e:
                logger.error(f"Error navigating back: {str(e)}")
                driver.refresh()
                time.sleep(3)
                wait_for_page_load(driver, 15)
                
            return success
        
        # Case 3: Nothing happened, click failed
        else:
            logger.warning(f"Click on IndexII button for document {document_number} had no effect")
            return False
    
    except Exception as e:
        logger.error(f"Error processing document {document_number}: {str(e)}")
        
        # Take error screenshot
        driver.save_screenshot(os.path.join(debug_dir, f"error_doc_{document_number}.png"))
        
        # Make sure we're back on the original handle
        if len(driver.window_handles) > len(original_handles):
            # Close any new tabs
            try:
                for handle in driver.window_handles:
                    if handle != original_handle:
                        driver.switch_to.window(handle)
                        driver.close()
                
                # Switch back to original
                driver.switch_to.window(original_handle)
            except Exception as tab_error:
                logger.error(f"Error closing tabs: {str(tab_error)}")
                # Try to force back to original window
                try:
                    driver.switch_to.window(original_handle)
                except:
                    if driver.window_handles:
                        driver.switch_to.window(driver.window_handles[0])
        
        return False

def get_current_page_number(driver):
    """
    Get the current page number with multiple detection methods.
    
    Args:
        driver: WebDriver instance
    
    Returns:
        int: Current page number or None if not detected
    """
    try:
        # Method 1: Look for span elements (selected page)
        spans = driver.find_elements(By.XPATH, "//span[string-length(text()) < 5]")
        for span in spans:
            span_text = span.text.strip()
            if span_text.isdigit():
                return int(span_text)
        
        # Method 2: Look for links with different styling (current page)
        links = driver.find_elements(By.XPATH, "//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page$\")]")
        for link in links:
            try:
                style = link.get_attribute("style")
                if style and "color:Black;" in style:
                    link_text = link.text.strip()
                    if link_text.isdigit():
                        return int(link_text)
            except:
                pass
        
        # Method 3: Try to infer from the URL or other elements
        try:
            page_inputs = driver.find_elements(By.XPATH, "//input[contains(@name, 'page') or contains(@name, 'Page')]")
            for input_element in page_inputs:
                value = input_element.get_attribute("value")
                if value and value.isdigit():
                    return int(value)
        except:
            pass
        
        logger.warning("Could not determine current page number")
        return None
    except Exception as e:
        logger.error(f"Error getting current page number: {str(e)}")
        return None
    
def process_all_documents(driver, output_dir, debug_dir):
    """Process all documents across all pages with improved reliability"""
    current_page = 1
    max_pages = 50  # Safety limit
    processed_documents = 0
    downloaded_documents = 0
    processed_button_ids = set()
    
    # Create debug directory
    os.makedirs(debug_dir, exist_ok=True)
    
    # Process all pages
    while current_page <= max_pages:
        logger.info(f"Processing page {current_page}")
        
        # Take screenshot of current page
        driver.save_screenshot(os.path.join(debug_dir, f"page_{current_page}.png"))
        
        # Verify we're on a results page
        if not verify_results_page(driver):
            logger.warning(f"Not on results page at page {current_page}, stopping processing")
            break
        
        # Get all IndexII buttons on current page
        index_buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
        logger.info(f"Found {len(index_buttons)} IndexII buttons on page {current_page}")
        
        # Process each button
        for i, button in enumerate(index_buttons):
            try:
                # Extract button ID for tracking
                button_id = None
                try:
                    onclick = button.get_attribute("onclick")
                    match = re.search(r"indexII\$(\d+)", onclick)
                    if match:
                        button_id = f"page_{current_page}_indexII_{match.group(1)}"
                except:
                    button_id = f"page_{current_page}_position_{i}"
                
                # Skip if already processed
                if button_id in processed_button_ids:
                    logger.info(f"Skipping already processed button {button_id}")
                    continue
                
                # Process this document
                document_number = processed_documents + 1
                logger.info(f"Processing document {document_number} (ID: {button_id})")
                
                # Process document with the improved function
                success = process_index_button(driver, button, document_number, output_dir, debug_dir)
                
                # Update tracking
                processed_documents += 1
                processed_button_ids.add(button_id)
                
                if success:
                    downloaded_documents += 1
                    logger.info(f"Successfully processed document {document_number}")
                else:
                    logger.warning(f"Failed to process document {document_number}")
                
                # Verify we're still on results page after processing
                if not verify_results_page(driver):
                    logger.warning("Not on results page after processing document, refreshing")
                    driver.refresh()
                    time.sleep(3)
                    
                    # Verify again after refresh
                    if not verify_results_page(driver):
                        logger.error("Still not on results page after refresh, stopping processing")
                        break
                    
                    # Re-find buttons after refresh
                    index_buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
                    if i < len(index_buttons):
                        # Update button reference
                        button = index_buttons[i]
                    else:
                        logger.warning(f"Button index {i} out of range after refresh")
                        break
                
                # Add a small delay between documents
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error processing button {i} on page {current_page}: {str(e)}")
                driver.save_screenshot(os.path.join(debug_dir, f"error_button_{i}_page_{current_page}.png"))
                
                # Try to recover
                try:
                    if not verify_results_page(driver):
                        driver.refresh()
                        time.sleep(3)
                except:
                    logger.error("Failed to recover after error")
                    break
        
        # Try to navigate to next page with improved function
        navigation_success = navigate_to_next_page(driver, current_page, debug_dir)
        
        if navigation_success:
            # Get new page number
            new_page = get_current_page_number(driver)
            if new_page is not None:
                current_page = new_page
            else:
                # If can't determine, assume next page
                current_page += 1
                
            logger.info(f"Advanced to page {current_page}")
            
            # Add delay between pages
            time.sleep(3)
        else:
            logger.info("No more pages to process")
            break
    
    # Return summary
    return {
        "pages_processed": current_page,
        "documents_processed": processed_documents,
        "documents_downloaded": downloaded_documents
    }