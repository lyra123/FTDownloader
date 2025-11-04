import aiohttp
import asyncio
import re
import os
import pandas as pd
import json
from tqdm.asyncio import tqdm_asyncio

# Helper to clean FapTap titles
def clean_title(title: str) -> str:
    return re.sub(r'\s*FapTap\s*', '', title).strip()

async def download_file(session, url, filename=None):
    if not filename:
        filename = url.split("/")[-1]
    async with session.get(url) as r:
        r.raise_for_status()
        total_size = int(r.headers.get('content-length', 0))
        block_size = 1024
        downloaded = 0
        with open(filename, 'wb') as f:
            async for chunk in r.content.iter_chunked(block_size):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size:
                    percent = downloaded / total_size * 100
                    print(f"\r{filename}: {percent:.2f}% [{downloaded}/{total_size} bytes]", end='')
        print(f"\n✅ Finished downloading {filename}")
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
        funscript_data["actions"].append(
            {"pos": int(row['value']), "at": int(row['time'])}
        )

    with open(output_file, 'w') as f:
        json.dump(funscript_data, f, indent=4)
    print(f"✅ Converted {csv_file} to {output_file}")

async def main():
    faptap_url = input("Enter FapTap video URL: ").strip()
    match = re.search(r'/v/(\d+)', faptap_url)
    if not match:
        print("❌ Could not extract video ID from URL.")
        return
    video_id = match.group(1)

    api_url = f"https://faptap.net/api/videos/{video_id}"
    print("Fetching video metadata...")
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            if resp.status != 200:
                print(f"❌ Failed to fetch metadata ({resp.status})")
                return
            data = (await resp.json())['data']

        title = clean_title(data.get('name', video_id))
        script_url = f"https://faptap.net/api/assets/{data['script']['url']}"
        csv_file = f"{title}.csv"
        funscript_file = f"{title}.funscript"

        # Download CSV
        await download_file(session, script_url, csv_file)

        # Convert CSV -> Funscript
        csv_to_funscript(csv_file, funscript_file)

        # Remove original CSV
        os.remove(csv_file)

        # Handle self-hosted video
        video_iframe_url = data.get('stream_url_selfhosted')
        if video_iframe_url:
            choice = input("Self-hosted video found. Download video? (Y/N): ").strip().lower()
            if choice == 'y':
                print("Fetching iframe page...")
                async with session.get(video_iframe_url) as iframe_resp:
                    iframe_html = await iframe_resp.text()

                mp4_matches = re.findall(r'https://[^"]+/play_(\d+)p\.mp4', iframe_html)
                qualities = sorted(list(set(mp4_matches)))
                if not qualities:
                    print("❌ No downloadable video found.")
                    return

                print(f"Available qualities: {', '.join(qualities)}p")
                selected = input(f"Which quality do you want? [{qualities[-1]}]: ").strip()
                if selected not in qualities:
                    selected = qualities[-1]

                mp4_url_match = re.search(rf'(https://[^"]+/play_{selected}p\.mp4)', iframe_html)
                if mp4_url_match:
                    mp4_url = mp4_url_match.group(1)
                    video_file = f"{title}.mp4"
                    await download_file(session, mp4_url, video_file)
                else:
                    print("❌ Selected quality not available.")
        else:
            print("⚠️ No self-hosted video source found. Only the Funscript has been downloaded.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Allow Ctrl+C to exit cleanly
    input("\nPress any key to exit...")