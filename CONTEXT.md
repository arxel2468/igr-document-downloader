# Updated Project Context

## Project Overview
This project automates the bulk downloading of Index-II documents from the Maharashtra government website (igrmaharashtra.gov.in). It handles CAPTCHA solving, form submission, pagination through search results, and document retrieval.

## Key Features
- **Bulk Document Processing:** Processes multiple property details for batch retrieval
- **Automated CAPTCHA Solving:** Uses Tesseract OCR for image-based CAPTCHA recognition
- **Postback Handling:** Manages ASP.NET's `__doPostBack` JavaScript functions for dynamic content
- **Pagination Navigation:** Handles multi-page results with up to 10 items per page
- **New Window Handling:** Switches between browser tabs to fetch and save PDFs
- **Error Handling & Retries:** Implements robust exception handling with retry mechanisms

## Project Structure
```
project_root/
│-- app.py                 # Handles jobs, API calls, and cleanup operations
│-- main.py                # Entry point for the automation script
│-- automation.py          # Contains web scraping, form filling, and result navigation logic
│-- captcha_solver.py      # Handles CAPTCHA extraction and solving
│-- document_processor.py  # Manages document retrieval and downloading
│-- requirements.txt       # Lists all necessary dependencies
│-- CONTEXT.md             # This file (explains project purpose and structure)
│-- README.md              # Guide on how to install and run the project
```

## Technical Details

### Search Results Handling
- Each results page contains up to 10 items
- IndexII buttons use JavaScript postback: `onclick="javascript:__doPostBack('RegistrationGrid','indexII$0')"`
- Button indices range from `indexII$0` to `indexII$9` on each page

### Pagination Implementation
- Current page shown as `<span>1</span>`
- Other pages as clickable links: `<a href="javascript:__doPostBack('RegistrationGrid','Page$2')" style="color:Black;">2</a>`
- Special "..." navigation element: `<a href="javascript:__doPostBack('RegistrationGrid','Page$11')" style="color:Black;">...</a>`

### Workflow
1. Fill and submit search form
2. Process search results table that appears below the form
3. For each result, click the corresponding "IndexII" button
4. Handle new window/tab that opens with the document
5. Download the document
6. Navigate through all result pages using pagination controls
7. Repeat until all documents are processed

## Implementation Focus
- **automation.py**: Handles form filling, result table navigation, and pagination
- **document_processor.py**: Manages document retrieval after "IndexII" button click
