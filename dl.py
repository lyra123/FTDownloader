import aiohttp
import asyncio
import re
import os
import pandas as pd
import json
from tqdm.asyncio import tqdm_asyncio
from colorama import Fore, Style, init
import textwrap
import time

init(autoreset=True)

def clean_title(title: str) -> str:
    """Remove FapTap branding from title."""
    return re.sub(r'\s*FapTap\s*', '', title).strip()

def safe_filename(name: str) -> str:
    """Remove illegal filename characters."""
    return re.sub(r'[\/\\\:\*\?\"\<\>\|\']', '', name).strip()

def log_failed_download(url: str):
    """Append failed video links to failed_video_downloads.txt."""
    with open("failed_video_downloads.txt", "a") as f:
        f.write(url + "\n")

async def download_file(session, url, filename=None):
    if not filename:
        filename = url.split("/")[-1]
        
    async with session.get(url) as r:
        r.raise_for_status()
        total_size = int(r.headers.get('content-length', 0))
        block_size = 1024
        downloaded = 0

        last_update_time = 0
        
        with open(filename, 'wb') as f:
            async for chunk in r.content.iter_chunked(block_size):
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if total_size and (now - last_update_time) >= 0.2:
                    percent = downloaded / total_size * 100
                    print(f"\r{Fore.CYAN}{filename}: {percent:.2f}% [{downloaded}/{total_size} bytes]", end='')
                    last_update_time = now

        if total_size:
            percent = downloaded / total_size * 100
            print(f"\r{Fore.CYAN}{filename}: {percent:.2f}% [{downloaded}/{total_size} bytes]")

        print(f"\n{Fore.GREEN}✅ Finished downloading {filename}")
    return filename

def csv_to_funscript(csv_file, output_file):
    df = pd.read_csv(csv_file, header=None)
    if df.iloc[0, 0] == 'time' and df.iloc[0, 1] == 'value':
        df = pd.read_csv(csv_file)
    else:
        df.columns = ['time', 'value']

    funscript_data = {
        "version": "1.1",
        "inverted": False,
        "range": 100,
        "actions": []
    }

    for _, row in df.iterrows():
        funscript_data["actions"].append({"pos": int(row['value']), "at": int(row['time'])})

    with open(output_file, 'w') as f:
        json.dump(funscript_data, f, indent=4)
    print(f"{Fore.GREEN}✅ Converted {csv_file} to {output_file}")

async def process_video(session, video_id, auto_download, highest_quality):
    api_url = f"https://faptap.net/api/videos/{video_id}"
    source_url = f"https://faptap.net/v/{video_id}"

    print(f"{Fore.YELLOW}\n[INFO] Fetching metadata for video ID: {video_id}...\n")
    async with session.get(api_url) as resp:
        if resp.status != 200:
            print(f"{Fore.RED}❌ Failed to fetch metadata ({resp.status})")
            log_failed_download(source_url)
            return
        data = (await resp.json())['data']

    raw_title = data.get('name', video_id)
    title = safe_filename(clean_title(raw_title))

    script_url = f"https://faptap.net/api/assets/{data['script']['url']}"
    csv_file = f"{title}.csv"
    funscript_file = f"{title}.funscript"

    print(f"{Fore.CYAN}Downloading Funscript for {title}...")
    await download_file(session, script_url, csv_file)

    csv_to_funscript(csv_file, funscript_file)
    os.remove(csv_file)

    video_iframe_url = data.get('stream_url_selfhosted')

    if not video_iframe_url:
        print(f"{Fore.YELLOW}⚠️ No self-hosted video source found. Only the Funscript has been downloaded.")
        log_failed_download(source_url)
        return

    async with session.get(video_iframe_url) as iframe_resp:
        iframe_html = await iframe_resp.text()

    mp4_matches = re.findall(r'https://[^"]+/play_(\d+)p\.mp4', iframe_html)
    qualities = sorted(list(set(mp4_matches)))

    if not qualities:
        print(f"{Fore.RED}❌ No downloadable video found for {title}.")
        log_failed_download(source_url)
        return
        
    if auto_download:
        selected_quality = qualities[-1]  # highest
        print(f"{Fore.YELLOW}Auto-selected video quality: {selected_quality}p")

        mp4_url_match = re.search(rf'(https://[^"]+/play_{selected_quality}p\.mp4)', iframe_html)
        if mp4_url_match:
            mp4_url = mp4_url_match.group(1)
            video_file = f"{title}.mp4"
            await download_file(session, mp4_url, video_file)
        else:
            print(f"{Fore.RED}❌ Failed to download video for {title}.")
            log_failed_download(source_url)
        return
        
    manual_download = input(f"{Fore.YELLOW}Self-hosted video found for {title}. Download video? (Y/N): ").strip().lower() == 'y'
    if manual_download:
        selected_quality = qualities[-1]
        mp4_url_match = re.search(rf'(https://[^"]+/play_{selected_quality}p\.mp4)', iframe_html)
        if mp4_url_match:
            mp4_url = mp4_url_match.group(1)
            video_file = f"{title}.mp4"
            await download_file(session, mp4_url, video_file)
        else:
            print(f"{Fore.RED}❌ Failed to download video for {title}.")
            log_failed_download(source_url)

async def bulk_download(session, file_name, auto_download, highest_quality):
    with open(file_name, 'r') as f:
        links = f.readlines()

    print(f"{Fore.CYAN}\n[INFO] Starting bulk download from {file_name}...\n")
    for link in tqdm_asyncio(links, desc="Downloading from bulk.txt", ncols=100):
        link = link.strip()
        if not link:
            continue

        match = re.search(r'/v/(\d+)', link)
        if match:
            video_id = match.group(1)
            await process_video(session, video_id, auto_download, highest_quality)
        else:
            print(f"{Fore.RED}❌ Invalid link format: {link}")

async def main():
    print(f"{Fore.MAGENTA}\n\nWelcome to the FapTap Video Downloader!\n{'='*40}\n")
    choice = input(f"{Fore.CYAN}Enter 'bulk' for bulk download, or provide a FapTap video URL: ").strip()

    async with aiohttp.ClientSession() as session:
        if choice == 'bulk':
            auto_download = input(f"{Fore.CYAN}Auto-download video if available? (Y/N): ").strip().lower() == 'y'
            if auto_download:
                print(f"{Fore.YELLOW}Auto-download is enabled.")
            highest_quality = True
            await bulk_download(session, 'bulk.txt', auto_download, highest_quality)

        else:
            match = re.search(r'/v/(\d+)', choice)
            if not match:
                print(f"{Fore.RED}❌ Invalid FapTap URL format.")
                return

            video_id = match.group(1)
            highest_quality = True
            await process_video(session, video_id, False, highest_quality)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"{Fore.RED}❌ Program interrupted.")
