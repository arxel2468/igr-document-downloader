
# IGR Maharashtra Property Document Automation Tool

A powerful automation tool to fetch property documents from the Maharashtra IGR (Inspector General of Registration) website.

## Overview

This script automates the process of retrieving property documents from the Maharashtra IGR service website. It handles:

1.  Navigating the IGR website interface
2.  Selecting location data (district, tahsil, village)
3.  Solving CAPTCHA challenges automatically using OCR
4.  Searching for property records by property number and year
5.  Downloading and processing property documents
6.  Providing a REST API interface for integration with other applications

## Features

-   Advanced CAPTCHA solving using multiple image processing techniques
-   Multi-platform support (Windows, Linux, macOS)
-   REST API for easy integration
-   Robust error handling and retry mechanisms
-   Detailed logging for troubleshooting
-   Support for concurrent document retrieval jobs

## Prerequisites

### Software Requirements

-   Python 3.7+
-   Chrome browser
-   Tesseract OCR
-   wkhtmltopdf

### Python Dependencies

```
selenium
webdriver-manager
pytesseract
pillow
pdfkit
flask
flask-cors
pytest

```

## Installation

1.  Clone the repository:
    
    ```
    git clone https://github.com/arxel2468/igr-document-downloader
    cd igr-document-downloader
    
    ```
    
2.  Install Python dependencies:
    
    ```
    pip install -r requirements.txt
    
    ```
    
3.  Install Tesseract OCR:
    
    -   **Windows**: Download and install from  [Tesseract GitHub](https://github.com/UB-Mannheim/tesseract/wiki)
    -   **Linux**:  `sudo apt-get install tesseract-ocr`
    -   **macOS**:  `brew install tesseract`
4.  Install wkhtmltopdf:
    
    -   **Windows**: Download and install from  [wkhtmltopdf website](https://wkhtmltopdf.org/downloads.html)
    -   **Linux**:  `sudo apt-get install wkhtmltopdf`
    -   **macOS**:  `brew install wkhtmltopdf`
5.  Ensure the location data file is in place:
    
    -   Make sure  `maharashtra_locations_final.json`  is in the root directory

## Configuration

The script automatically detects your operating system and configures paths for:

-   Tesseract OCR executable
-   wkhtmltopdf executable

You may need to adjust these paths in the script if your installation locations differ from the defaults.

## Usage

### Running the API Server

```
python selenium_automation.py

```

The API server will start and listen for requests on port 5000 by default.

### Running Tests
Execute the test suite by running:

```

pytest test.py -v

```

For more detailed output with logging information:

```

pytest test.py -v --log-cli-level=INFO

```

### API Endpoints

-   **POST /submit_job**: Submit a new document retrieval job
    
    ```json
    {
      "year": "2023",
      "district": "Pune",
      "tahsil": "Haveli",
      "village": "Kothrud",
      "property_no": "123456"
    }
    
    ```
    
-   **GET /job_status/{job_id}**: Check the status of a job
    
-   **GET /download/{job_id}**: Download the retrieved documents as a ZIP file
    

## Customization

-   For headless operation (server environments), uncomment the headless options in the  `run_automation`  function
-   Adjust CAPTCHA solving parameters in the  `solve_captcha_with_multiple_techniques`  function
-   Modify logging levels in the logging configuration section

## Troubleshooting

-   Check the  `igr_automation.log`  file for detailed logs
-   Examine debug screenshots in the job's debug directory
-   For CAPTCHA issues, review the processed CAPTCHA images in the  `temp_captchas`  directory

## Notes

-   The script creates temporary directories for CAPTCHA processing and debugging
-   The automation may need adjustments if the IGR website structure changes
-   For production use, consider implementing rate limiting to avoid IP blocking

## Limitations

-   CAPTCHA solving accuracy depends on the quality of the CAPTCHA images
-   The IGR website may have periodic maintenance windows when the service is unavailable
-   Some property documents may require additional verification steps not covered by this automation
