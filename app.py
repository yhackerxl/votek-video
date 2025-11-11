from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import yt_dlp
import os
from pathlib import Path
import io
import uuid

app = Flask(__name__)

# NOTE: DOWNLOAD_FOLDER is no longer needed as we are streaming in memory.

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/info", methods=["POST"])
def get_video_info():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        # --- Cookie Logic for Info Fetch ---
        cookie_file = None
        if "youtube.com" in url or "youtu.be" in url:
            cookie_file = 'youtube_cookies.txt'
        elif "instagram.com" in url or "instagr.am" in url:
            cookie_file = 'instagram_cookies.txt'

        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "allow_unplayable_formats": True,
            "format": "bestvideo[ext=mp4][vcodec!=none]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/114.0.0.0 Safari/537.36"
            }
        }
        
        # Add cookiefile only if needed (fixes bot detection)
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []

            for f in info.get("formats", []):
                if not f.get("url"):
                    continue
                if f.get("format_note") == "DASH video" or f.get("format_note") == "DASH audio":
                    continue
                
                is_video = f.get("vcodec") != 'none'
                is_audio = f.get("acodec") != 'none'

                if is_video or is_audio:
                    formats.append({
                        "format_id": f["format_id"],
                        "resolution": f.get("resolution") or f.get("format_note"),
                        "filesize": f.get("filesize"),
                        "ext": f.get("ext"),
                        "vcodec": f.get("vcodec"),
                        "acodec": f.get("acodec"),
                        "format_note": f.get("format_note"),
                        "has_audio": is_audio and is_video,
                    })

            return jsonify({
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "formats": formats
            })

    except Exception as e:
        print("Error in /info:", e)
        # Note: If cookies are missing or invalid, the error will be in str(e)
        return jsonify({"error": str(e)}), 500


@app.route("/download", methods=["POST"])
def download_video():
    data = request.get_json()
    url = data.get("url")
    format_id = data.get("format_id")
    filename = data.get("filename", "video")

    if not url or not format_id:
        return jsonify({"error": "URL and format_id required"}), 400

    try:
        selected_format = format_id
        should_merge = False
        cookie_file = None

        # --- Cookie & Merge Logic for Download ---
        if "youtube.com" in url or "youtu.be" in url:
            selected_format = f"{format_id}+bestaudio"
            should_merge = True
            cookie_file = 'youtube_cookies.txt'
        elif "instagram.com" in url or "instagr.am" in url:
            cookie_file = 'instagram_cookies.txt'
        # For other sites, we let yt-dlp handle it with the selected format_id

        class BytesBufferLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg): print(f"YTDL-Error: {msg}")

        video_buffer = io.BytesIO()

        ydl_opts = {
            "outtmpl": "-", # Output to stdout/buffer
            "format": selected_format,
            "merge_output_format": "mp4",
            "quiet": True,
            "logger": BytesBufferLogger(),
            "allow_unplayable_formats": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/114.0.0.0 Safari/537.36"
            }
        }
        
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        # Configure Postprocessors to pipe to the in-memory buffer
        if should_merge:
             ydl_opts["postprocessors"] = [{
                 'key': 'FFmpegVideoRemuxer',
                 'prefer_ffmpeg': True,
                 'exec': lambda info: [
                     None, 
                     {'out': video_buffer}
                 ],
             }]
        else:
             ydl_opts['outtmpl'] = {'out': video_buffer}


        # 1. Start the download/processing process (in memory)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # 2. Prepare the buffer for reading and streaming
        video_buffer.seek(0)
        
        # 3. Define the generator function for streaming chunks
        def generate():
            chunk_size = 8192
            while True:
                chunk = video_buffer.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        
        # 4. Return the Flask streaming response
        response = Response(
            stream_with_context(generate()),
            # Use 'attachment' to force the browser to download the file
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename}.mp4\"",
                "Content-Type": "video/mp4",
                # Important for streaming large files
                "Transfer-Encoding": "chunked" 
            }
        )
        return response

    except Exception as e:
        print("Error during streaming download:", e)
        # Detailed error for debugging failed downloads/auth issues
        return jsonify({"error": f"Download failed. Check URL or cookies. Error: {str(e)}"}), 500


if __name__ == "__main__":
    # Use gunicorn in production
    app.run(debug=True, port=5000)