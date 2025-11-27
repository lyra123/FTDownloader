import aiohttp
import asyncio
import re
import os
import csv
import json
import sys
from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm
from colorama import Fore, init
import time

# Maximum number of concurrent downloads in bulk mode (default)
DEFAULT_CONCURRENT_DOWNLOADS = 3

init(autoreset=True)

def clean_title(title: str) -> str:
    return re.sub(r'\s*FapTap\s*', '', title).strip()

def safe_filename(name: str) -> str:
    return re.sub(r'[\/\\\:\*\?\"\<\>\|\']', '', name).strip()

def log_failed_download(url: str, output_dir: str = "."):
    log_file = os.path.join(output_dir, "failed_video_downloads.txt")
    with open(log_file, "a") as f:
        f.write(url + "\n")

def log_debug(message: str, output_dir: str = "."):
    log_file = os.path.join(output_dir, "debug.txt")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Failed to write to debug log: {e}")

async def download_file(session, url, filename=None, show_progress=True):
    if not filename:
        filename = url.split("/")[-1]
    
    output_dir = os.path.dirname(filename) if filename else "."
    if not output_dir:
        output_dir = "."
        
    basename = os.path.basename(filename)
    log_debug(f"Starting download: {url} -> {basename}", output_dir)
        
    try:
        async with session.get(url) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            block_size = 65536  
            downloaded = 0
            
            start_time = time.time()
            last_update_time = 0
            
            with open(filename, 'wb') as f:
                async for chunk in r.content.iter_chunked(block_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    
                    if (now - last_update_time) >= 5.0: # Log every 5 seconds
                        elapsed = now - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        percent = (downloaded / total_size * 100) if total_size else 0
                        
                        if speed < 1024:
                            speed_str = f"{speed:.2f} B/s"
                        elif speed < 1024*1024:
                            speed_str = f"{speed/1024:.2f} KB/s"
                        else:
                            speed_str = f"{speed/1024/1024:.2f} MB/s"
                            
                        log_msg = f"{basename}: {percent:.2f}% ({downloaded}/{total_size}) - {speed_str}"
                        log_debug(log_msg, output_dir)
                        
                        if show_progress and total_size:
                            sys.stdout.write(f"\r{Fore.CYAN}{basename}: {percent:.2f}% [{downloaded}/{total_size} bytes] - {speed_str}")
                            sys.stdout.flush()
                        
                        last_update_time = now

            if show_progress and total_size:
                percent = downloaded / total_size * 100
                sys.stdout.write(f"\r{Fore.CYAN}{basename}: {percent:.2f}% [{downloaded}/{total_size} bytes]\n")
                sys.stdout.flush()

            if show_progress:
                print(f"{Fore.GREEN}✅ Finished downloading {basename}")
            
            log_debug(f"Finished downloading {basename}", output_dir)
            
    except Exception as e:
        log_debug(f"Error downloading {basename}: {str(e)}", output_dir)
        raise e
        
    return filename

def csv_to_funscript(csv_file, output_file, show_message=True):
    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        rows = list(reader)
    
    if rows[0][0] == 'time' and rows[0][1] == 'value':
        rows = rows[1:]  
    
    funscript_data = {
        "version": "1.1",
        "inverted": False,
        "range": 100,
        "actions": [{"pos": int(row[1]), "at": int(row[0])} for row in rows]
    }

    with open(output_file, 'w') as f:
        json.dump(funscript_data, f, separators=(',', ':'))
    if show_message:
        print(f"{Fore.GREEN}✅ Converted {csv_file} to {output_file}")

async def process_video(session, video_id, auto_download, highest_quality, show_progress=True, output_dir="."):
    api_url = f"https://faptap.net/api/videos/{video_id}"
    source_url = f"https://faptap.net/v/{video_id}"
    
    status = {
        'title': None,
        'funscript': False,
        'video': False,
        'quality': None,
        'error': None
    }

    if show_progress:
        print(f"{Fore.YELLOW}\n[INFO] Fetching metadata for video ID: {video_id}...\n")
    
    log_debug(f"Fetching metadata for video ID: {video_id}", output_dir)
    
    async with session.get(api_url) as resp:
        if resp.status != 200:
            error_msg = f"Failed to fetch metadata ({resp.status})"
            if show_progress:
                print(f"{Fore.RED}❌ {error_msg}")
            status['error'] = error_msg
            log_failed_download(source_url, output_dir)
            return status
        data = (await resp.json())['data']

    raw_title = data.get('name', video_id)
    title = safe_filename(clean_title(raw_title))
    status['title'] = title

    script_url = f"https://faptap.net/api/assets/{data['script']['url']}"
    csv_file = os.path.join(output_dir, f"{title}.csv")
    funscript_file = os.path.join(output_dir, f"{title}.funscript")

    if show_progress:
        print(f"{Fore.CYAN}Downloading Funscript for {title}...")
    
    try:
        await download_file(session, script_url, csv_file, show_progress)
        csv_to_funscript(csv_file, funscript_file, show_progress)
        os.remove(csv_file)
        status['funscript'] = True
    except Exception as e:
        status['error'] = f"Funscript download failed: {str(e)}"
        if show_progress:
            print(f"{Fore.RED}❌ {status['error']}")
        return status

    video_iframe_url = data.get('stream_url_selfhosted')

    if not video_iframe_url:
        if show_progress:
            print(f"{Fore.YELLOW}⚠️ No self-hosted video source found. Only the Funscript has been downloaded.")
        log_failed_download(source_url, output_dir)
        return status

    async with session.get(video_iframe_url) as iframe_resp:
        iframe_html = await iframe_resp.text()

    mp4_matches = re.findall(r'https://[^"]+/play_(\d+)p\.mp4', iframe_html)
    qualities = sorted(list(set(mp4_matches)))

    if not qualities:
        error_msg = "No downloadable video found"
        if show_progress:
            print(f"{Fore.RED}❌ {error_msg}")
        status['error'] = error_msg
        log_failed_download(source_url, output_dir)
        return status
        
    if auto_download:
        selected_quality = qualities[-1]
        status['quality'] = f"{selected_quality}p"
        if show_progress:
            print(f"{Fore.YELLOW}Auto-selected video quality: {selected_quality}p")

        mp4_url_match = re.search(rf'(https://[^"]+/play_{selected_quality}p\.mp4)', iframe_html)
        if mp4_url_match:
            mp4_url = mp4_url_match.group(1)
            video_file = os.path.join(output_dir, f"{title}.mp4")
            try:
                await download_file(session, mp4_url, video_file, show_progress)
                status['video'] = True
            except Exception as e:
                status['error'] = f"Video download failed: {str(e)}"
                if show_progress:
                    print(f"{Fore.RED}❌ {status['error']}")
        else:
            error_msg = "Failed to find video URL"
            if show_progress:
                print(f"{Fore.RED}❌ {error_msg}")
            status['error'] = error_msg
            log_failed_download(source_url, output_dir)
        return status
        
    manual_download = input(f"{Fore.YELLOW}Self-hosted video found for {title}. Download video? (Y/N): ").strip().lower() == 'y'
    if manual_download:
        selected_quality = qualities[-1]
        status['quality'] = f"{selected_quality}p"
        mp4_url_match = re.search(rf'(https://[^"]+/play_{selected_quality}p\.mp4)', iframe_html)
        if mp4_url_match:
            mp4_url = mp4_url_match.group(1)
            video_file = os.path.join(output_dir, f"{title}.mp4")
            try:
                await download_file(session, mp4_url, video_file, show_progress)
                status['video'] = True
            except Exception as e:
                status['error'] = f"Video download failed: {str(e)}"
                if show_progress:
                    print(f"{Fore.RED}❌ {status['error']}")
        else:
            error_msg = "Failed to find video URL"
            if show_progress:
                print(f"{Fore.RED}❌ {error_msg}")
            status['error'] = error_msg
            log_failed_download(source_url, output_dir)
    
    return status

async def bulk_download(session, file_name, auto_download, highest_quality, max_concurrent, output_dir):
    with open(file_name, 'r') as f:
        links = [line.strip() for line in f if line.strip()]

    total = len(links)
    completed = 0
    lock = asyncio.Lock()

    print(f"{Fore.CYAN}\n[INFO] Starting bulk download from {file_name}...\n")
    print(f"{Fore.YELLOW}[INFO] Processing {total} videos with {max_concurrent} concurrent downloads\n")
    
    log_debug(f"Starting bulk download from {file_name}. Total: {total}, Concurrent: {max_concurrent}", output_dir)
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    pbar = tqdm(bar_format='{desc}', desc="In Progress")
    
    async def heartbeat():
        dots = 1
        while True:
            pbar.set_description(f"In Progress {'.' * dots}")
            dots = (dots % 3) + 1
            await asyncio.sleep(0.5)

    heartbeat_task = asyncio.create_task(heartbeat())

    async def process_with_semaphore(link, index):
        nonlocal completed
        async with semaphore:
            match = re.search(r'/v/(\d+)', link)
            if match:
                video_id = match.group(1)
                tqdm.write(f"{Fore.CYAN}[{index + 1}/{total}] Processing: {video_id}...")
                
                status = await process_video(session, video_id, auto_download, highest_quality, show_progress=False, output_dir=output_dir)
                
                async with lock:
                    completed += 1
                    
                    # Build status line
                    if status and status.get('title'):
                        title = status['title'][:50] + '...' if len(status['title']) > 50 else status['title']
                        parts = [f"{Fore.GREEN}[{completed}/{total}] {title}"]
                        
                        if status.get('quality'):
                            parts.append(f"{Fore.YELLOW}{status['quality']}")
                        
                        status_items = []
                        if status.get('funscript'):
                            status_items.append(f"{Fore.GREEN}✅ Funscript")
                        if status.get('video'):
                            status_items.append(f"{Fore.GREEN}✅ Video")
                        else:
                            status_items.append(f"{Fore.RED}❌ Video")
                        
                        if status.get('error'):
                            status_items.append(f"{Fore.RED}❌ {status['error']}")
                        
                        if status_items:
                            parts.append(" | ".join(status_items))
                        
                        tqdm.write(" - ".join(parts))
                    else:
                        tqdm.write(f"{Fore.RED}[{completed}/{total}] Failed to process video {video_id}")
            else:
                async with lock:
                    completed += 1
                    tqdm.write(f"{Fore.RED}[{completed}/{total}] Invalid link format: {link}")
    
    try:
        await asyncio.gather(*[process_with_semaphore(link, i) for i, link in enumerate(links)])
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        pbar.close()

    print(f"{Fore.GREEN}\n✅ Bulk download complete! {completed}/{total} videos processed successfully.")

def get_output_directory():
    """Prompt user for output directory and validate it exists."""
    while True:
        output_dir = input(f"{Fore.CYAN}Enter output directory (press Enter for current directory): ").strip()
        
        if not output_dir:
            return "."
        
        # Expand user home directory if ~ is used
        output_dir = os.path.expanduser(output_dir)
        
        if os.path.exists(output_dir) and os.path.isdir(output_dir):
            return output_dir
        else:
            print(f"{Fore.RED}❌ Directory does not exist: {output_dir}")
            create = input(f"{Fore.YELLOW}Create this directory? (Y/N): ").strip().lower()
            if create == 'y':
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    print(f"{Fore.GREEN}✅ Created directory: {output_dir}")
                    return output_dir
                except Exception as e:
                    print(f"{Fore.RED}❌ Failed to create directory: {e}")
            else:
                print(f"{Fore.YELLOW}Please enter a valid directory path.")

def get_concurrent_count():
    """Prompt user for number of concurrent downloads."""
    while True:
        count_input = input(f"{Fore.CYAN}Number of concurrent downloads (default {DEFAULT_CONCURRENT_DOWNLOADS}): ").strip()
        
        if not count_input:
            return DEFAULT_CONCURRENT_DOWNLOADS
        
        try:
            count = int(count_input)
            if count < 1:
                print(f"{Fore.RED}❌ Must be at least 1")
                continue
            if count > 10:
                print(f"{Fore.YELLOW}⚠️ Warning: High concurrency may cause issues. Recommended maximum is 10.")
                confirm = input(f"{Fore.YELLOW}Continue with {count}? (Y/N): ").strip().lower()
                if confirm != 'y':
                    continue
            return count
        except ValueError:
            print(f"{Fore.RED}❌ Please enter a valid number")

async def main():
    print(f"{Fore.MAGENTA}\n\nWelcome to the FapTap Video Downloader!\n{'='*40}\n")
    choice = input(f"{Fore.CYAN}Enter 'bulk' for bulk download, or provide a FapTap video URL: ").strip()

    # Set a timeout for requests. 
    # total=None disables the total timeout (important for large files).
    # sock_read=1800 sets a 30-minute timeout for reading data from the socket.
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=1800)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if choice == 'bulk':
            output_dir = get_output_directory()
            max_concurrent = get_concurrent_count()
            auto_download = input(f"{Fore.CYAN}Auto-download video if available? (Y/n): ").strip().lower() != 'n'
            if auto_download:
                print(f"{Fore.YELLOW}Auto-download is enabled.")
            highest_quality = True
            await bulk_download(session, 'bulk.txt', auto_download, highest_quality, max_concurrent, output_dir)

        else:
            match = re.search(r'/v/(\d+)', choice)
            if not match:
                print(f"{Fore.RED}❌ Invalid FapTap URL format.")
                return

            output_dir = get_output_directory()
            video_id = match.group(1)
            highest_quality = True
            await process_video(session, video_id, False, highest_quality, output_dir=output_dir)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"{Fore.RED}❌ Program interrupted.")
