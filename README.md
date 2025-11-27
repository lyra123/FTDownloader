# FapTap Video Downloader

A robust Python script for downloading videos and funscripts from FapTap.net. Supports both single video downloads and bulk downloading from a list.

## Features

-   **Single & Bulk Download**: Download individual videos or process a list of URLs.
-   **Auto-Download**: Option to automatically download the highest quality video available.
-   **Funscript Support**: Automatically downloads and converts scripts to `.funscript` format. Now 63.7% smaller filesizes.
-   **Smart Logging**: 
    -   Detailed `debug.txt` log with download speeds and progress.
    -   `failed_video_downloads.txt` tracks any failed URLs.
-   **Visual Feedback**:
    -   Clean console output with color-coded status.
    -   "In Progress..." heartbeat indicator during bulk downloads.
-   **Reliability**:
    -   Network timeouts to prevent hangs.
    -   Automatic retries and error handling.

## Installation

1.  **Install Python 3.8+**
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

Run the script:
```bash
python dl.py
```

### Modes

1.  **Single Video**: Paste a FapTap video URL when prompted.
2.  **Bulk Download**:
    -   Create a text file (e.g., `bulk.txt`) with one FapTap URL per line.
    -   Enter `bulk` when prompted.
    -   Follow the prompts for output directory and concurrency.

### Output Structure

Files are saved to your specified output directory:
-   `[Title].mp4`: The video file.
-   `[Title].funscript`: The synchronized script (compact).
-   `debug.txt`: Detailed log of operations and download stats.
-   `failed_video_downloads.txt`: List of URLs that failed to process.

## Troubleshooting

-   **Hangs**: If a download seems stuck, check `debug.txt` for the latest progress and speed. The script has a 30-minute timeout to prevent infinite hangs.
-   **Missing Videos**: If a video is not found, the status will show `❌ Video`. Check `failed_video_downloads.txt` for a list of these URLs.
-   **Issues**: If you encounter bugs, please check `debug.txt` and include relevant sections when reporting the issue.
