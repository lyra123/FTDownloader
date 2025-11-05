# FTDownloader
A private script and video downloader for FapTap, built in Python. I suggest placing this file into its own folder because downloaded content will appear next to it in the same directory.

This is tested to run on the latest version of Python with requirements installed. 

Usage (python):
```sh
pip install -r requirements.txt
python dl.py
```
For bulk downloading, you will need to create a 'bulk.txt' file in same directory as .exe or where you execute the python script from. Links should be line separated like in the example provided. When prompted for a FapTap link, type 'bulk' to access this feature.

Auto-download (Y/N) - choose if you want videos to automatically download from the bulk list (highest quality available). If you choose no, you will have to manually prompt yes or no for each link IF a video is found.
