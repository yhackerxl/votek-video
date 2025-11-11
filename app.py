from flask import Flask, render_template, request, send_file, jsonify
# New imports for streaming
from flask import Response, stream_with_context
import yt_dlp
import os
import io # Used for in-memory buffer
from pathlib import Path
import uuid # Still useful for unique filename for the client

app = Flask(__name__)

# NOTE: The DOWNLOAD_FOLDER and its creation are no longer needed
# DOWNLOAD_FOLDER = Path(__file__).parent / "downloads"
# DOWNLOAD_FOLDER.mkdir(exist_ok=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/info", methods=["POST"])
# The /info route remains the same as it doesn't download
def get_video_info():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "allow_unplayable_formats": True,
            # Add this: Instruct yt-dlp to prioritize formats that include both audio and video
            "format": "bestvideo[ext=mp4][vcodec!=none]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/114.0.0.0 Safari/537.36"
            }
        }

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
        return jsonify({"error": str(e)}), 500


@app.route("/download", methods=["POST"])
def download_video():
    data = request.get_json()
    url = data.get("url")
    format_id = data.get("format_id")
    filename = data.get("filename", "video") # Get title from frontend

    if not url or not format_id:
        return jsonify({"error": "URL and format_id required"}), 400

    try:
        selected_format = format_id
        should_merge = False
        
        if "youtube.com" in url or "youtu.be" in url:
            selected_format = f"{format_id}+bestaudio"
            should_merge = True

        # --- Yt-dlp hook to capture output as stream/bytes ---
        class BytesBufferLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg): print(f"YTDL-Error: {msg}")

        # In-memory buffer to hold video data before streaming to client
        video_buffer = io.BytesIO()

        ydl_opts = {
            # Use 'file' as the output template to write to the postprocessor's output object
            "outtmpl": "-",
            # The 'format' is crucial for selecting the stream
            "format": selected_format,
            "merge_output_format": "mp4",
            "quiet": True,
            "logger": BytesBufferLogger(), # Use custom logger to suppress logs
            "allow_unplayable_formats": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/114.0.0.0 Safari/537.36"
            }
        }

        # Use the 'postprocessors' key to pipe the output to a Python file object (BytesIO)
        if should_merge:
             # Use the output object provided by yt-dlp's API
             ydl_opts["postprocessors"] = [{
                 'key': 'FFmpegVideoRemuxer',
                 'prefer_ffmpeg': True,
                 'exec': lambda info: [
                     None, # Skip the default command
                     {'out': video_buffer} # Pipe final output to the buffer
                 ],
             }]
        else:
             # For non-merged formats, pipe directly to the output object
             ydl_opts['outtmpl'] = {'out': video_buffer}


        # 1. Start the download/processing process (this runs in memory)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # 2. Prepare the buffer for reading and streaming
        video_buffer.seek(0)
        
        # 3. Define the generator function for streaming chunks
        def generate():
            chunk_size = 8192 # Define chunk size (8KB is common)
            while True:
                chunk = video_buffer.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        
        # 4. Return the Flask streaming response
        response = Response(
            stream_with_context(generate()),
            # Instruct the browser to download the file
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename}.mp4\"",
                "Content-Type": "video/mp4",
                # This is important for large file streaming
                "Transfer-Encoding": "chunked"
            }
        )
        return response

    except Exception as e:
        print("Error during streaming download:", e)
        # No cleanup needed since nothing was saved to disk
        return jsonify({"error": f"Download failed. Did you install FFmpeg? Error: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)