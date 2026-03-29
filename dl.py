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

    # 1. Fetch available sources from FapTap's internal API for better accuracy
    bunny_sources_url = f"https://faptap.net/api/videos/{video_id}/bunny-sources"
    available_qualities = []
    
    log_debug(f"Fetching authoritative sources from: {bunny_sources_url}", output_dir)
    
    try:
        async with session.get(bunny_sources_url) as bunny_resp:
            if bunny_resp.status == 200:
                bunny_data = await bunny_resp.json()
                sources = bunny_data.get('data', [])
                for source in sources:
                    q = source.get('quality')
                    if q:
                        available_qualities.append({
                            'quality': int(q),
                            'url': source.get('url'),
                            'format': source.get('format')
                        })
    except Exception as e:
        log_debug(f"Failed to fetch bunny-sources: {e}", output_dir)

    # 2. Fallback to scraping iframe if API fails or returns no sources
    if not available_qualities:
        video_iframe_url = data.get('stream_url_selfhosted')
        if video_iframe_url:
            async with session.get(video_iframe_url) as iframe_resp:
                iframe_html = await iframe_resp.text()

            base_url_match = re.search(r'(https://[^"]+)/play_\d+p\.mp4', iframe_html)
            base_video_url = base_url_match.group(1) if base_url_match else None
            
            # Try playlist.m3u8 for discovery
            if base_video_url:
                try:
                    async with session.get(f"{base_video_url}/playlist.m3u8", headers={'Referer': 'https://faptap.net/'}) as playlist_resp:
                        if playlist_resp.status == 200:
                            playlist_text = await playlist_resp.text()
                            m3u8_matches = re.findall(r'(\d+)p/video\.m3u8', playlist_text)
                            for q in set(m3u8_matches):
                                available_qualities.append({
                                    'quality': int(q),
                                    'url': f"{base_video_url}/{q}p/video.m3u8",
                                    'format': 'hls'
                                })
                except Exception as e:
                    log_debug(f"Failed to scrape playlist.m3u8: {e}", output_dir)
            
            # Last resort: direct .mp4 matches in iframe HTML
            if not available_qualities:
                mp4_matches = re.findall(r'https://[^"]+/play_(\d+)p\.mp4', iframe_html)
                for q in set(mp4_matches):
                    available_qualities.append({
                        'quality': int(q),
                        'url': f"{base_video_url}/play_{q}p.mp4" if base_video_url else None,
                        'format': 'mp4'
                    })

    # Filter and sort qualities (highest first)
    preferred_tiers = [1080, 720, 480, 360, 240]
    available_qualities = [q for q in available_qualities if q['quality'] in preferred_tiers]
    available_qualities.sort(key=lambda x: x['quality'], reverse=True)

    if not available_qualities:
        error_msg = "No downloadable video found (FT Server)"
        if show_progress:
            print(f"{Fore.RED}❌ {error_msg}")
        status['error'] = error_msg
        log_failed_download(source_url, output_dir)
        return status

    async def try_download_quality(q_info):
        selected_quality = q_info['quality']
        status['quality'] = f"{selected_quality}p"
        
        # Determine the direct MP4 URL to try first (standard FapTap pattern)
        # Even if the API says HLS, we check for a direct MP4 as it's faster to download
        mp4_url = q_info['url'] if q_info['format'] == 'mp4' else None
        if not mp4_url and q_info['url']:
            # Try to derive the .mp4 path from the .m3u8 path
            # Pattern: .../{quality}p/video.m3u8 -> .../play_{quality}p.mp4
            mp4_url = q_info['url'].split('/video.m3u8')[0].rsplit('/', 1)[0] + f"/play_{selected_quality}p.mp4"

        video_file = os.path.join(output_dir, f"{title}.mp4")
        
        # Attempt direct MP4 download first
        if mp4_url:
            try:
                log_debug(f"Attempting direct MP4 download: {mp4_url}", output_dir)
                await download_file(session, mp4_url, video_file, show_progress)
                return True
            except Exception as e:
                log_debug(f"Direct MP4 download failed ({selected_quality}p): {e}", output_dir)

        # Fallback to HLS download if MP4 fails or is unavailable
        if q_info['format'] == 'hls' or 'video.m3u8' in q_info['url']:
            try:
                log_debug(f"Attempting HLS download: {q_info['url']}", output_dir)
                if show_progress:
                    print(f"{Fore.YELLOW}Direct MP4 unavailable for {selected_quality}p. Downloading via segments (this may take a moment)...")
                await download_hls(session, q_info['url'], video_file, show_progress)
                return True
            except Exception as e:
                log_debug(f"HLS download failed ({selected_quality}p): {e}", output_dir)
        
        return False

    if auto_download:
        for q_info in available_qualities:
            if await try_download_quality(q_info):
                status['video'] = True
                status['error'] = None
                break
            else:
                status['error'] = f"Failed to download at {q_info['quality']}p"
                if show_progress:
                    print(f"{Fore.RED}⚠️ Failed to download {q_info['quality']}p. Trying next quality...")

        if not status['video']:
            log_failed_download(source_url, output_dir)
        return status

    # Manual Download Mode
    manual_download = input(f"{Fore.YELLOW}Self-hosted video found for {title}. Download video? (Y/N): ").strip().lower() == 'y'
    if manual_download:
        for q_info in available_qualities:
            if await try_download_quality(q_info):
                status['video'] = True
                status['error'] = None
                break
            else:
                status['error'] = f"Failed to download at {q_info['quality']}p"
                if show_progress:
                    print(f"{Fore.RED}⚠️ Failed to download {q_info['quality']}p. Trying next quality...")
                    
        if not status['video']:
            log_failed_download(source_url, output_dir)
    
    return status

async def download_hls(session, playlist_url, output_file, show_progress=True):
    """
    Experimental HLS downloader that fetches segments and joins them.
    Used as fallback when direct .mp4 links are unavailable (common for 1080p).
    """
    base_url = playlist_url.rsplit('/', 1)[0]
    
    async with session.get(playlist_url) as resp:
        if resp.status != 200:
            raise Exception(f"Failed to fetch playlist (HTTP {resp.status})")
        playlist_text = await resp.text()

    # Simple M3U8 segment parser
    segments = [line.strip() for line in playlist_text.splitlines() if line and not line.startswith('#')]
    if not segments:
        raise Exception("No segments found in playlist")

    total_segments = len(segments)
    basename = os.path.basename(output_file)
    
    # Track progress
    pbar = None
    if show_progress:
        pbar = tqdm(total=total_segments, desc=f"{Fore.CYAN}Downloading {basename}", unit="seg")

    # Download segments with a semaphore to limit concurrency
    semaphore = asyncio.Semaphore(10)
    
    async def download_segment(segment_url, index):
        if not segment_url.startswith('http'):
            segment_url = f"{base_url}/{segment_url}"
            
        async with semaphore:
            for attempt in range(3): # Simple retry logic
                try:
                    async with session.get(segment_url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if pbar: pbar.update(1)
                            return index, data
                except Exception:
                    await asyncio.sleep(1)
            raise Exception(f"Failed to download segment {index} after retries")

    # Execute downloads
    tasks = [download_segment(url, i) for i, url in enumerate(segments)]
    results = await asyncio.gather(*tasks)
    
    # Sort results by index to ensure correct order
    results.sort(key=lambda x: x[0])
    
    # Write segments sequentially
    with open(output_file, 'wb') as f:
        for _, segment_data in results:
            f.write(segment_data)

    if pbar:
        pbar.close()
        print(f"{Fore.GREEN}✅ Finished assembling HLS stream: {basename}")


async def bulk_download(session, file_name, auto_download, highest_quality, max_concurrent, output_dir):
    if not os.path.exists(file_name):
        with open(file_name, 'w') as f:
            pass
        print(f"{Fore.YELLOW}[INFO] {file_name} not found. Created an empty one.")
        return

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

                        # Remove link from bulk.txt if successful
                        if status.get('funscript') and (not auto_download or status.get('video')):
                            try:
                                with open(file_name, 'r') as f:
                                    lines = f.readlines()
                                with open(file_name, 'w') as f:
                                    for line_content in lines:
                                        if line_content.strip() != link:
                                            f.write(line_content)
                            except Exception as e:
                                tqdm.write(f"{Fore.RED}Error updating {file_name}: {e}")
                    else:
                        error_reason = status.get('error', 'Unknown error') if status else 'Unknown error'
                        tqdm.write(f"{Fore.RED}[{completed}/{total}] Failed to process video {video_id}: {error_reason}")
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
    while True:
        output_dir = input(f"{Fore.CYAN}Enter output directory (press Enter for current directory): ").strip()
        
        if not output_dir:
            return "."
        
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
