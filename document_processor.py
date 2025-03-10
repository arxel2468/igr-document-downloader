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
    Process all IndexII buttons across all pages with better page tracking.
    
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
    
    # Take initial screenshot
    driver.save_screenshot(os.path.join(debug_dir, "initial_page.png"))
    
    # Initialize tracking variables
    processed_document_hashes = set()  # Not used but kept for compatibility
    documents_processed = 0
    documents_downloaded = 0
    processed_pages = set()  # Track pages we've already processed
    
    # Get current page number
    current_page = get_current_page_number(driver)
    if current_page is None:
        current_page = 1
        logger.info("Could not determine initial page number, assuming page 1")
    else:
        logger.info(f"Starting processing from page {current_page}")
    
    # Set safety limits
    max_pages = 100  # Maximum number of pages to process
    max_attempts_per_page = 2  # Maximum attempts per page
    max_navigation_failures = 3  # Maximum consecutive navigation failures
    page_attempts = {}  # Track attempts per page
    
    # Tracking variables
    consecutive_failures = 0
    iteration = 0
    
    while iteration < max_pages:
        iteration += 1
        logger.info(f"Processing page {current_page} (iteration {iteration})")
        
        # Take screenshot at start of iteration
        driver.save_screenshot(os.path.join(debug_dir, f"iteration_{iteration}_page_{current_page}.png"))
        
        # Check if we've already processed this page too many times
        page_attempts[current_page] = page_attempts.get(current_page, 0) + 1
        
        if page_attempts[current_page] > max_attempts_per_page:
            logger.warning(f"Page {current_page} has been attempted {page_attempts[current_page]} times, " 
                          f"which exceeds the limit of {max_attempts_per_page}. Moving to next page.")
            
            # Try to move to next page
            if navigate_to_next_page(driver, current_page, debug_dir):
                # Update page number
                new_page = get_current_page_number(driver)
                if new_page is not None:
                    if new_page != current_page:
                        logger.info(f"Successfully moved from page {current_page} to page {new_page}")
                        current_page = new_page
                    else:
                        # Force increment if page number didn't change
                        current_page += 1
                        logger.info(f"Page number didn't change, forcing move to page {current_page}")
                else:
                    # Assume next page
                    current_page += 1
                    logger.info(f"Could not determine new page number, assuming page {current_page}")
                
                consecutive_failures = 0  # Reset failures counter
            else:
                logger.warning("Failed to navigate to next page. Ending processing.")
                break
            
            # Skip to next iteration
            continue
        
        # Process all documents on current page
        page_results = process_page_documents(
            driver,
            current_page,
            output_dir,
            debug_dir,
            processed_document_hashes,
            set(),  # Empty set for button identifiers (not used)
            documents_processed
        )
        
        # Mark this page as processed
        processed_pages.add(current_page)
        
        # Update counters
        documents_processed += page_results['processed']
        documents_downloaded += page_results['downloaded']
        
        # Log results
        logger.info(f"Completed processing page {current_page}: {page_results['processed']} processed, {page_results['downloaded']} downloaded")
        
        # Update job status if tracking enabled
        if job_id and jobs:
            try:
                jobs[job_id].update({
                    "processed_documents": documents_processed,
                    "downloaded_documents": documents_downloaded,
                    "current_page": current_page
                })
            except Exception as job_error:
                logger.error(f"Error updating job status: {str(job_error)}")
        
        # Take screenshot after processing
        driver.save_screenshot(os.path.join(debug_dir, f"after_processing_page_{current_page}.png"))
        
        # Attempt to navigate to next page
        logger.info(f"Attempting to navigate from page {current_page} to next page")
        
        if navigate_to_next_page(driver, current_page, debug_dir):
            # Reset failures counter
            consecutive_failures = 0
            
            # Get new page number
            new_page = get_current_page_number(driver)
            logger.info(f"After navigation, current page is: {new_page}")
            
            if new_page is not None:
                # Check if we actually moved to a different page
                if new_page != current_page:
                    logger.info(f"Successfully navigated from page {current_page} to page {new_page}")
                    current_page = new_page
                else:
                    logger.warning(f"Navigation appeared successful but still on page {current_page}")
                    # Force increment to avoid getting stuck
                    current_page += 1
                    logger.info(f"Forcing move to page {current_page}")
            else:
                # If can't determine, assume next page
                current_page += 1
                logger.info(f"Could not determine new page number, assuming page {current_page}")
            
            # Add delay between pages
            time.sleep(3)
        else:
            # Increment failures counter
            consecutive_failures += 1
            
            if consecutive_failures >= max_navigation_failures:
                logger.warning(f"Reached maximum consecutive navigation failures ({max_navigation_failures}). Ending processing.")
                break
                
            logger.warning(f"Failed to navigate from page {current_page} (failure {consecutive_failures}/{max_navigation_failures})")
            
            # Try again with a page refresh
            try:
                driver.refresh()
                time.sleep(3)
                
                # Try navigation again
                if navigate_to_next_page(driver, current_page, debug_dir):
                    consecutive_failures = 0  # Reset counter
                    
                    # Get new page number
                    new_page = get_current_page_number(driver)
                    if new_page is not None:
                        current_page = new_page
                    else:
                        # Assume next page
                        current_page += 1
                        
                    logger.info(f"Successfully navigated to page {current_page} after refresh")
                else:
                    logger.info("No next page available after refresh. Likely at the last page.")
                    break
            except Exception as e:
                logger.error(f"Error during refresh and retry: {str(e)}")
                break
    
    # Prepare summary
    summary = {
        "pages_processed": len(processed_pages),
        "documents_processed": documents_processed,
        "documents_downloaded": documents_downloaded,
        "processed_pages": sorted(list(processed_pages))
    }
    
    logger.info(f"Processing complete. Summary: {summary}")
    
    return summary

def navigate_to_next_page(driver, current_page, debug_dir):
    """
    Navigate to the next page of search results with better pagination detection.
    
    Args:
        driver: WebDriver instance
        current_page: Current page number
        debug_dir: Directory to save debug screenshots
        
    Returns:
        bool: True if navigation was successful, False otherwise
    """
    try:
        # Take screenshot before navigation attempt
        driver.save_screenshot(os.path.join(debug_dir, f"before_navigate_page_{current_page}.png"))
        
        # Log current page number and expected next page
        next_page = current_page + 1
        logger.info(f"Current page: {current_page}, looking for next page: {next_page}")
        
        # Find all pagination links - using the correct table structure based on the HTML snippet
        pagination_links = driver.find_elements(By.XPATH, "//tr[td/a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page$\")]]//td/a")
        
        # Log all found pagination links for debugging
        if pagination_links:
            logger.info(f"Found {len(pagination_links)} pagination links")
            
            # Create a list of available page numbers for better decision making
            available_pages = []
            ellipsis_found = False
            
            for i, link in enumerate(pagination_links):
                try:
                    text = link.text.strip()
                    href = link.get_attribute("href")
                    logger.info(f"Link {i+1}: text='{text}', href='{href}'")
                    
                    # Check if this is an ellipsis link
                    if text == "...":
                        ellipsis_found = True
                        # Extract target page number from href
                        match = re.search(r"Page\$(\d+)", href)
                        if match:
                            logger.info(f"Ellipsis points to page {match.group(1)}")
                    elif text.isdigit():
                        available_pages.append(int(text))
                except:
                    continue
            
            # Log available pages and whether ellipsis was found
            if available_pages:
                logger.info(f"Available page numbers: {sorted(available_pages)}")
            if ellipsis_found:
                logger.info("Ellipsis link '...' is available")
        else:
            logger.warning("No pagination links found")
            # Take screenshot to debug why links weren't found
            driver.save_screenshot(os.path.join(debug_dir, f"no_pagination_links_page_{current_page}.png"))
            
            # Save page source for debugging
            with open(os.path.join(debug_dir, f"page_source_no_links_{current_page}.html"), 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
                
            # Try refreshing the page once before giving up
            logger.info("Refreshing page to try again...")
            driver.refresh()
            time.sleep(3)
            
            # Try again with a different XPath that's more permissive
            pagination_links = driver.find_elements(By.XPATH, "//a[contains(@href, \"javascript:__doPostBack\")]")
            if pagination_links:
                logger.info(f"After refresh, found {len(pagination_links)} potential pagination links")
                # Continue with the rest of the function
            else:
                return False
        
        # STRATEGY 1: Try direct link to next page first
        logger.info(f"STRATEGY 1: Looking for direct link to page {next_page}")
        next_page_link = None
        
        for link in pagination_links:
            try:
                if link.text.strip() == str(next_page):
                    next_page_link = link
                    break
            except:
                continue
                
        if next_page_link:
            logger.info(f"Found direct link to page {next_page}, clicking it")
            
            try:
                # Scroll to the link
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                # Click the link
                next_page_link.click()
                time.sleep(3)
                
                # Verify navigation was successful
                if verify_navigation_success(driver, debug_dir):
                    # Get new page number to confirm
                    new_page = get_current_page_number(driver)
                    if new_page is not None:
                        logger.info(f"Successfully navigated to page {new_page} via direct link")
                    return True
            except Exception as e:
                logger.warning(f"Error clicking next page link: {str(e)}")
        
        # STRATEGY 2: If no direct next page link, try using the ellipsis if available
        logger.info("STRATEGY 2: Looking for ellipsis link")
        ellipsis_link = None
        
        for link in pagination_links:
            try:
                if link.text.strip() == "...":
                    href = link.get_attribute("href")
                    # Make sure this is a forward ellipsis (check the target page number)
                    match = re.search(r"Page\$(\d+)", href)
                    if match and int(match.group(1)) > current_page:
                        logger.info(f"Found forward ellipsis to page {match.group(1)}")
                        ellipsis_link = link
                        break
            except:
                continue
        
        if ellipsis_link:
            logger.info("Clicking ellipsis link to navigate to next set of pages")
            
            try:
                # Scroll to the link
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                # Click the link
                ellipsis_link.click()
                time.sleep(3)
                
                # Verify navigation was successful
                if verify_navigation_success(driver, debug_dir):
                    # Get new page number to confirm
                    new_page = get_current_page_number(driver)
                    if new_page is not None:
                        logger.info(f"Successfully navigated to page {new_page} via ellipsis")
                    return True
            except Exception as e:
                logger.warning(f"Error clicking ellipsis link: {str(e)}")
        
        # STRATEGY 3: If no direct next page or ellipsis, try any page number greater than current
        logger.info("STRATEGY 3: Looking for any page greater than current")
        higher_page_links = []
        
        for link in pagination_links:
            try:
                text = link.text.strip()
                if text.isdigit() and int(text) > current_page:
                    higher_page_links.append((int(text), link))
            except:
                continue
        
        if higher_page_links:
            # Sort by page number and take the lowest (next available)
            higher_page_links.sort()
            next_available_page, link = higher_page_links[0]
            logger.info(f"Found higher page {next_available_page}, clicking it")
            
            try:
                # Scroll to the link
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                # Click the link
                link.click()
                time.sleep(3)
                
                # Verify navigation was successful
                if verify_navigation_success(driver, debug_dir):
                    # Get new page number to confirm
                    new_page = get_current_page_number(driver)
                    if new_page is not None:
                        logger.info(f"Successfully navigated to page {new_page} via higher page link")
                    return True
            except Exception as e:
                logger.warning(f"Error clicking higher page link: {str(e)}")
        
        # If all navigation strategies failed, try direct JavaScript approach
        logger.info("STRATEGY 4: Using JavaScript postback directly")
        try:
            script = f"__doPostBack('RegistrationGrid','Page${next_page}')"
            logger.info(f"Executing JavaScript: {script}")
            driver.execute_script(script)
            time.sleep(3)
            
            # Verify navigation was successful
            if verify_navigation_success(driver, debug_dir):
                new_page = get_current_page_number(driver)
                if new_page is not None:
                    logger.info(f"Successfully navigated to page {new_page} via JavaScript")
                return True
        except Exception as e:
            logger.warning(f"Error executing JavaScript navigation: {str(e)}")
        
        # If all navigation strategies failed, we might be at the last page
        logger.info("All navigation strategies failed, likely at the last page")
        return False
        
    except Exception as e:
        logger.error(f"Error navigating to next page: {str(e)}")
        # Take screenshot for debugging
        try:
            driver.save_screenshot(os.path.join(debug_dir, f"error_navigate_page_{current_page}.png"))
        except:
            pass
        return False

def verify_navigation_and_page(driver, expected_page, debug_dir):
    """
    Verify that navigation was successful and we're on the expected page.
    
    Args:
        driver: WebDriver instance
        expected_page: Expected page number after navigation
        debug_dir: Directory for debug screenshots
        
    Returns:
        bool: True if navigation was successful, False otherwise
    """
    try:
        # Take screenshot after navigation
        try:
            driver.save_screenshot(os.path.join(debug_dir, f"after_navigate_to_page_{expected_page}.png"))
        except:
            pass
        
        # Wait for page load
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except:
            logger.warning("Timeout waiting for page to load completely")
        
        # Check for IndexII buttons to verify we're on a results page
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
            )
            
            # Count buttons for logging
            buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
            logger.info(f"Found {len(buttons)} IndexII buttons after navigation")
            
            # Check current page number
            current_page = get_current_page_number(driver)
            if current_page is not None:
                logger.info(f"Current page after navigation: {current_page}")
                
                # If we're on the expected page, great!
                if current_page == expected_page:
                    return True
                # If we're on any different page than before, that's also fine
                elif current_page != expected_page:
                    logger.warning(f"Navigation succeeded but landed on page {current_page} instead of expected page {expected_page}")
                    return True
            else:
                logger.warning("Couldn't determine page number after navigation")
                # Consider navigation successful if we can see IndexII buttons
                return True
            
        except TimeoutException:
            logger.warning("No IndexII buttons found after navigation")
            
            # Try refreshing once
            try:
                driver.refresh()
                time.sleep(3)
                
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                )
                logger.info("Found IndexII buttons after refresh")
                return True
            except:
                logger.warning("No IndexII buttons found after refresh")
                return False
    except Exception as e:
        logger.error(f"Error verifying navigation: {str(e)}")
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
    Verify that the current page is a search results page.
    
    Args:
        driver: WebDriver instance
    
    Returns:
        bool: True if the current page is a results page, False otherwise
    """
    try:
        # Check for IndexII buttons - the main indicator of a results page
        buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
        if buttons and len(buttons) > 0:
            return True
        
        # Additional check for pagination section
        pagination = driver.find_elements(By.XPATH, "//a[contains(@href, \"javascript:__doPostBack('RegistrationGrid','Page$\")]")
        if pagination and len(pagination) > 0:
            return True
        
        # Check for RegistrationGrid which contains the results
        grid = driver.find_elements(By.ID, "RegistrationGrid")
        if grid and len(grid) > 0:
            return True
        
        # If none of the above were found, it's not a results page
        return False
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
    Verify that navigation was successful by checking for IndexII buttons.
    
    Args:
        driver: WebDriver instance
        debug_dir: Directory for debug screenshots
        
    Returns:
        bool: True if navigation was successful, False otherwise
    """
    try:
        # Take screenshot after navigation
        try:
            driver.save_screenshot(os.path.join(debug_dir, "after_navigation.png"))
        except:
            pass
        
        # Wait for page to load
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except:
            logger.warning("Timeout waiting for page to load completely")
        
        # Check for IndexII buttons
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
            )
            
            # Count buttons for logging
            buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
            logger.info(f"Found {len(buttons)} IndexII buttons after navigation")
            
            # Get current page number for logging
            current_page = get_current_page_number(driver)
            if current_page:
                logger.info(f"Current page after navigation: {current_page}")
            
            return True
        except:
            logger.warning("No IndexII buttons found after navigation")
            
            # Try refreshing once
            try:
                driver.refresh()
                time.sleep(3)
                
                # Check again for IndexII buttons
                buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
                if buttons and len(buttons) > 0:
                    logger.info(f"Found {len(buttons)} IndexII buttons after refresh")
                    return True
                else:
                    logger.warning("No IndexII buttons found after refresh")
                    return False
            except:
                logger.warning("Error during refresh")
                return False
    except Exception as e:
        logger.error(f"Error verifying navigation: {str(e)}")
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
        processed_document_hashes: Set of already processed document hashes (not used in this version)
        processed_button_identifiers: Set of already processed button identifiers (not used in this version)
        documents_processed_so_far: Count of documents processed before this page
    
    Returns:
        dict: Results of processing this page
    """
    page_dir = os.path.join(debug_dir, f"page_{page_number}")
    os.makedirs(page_dir, exist_ok=True)
    
    page_processed = 0
    page_downloaded = 0
    
    try:
        # Take screenshot of page before processing
        try:
            driver.save_screenshot(os.path.join(page_dir, f"page_{page_number}_before_processing.png"))
        except:
            logger.warning("Could not take initial page screenshot")
        
        # Wait for page to load properly
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
            )
            logger.info(f"IndexII buttons found on page {page_number}")
        except TimeoutException:
            logger.warning(f"No IndexII buttons found on page {page_number}")
            try:
                driver.save_screenshot(os.path.join(page_dir, "no_index_buttons.png"))
            except:
                pass
            return {"processed": 0, "downloaded": 0}
        
        # Get all buttons on this page
        buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
        logger.info(f"Found {len(buttons)} IndexII buttons on page {page_number}")
        
        # Process each button
        for i in range(len(buttons)):
            # Get a fresh reference to all buttons to avoid stale elements
            fresh_buttons = driver.find_elements(By.XPATH, "//input[@value='IndexII']")
            
            if i >= len(fresh_buttons):
                logger.warning(f"Button index {i} out of range (found {len(fresh_buttons)} buttons)")
                break
                
            # Calculate document number for file naming
            document_number = documents_processed_so_far + page_processed + 1
            
            # Process this button
            logger.info(f"Processing document {document_number} on page {page_number} (button {i+1}/{len(buttons)})")
            
            try:
                # Use a simplified approach to click the button and handle the document
                result = process_button_simply(driver, fresh_buttons[i], document_number, page_number, output_dir, page_dir)
                
                if result:
                    page_downloaded += 1
                
                page_processed += 1
                
                # Add short delay between documents
                time.sleep(2)
            except Exception as e:
                logger.error(f"Error processing button {i} on page {page_number}: {str(e)}")
                # Continue with next button
                
                # Try to get back to results page if needed
                try:
                    # Check if we're still on results page
                    if not verify_results_page(driver):
                        logger.warning("Not on results page after error, refreshing")
                        driver.refresh()
                        time.sleep(3)
                except:
                    logger.warning("Error checking results page after button error")
    
    except Exception as e:
        logger.error(f"Error processing page {page_number}: {str(e)}")
        try:
            driver.save_screenshot(os.path.join(page_dir, "page_error.png"))
        except:
            pass
    
    logger.info(f"Completed processing page {page_number}: {page_processed} processed, {page_downloaded} downloaded")
    return {
        "processed": page_processed,
        "downloaded": page_downloaded
    }

def process_single_document_with_button(driver, button, document_number, doc_id, output_dir, debug_dir):
    """
    Process a single document using a direct button reference.
    
    Args:
        driver: WebDriver instance
        button: The IndexII button element to click
        document_number: Document number for naming
        doc_id: Unique document ID from the table
        output_dir: Directory to save document
        debug_dir: Directory for debug files
    
    Returns:
        bool: True if document was successfully processed, False otherwise
    """
    # Store original window handles
    original_handles = driver.window_handles
    original_handle = driver.current_window_handle
    original_url = driver.current_url
    
    try:
        # Scroll to button to ensure it's visible
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            time.sleep(1)
        except:
            logger.warning(f"Failed to scroll to button for document ID {doc_id}")
            # Continue anyway
        
        # Try to click the button directly
        click_successful = False
        
        # Method 1: Direct click
        try:
            logger.info(f"Clicking IndexII button for document ID {doc_id} (doc #{document_number})")
            button.click()
            time.sleep(3)
            
            # Check if click worked
            new_handles = driver.window_handles
            if len(new_handles) > len(original_handles) or driver.current_url != original_url:
                click_successful = True
        except Exception as e:
            logger.warning(f"Direct click failed for document ID {doc_id}: {str(e)}")
        
        # Method 2: JavaScript click as fallback
        if not click_successful:
            try:
                logger.info(f"Using JavaScript click for document ID {doc_id}")
                driver.execute_script("arguments[0].click();", button)
                time.sleep(3)
                
                # Check if click worked
                new_handles = driver.window_handles
                if len(new_handles) > len(original_handles) or driver.current_url != original_url:
                    click_successful = True
            except Exception as e:
                logger.warning(f"JavaScript click failed for document ID {doc_id}: {str(e)}")
        
        # If all clicks failed
        if not click_successful:
            logger.warning(f"All click methods failed for document ID {doc_id}")
            return False
        
        # Handle new tab or page change
        new_handles = driver.window_handles
        
        # Case 1: New tab opened
        if len(new_handles) > len(original_handles):
            logger.info(f"New tab opened for document ID {doc_id}")
            
            # Switch to new tab
            new_handle = [h for h in new_handles if h not in original_handles][0]
            driver.switch_to.window(new_handle)
            
            # Wait for document to load
            try:
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(2)  # Additional wait for content to load
                
                # Generate PDF
                pdf_path = os.path.join(output_dir, f"Document-{document_number}-ID{doc_id}.pdf")
                
                try:
                    # Use PDF printing
                    pdf_options = {
                        'printBackground': True,
                        'paperWidth': 8.27,  # A4 width
                        'paperHeight': 11.69,  # A4 height
                        'marginTop': 0.4,
                        'marginBottom': 0.4,
                        'scale': 1.0
                    }
                    
                    pdf_data = driver.execute_cdp_cmd('Page.printToPDF', pdf_options)
                    
                    with open(pdf_path, 'wb') as pdf_file:
                        pdf_file.write(base64.b64decode(pdf_data['data']))
                    
                    logger.info(f"Document ID {doc_id} saved to {pdf_path}")
                    success = True
                except Exception as pdf_error:
                    logger.warning(f"PDF generation failed for document ID {doc_id}: {str(pdf_error)}")
                    
                    # Fallback to screenshot if PDF fails
                    screenshot_path = os.path.join(output_dir, f"Document-{document_number}-ID{doc_id}.png")
                    driver.save_screenshot(screenshot_path)
                    logger.info(f"Saved screenshot instead for document ID {doc_id}")
                    success = True
                
                # Close tab and return to original
                driver.close()
                driver.switch_to.window(original_handle)
                return success
            except Exception as e:
                logger.error(f"Error processing document ID {doc_id} in new tab: {str(e)}")
                
                # Make sure we close the tab and go back
                try:
                    driver.close()
                    driver.switch_to.window(original_handle)
                except:
                    # If we can't close/switch properly, try to get back to a working state
                    for handle in driver.window_handles:
                        if handle == original_handle:
                            driver.switch_to.window(handle)
                            break
                return False
        
        # Case 2: URL changed but no new tab
        elif driver.current_url != original_url:
            logger.info(f"Page content changed for document ID {doc_id} (no new tab)")
            
            # Generate PDF
            pdf_path = os.path.join(output_dir, f"Document-{document_number}-ID{doc_id}.pdf")
            
            try:
                # Use PDF printing
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
                
                logger.info(f"Document ID {doc_id} saved to {pdf_path}")
                success = True
            except Exception as pdf_error:
                logger.warning(f"PDF generation failed for document ID {doc_id}: {str(pdf_error)}")
                
                # Fallback to screenshot
                screenshot_path = os.path.join(output_dir, f"Document-{document_number}-ID{doc_id}.png")
                driver.save_screenshot(screenshot_path)
                logger.info(f"Saved screenshot instead for document ID {doc_id}")
                success = True
            
            # Navigate back to results
            try:
                driver.back()
                time.sleep(2)
                
                # Make sure we're back on results page
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//input[@value='IndexII']"))
                    )
                except:
                    logger.warning("Back navigation didn't return to results, refreshing")
                    driver.refresh()
                    time.sleep(3)
            except:
                # If back navigation fails, try to reload the original URL
                try:
                    driver.get(original_url)
                    time.sleep(3)
                except:
                    pass
            
            return success
        
        # Case 3: Nothing changed (both methods failed)
        else:
            logger.warning(f"Button click had no visible effect for document ID {doc_id}")
            return False
    
    except Exception as e:
        logger.error(f"Error processing document ID {doc_id}: {str(e)}")
        
        # Try to recover to original state
        try:
            # If new tabs were opened, close them
            if len(driver.window_handles) > len(original_handles):
                for handle in driver.window_handles:
                    if handle != original_handle:
                        driver.switch_to.window(handle)
                        driver.close()
                
                driver.switch_to.window(original_handle)
            
            # If we navigated away, go back to original URL
            if driver.current_url != original_url:
                driver.get(original_url)
                time.sleep(3)
        except:
            # Last resort - just try to get back to original URL
            try:
                driver.get(original_url)
                time.sleep(3)
            except:
                pass
        
        return False

def get_current_page_number(driver):
    """
    Get the current page number from the pagination controls.
    
    Args:
        driver: WebDriver instance
    
    Returns:
        int: Current page number or None if not detected
    """
    try:
        # Method 1: Look for span tag inside the pagination controls (most reliable)
        # This is the element that looks like: <span>1</span>
        spans = driver.find_elements(By.XPATH, "//tr[@class='GridPager']/td/span")
        for span in spans:
            try:
                text = span.text.strip()
                if text.isdigit():
                    logger.info(f"Current page detected as {text} from span tag")
                    driver.save_screenshot(f"debug/page_{text}_detected.png")
                    return int(text)
            except:
                pass
                
        # Method 2: Look for pagination controls and infer page number
        # Check for selected page by looking at links without href
        selected = driver.find_elements(By.XPATH, "//tr[@class='GridPager']/td/span[not(parent::a)]")
        for span in selected:
            try:
                text = span.text.strip()
                if text.isdigit():
                    logger.info(f"Current page detected as {text} from selected page span")
                    return int(text)
            except:
                pass
        
        # Method 3: Check for styled links which indicate current page
        links = driver.find_elements(By.XPATH, "//tr[@class='GridPager']/td/a")
        for link in links:
            try:
                style = link.get_attribute("style")
                if style and "color:White" in style:  # Selected page is styled differently
                    text = link.text.strip()
                    if text.isdigit():
                        logger.info(f"Current page detected as {text} from styled link")
                        return int(text)
            except:
                pass
                
        # Take a screenshot to help debug page number issue
        try:
            driver.save_screenshot("debug/page_number_detection_issue.png")
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
                success = process_single_document(driver, i, document_number, output_dir, debug_dir)
                
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

def process_button_simply(driver, button, document_number, page_number, output_dir, debug_dir):
    """
    Simply process a single IndexII button without tracking document IDs.
    
    Args:
        driver: WebDriver instance
        button: The IndexII button element to click
        document_number: Document number for naming
        page_number: Current page number
        output_dir: Directory to save document
        debug_dir: Directory for debug files
    
    Returns:
        bool: True if document was successfully processed, False otherwise
    """
    # Store original window handles
    original_handles = driver.window_handles
    original_handle = driver.current_window_handle
    original_url = driver.current_url
    
    try:
        # Extract onclick attribute for direct JavaScript execution (most reliable)
        onclick = button.get_attribute("onclick")
        click_successful = False
        
        # Method 1: Try using __doPostBack if available
        if onclick and "__doPostBack" in onclick:
            match = re.search(r"__doPostBack\('([^']+)',\s*'([^']+)'\)", onclick)
            if match:
                target, argument = match.groups()
                logger.info(f"Executing __doPostBack for document {document_number}")
                
                # Execute JavaScript directly
                driver.execute_script(f"__doPostBack('{target}', '{argument}')")
                time.sleep(2.5)  # Wait a bit longer
                
                # Check for new tab
                new_handles = driver.window_handles
                if len(new_handles) > len(original_handles):
                    click_successful = True
                    logger.info(f"JavaScript execution opened new tab for document {document_number}")
                elif driver.current_url != original_url:
                    click_successful = True
                    logger.info(f"JavaScript execution changed URL for document {document_number}")
        
        # Method 2: Try direct click if JavaScript didn't work
        if not click_successful:
            try:
                # Scroll to make button visible
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                time.sleep(1)
                
                # Click the button
                button.click()
                logger.info(f"Clicked IndexII button for document {document_number}")
                time.sleep(2.5)  # Wait a bit longer
                
                # Check for new tab
                new_handles = driver.window_handles
                if len(new_handles) > len(original_handles):
                    click_successful = True
                    logger.info(f"Direct click opened new tab for document {document_number}")
                elif driver.current_url != original_url:
                    click_successful = True
                    logger.info(f"Direct click changed URL for document {document_number}")
            except Exception as click_error:
                # If direct click fails, try JavaScript click
                try:
                    logger.info(f"Direct click failed, trying JavaScript click for document {document_number}")
                    driver.execute_script("arguments[0].click();", button)
                    time.sleep(2.5)  # Wait a bit longer
                    
                    # Check for new tab
                    new_handles = driver.window_handles
                    if len(new_handles) > len(original_handles):
                        click_successful = True
                        logger.info(f"JavaScript click opened new tab for document {document_number}")
                    elif driver.current_url != original_url:
                        click_successful = True
                        logger.info(f"JavaScript click changed URL for document {document_number}")
                except Exception as js_error:
                    logger.error(f"JavaScript click also failed for document {document_number}")
        
        # If all click methods failed
        if not click_successful:
            logger.warning(f"All click methods failed for document {document_number}")
            return False
        
        # Handle new tab or page change
        new_handles = driver.window_handles
        
        # Case 1: New tab opened
        if len(new_handles) > len(original_handles):
            logger.info(f"New tab opened for document {document_number}")
            
            # Find the new tab handle
            new_handle = None
            for handle in new_handles:
                if handle not in original_handles:
                    new_handle = handle
                    break
            
            if not new_handle:
                logger.error(f"Could not identify new tab for document {document_number}")
                return False
            
            # Switch to new tab (deliberately using new_handle instead of relying on list comprehension)
            logger.info(f"Switching to new tab for document {document_number}")
            driver.switch_to.window(new_handle)
            
            # Wait for document to load
            try:
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(2)  # Additional wait for content to load
                
                # Generate PDF
                pdf_path = os.path.join(output_dir, f"Document-P{page_number}-{document_number}.pdf")
                
                try:
                    # Use PDF printing
                    pdf_options = {
                        'printBackground': True,
                        'paperWidth': 8.27,  # A4 width
                        'paperHeight': 11.69,  # A4 height
                        'marginTop': 0.4,
                        'marginBottom': 0.4,
                        'scale': 1.0
                    }
                    
                    pdf_data = driver.execute_cdp_cmd('Page.printToPDF', pdf_options)
                    
                    with open(pdf_path, 'wb') as pdf_file:
                        pdf_file.write(base64.b64decode(pdf_data['data']))
                    
                    logger.info(f"Document {document_number} saved to {pdf_path}")
                    success = True
                except Exception as pdf_error:
                    logger.warning(f"PDF generation failed: {str(pdf_error)}")
                    
                    # Fallback to screenshot
                    screenshot_path = os.path.join(output_dir, f"Document-P{page_number}-{document_number}.png")
                    driver.save_screenshot(screenshot_path)
                    logger.info(f"Saved screenshot instead at {screenshot_path}")
                    success = True
            except Exception as e:
                logger.error(f"Error processing document in new tab: {str(e)}")
                success = False
            
            # Always close the new tab and switch back regardless of success/failure
            logger.info(f"Closing tab for document {document_number}")
            driver.close()
            driver.switch_to.window(original_handle)
            
            # Verify we're back on the original tab
            if driver.current_url != original_url:
                logger.warning(f"URL changed after switching back from document {document_number}, refreshing")
                driver.get(original_url)
                time.sleep(2)
            
            return success
        
        # Case 2: URL changed but no new tab
        elif driver.current_url != original_url:
            logger.info(f"Page content changed for document {document_number} (no new tab)")
            
            # Generate PDF
            pdf_path = os.path.join(output_dir, f"Document-P{page_number}-{document_number}.pdf")
            
            try:
                # Use PDF printing
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
                
                logger.info(f"Document {document_number} saved to {pdf_path}")
                success = True
            except Exception as pdf_error:
                logger.warning(f"PDF generation failed: {str(pdf_error)}")
                
                # Fallback to screenshot
                screenshot_path = os.path.join(output_dir, f"Document-P{page_number}-{document_number}.png")
                driver.save_screenshot(screenshot_path)
                logger.info(f"Saved screenshot instead at {screenshot_path}")
                success = True
            
            # Navigate back to results
            try:
                logger.info(f"Navigating back from document {document_number}")
                driver.back()
                time.sleep(2)
                
                # Make sure we're back on results page
                if not verify_results_page(driver):
                    logger.warning("Back navigation didn't return to results, refreshing")
                    driver.refresh()
                    time.sleep(2)
            except:
                # If back navigation fails, try to reload the original URL
                try:
                    logger.warning(f"Back navigation failed for document {document_number}, loading original URL")
                    driver.get(original_url)
                    time.sleep(2)
                except:
                    pass
            
            return success
        
        # Case 3: Nothing changed
        else:
            logger.warning(f"Button click had no visible effect for document {document_number}")
            return False
    
    except Exception as e:
        logger.error(f"Error processing document {document_number}: {str(e)}")
        
        # Always try to recover to original state
        try:
            # Check if we have new tabs to close
            current_handles = driver.window_handles
            if len(current_handles) > len(original_handles):
                # Close any new tabs that were opened
                for handle in current_handles:
                    if handle != original_handle and handle in driver.window_handles:
                        try:
                            driver.switch_to.window(handle)
                            driver.close()
                        except:
                            logger.warning(f"Failed to close extra tab during error recovery")
                
                # Make sure we're on the original tab
                if original_handle in driver.window_handles:
                    driver.switch_to.window(original_handle)
            
            # If we navigated away, go back to original URL
            if driver.current_url != original_url:
                driver.get(original_url)
                time.sleep(2)
        except Exception as recovery_error:
            logger.error(f"Error during recovery: {str(recovery_error)}")
            # Last resort - try to get back to original URL
            try:
                driver.get(original_url)
                time.sleep(2)
            except:
                pass
        
        return False