import os
import re
import shutil
import argparse
from datetime import datetime
import json
import hashlib
import subprocess
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from urllib.parse import quote

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv")
SUMMARY_FILE = "summaries.json"
AUTO_MONITOR = False  # Set to True to enable auto-monitoring by default (CLI -m also enables it)
ENABLE_EXTENDED_NAMING = True  # Set to False to disable extended filename format

# Source/destination folders. Defined once here and referenced everywhere so
# there is a single place to change them. The CLI --source/--dest flags can
# override these at runtime.
SOURCE_FOLDER = "E:\\OUTPOST"
DESTINATION_FOLDER = "B:\\"

# Default YouTube channel to scope title searches to (CLI --channel can set it).
# None means fall back to per-show channels and otherwise a global search.
DEFAULT_CHANNEL = None

# yt-dlp availability (used by the downloader). Checked at import time.
YTDLP_AVAILABLE = shutil.which("yt-dlp") is not None

# ---------------------------------------------------------------------------
# Logging shim. Every function below calls log(...) instead of print(...), so a
# host (e.g. the Paragon Publisher GUI) can redirect output to a log pane by
# calling set_logger(). Defaults to print() for standalone CLI use.
# ---------------------------------------------------------------------------
_LOG_FN = print

def set_logger(fn):
    """Route all harvester output through fn (a callable taking one string).
    Pass None to restore printing to stdout."""
    global _LOG_FN
    _LOG_FN = fn or print

def log(*args):
    """print()-compatible shim that forwards to the current logger."""
    try:
        _LOG_FN(" ".join(str(a) for a in args))
    except Exception:
        # Never let a logging failure break processing.
        pass

def strip_4byte_chars(text):
    """Remove characters outside the Basic Multilingual Plane (code points
    above U+FFFF). Those need 4 bytes in UTF-8, which Kodi's default `utf8`
    MySQL columns cannot store -- that's the cause of MySQL error 1366 during
    a library scan. Stripping them keeps NFO text scan-safe. Ordinary BMP
    symbols (<= U+FFFF, up to 3 bytes) are preserved, so this only drops
    things like astral-plane emoji (e.g. the moon emoji in a plot)."""
    if not text:
        return text
    return ''.join(ch for ch in text if ord(ch) <= 0xFFFF)

def clean_title(title):
    return strip_4byte_chars(title.strip().title())

def extract_video_id(filename):
    """Extract YouTube video ID from filename [ID].ext format"""
    match = re.search(r'\[([a-zA-Z0-9_-]{11})\]', filename)
    if match:
        return match.group(1)
    return None

def build_channel_search_url(channel, query):
    """Turn a channel link/handle/ID into a channel-scoped YouTube search URL.

    Accepts a full channel URL (with or without a trailing tab like /videos),
    an @handle, or a raw UC... channel ID, and returns the channel's search-tab
    URL with the query URL-encoded.
    """
    channel = channel.strip()
    q = quote(query)

    if channel.startswith(("http://", "https://")):
        base = channel.rstrip('/')
        # Strip a trailing tab so we can append /search cleanly
        for tab in ('/videos', '/featured', '/streams', '/shorts',
                    '/playlists', '/community', '/about', '/search'):
            if base.lower().endswith(tab):
                base = base[: -len(tab)]
        return f"{base}/search?query={q}"

    if channel.startswith('@'):
        return f"https://www.youtube.com/{channel}/search?query={q}"

    if channel.startswith('UC') and len(channel) == 24:
        return f"https://www.youtube.com/channel/{channel}/search?query={q}"

    # Bare name -> treat as a handle
    return f"https://www.youtube.com/@{channel}/search?query={q}"

def search_youtube_by_title(title, channel=None):
    """Search YouTube for a video ID by title.

    If `channel` (a URL, @handle, or UC... ID) is given, the search is scoped
    to that channel's search tab so we match the exact uploader instead of
    taking whatever the top global result happens to be.
    """
    try:
        if channel:
            url = build_channel_search_url(channel, title)
            log(f"Searching channel for: {title}")
            log(f"  ({url})")
            cmd = ['yt-dlp', '--get-id', '--playlist-items', '1', url]
        else:
            log(f"Searching YouTube for: {title}")
            cmd = ['yt-dlp', '--get-id', f'ytsearch1:{title}']

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and result.stdout.strip():
            # Channel search can return multiple IDs; take the first.
            video_id = result.stdout.strip().splitlines()[0].strip()
            log(f"Found video ID: {video_id}")
            return video_id
        elif channel:
            log("No match found on that channel.")
    except Exception as e:
        log(f"Warning: Could not search YouTube: {e}")
    
    return None

def get_youtube_metadata(video_id):
    """Fetch metadata from YouTube using yt-dlp"""
    if not video_id:
        return None
    
    try:
        result = subprocess.run(
            ['yt-dlp', '--dump-json', '--no-download', f'https://www.youtube.com/watch?v={video_id}'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        log(f"Warning: Could not fetch YouTube metadata: {e}")
    
    return None

def clean_description(description, video_title, channel_name):
    """Clean up YouTube description by removing promotional content"""
    if not description:
        return f"{video_title} from {channel_name}"
    
    # Keywords that indicate promotional/technical sections
    remove_keywords = [
        'merch store', 'merch:', 'store:',
        'patreon', 'support me on',
        'special thanks', 'thanks to',
        'follow me', 'social media', 'twitter', 'instagram', 'facebook',
        'music:', 'music by', 'song:', 'songs used',
        'licensed under', 'creative commons', 'cc by',
        'subscribe', 'like and subscribe',
        'check out', 'links:',
        'equipment:', 'gear:',
        'discord:', 'join my discord',
        'outro music', 'background music',
        'footage from', 'clips from',
        '▬▬▬', '━━━', '═══', '───',
        'download', 'stream',
        'listen to', 'available now', 'out now',
        'spotify', 'apple music', 'itunes',
        'descargar', 'apoyo',
        'lyrics', 'letra',
        '[verse', '[chorus', '[bridge', '[intro', '[outro',
        '(verse', '(chorus', '(bridge', '(intro', '(outro',
        'official lyric video', 'lyric video',
    ]
    
    lines = description.split('\n')
    content_lines = []
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # Skip empty lines
        if not line.strip():
            continue
        
        # Skip lines that contain URLs
        if 'http://' in line_lower or 'https://' in line_lower or 'www.' in line_lower:
            continue
        
        # Skip lines with link shorteners
        if any(domain in line_lower for domain in ['.lnk.to/', 'bit.ly/', 'youtu.be/', 'smarturl.']):
            continue
        
        # Skip lines with » or « (promotional sections)
        if '»' in line or '«' in line:
            continue
        
        # Skip lines that look like lyrics
        if any(marker in line_lower for marker in ['[verse', '[chorus', '[bridge', '[intro', '[outro', '[pre-', '[post-']):
            continue
        
        # Skip lines that start with common lyric patterns
        if line_lower.startswith(('verse ', 'chorus ', 'bridge ', 'intro:', 'outro:', 'pre-chorus', 'post-chorus')):
            continue
        
        # Skip separator lines
        if len(line.strip()) > 0 and len(re.findall(r'[▬━═─_\-=*#»«]', line)) / len(line.strip()) > 0.5:
            continue
        
        # Check if this is a promotional line
        is_promotional = any(keyword in line_lower for keyword in remove_keywords)
        
        # If promotional and we have content, stop collecting
        if is_promotional and len(content_lines) > 0:
            break
        
        # If promotional and no content yet, skip this line
        if is_promotional:
            continue
        
        # This is actual content
        content_lines.append(line.strip())
    
    # Join collected lines
    cleaned = ' '.join(content_lines)
    
    # Remove multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # If we didn't find enough content, use fallback
    if len(cleaned) < 10:
        return f"{video_title} from {channel_name}"
    
    # Limit to 500 characters
    if len(cleaned) > 500:
        cleaned = cleaned[:497] + '...'
    
    # Drop 4-byte characters (emoji) so the plot is safe for Kodi's utf8 DB
    return strip_4byte_chars(cleaned)

def get_video_stream_info(video_path):
    """Extract detailed stream information using ffprobe"""
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            str(video_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return None
        
        data = json.loads(result.stdout)
        
        # Extract video stream info
        video_stream = next((s for s in data.get('streams', []) if s['codec_type'] == 'video'), None)
        audio_stream = next((s for s in data.get('streams', []) if s['codec_type'] == 'audio'), None)
        
        if not video_stream:
            return None
        
        # Calculate aspect ratio
        width = int(video_stream.get('width', 1920))
        height = int(video_stream.get('height', 1080))
        aspect = round(width / height, 3) if height > 0 else 1.778
        
        # Get duration in seconds
        duration = float(data.get('format', {}).get('duration', 0))
        duration_seconds = int(duration)
        
        stream_info = {
            'video': {
                'codec': video_stream.get('codec_name', 'h264'),
                'width': width,
                'height': height,
                'aspect': aspect,
                'duration_seconds': duration_seconds,
                'scantype': 'progressive'
            },
            'audio': {
                'codec': audio_stream.get('codec_name', 'aac') if audio_stream else 'aac',
                'channels': int(audio_stream.get('channels', 2)) if audio_stream else 2
            }
        }
        
        return stream_info
        
    except Exception as e:
        log(f"Warning: Could not extract stream info: {e}")
        return None

def suggest_show_summary(show_name):
    """Creates a customized summary suggestion for a show based on its name."""
    # Try to create a more specific and interesting summary based on the show name
    if any(music_word in show_name.lower() for music_word in ["band", "music", "artist", "singer", "rock", "metal", "pop", "jazz", "hip hop", "rap", "orchestra"]):
        return f"A collection of powerful tracks by the acclaimed musical act {show_name}. Experience their unique sound and artistic evolution through this carefully curated selection."
    elif any(comedy_word in show_name.lower() for comedy_word in ["comedy", "funny", "laugh", "humor", "stand up", "standup"]):
        return f"Hilarious performances from {show_name} that showcase their unique comedic style and timing. Each episode delivers memorable jokes and situations that will leave you laughing."
    elif any(documentary_word in show_name.lower() for documentary_word in ["documentary", "nature", "history", "science", "discover", "explore"]):
        return f"An insightful documentary series featuring {show_name}. Each episode explores fascinating subjects with depth and clarity, providing viewers with a new perspective."
    else:
        # Generic but still more detailed than a simple template
        return f"A captivating collection featuring {show_name}. This series showcases their best work, highlighting the unique style and creativity that has earned them recognition."

def generate_plot(show_name, episode_title, series_summary=None, youtube_description=None):
    """Generates a plot summary, using YouTube description if available."""

    # Priority: YouTube description (cleaned) > Series summary > Generic
    if youtube_description and len(youtube_description) > 10:
        return youtube_description
    elif series_summary:
        # Combine the series summary and episode title
        plot = f"{series_summary} This one is called {episode_title}."
    else:
        plot = f"Episode '{episode_title}' of {show_name}."

    return plot

def generate_nfo(show_name, episode_title, season, episode, file_path, genre, date_added, series_summary, youtube_metadata=None):
    # Get stream info from video file
    stream_info = get_video_stream_info(file_path)
    
    # If ffprobe fails, use defaults
    if not stream_info:
        stream_info = {
            'video': {
                'codec': 'h264',
                'width': 1920,
                'height': 1080,
                'aspect': 1.778,
                'duration_seconds': 0,
                'scantype': 'progressive'
            },
            'audio': {
                'codec': 'aac',
                'channels': 2
            }
        }
    
    # Get YouTube description if available
    youtube_description = None
    aired_date = date_added
    
    if youtube_metadata:
        raw_description = youtube_metadata.get('description', '')
        if raw_description:
            youtube_description = clean_description(raw_description, episode_title, show_name)
        
        # Get upload date
        upload_date = youtube_metadata.get('upload_date', '')
        if upload_date:
            try:
                aired_date = datetime.strptime(upload_date, '%Y%m%d').strftime('%Y-%m-%d')
            except:
                aired_date = date_added
    
    # Generate plot content
    plot_content = generate_plot(show_name, episode_title, series_summary, youtube_description)

    # Escape everything user-derived so special chars (&, <, >) yield valid XML
    title_xml = xml_escape(clean_title(episode_title))
    showtitle_xml = xml_escape(clean_title(show_name))
    plot_xml = xml_escape(strip_4byte_chars(plot_content))
    genre_xml = xml_escape(strip_4byte_chars(genre) if genre else "")
    filename_xml = xml_escape(os.path.basename(file_path))

    nfo_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<episodedetails>
    <title>{title_xml}</title>
    <showtitle>{showtitle_xml}</showtitle>
    <userrating>0</userrating>
    <top250>0</top250>
    <season>{season}</season>
    <episode>{episode}</episode>
    <plot>{plot_xml}</plot>
    <mpaa>TV-14</mpaa>
    <playcount>0</playcount>
    <lastplayed>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</lastplayed>
    <aired>{aired_date}</aired>
    <genre>{genre_xml}</genre>
    <dateadded>{date_added}</dateadded>
    <file>{filename_xml}</file>
    <fileinfo>
        <streamdetails>
            <video>
                <durationinseconds>{stream_info['video']['duration_seconds']}</durationinseconds>
                <codec>{stream_info['video']['codec']}</codec>
                <aspect>{stream_info['video']['aspect']}</aspect>
                <width>{stream_info['video']['width']}</width>
                <height>{stream_info['video']['height']}</height>
                <scantype>{stream_info['video']['scantype']}</scantype>
            </video>
            <audio>
                <codec>{stream_info['audio']['codec']}</codec>
                <channels>{stream_info['audio']['channels']}</channels>
            </audio>
        </streamdetails>
    </fileinfo>
    <generator>
        <appname>Paragon Harvester</appname>
        <appversion>1.0.0</appversion>
        <kodiversion>17</kodiversion>
        <datetime>{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}</datetime>
    </generator>
</episodedetails>"""

    nfo_filename = os.path.splitext(file_path)[0] + ".nfo"
    with open(nfo_filename, "w", encoding="utf-8") as f:
        f.write(nfo_content)
    log(f"Generated: {nfo_filename} (with stream details)")

def rename_to_extended_format(video_path, show_name, genre):
    """Rename video and NFO to extended format after processing"""
    if not ENABLE_EXTENDED_NAMING:
        return video_path
    
    try:
        base_path = os.path.splitext(video_path)[0]
        nfo_path = base_path + ".nfo"
        video_ext = os.path.splitext(video_path)[1]
        
        if not os.path.exists(nfo_path):
            log(f"Warning: NFO not found for extended naming: {nfo_path}")
            return video_path
        
        # Parse NFO to get metadata
        tree = ET.parse(nfo_path)
        root = tree.getroot()
        
        # Extract metadata
        season = root.find('.//season')
        episode = root.find('.//episode')
        title = root.find('.//title')
        
        # Extract stream details
        width_elem = root.find('.//fileinfo/streamdetails/video/width')
        audio_codec_elem = root.find('.//fileinfo/streamdetails/audio/codec')
        audio_channels_elem = root.find('.//fileinfo/streamdetails/audio/channels')
        
        if season is None or episode is None or title is None:
            log(f"Warning: Missing required NFO fields for extended naming")
            return video_path
        
        # Build extended filename. Zero-pad season/episode to at least two
        # digits so the format is 01x01, not 1x1. (int() handles values the
        # NFO stored as plain numbers; the fallback covers any odd text.)
        try:
            season_num = f"{int(season.text):02d}"
            episode_num = f"{int(episode.text):02d}"
        except (TypeError, ValueError):
            season_num = str(season.text).zfill(2)
            episode_num = str(episode.text).zfill(2)
        episode_title = title.text
        
        # Determine resolution from width
        resolution = "480"
        if width_elem is not None and width_elem.text:
            width = int(width_elem.text)
            if width >= 3800:
                resolution = "2160"
            elif width >= 1900:
                resolution = "1080"
            elif width >= 1260:
                resolution = "720"
        
        # Audio codec
        audio_codec = "AAC"
        if audio_codec_elem is not None and audio_codec_elem.text:
            audio_codec = audio_codec_elem.text.upper()
        
        # Audio channels
        audio_channels = "2"
        if audio_channels_elem is not None and audio_channels_elem.text:
            audio_channels = audio_channels_elem.text
        
        # Sanitize filename components
        def sanitize(text):
            # Remove invalid Windows filename characters
            invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
            for char in invalid_chars:
                text = text.replace(char, '')
            return text.strip()
        
        episode_title = sanitize(episode_title)
        show_name = sanitize(show_name)
        if not genre:
            genre = "Unknown"
        genre = sanitize(genre)
        
        # Build new filename
        new_base = f"{season_num}x{episode_num} - {episode_title} - {show_name} - {genre} - {resolution} - {audio_channels} - {audio_codec} - None"
        new_video_path = os.path.join(os.path.dirname(video_path), new_base + video_ext)
        new_nfo_path = os.path.join(os.path.dirname(video_path), new_base + ".nfo")
        
        # Check if already in correct format
        if video_path == new_video_path:
            log(f"Already in extended format: {os.path.basename(video_path)}")
            return video_path
        
        # Rename files
        log(f"Renaming to extended format:")
        log(f"  {os.path.basename(video_path)} ->")
        log(f"  {os.path.basename(new_video_path)}")
        
        os.rename(video_path, new_video_path)
        os.rename(nfo_path, new_nfo_path)
        
        return new_video_path
        
    except Exception as e:
        log(f"Error in extended naming: {e}")
        return video_path

def generate_tvshow_nfo(show_name, genre, summary, show_folder):
    """Generates a tvshow.nfo file with show metadata."""
    # Get current date in ISO format for dateadded
    current_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Escape user-derived fields for valid XML
    showtitle_xml = xml_escape(clean_title(show_name))
    summary_xml = xml_escape(strip_4byte_chars(summary) if summary else "")
    genre_xml = xml_escape(strip_4byte_chars(genre) if genre else "")

    # Kodi keys a show on its <uniqueid>. A hardcoded id shared by every show
    # makes Kodi think each new show is one it already has, so it silently
    # skips all but the first. Derive a stable, per-show id from the title so
    # each show is distinct and re-scans update the same show (idempotent).
    show_uid = hashlib.md5(clean_title(show_name).encode("utf-8")).hexdigest()[:12]
    show_uid_xml = xml_escape(show_uid)

    nfo_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<tvshow>
    <title>{showtitle_xml}</title>
    <showtitle></showtitle>
    <sorttitle clear="true">{showtitle_xml}</sorttitle>
    <originaltitle>{showtitle_xml}</originaltitle>
    <!-- Stable per-show id derived from the title so Kodi keeps shows distinct -->
    <uniqueid default="true" type="paragon">{show_uid_xml}</uniqueid>
    <userrating>0</userrating>
    <top250>0</top250>
    <episode>1</episode>
    <season>1</season>
    <plot>{summary_xml}</plot>
    <mpaa>TV-14</mpaa>
    <premiered></premiered>
    <year></year>
    <dateadded></dateadded>
    <status>Continuing</status>
    <runtime>5</runtime>
    <trailer></trailer>
    <genre>{genre_xml}</genre>
    <generator>
        <appname>MediaElch</appname>
        <appversion>2.12.0</appversion>
        <kodiversion>17</kodiversion>
        <datetime>{current_date}</datetime>
    </generator>
</tvshow>"""

    nfo_filename = os.path.join(show_folder, "tvshow.nfo")
    with open(nfo_filename, "w", encoding="utf-8") as f:
        f.write(nfo_content)
    log(f"Generated: {nfo_filename}")

def clean_episode_title(title):
    """Cleans up an episode title by removing extraneous information."""
    original_title = title
    log(f"DEBUG - Starting with title: '{title}'")
    
    # Remove text in various types of brackets
    title = re.sub(r'\s*\([^)]*\)', '', title)  # Remove parentheses
    title = re.sub(r'\s*\[[^\]]*\]', '', title)  # Remove square brackets
    title = re.sub(r'\s*\{[^}]*\}', '', title)  # Remove curly braces
    title = re.sub(r'\s*<[^>]*>', '', title)  # Remove angle brackets
    
    log(f"DEBUG - After bracket removal: '{title}'")
    
    # For video suffixes, use a safer word boundary approach
    title = re.sub(r' official music video$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' music video$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' official video$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' official audio$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' lyric video$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' official lyric video$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' visualizer$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' official visualizer$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' hd$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' hq$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' 4k$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' 8k$', '', title, flags=re.IGNORECASE)
    
    log(f"DEBUG - After suffix removal: '{title}'")
    
    # Hyphen patterns - only remove specific endings
    title = re.sub(r' - official video$', '', title, flags=re.IGNORECASE) 
    title = re.sub(r' - music video$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' - audio$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' - lyric video$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' - hd$', '', title, flags=re.IGNORECASE)
    title = re.sub(r' - 4k$', '', title, flags=re.IGNORECASE)
    
    log(f"DEBUG - After hyphen removal: '{title}'")
    
    # Featuring artists - simplified to avoid complex patterns
    if ' ft. ' in title.lower():
        title = title.split(' ft. ')[0]
    if ' feat. ' in title.lower():
        title = title.split(' feat. ')[0]
    if ' featuring ' in title.lower():
        title = title.split(' featuring ')[0]
    
    # Remove " by (artist)" patterns
    if ' by ' in title:
        title = title.split(' by ')[0]
    
    log(f"DEBUG - After featuring removal: '{title}'")
        
    # Final cleanup
    title = ' '.join(title.split())  # Remove extra spaces
    if not title or len(title) < 3:
        log(f"WARNING - Title cleaning too aggressive, reverting to: '{original_title}'")
        title = original_title
    
    log(f"DEBUG - Final cleaned title: '{title}'")
    return strip_4byte_chars(title)

def process_file(file_path, destination_folder, default_genre, nfo_handling, show_data, source_folder,
                 new_show_cb=None):
    """Processes a single video file.

    new_show_cb, when given, makes the first-sighting of a show non-interactive
    (used by the GUI). It is called as
        new_show_cb(show_key, show_name, suggested_summary, default_genre)
    and must return a dict with optional keys 'summary', 'genre', 'channel'.
    When new_show_cb is None the original interactive input() prompts are used.
    """
    
    # Extract the show name and episode title
    filename = os.path.basename(file_path)
    file_dir = os.path.dirname(file_path)
    log(f"Processing filename: {filename}")
    
    # Check if video is in a subfolder within source folder
    # If so, use folder name as show name
    relative_path = os.path.relpath(file_dir, source_folder)
    
    if relative_path != '.' and relative_path != source_folder:
        # Video is in a subfolder - use folder name as show
        folder_name = os.path.basename(file_dir)
        show_name = folder_name
        # Entire filename becomes episode title
        episode_title = os.path.splitext(filename)[0]
        extension = os.path.splitext(filename)[1][1:]  # Remove the dot
        log(f"Found in subfolder: '{folder_name}'")
        log(f"Using folder as show name: '{show_name}'")
        log(f"Episode title from filename: '{episode_title}'")
    else:
        # Video is in root source folder - parse filename for show and episode
        # First pattern tries to match "ShowName - EpisodeTitle.ext"
        match = re.match(r"(.+?)\s*[-_]\s*(.+?)\.(\w+)$", filename)
        if not match:
            # Second pattern is more lenient
            match = re.match(r"(.+?)[\s_\.-]+(.+?)\.(\w+)$", filename)
            if not match:
                log(f"Skipping unrecognized file: {filename}")
                return

        show_name, episode_title, extension = match.groups()
        log(f"Extracted from filename - Show: '{show_name}', Episode: '{episode_title}'")
    
    # Normalize show_name for dictionary key (case-insensitive lookup)
    show_key = show_name.strip().title()

    # Register the show on first sighting, or advance its episode counter.
    # This runs BEFORE the YouTube lookup so that a channel the user supplies
    # here (or via --channel) can scope the search to the exact uploader.
    if show_key not in show_data:
        show_data[show_key] = {
            "season": 1,
            "episode": 1,
            "genre": None,
            "summary": None,
            "channel": None
        }

        # Generate default summary
        default_summary = suggest_show_summary(show_name)

        if new_show_cb is not None:
            # Non-interactive path (GUI). The host resolves the new show's
            # metadata; anything it omits falls back to sensible defaults.
            log(f"\nNew show '{show_key}' - using suggested summary.")
            info = new_show_cb(show_key, show_name, default_summary, default_genre) or {}
            show_data[show_key]["summary"] = info.get("summary") or default_summary
            resolved_genre = info.get("genre") if info.get("genre") is not None else default_genre
            show_data[show_key]["genre"] = resolved_genre
            resolved_channel = info.get("channel") or DEFAULT_CHANNEL
            show_data[show_key]["channel"] = resolved_channel or None
        else:
            log(f"\nSuggested summary for '{show_key}':")
            log(f"----------\n{default_summary}\n----------")
            edit_choice = input("Accept this summary? (y/n/e - yes/no/edit): ").strip().lower()

            if edit_choice == 'n':
                edited_summary = input("Enter new summary description: ").strip()
            elif edit_choice == 'e':
                edited_summary = input("Edit summary: ").strip()
            else:
                edited_summary = default_summary

            show_data[show_key]["summary"] = edited_summary

            if default_genre is None:
                genre = input(f"Enter genre for '{show_key}' (or blank to skip): ").strip()
                if genre:
                    show_data[show_key]["genre"] = genre
            else:
                show_data[show_key]["genre"] = default_genre

            # Ask for the exact YouTube channel to match. When set, every
            # title-based lookup for this show is scoped to that channel instead
            # of a blind global search, so we match the right uploader. A
            # --channel value (if given) is offered as the default.
            channel_prompt = "Enter YouTube channel URL or @handle to match this show exactly"
            if DEFAULT_CHANNEL:
                channel_prompt += f" [default: {DEFAULT_CHANNEL}]"
            channel_prompt += " (blank to auto-search): "
            entered_channel = input(channel_prompt).strip()
            if not entered_channel and DEFAULT_CHANNEL:
                entered_channel = DEFAULT_CHANNEL
            show_data[show_key]["channel"] = entered_channel or None
    else:
        # Backfill the channel field for data written by older versions
        show_data[show_key].setdefault("channel", None)
        show_data[show_key]["episode"] += 1
        if show_data[show_key]["episode"] > 24:
            show_data[show_key]["episode"] = 1
            show_data[show_key]["season"] += 1

    # Effective channel: the per-show stored value wins, else the CLI default.
    effective_channel = show_data[show_key].get("channel") or DEFAULT_CHANNEL

    # Try to extract YouTube video ID from filename first
    video_id = extract_video_id(filename)
    youtube_metadata = None
    
    if video_id:
        # We already have the exact video; channel scoping is unnecessary.
        log(f"Found YouTube video ID in filename: {video_id}")
        youtube_metadata = get_youtube_metadata(video_id)
    else:
        # No video ID found - search YouTube by title
        # Combine show name and episode title for better search
        search_query = f"{show_name} {episode_title}"
        if effective_channel:
            log(f"No video ID found, searching channel '{effective_channel}' for: '{search_query}'")
        else:
            log(f"No video ID found, searching YouTube for: '{search_query}'")
        video_id = search_youtube_by_title(search_query, effective_channel)
        if video_id:
            youtube_metadata = get_youtube_metadata(video_id)
        else:
            log("Could not find video on YouTube, using generic metadata")
    
    # Clean up the episode title
    episode_title = clean_episode_title(episode_title)

    show_folder = os.path.join(destination_folder, show_key)
    if not os.path.exists(show_folder):
        os.makedirs(show_folder)
        log(f"Created folder: {show_folder}")
        # Create tvshow.nfo here
        tvshow_nfo_path = os.path.join(show_folder, "tvshow.nfo")
        if not os.path.exists(tvshow_nfo_path):
            generate_tvshow_nfo(show_name, show_data[show_key]["genre"], show_data[show_key]["summary"], show_folder)

    new_file_path = os.path.join(show_folder, os.path.basename(file_path))
    if os.path.exists(new_file_path):
        base, ext = os.path.splitext(os.path.basename(file_path))
        counter = 1
        while os.path.exists(os.path.join(show_folder, f"{base}_{counter}{ext}")):
            counter += 1
        new_file_path = os.path.join(show_folder, f"{base}_{counter}{ext}")

    try:
        shutil.move(file_path, new_file_path)
        log(f"Moved: {os.path.basename(file_path)} -> {new_file_path}")
    except OSError as e:
        log(f"Error moving {os.path.basename(file_path)}: {e}")
        return

    season = show_data[show_key]["season"]
    episode = show_data[show_key]["episode"]
    base, ext = os.path.splitext(os.path.basename(new_file_path))
    new_filename = f"S{season:02d}E{episode:02d} - {episode_title}{ext}"
    renamed_file_path = os.path.join(show_folder, new_filename)

    if os.path.exists(renamed_file_path):
        base, ext = os.path.splitext(new_filename)
        counter = 1
        while os.path.exists(os.path.join(show_folder, f"{base}_{counter}{ext}")):
            counter += 1
        renamed_file_path = os.path.join(show_folder, f"{base}_{counter}{ext}")

    try:
        os.rename(new_file_path, renamed_file_path)
        log(f"Renamed: {os.path.basename(new_file_path)} -> {os.path.basename(renamed_file_path)}")
    except OSError as e:
        log(f"Error renaming {os.path.basename(new_file_path)}: {e}")
        return

    nfo_path = os.path.splitext(renamed_file_path)[0] + ".nfo"
    if nfo_handling == "skip" and os.path.exists(nfo_path):
        log(f"Skipping NFO for {os.path.basename(renamed_file_path)} (exists).")
        return
    elif nfo_handling == "ask" and os.path.exists(nfo_path):
        if input(f"Overwrite NFO for {os.path.basename(renamed_file_path)}? (y/n): ").lower() != 'y':
            log(f"Skipping NFO for {os.path.basename(renamed_file_path)}.")
            return

    date_added = "2000-01-01"
    generate_nfo(show_name, episode_title, season, episode, renamed_file_path,
                 show_data[show_key]["genre"], date_added, show_data[show_key]["summary"], youtube_metadata)
    
    # Rename to extended format if enabled
    if ENABLE_EXTENDED_NAMING:
        final_file_path = rename_to_extended_format(renamed_file_path, show_name, show_data[show_key]["genre"])
    else:
        final_file_path = renamed_file_path


def process_videos(default_genre, nfo_handling):
    """Main function to process videos."""

    source_folder = SOURCE_FOLDER  # From module constant / CLI override
    destination_folder = DESTINATION_FOLDER   # From module constant / CLI override
    
    log(f"Scanning source folder: {source_folder}")
    log("This will include all subfolders within the source folder")

    show_data = {}

    try:
        with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
            show_data = json.load(f)
            for show_key, data in show_data.items():
                if isinstance(data, tuple):
                    season, episode, *genre = data
                    genre = genre[0] if genre else None
                    show_data[show_key] = {
                        "season": season,
                        "episode": episode,
                        "genre": genre,
                        "summary": None
                    }
                else:
                    if "summary" not in data:
                        data["summary"] = None
                    if "genre" not in data:
                        data["genre"] = None
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        log(f"Error: {SUMMARY_FILE} is not a valid JSON file.  Starting with no summaries.")
        show_data = {}

    total_videos = 0
    processed_videos = 0
    
    # First, count total videos for progress reporting
    log("Counting video files...")
    for root, _, files in os.walk(source_folder):
        for file in files:
            if file.lower().endswith(VIDEO_EXTENSIONS):
                total_videos += 1
    
    log(f"Found {total_videos} video files to process")
    
    # Now process each video file
    for root, _, files in os.walk(source_folder):
        for file in files:
            if file.lower().endswith(VIDEO_EXTENSIONS):
                processed_videos += 1
                file_path = os.path.join(root, file)
                log(f"\nProcessing file {processed_videos} of {total_videos}: {os.path.basename(file_path)}")
                log(f"From folder: {os.path.relpath(root, source_folder)}")
                process_file(file_path, destination_folder, default_genre,
                             nfo_handling, show_data, source_folder)

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(show_data, f, indent=4)

class VideoFileHandler(FileSystemEventHandler):
    """Handler for auto-monitoring mode"""
    def __init__(self, default_genre, nfo_handling, show_data_file):
        self.default_genre = default_genre
        self.nfo_handling = nfo_handling
        self.show_data_file = show_data_file
        self.processing = set()
    
    def on_created(self, event):
        if event.is_directory:
            return
        
        filepath = event.src_path
        if not filepath.lower().endswith(VIDEO_EXTENSIONS):
            return
        
        # Wait for file to finish writing
        time.sleep(5)
        
        if filepath not in self.processing:
            self.processing.add(filepath)
            log(f"\nNew video detected: {os.path.basename(filepath)}")
            
            # Wait for file to finish writing
            prev_size = -1
            curr_size = os.path.getsize(filepath)
            while prev_size != curr_size:
                time.sleep(2)
                prev_size = curr_size
                curr_size = os.path.getsize(filepath)
            
            # Load show data
            show_data = {}
            try:
                with open(self.show_data_file, "r", encoding="utf-8") as f:
                    show_data = json.load(f)
            except:
                pass
            
            # Process the file
            source_folder = SOURCE_FOLDER
            destination_folder = DESTINATION_FOLDER
            process_file(filepath, destination_folder, self.default_genre,
                        self.nfo_handling, show_data, source_folder)
            
            # Save show data
            with open(self.show_data_file, "w", encoding="utf-8") as f:
                json.dump(show_data, f, indent=4)
            
            self.processing.remove(filepath)

def run_auto_monitor(default_genre, nfo_handling):
    """Run in auto-monitoring mode"""
    if not WATCHDOG_AVAILABLE:
        log("ERROR: Watchdog library not installed. Install with: pip install watchdog")
        return
    
    source_folder = SOURCE_FOLDER
    
    log("=" * 60)
    log("  Paragon Harvester - Auto-Monitor Mode")
    log("=" * 60)
    log(f"Watching: {source_folder}")
    log("Press Ctrl+C to stop")
    log("=" * 60 + "\n")
    
    event_handler = VideoFileHandler(default_genre, nfo_handling, SUMMARY_FILE)
    observer = Observer()
    observer.schedule(event_handler, source_folder, recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("\n\nStopping auto-monitor...")
        observer.stop()

    observer.join()

# ---------------------------------------------------------------------------
# GUI-callable entry points. These wrap the same pipeline used by the CLI but
# take explicit paths, a non-interactive new_show_cb, and a stop signal so they
# can be driven from a background thread (e.g. the Paragon Publisher GUI). The
# NFO and filename output is produced by the exact same functions as the CLI,
# so results are byte-for-byte identical to the validated standalone tool.
# ---------------------------------------------------------------------------

def _default_summary_file(destination_folder):
    """Where per-show state (season/episode counters, summaries) is stored.
    Kept alongside the destination library so it is stable across runs."""
    return os.path.join(destination_folder, SUMMARY_FILE)

def _load_show_data(summary_file):
    """Load and normalize the show-state JSON, tolerating older formats."""
    show_data = {}
    try:
        with open(summary_file, "r", encoding="utf-8") as f:
            show_data = json.load(f)
        for show_key, data in list(show_data.items()):
            if isinstance(data, (list, tuple)):
                season, episode, *genre = data
                show_data[show_key] = {
                    "season": season, "episode": episode,
                    "genre": genre[0] if genre else None,
                    "summary": None, "channel": None,
                }
            else:
                data.setdefault("summary", None)
                data.setdefault("genre", None)
                data.setdefault("channel", None)
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        log(f"Error: {summary_file} is not valid JSON. Starting with no summaries.")
        show_data = {}
    return show_data

def run_harvest(source_folder, destination_folder, default_genre="", nfo_handling="skip",
                channel=None, new_show_cb=None, should_stop=None, summary_file=None):
    """One-shot organize of every video under source_folder into destination_folder.

    Non-interactive: new_show_cb resolves per-show metadata (see process_file).
    should_stop, if given, is a callable checked between files to allow an early
    abort. Returns the number of files processed.
    """
    global DEFAULT_CHANNEL
    DEFAULT_CHANNEL = (channel or "").strip() or None
    if summary_file is None:
        summary_file = _default_summary_file(destination_folder)

    if not os.path.isdir(source_folder):
        log(f"Source folder not found: {source_folder}")
        return 0

    log(f"Scanning source folder: {source_folder}")
    log("This will include all subfolders within the source folder")

    show_data = _load_show_data(summary_file)

    total_videos = 0
    log("Counting video files...")
    for root, _, files in os.walk(source_folder):
        for file in files:
            if file.lower().endswith(VIDEO_EXTENSIONS):
                total_videos += 1
    log(f"Found {total_videos} video files to process")

    processed = 0
    aborted = False
    for root, _, files in os.walk(source_folder):
        for file in files:
            if should_stop is not None and should_stop():
                aborted = True
                break
            if file.lower().endswith(VIDEO_EXTENSIONS):
                processed += 1
                file_path = os.path.join(root, file)
                log(f"\nProcessing file {processed} of {total_videos}: {os.path.basename(file_path)}")
                log(f"From folder: {os.path.relpath(root, source_folder)}")
                try:
                    process_file(file_path, destination_folder, default_genre,
                                 nfo_handling, show_data, source_folder, new_show_cb=new_show_cb)
                except Exception as e:
                    log(f"Error processing {os.path.basename(file_path)}: {e}")
        if aborted:
            break

    # Persist per-show state even on an early stop so counters aren't lost.
    try:
        os.makedirs(os.path.dirname(summary_file) or ".", exist_ok=True)
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(show_data, f, indent=4)
    except OSError as e:
        log(f"Warning: could not save show state to {summary_file}: {e}")

    log(f"\n{'Stopped' if aborted else 'Done'}. Processed {processed} file(s).")
    return processed

class _GuiVideoFileHandler(FileSystemEventHandler):
    """Watchdog handler for GUI monitor mode: explicit paths + new_show_cb, and
    it reloads/saves the show-state file around each processed file so counters
    survive across events."""
    def __init__(self, source_folder, destination_folder, default_genre, nfo_handling,
                 summary_file, new_show_cb=None):
        self.source_folder = source_folder
        self.destination_folder = destination_folder
        self.default_genre = default_genre
        self.nfo_handling = nfo_handling
        self.summary_file = summary_file
        self.new_show_cb = new_show_cb
        self.processing = set()

    def on_created(self, event):
        if event.is_directory:
            return
        filepath = event.src_path
        if not filepath.lower().endswith(VIDEO_EXTENSIONS):
            return
        if filepath in self.processing:
            return
        self.processing.add(filepath)
        try:
            log(f"\nNew video detected: {os.path.basename(filepath)}")
            time.sleep(5)  # let the file start settling
            # Wait until the file size stops changing (finished writing)
            prev_size = -1
            try:
                curr_size = os.path.getsize(filepath)
            except OSError:
                return
            while prev_size != curr_size:
                time.sleep(2)
                prev_size = curr_size
                try:
                    curr_size = os.path.getsize(filepath)
                except OSError:
                    return

            show_data = _load_show_data(self.summary_file)
            try:
                process_file(filepath, self.destination_folder, self.default_genre,
                             self.nfo_handling, show_data, self.source_folder,
                             new_show_cb=self.new_show_cb)
            except Exception as e:
                log(f"Error processing {os.path.basename(filepath)}: {e}")
            try:
                with open(self.summary_file, "w", encoding="utf-8") as f:
                    json.dump(show_data, f, indent=4)
            except OSError as e:
                log(f"Warning: could not save show state: {e}")
        finally:
            self.processing.discard(filepath)

def run_monitor(source_folder, destination_folder, default_genre="", nfo_handling="skip",
                channel=None, new_show_cb=None, stop_event=None, summary_file=None):
    """Watch source_folder and organize new videos as they arrive, until
    stop_event is set. Requires the watchdog library. Blocks the calling thread,
    so run it on a background thread from the GUI."""
    global DEFAULT_CHANNEL
    DEFAULT_CHANNEL = (channel or "").strip() or None
    if summary_file is None:
        summary_file = _default_summary_file(destination_folder)

    if not WATCHDOG_AVAILABLE:
        log("ERROR: Watchdog library not installed. Install with: pip install watchdog")
        return
    if not os.path.isdir(source_folder):
        log(f"Source folder not found: {source_folder}")
        return

    log("=" * 60)
    log("  Paragon Harvester - Monitor Mode")
    log("=" * 60)
    log(f"Watching: {source_folder}")
    log("=" * 60 + "\n")

    handler = _GuiVideoFileHandler(source_folder, destination_folder, default_genre,
                                   nfo_handling, summary_file, new_show_cb=new_show_cb)
    observer = Observer()
    observer.schedule(handler, source_folder, recursive=True)
    observer.start()
    try:
        while stop_event is None or not stop_event.is_set():
            time.sleep(0.5)
    finally:
        log("\nStopping monitor...")
        observer.stop()
        observer.join()
        log("Monitor stopped.")

# ---------------------------------------------------------------------------
# Downloader (yt-dlp). Fetches video/playlist/channel URLs straight into the
# source folder, laid out as <source>/<Channel>/<Title> [<id>].<ext> so the
# organize pipeline treats each channel folder as a show and reads the exact
# YouTube metadata from the embedded [id]. yt-dlp is the same engine that apps
# like 4K Video Downloader wrap, so this replaces the separate download step.
# ---------------------------------------------------------------------------

def detect_js_runtime():
    """Find a JavaScript runtime for yt-dlp. Returns (name, path):
        name: 'deno'/'node'/'bun', or None if none found
        path: full path to the executable if it was found OFF the PATH (so it
              must be passed to yt-dlp explicitly), or None if it's on the PATH
              already. Deno installed via winget frequently ends up off the
              PATH of an already-running process, which is why we also probe
              its common install locations."""
    for rt in ("deno", "node", "bun"):
        if shutil.which(rt):
            return (rt, None)

    # Not on PATH - probe common Windows locations for deno.exe.
    import glob
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    candidates = [
        os.path.join(home, ".deno", "bin", "deno.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Links", "deno.exe"),
        os.path.join(local, "deno", "deno.exe"),
    ]
    candidates += glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages",
                                         "DenoLand.Deno*", "**", "deno.exe"),
                            recursive=True)
    for c in candidates:
        if os.path.isfile(c):
            return ("deno", c)
    return (None, None)

def check_environment():
    """Report on the external tools the downloader relies on. Returns a dict:
        yt_dlp:          version string, or None if not found
        ffmpeg:          True/False (needed to merge video+audio streams)
        js_runtime:      'deno'/'node'/'bun' if found, else None
        js_runtime_path: full path if found off-PATH, else None
    A missing JS runtime is the usual reason downloads come back audio-only or
    403: YouTube needs JS run to hand over the video stream."""
    rt_name, rt_path = detect_js_runtime()
    info = {"yt_dlp": None, "ffmpeg": shutil.which("ffmpeg") is not None,
            "js_runtime": rt_name, "js_runtime_path": rt_path}
    if shutil.which("yt-dlp"):
        try:
            out = subprocess.run(["yt-dlp", "--version"], capture_output=True,
                                 text=True, timeout=10)
            if out.returncode == 0:
                info["yt_dlp"] = out.stdout.strip()
        except Exception:
            pass
    return info

def get_installed_ytdlp_version():
    if not shutil.which("yt-dlp"):
        return None
    try:
        out = subprocess.run(["yt-dlp", "--version"], capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None

def get_latest_ytdlp_version(timeout=8):
    """Latest stable yt-dlp version from PyPI, or None if it can't be reached."""
    try:
        import urllib.request
        with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))["info"]["version"]
    except Exception:
        return None

def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))

def check_ytdlp_update(timeout=8):
    """Return {current, latest, update_available}. Needs network for `latest`;
    update_available is False when either version is unknown."""
    current = get_installed_ytdlp_version()
    latest = get_latest_ytdlp_version(timeout)
    available = bool(current and latest and _ver_tuple(current) < _ver_tuple(latest))
    return {"current": current, "latest": latest, "update_available": available}

def update_ytdlp(log=None):
    """Update yt-dlp via pip in the running interpreter's environment. Streams
    output through log (defaults to print). Returns True on success."""
    import sys
    logf = log or print
    logf("Updating yt-dlp (pip install -U yt-dlp)...")
    try:
        proc = subprocess.Popen([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            logf(line.rstrip())
        proc.wait()
        ok = proc.returncode == 0
        logf("yt-dlp update complete." if ok
             else f"yt-dlp update failed (exit code {proc.returncode}).")
        return ok
    except Exception as e:
        logf(f"yt-dlp update error: {e}")
        return False

def is_watch_url(url):
    """True if url points at a single video (a watch page or youtu.be link),
    even when it carries a '&list=...' mix/playlist parameter."""
    u = url.lower()
    return ("watch?v=" in u) or ("youtu.be/" in u) or ("/shorts/" in u)

def build_ytdlp_download_cmd(url, source_folder, resolution=None, container="mkv",
                             archive_file=None, no_playlist=False,
                             cookies_from_browser=None, js_runtime=None,
                             js_runtime_path=None, prefer_h264=True,
                             cookies_file=None, extra_args=None):
    """Construct the yt-dlp argument list for one URL. Factored out so it can be
    tested without actually downloading. resolution is a max height as a string
    ('2160'/'1080'/'720') or None for best. container is the merged output
    container ('mkv' or 'mp4'). archive_file, if given, skips already-downloaded
    videos (subscription-style 'only new'). no_playlist forces just the single
    video (used for watch URLs that carry a '&list=' mix). cookies_from_browser
    (e.g. 'chrome'/'firefox'/'edge'/'brave') passes browser cookies to work
    around 'HTTP 403 Forbidden' anti-bot blocks."""
    # Save as <source>/<Channel>/<Title> [<id>].<ext>
    outtmpl = os.path.join(source_folder, "%(uploader)s", "%(title)s [%(id)s].%(ext)s")

    if resolution:
        fmt = f"bv*[height<={resolution}]+ba/b[height<={resolution}]"
    else:
        fmt = "bv*+ba/b"

    cmd = [
        "yt-dlp",
        "-f", fmt,
    ]
    # Prefer H.264 (avc1) video and AAC audio. YouTube's high formats are often
    # AV1 (itags 399/400/401), which many players and Kodi hardware decoders
    # can't render -> audio plays but the picture is black. H.264 is universally
    # compatible. Falls back to whatever's available if H.264 isn't offered.
    if prefer_h264:
        cmd += ["-S", "vcodec:h264,res,acodec:aac"]
    cmd += [
        "--merge-output-format", container,
        # merge-output-format only applies when streams are merged; remux-video
        # also converts a single/already-combined format so the final file
        # always matches the chosen container (e.g. mkv, not mp4). Both are
        # no-ops when the file is already in the target container.
        "--remux-video", container,
        "-o", outtmpl,
        "--no-overwrites",
        "--ignore-errors",       # one bad item shouldn't abort a playlist/channel
        "--newline",             # one progress update per line (parseable)
        # Emit a machine-readable percent line a host can turn into a progress
        # bar. Prefixed with [PHPROGRESS] so the GUI can recognise and hide it.
        "--progress-template", "download:[PHPROGRESS] %(progress._percent_str)s",
    ]
    if no_playlist:
        cmd.append("--no-playlist")
    # yt-dlp only auto-uses Deno when it's on PATH. Tell it explicitly about
    # Node/Bun, or about a Deno found off-PATH (with its full path), otherwise
    # YouTube extraction without JS often yields audio-only or 403.
    if js_runtime and js_runtime_path:
        cmd += ["--js-runtimes", f"{js_runtime}:{js_runtime_path}"]
    elif js_runtime in ("node", "bun"):
        cmd += ["--js-runtimes", js_runtime]
    # YouTube now requires solving a JS "n challenge"; the JS runtime also needs
    # yt-dlp's EJS solver script (downloaded once from GitHub, then cached).
    # Without it: "n challenge solving failed" -> "Only images are available" ->
    # "Requested format is not available".
    if js_runtime:
        cmd += ["--remote-components", "ejs:github"]
    # A cookies.txt file is the most reliable auth path on Windows (Chrome
    # locks / app-bound-encrypts its cookie DB, breaking --cookies-from-browser).
    # It takes precedence over live browser extraction when both are set.
    if cookies_file:
        cmd += ["--cookies", cookies_file]
    elif cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    if archive_file:
        cmd += ["--download-archive", archive_file]
    # User-supplied extra yt-dlp args (escape hatch for YouTube's shifting
    # requirements, e.g. --extractor-args, PO-token settings). Appended last so
    # they can override earlier defaults.
    if extra_args:
        cmd += list(extra_args)
    cmd.append(url)
    return cmd

def download_urls(urls, source_folder, resolution=None, container="mkv",
                  archive_file=None, should_stop=None, whole_playlist=False,
                  cookies_from_browser=None, prefer_h264=True, cookies_file=None,
                  extra_args=None):
    """Download each URL (video, playlist, or channel) into source_folder via
    yt-dlp, streaming output through the logger. Returns (ok_count, fail_count).
    should_stop, if given, is polled to allow cancelling between and during
    downloads. whole_playlist=False makes a watch URL that carries a '&list='
    grab only the single video (not the whole auto-mix); set True to honour the
    list. cookies_from_browser works around HTTP 403 anti-bot errors."""
    if not YTDLP_AVAILABLE:
        log("ERROR: yt-dlp not found on PATH. Install it: pip install yt-dlp")
        return (0, 0)

    if isinstance(urls, str):
        urls = [urls]
    urls = [u.strip() for u in urls if u and u.strip()]
    if not urls:
        log("No URLs to download.")
        return (0, 0)

    os.makedirs(source_folder, exist_ok=True)

    # Detect a JS runtime once. yt-dlp only auto-uses Deno on PATH; Node/Bun or
    # an off-PATH Deno must be passed explicitly (see detect_js_runtime).
    js_runtime, js_runtime_path = detect_js_runtime()
    if js_runtime is None:
        log("WARNING: no JS runtime (deno/node/bun) found - YouTube may return "
            "audio-only or HTTP 403. Install Deno: winget install DenoLand.Deno")
    elif js_runtime_path:
        log(f"Using JS runtime: {js_runtime} (found off-PATH at {js_runtime_path})")
    elif js_runtime != "deno":
        log(f"Using JS runtime: {js_runtime}")

    ok = fail = 0
    for url in urls:
        if should_stop is not None and should_stop():
            log("Download cancelled.")
            break
        log(f"\nDownloading: {url}")
        # A watch URL that carries a '&list=' would otherwise pull the whole
        # (often auto-generated) mix; restrict to the single video unless the
        # caller explicitly wants the list.
        no_playlist = is_watch_url(url) and not whole_playlist
        if no_playlist and "list=" in url.lower():
            log("  (watch URL with a list - downloading just this video; "
                "enable 'Whole playlist/channel' to fetch the list)")
        cmd = build_ytdlp_download_cmd(url, source_folder, resolution, container,
                                       archive_file, no_playlist=no_playlist,
                                       cookies_from_browser=cookies_from_browser,
                                       js_runtime=js_runtime,
                                       js_runtime_path=js_runtime_path,
                                       prefer_h264=prefer_h264,
                                       cookies_file=cookies_file,
                                       extra_args=extra_args)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
        except Exception as e:
            log(f"  Failed to start yt-dlp: {e}")
            fail += 1
            continue

        try:
            for line in proc.stdout:
                log(line.rstrip())
                if should_stop is not None and should_stop():
                    log("  Stop requested - terminating download...")
                    proc.terminate()
                    break
            proc.wait()
        except Exception as e:
            log(f"  Download error: {e}")
            try:
                proc.terminate()
            except Exception:
                pass

        if proc.returncode == 0:
            ok += 1
        else:
            # --ignore-errors can still yield a non-zero code on partial channel
            # failures; report it but keep going.
            fail += 1
            log(f"  yt-dlp exited with code {proc.returncode} for: {url}")

    log(f"\nDownload finished. {ok} URL(s) ok, {fail} with errors.")
    return (ok, fail)

def sanitize_existing_nfos(root_folder):
    """Walk a folder and strip 4-byte characters from every .nfo in place.

    This fixes already-organized files whose NFOs contain emoji that Kodi's
    utf8 MySQL DB rejects (error 1366). Returns the list of episode-NFO base
    names (filename without extension) that were changed, so an optional Kodi
    refresh can target exactly those episodes.
    """
    changed_bases = []
    if not os.path.isdir(root_folder):
        log(f"Folder not found: {root_folder}")
        return changed_bases

    log(f"Scanning '{root_folder}' for .nfo files with 4-byte characters...")
    for dirpath, _dirs, files in os.walk(root_folder):
        for name in files:
            if not name.lower().endswith(".nfo"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    original = f.read()
            except (OSError, UnicodeDecodeError) as e:
                log(f"  Skipped (couldn't read): {path} ({e})")
                continue

            cleaned = strip_4byte_chars(original)
            if cleaned != original:
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(cleaned)
                except OSError as e:
                    log(f"  Skipped (couldn't write): {path} ({e})")
                    continue
                removed = len(original) - len(cleaned)
                log(f"  Cleaned {removed} char(s): {path}")
                # tvshow.nfo isn't an episode; don't queue it for episode refresh
                if name.lower() != "tvshow.nfo":
                    changed_bases.append(os.path.splitext(name)[0])

    log(f"\nDone. {len(changed_bases)} episode NFO(s) changed.")
    return changed_bases

def kodi_rpc(host, port, user, password, method, params=None):
    """Call Kodi's JSON-RPC endpoint and return the 'result' payload.

    Uses only the standard library so there's no extra dependency.
    """
    import urllib.request
    import base64

    url = f"http://{host}:{port}/jsonrpc"
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                headers={"Content-Type": "application/json"})
    if user:
        token = base64.b64encode(f"{user}:{password or ''}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")

    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("result")

def kodi_refresh_changed(changed_bases, host, port=8080, user=None, password=None):
    """Force Kodi to re-read the (now clean) NFOs for the changed episodes.

    A normal library scan won't re-read NFOs for files Kodi already knows, so
    we match each changed file to its Kodi episodeid (by video filename) and
    call VideoLibrary.RefreshEpisode, which re-ingests the local NFO.
    """
    if not changed_bases:
        log("Nothing to refresh in Kodi.")
        return

    log(f"\nAsking Kodi at {host}:{port} to refresh {len(changed_bases)} episode(s)...")
    try:
        result = kodi_rpc(host, port, user, password,
                          "VideoLibrary.GetEpisodes", {"properties": ["file"]})
    except Exception as e:
        log(f"Could not reach Kodi at {host}:{port} - {e}")
        log("Enable Settings > Services > Control > 'Allow remote control via HTTP' "
              "and pass --kodi-user/--kodi-pass if you set a username/password.")
        return

    # Map each known episode's video basename (no extension) -> episodeid
    by_base = {}
    for ep in (result or {}).get("episodes", []):
        base = os.path.splitext(os.path.basename(ep.get("file", "")))[0]
        if base:
            by_base[base] = ep["episodeid"]

    refreshed = 0
    for base in changed_bases:
        episode_id = by_base.get(base)
        if episode_id is None:
            log(f"  No Kodi match for: {base}")
            continue
        try:
            kodi_rpc(host, port, user, password, "VideoLibrary.RefreshEpisode",
                     {"episodeid": episode_id, "ignorenfo": False})
            refreshed += 1
        except Exception as e:
            log(f"  Refresh failed for {base}: {e}")
    log(f"Kodi refreshed {refreshed} of {len(changed_bases)} episode(s).")

def reset_show(show_name_input):
    """Scrap a show's saved data and start it over.

    Resets genre and plot (re-prompts for new values), and resets the episode
    counter so the NEXT file processed for this show becomes 01x01. The matched
    channel is preserved by default. If the show's destination folder already
    exists, its tvshow.nfo is regenerated so the show-level plot/genre update.
    """
    # Load existing data
    try:
        with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
            show_data = json.load(f)
    except FileNotFoundError:
        log(f"No {SUMMARY_FILE} found - there is no saved show data to reset.")
        return
    except json.JSONDecodeError:
        log(f"Error: {SUMMARY_FILE} is not valid JSON; cannot reset.")
        return

    # Resolve the show key the same way processing does (case-insensitive)
    show_key = show_name_input.strip().title()
    if show_key not in show_data:
        log(f"Show '{show_key}' not found in {SUMMARY_FILE}.")
        if show_data:
            log("Known shows:")
            for k in sorted(show_data.keys()):
                log(f"  - {k}")
        return

    current = show_data[show_key]
    log(f"\nCurrent data for '{show_key}':")
    log(f"  Season/Episode : {current.get('season', 1):02d}x{current.get('episode', 1):02d}")
    log(f"  Genre          : {current.get('genre')}")
    log(f"  Channel        : {current.get('channel')}")
    log(f"  Summary        : {current.get('summary')}")

    if input(f"\nScrap this data and start '{show_key}' over? (y/n): ").strip().lower() != 'y':
        log("Reset cancelled.")
        return

    # New plot/summary - offer a fresh suggestion like the new-show flow
    default_summary = suggest_show_summary(show_key)
    log(f"\nSuggested summary for '{show_key}':")
    log(f"----------\n{default_summary}\n----------")
    edit_choice = input("Accept this summary? (y/n/e - yes/no/edit): ").strip().lower()
    if edit_choice == 'n':
        new_summary = input("Enter new summary description: ").strip()
    elif edit_choice == 'e':
        new_summary = input("Edit summary: ").strip()
    else:
        new_summary = default_summary

    # New genre
    new_genre = input("Enter new genre (blank to clear): ").strip() or None

    # Channel - preserve by default
    current_channel = current.get('channel')
    if current_channel:
        if input(f"Keep matched channel '{current_channel}'? (y/n): ").strip().lower() == 'n':
            new_channel = input("Enter new channel URL/@handle (blank for none): ").strip() or None
        else:
            new_channel = current_channel
    else:
        new_channel = input("Enter channel URL/@handle to match (blank for none): ").strip() or None

    # Rewrite the entry. episode=0 so the next processed file increments to 1,
    # i.e. starts at 01x01.
    show_data[show_key] = {
        "season": 1,
        "episode": 0,
        "genre": new_genre,
        "summary": new_summary,
        "channel": new_channel
    }

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(show_data, f, indent=4)
    log(f"\n'{show_key}' has been reset. The next file processed will start at 01x01.")

    # Refresh show-level metadata if the destination folder already exists
    show_folder = os.path.join(DESTINATION_FOLDER, show_key)
    if os.path.isdir(show_folder):
        generate_tvshow_nfo(show_key, new_genre, new_summary, show_folder)
        log(f"Updated show metadata: {os.path.join(show_folder, 'tvshow.nfo')}")
    else:
        log("(Destination folder doesn't exist yet; tvshow.nfo will be created on the next run.)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Organize video files into show folders.")
    parser.add_argument("-g", "--genre", help="Default genre for all shows.", default=None)
    parser.add_argument("-n", "--nfo", choices=["skip", "overwrite", "ask"], default="skip",
                        help="NFO handling: 'skip' (default), 'overwrite', 'ask'.")
    parser.add_argument("-m", "--monitor", action="store_true", 
                        help="Enable auto-monitoring mode (watches for new files).")
    parser.add_argument("-s", "--source", default=None,
                        help=f"Source folder to scan (default: {SOURCE_FOLDER}).")
    parser.add_argument("-d", "--dest", default=None,
                        help=f"Destination folder for organized files (default: {DESTINATION_FOLDER}).")
    parser.add_argument("-c", "--channel", default=None,
                        help="YouTube channel URL, @handle, or UC... ID to scope title "
                             "searches to. Used as the default for shows that don't already "
                             "have a channel saved; you can still override per-show when prompted.")
    parser.add_argument("-r", "--reset", default=None, metavar="SHOW",
                        help="Scrap a saved show's data and start it over (new genre, "
                             "plot, and numbering from 01x01). Pass the show name, e.g. "
                             "--reset \"Lofi Girl\". Channel is preserved by default.")
    parser.add_argument("--sanitize", action="store_true",
                        help="Strip 4-byte characters (emoji) from every existing .nfo in "
                             "the destination folder, fixing Kodi MySQL error 1366. "
                             "Add --kodi-host to also make Kodi re-read the cleaned files.")
    parser.add_argument("--kodi-host", default=None,
                        help="Kodi host/IP for an automatic library refresh after --sanitize "
                             "(e.g. 10.0.0.39). Requires Kodi's HTTP remote control.")
    parser.add_argument("--kodi-port", type=int, default=8080,
                        help="Kodi JSON-RPC port (default: 8080).")
    parser.add_argument("--kodi-user", default=None, help="Kodi remote-control username.")
    parser.add_argument("--kodi-pass", default=None, help="Kodi remote-control password.")
    args = parser.parse_args()

    # Apply CLI path overrides to the module globals so every function
    # (including the watchdog handler, which reads the globals) sees them.
    if args.source:
        SOURCE_FOLDER = args.source
    if args.dest:
        DESTINATION_FOLDER = args.dest
    if args.channel:
        DEFAULT_CHANNEL = args.channel

    # Reset mode runs by itself and then exits, without processing any files.
    if args.reset:
        reset_show(args.reset)
    elif args.sanitize:
        changed = sanitize_existing_nfos(DESTINATION_FOLDER)
        if args.kodi_host:
            kodi_refresh_changed(changed, args.kodi_host, args.kodi_port,
                                 args.kodi_user, args.kodi_pass)
        elif changed:
            log("\nNFOs cleaned. In Kodi, refresh those items (or re-run with "
                  "--kodi-host) so it re-reads the fixed metadata.")
    else:
        log("Welcome to the Video Organizer!")

        if args.genre is None:
            genre_choice = input("Use a default genre for all shows? (y/n): ").strip().lower()
            if genre_choice == 'y':
                args.genre = input("Enter the default genre: ").strip()

        if args.monitor or AUTO_MONITOR:
            run_auto_monitor(args.genre, args.nfo)
        else:
            process_videos(args.genre, args.nfo)
            log("\nProcessing complete!")