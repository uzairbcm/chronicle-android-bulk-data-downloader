# Chronicle Bulk Data Downloader

WORK IN PROGRESS, please feel free to open an issue or email at uzair.alam@bcm.edu if you experience any issues.

A tool for downloading Chronicle data in bulk. 

Not affiliated with Chronicle or GetMethodic, please visit them here: https://getmethodic.com/

**Please do not lower or remove the rate limiting.**

## About the Application

This application provides a GUI interface for downloading data from Chronicle studies, with features for:

- Downloading various types of Chronicle data (raw usage events, preprocessed data, surveys, raw iOS sensor data, time use diaries)
- Filtering participants by ID (inclusive or exclusive)
- Organizing and archiving downloaded data
- Optionally deleting zero byte files to ignore empty files

## Usage

1. Select the download folder
2. Paste the token you copied from the Chronicle GetMethodic website, located here:
   
![Authorization Token Copy](./authorization_token_copy_location.png)

4. Enter a valid Chronicle study ID
5. Optionally provide participant IDs to filter (separated by commas)
   - a. Exclusive filtering (default) excludes the IDs that you list
   - b. Inclusive filtering (when checkbox is checked) only downloads the IDs that you listed
4. Check which data types to download
5. Optionally check if you want to delete zero byte files
6. Click the "Run" button
