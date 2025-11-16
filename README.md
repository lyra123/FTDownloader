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

When bulk downloading, any videos NOT found will be put into a list (failed_video_downloads.txt). This is created automatically in the same directory as the .exe. The process would then be to look through the video list manually and find them by scouring the internet far and wide, as I cannot automate this. After you have found everything in the list, you can delete that file because it will regenerate when needed for the next bulk command. :)

## Options to run this script
1. **Win/Mac/Linux Users** can run from the source code with python on any machine after installing requirements.
2. **Windows Users** can use the standalone .exe binary provided in releases without installing anything.
3. **Mac Users** can use the standalone .dmg binary provided in releases without installing anything
