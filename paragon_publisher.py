#!/usr/bin/env python3
"""
PyRenamer - A Smart File Renamer (Paragon Edition)
A powerful bulk file renaming tool with modern CustomTkinter GUI

Features:
- Replace text, Remove characters, Insert text
- Trim, Add prefix/suffix, Add numbers/sequence
- Change case, Regex support
- EXIF metadata for photos, ID3 tags for audio
- Date/time insertion, Live preview
- Dark/Light themes, Undo support, Rule chaining
- Drag & Drop support
- MP3tag-style tag editor with MusicBrainz lookup
"""

import os
import re
import json
import io
from datetime import datetime
import urllib.request
import urllib.parse
import customtkinter as ctk
from tkinter import filedialog, messagebox
import tkinter as tk
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict, Any
from enum import Enum
import threading

# Optional dependencies - graceful fallback
try:
    from PIL import Image, ImageTk
    from PIL.ExifTags import TAGS
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from mutagen import File as MutagenFile
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TRCK, TCON, COMM, TPE2, TCOM, TPOS
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggvorbis import OggVorbis
    import io
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

# Drag and drop support
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False


# =============================================================================
# MOUSE WHEEL SCROLL FIX FOR CUSTOMTKINTER
# =============================================================================

def bind_mousewheel_to_scrollable(widget, scrollable_frame):
    """Bind mouse wheel events to a CTkScrollableFrame for proper scrolling.
    
    This fixes the common issue where mouse wheel doesn't work in CustomTkinter
    scrollable frames. Call this on any widget inside a scrollable frame.
    """
    def _on_mousewheel(event):
        # Get the canvas inside the scrollable frame
        try:
            canvas = scrollable_frame._parent_canvas
            if canvas.winfo_exists():
                # Linux uses Button-4/5, Windows/Mac use MouseWheel
                if event.num == 4 or event.delta > 0:
                    canvas.yview_scroll(-1, "units")
                elif event.num == 5 or event.delta < 0:
                    canvas.yview_scroll(1, "units")
        except:
            pass
    
    # Bind for different platforms
    widget.bind("<MouseWheel>", _on_mousewheel)  # Windows/Mac
    widget.bind("<Button-4>", _on_mousewheel)    # Linux scroll up
    widget.bind("<Button-5>", _on_mousewheel)    # Linux scroll down


def enable_mousewheel_scrolling(root):
    """Enable mouse wheel scrolling globally for all CTkScrollableFrames.
    
    This patches CTkScrollableFrame to automatically bind mouse wheel events
    when widgets are added to it.
    """
    def _bind_to_all_children(scrollable_frame):
        """Recursively bind mouse wheel to all children of a scrollable frame"""
        def _on_mousewheel(event):
            try:
                canvas = scrollable_frame._parent_canvas
                if canvas.winfo_exists():
                    if event.num == 4 or event.delta > 0:
                        canvas.yview_scroll(-1, "units")
                    elif event.num == 5 or event.delta < 0:
                        canvas.yview_scroll(1, "units")
            except:
                pass
        
        def bind_recursive(widget):
            try:
                widget.bind("<MouseWheel>", _on_mousewheel)
                widget.bind("<Button-4>", _on_mousewheel)
                widget.bind("<Button-5>", _on_mousewheel)
                for child in widget.winfo_children():
                    bind_recursive(child)
            except:
                pass
        
        bind_recursive(scrollable_frame)
    
    # Override CTkScrollableFrame to auto-bind mouse wheel
    original_init = ctk.CTkScrollableFrame.__init__
    
    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        
        def _on_mousewheel(event):
            try:
                canvas = self._parent_canvas
                if canvas.winfo_exists():
                    if event.num == 4 or event.delta > 0:
                        canvas.yview_scroll(-1, "units")
                    elif event.num == 5 or event.delta < 0:
                        canvas.yview_scroll(1, "units")
            except:
                pass
        
        # Bind to the frame itself
        self.bind("<MouseWheel>", _on_mousewheel)
        self.bind("<Button-4>", _on_mousewheel)
        self.bind("<Button-5>", _on_mousewheel)
        
        # Also bind to the internal canvas
        try:
            self._parent_canvas.bind("<MouseWheel>", _on_mousewheel)
            self._parent_canvas.bind("<Button-4>", _on_mousewheel)
            self._parent_canvas.bind("<Button-5>", _on_mousewheel)
        except:
            pass
        
        # Bind when entering the scrollable area
        def _on_enter(event):
            _bind_to_all_children(self)
        
        self.bind("<Enter>", _on_enter)
    
    ctk.CTkScrollableFrame.__init__ = patched_init


# =============================================================================
# LIBRARY CACHE SYSTEM
# =============================================================================

class LibraryCache:
    """Cache system for library scanning to speed up loading on network shares"""
    
    CACHE_DIR = Path.home() / ".pyrenamer_cache"
    CACHE_VERSION = 1  # Increment to invalidate old caches
    
    @classmethod
    def _get_cache_path(cls, library_type: str, library_path: str) -> Path:
        """Get the cache file path for a library"""
        cls.CACHE_DIR.mkdir(exist_ok=True)
        # Create a safe filename from the path
        import hashlib
        path_hash = hashlib.md5(library_path.encode()).hexdigest()[:12]
        return cls.CACHE_DIR / f"{library_type}_{path_hash}.json"
    
    @classmethod
    def load_cache(cls, library_type: str, library_path: str) -> Optional[List[Dict]]:
        """Load cached library data if available"""
        cache_path = cls._get_cache_path(library_type, library_path)
        
        try:
            if cache_path.exists():
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Check cache version
                if data.get('version') != cls.CACHE_VERSION:
                    return None
                
                # Check if library path matches
                if data.get('library_path') != library_path:
                    return None
                
                return data.get('items', [])
        except Exception as e:
            print(f"Cache load error: {e}")
        
        return None
    
    @classmethod
    def save_cache(cls, library_type: str, library_path: str, items: List[Dict]):
        """Save library data to cache"""
        cache_path = cls._get_cache_path(library_type, library_path)
        
        try:
            # Filter out non-serializable items (like PIL images)
            clean_items = []
            for item in items:
                clean_item = {}
                for k, v in item.items():
                    # Skip non-JSON-serializable values
                    if isinstance(v, (str, int, float, bool, type(None), list, dict)):
                        clean_item[k] = v
                clean_items.append(clean_item)
            
            data = {
                'version': cls.CACHE_VERSION,
                'library_path': library_path,
                'cached_at': datetime.now().isoformat(),
                'items': clean_items
            }
            
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Cache save error: {e}")
    
    @classmethod
    def clear_cache(cls, library_type: str = None, library_path: str = None):
        """Clear cache files"""
        try:
            if library_type and library_path:
                # Clear specific cache
                cache_path = cls._get_cache_path(library_type, library_path)
                if cache_path.exists():
                    cache_path.unlink()
            else:
                # Clear all caches
                if cls.CACHE_DIR.exists():
                    for f in cls.CACHE_DIR.glob("*.json"):
                        f.unlink()
        except Exception as e:
            print(f"Cache clear error: {e}")


# =============================================================================
# PARAGON COLOR SCHEME
# =============================================================================

class ParagonTheme:
    """Paragon TV inspired color scheme - Pink & Orange edition"""
    
    # Core colors
    BG_DARK = "#0a0a0a"           # Main background
    BG_SECONDARY = "#111111"      # Panel backgrounds
    BG_TERTIARY = "#1a1a1a"       # Card/input backgrounds
    BG_HOVER = "#252525"          # Hover states
    
    # Accent colors
    RED_PRIMARY = "#cc2200"       # Primary red
    RED_LIGHT = "#ff4444"         # Bright Red - PYRENAMER title
    RED_DARK = "#8b1500"          # Darker red
    ORANGE = "#ff4444"            # Bright Red accent
    GOLD = "#ff6600"              # Orange - buttons, highlights
    GOLD_LIGHT = "#ff8533"        # Lighter orange
    
    # Text colors
    TEXT_PRIMARY = "#ffffff"      # Main text
    TEXT_SECONDARY = "#b0b0b0"    # Muted text
    TEXT_MUTED = "#777777"        # Even more muted text
    TEXT_DISABLED = "#666666"     # Disabled text
    
    # Status colors
    SUCCESS = "#44dd88"           # Green for success/changes
    ERROR = "#ff4444"             # Red for errors
    WARNING = "#ffaa00"           # Warning yellow
    
    # Border colors
    BORDER_GOLD = "#ff6600"       # Orange borders
    BORDER_RED = "#8b1500"        # Red borders
    BORDER_DARK = "#333333"       # Subtle borders


# =============================================================================
# RENAME RULES
# =============================================================================

@dataclass
class RenameRule:
    """Base class for rename rules"""
    enabled: bool = True
    name: str = ""
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        raise NotImplementedError


@dataclass
class ReplaceRule(RenameRule):
    """Find and replace text"""
    name: str = "Replace"
    find: str = ""
    replace: str = ""
    use_regex: bool = False
    case_sensitive: bool = True
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        if not self.enabled or not self.find:
            return filename
        
        if self.use_regex:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            try:
                return re.sub(self.find, self.replace, filename, flags=flags)
            except re.error:
                return filename
        else:
            if self.case_sensitive:
                return filename.replace(self.find, self.replace)
            else:
                pattern = re.compile(re.escape(self.find), re.IGNORECASE)
                return pattern.sub(self.replace, filename)


@dataclass
class RemoveRule(RenameRule):
    """Remove characters from filename"""
    name: str = "Remove"
    start_pos: int = 0
    count: int = 0
    from_end: bool = False
    remove_digits: bool = False
    remove_spaces: bool = False
    remove_illegal: bool = False      # \ / : * ? " < > |
    remove_brackets: bool = False     # ( ) [ ] { }
    remove_punctuation: bool = False  # ! @ # $ % ^ & ~ ` ; ' ,
    remove_all_special: bool = False  # All non-alphanumeric except spaces
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        if not self.enabled:
            return filename
        
        result = filename
        
        if self.count > 0:
            if self.from_end:
                if self.start_pos == 0:
                    result = result[:-self.count] if self.count < len(result) else ""
                else:
                    end_pos = len(result) - self.start_pos
                    start_pos = end_pos - self.count
                    if start_pos >= 0 and end_pos <= len(result):
                        result = result[:start_pos] + result[end_pos:]
            else:
                end_pos = self.start_pos + self.count
                result = result[:self.start_pos] + result[end_pos:]
        
        if self.remove_digits:
            result = re.sub(r'\d', '', result)
        if self.remove_spaces:
            result = result.replace(' ', '')
        
        # Illegal file characters: \ / : * ? " < > |
        if self.remove_illegal:
            result = re.sub(r'[\\/:*?"<>|]', '', result)
        
        # Brackets: ( ) [ ] { }
        if self.remove_brackets:
            result = re.sub(r'[\(\)\[\]\{\}]', '', result)
        
        # Punctuation: ! @ # $ % ^ & ~ ` ; ' ,
        if self.remove_punctuation:
            result = re.sub(r'[!@#$%^&~`;\',.]+', '', result)
        
        # All non-alphanumeric (keep spaces and dashes for readability)
        if self.remove_all_special:
            result = re.sub(r'[^\w\s\-]', '', result)
        
        # Clean up multiple spaces
        if self.remove_illegal or self.remove_brackets or self.remove_punctuation or self.remove_all_special:
            result = re.sub(r'\s+', ' ', result).strip()
        
        return result


@dataclass
class InsertRule(RenameRule):
    """Insert text at position"""
    name: str = "Insert"
    text: str = ""
    position: int = 0
    from_end: bool = False
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        if not self.enabled or not self.text:
            return filename
        
        if self.from_end:
            pos = len(filename) - self.position
        else:
            pos = self.position
        
        pos = max(0, min(pos, len(filename)))
        return filename[:pos] + self.text + filename[pos:]


@dataclass
class CaseRule(RenameRule):
    """Change case of filename"""
    name: str = "Change Case"
    case_type: str = "lower"
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        if not self.enabled:
            return filename
        
        if self.case_type == "lower":
            return filename.lower()
        elif self.case_type == "upper":
            return filename.upper()
        elif self.case_type == "title":
            return filename.title()
        elif self.case_type == "sentence":
            return filename.capitalize()
        elif self.case_type == "swap":
            return filename.swapcase()
        
        return filename


@dataclass
class SwapRule(RenameRule):
    """Swap segments around a delimiter (e.g., 'Artist - Title' -> 'Title - Artist')"""
    name: str = "Swap"
    delimiter: str = " - "
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        if not self.enabled:
            return filename
        
        # Only swap if delimiter exists
        if self.delimiter not in filename:
            return filename
        
        # Split by delimiter and reverse the parts
        parts = filename.split(self.delimiter)
        return self.delimiter.join(reversed(parts))


@dataclass
class NumberRule(RenameRule):
    """Add sequential numbers"""
    name: str = "Add Number"
    start: int = 1
    step: int = 1
    padding: int = 2
    position: str = "suffix"
    separator: str = "_"
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        if not self.enabled:
            return filename
        
        number = self.start + (index * self.step)
        num_str = str(number).zfill(self.padding)
        
        if self.position == "prefix":
            return f"{num_str}{self.separator}{filename}"
        elif self.position == "suffix":
            return f"{filename}{self.separator}{num_str}"
        elif self.position == "replace":
            return num_str
        
        return filename


@dataclass
class TVShowRule(RenameRule):
    """TV Show season/episode numbering"""
    name: str = "TV Show"
    season: int = 1
    episode_start: int = 1
    episode_step: int = 1
    max_episodes: int = 0  # 0 = unlimited (no auto-season increment)
    format_style: str = "S00E00"  # S00E00, 00x00, Season 0 Episode 0
    separator: str = " - "
    position: str = "prefix"
    include_show_name: bool = False
    show_name: str = ""
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        if not self.enabled:
            return filename
        
        # Calculate episode number
        episode = self.episode_start + (index * self.episode_step)
        season = self.season
        
        # Handle auto-season increment if max_episodes is set
        if self.max_episodes > 0:
            # Calculate how many complete seasons we've passed
            total_eps = self.episode_start - 1 + (index * self.episode_step)
            seasons_passed = total_eps // self.max_episodes
            episode = (total_eps % self.max_episodes) + 1
            season = self.season + seasons_passed
        
        # Format the season/episode string based on style
        if self.format_style == "S00E00":
            se_str = f"S{str(season).zfill(2)}E{str(episode).zfill(2)}"
        elif self.format_style == "00x00":
            se_str = f"{str(season).zfill(2)}x{str(episode).zfill(2)}"
        elif self.format_style == "0x00":
            se_str = f"{season}x{str(episode).zfill(2)}"
        elif self.format_style == "Season 0 Episode 0":
            se_str = f"Season {season} Episode {episode}"
        elif self.format_style == "s0e0":
            se_str = f"s{season}e{episode}"
        else:
            se_str = f"S{str(season).zfill(2)}E{str(episode).zfill(2)}"
        
        # Add show name if enabled
        if self.include_show_name and self.show_name:
            se_str = f"{self.show_name}{self.separator}{se_str}"
        
        # Apply to filename
        if self.position == "prefix":
            return f"{se_str}{self.separator}{filename}"
        elif self.position == "replace":
            return se_str
        elif self.position == "suffix":
            return f"{filename}{self.separator}{se_str}"
        
        return filename


@dataclass
class DateTimeRule(RenameRule):
    """Add date/time to filename"""
    name: str = "Date/Time"
    format: str = "%Y-%m-%d"
    use_file_date: bool = True
    position: str = "prefix"
    separator: str = "_"
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        if not self.enabled:
            return filename
        
        if self.use_file_date and 'modified_date' in metadata:
            dt = metadata['modified_date']
        else:
            dt = datetime.now()
        
        try:
            date_str = dt.strftime(self.format)
        except ValueError:
            date_str = dt.strftime("%Y-%m-%d")
        
        if self.position == "prefix":
            return f"{date_str}{self.separator}{filename}"
        elif self.position == "suffix":
            return f"{filename}{self.separator}{date_str}"
        
        return filename


@dataclass
class MetadataRule(RenameRule):
    """Rename based on file metadata"""
    name: str = "Metadata"
    template: str = "{artist} - {title}"
    fallback: str = "{original}"
    
    def apply(self, filename: str, index: int, metadata: dict) -> str:
        if not self.enabled:
            return filename
        
        template = self.template
        result = template
        
        placeholders = re.findall(r'\{(\w+)\}', template)
        
        for placeholder in placeholders:
            if placeholder == "original":
                value = filename
            elif placeholder in metadata:
                value = str(metadata[placeholder])
            else:
                value = None
            
            if value:
                result = result.replace(f"{{{placeholder}}}", value)
            else:
                result = self.fallback.replace("{original}", filename)
                break
        
        result = re.sub(r'[<>:"/\\|?*]', '_', result)
        return result


# =============================================================================
# FILE HANDLING
# =============================================================================

class FileItem:
    """Represents a file to be renamed"""
    def __init__(self, path: str):
        self.path = path
        self.original_name = os.path.basename(path)
        self.name_without_ext = os.path.splitext(self.original_name)[0]
        self.extension = os.path.splitext(self.original_name)[1]
        self.new_name = self.original_name
        self.metadata: Dict[str, Any] = {}
        self._load_metadata()
    
    @property
    def size(self) -> int:
        """File size in bytes"""
        return self.metadata.get('size', 0)
    
    @property
    def modified_date(self) -> Optional[datetime]:
        """File modification date"""
        return self.metadata.get('modified_date')
    
    def _load_metadata(self):
        try:
            stat = os.stat(self.path)
            self.metadata['modified_date'] = datetime.fromtimestamp(stat.st_mtime)
            self.metadata['created_date'] = datetime.fromtimestamp(stat.st_ctime)
            self.metadata['size'] = stat.st_size
        except OSError:
            pass
        
        if HAS_PIL and self.extension.lower() in ['.jpg', '.jpeg', '.png', '.tiff', '.webp']:
            self._load_exif()
        
        if HAS_MUTAGEN and self.extension.lower() in ['.mp3', '.flac', '.ogg', '.m4a', '.wav']:
            self._load_audio_tags()
    
    def _load_exif(self):
        try:
            with Image.open(self.path) as img:
                exif_data = img._getexif()
                if exif_data:
                    for tag_id, value in exif_data.items():
                        tag = TAGS.get(tag_id, tag_id)
                        if isinstance(value, bytes):
                            continue
                        self.metadata[tag.lower()] = value
        except Exception:
            pass
    
    def _load_audio_tags(self):
        try:
            audio = MutagenFile(self.path, easy=True)
            if audio:
                for key in ['title', 'artist', 'album', 'date', 'genre', 'tracknumber']:
                    if key in audio:
                        value = audio[key]
                        if isinstance(value, list):
                            value = value[0]
                        self.metadata[key] = str(value)
        except Exception:
            pass


class UndoManager:
    """Manages undo operations"""
    def __init__(self):
        self.history: List[List[tuple]] = []
        self.max_history = 50
    
    def save_state(self, renames: List[tuple]):
        self.history.append(renames)
        if len(self.history) > self.max_history:
            self.history.pop(0)
    
    def can_undo(self) -> bool:
        return len(self.history) > 0
    
    def undo(self) -> Optional[List[tuple]]:
        if not self.history:
            return None
        last_operation = self.history.pop()
        return [(new_path, old_path) for old_path, new_path in last_operation]


# =============================================================================
# TAG MANAGER - MP3TAG-STYLE FUNCTIONALITY
# =============================================================================

class TagManager:
    """Handles reading/writing audio file tags (MP3tag-style)"""
    
    # Supported audio extensions
    AUDIO_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.mp4', '.ogg', '.opus', '.wma', '.wav', '.aiff', '.ape'}
    
    # Core tag fields (MP3tag compatible names)
    CORE_FIELDS = ['title', 'artist', 'album', 'year', 'track', 'genre', 'comment', 'albumartist']
    
    # Extended tag fields
    EXTENDED_FIELDS = ['composer', 'discnumber', 'bpm', 'compilation', 'publisher', 'copyright', 
                       'encodedby', 'mood', 'isrc', 'lyrics', 'conductor', 'remixer', 'language']
    
    @staticmethod
    def is_audio_file(filepath: str) -> bool:
        """Check if file is a supported audio format"""
        ext = os.path.splitext(filepath)[1].lower()
        return ext in TagManager.AUDIO_EXTENSIONS
    
    @staticmethod
    def read_tags(filepath: str) -> Dict[str, Any]:
        """Read all tags from an audio file"""
        if not HAS_MUTAGEN:
            return {}
        
        print(f"Reading tags from: {filepath}")
        
        try:
            audio = MutagenFile(filepath, easy=True)
            if audio is None:
                return {}
            
            tags = {}
            
            # EasyID3 field names to read
            easyid3_fields = ['title', 'artist', 'album', 'albumartist', 'date', 'tracknumber', 
                             'discnumber', 'genre', 'comment', 'composer', 'bpm', 'copyright',
                             'encodedby', 'mood', 'conductor']
            
            # Read fields
            for field in easyid3_fields:
                value = audio.get(field)
                if value:
                    val = value[0] if isinstance(value, list) else value
                    tags[field] = val
                    
                    # Also provide common aliases
                    if field == 'date':
                        tags['year'] = val
                    elif field == 'tracknumber':
                        tags['track'] = val
                    elif field == 'discnumber':
                        tags['disc'] = val
            
            # Get duration and bitrate
            if hasattr(audio, 'info'):
                if hasattr(audio.info, 'length'):
                    tags['_duration'] = audio.info.length
                if hasattr(audio.info, 'bitrate'):
                    tags['_bitrate'] = audio.info.bitrate
                if hasattr(audio.info, 'sample_rate'):
                    tags['_samplerate'] = audio.info.sample_rate
            
            print(f"Read tags: {tags}")
            return tags
            
        except Exception as e:
            print(f"Error reading tags from {filepath}: {e}")
            return {}
    
    # Map common tag names to EasyID3 keys
    TAG_KEY_MAP = {
        'year': 'date',
        'track': 'tracknumber',
        'disc': 'discnumber',
        'comment': 'comment',  # Keep as is but might need special handling
    }
    
    # Reverse map for reading
    TAG_KEY_REVERSE_MAP = {v: k for k, v in TAG_KEY_MAP.items()}
    
    @staticmethod
    def _normalize_tag_key(key: str, for_write: bool = True) -> str:
        """Normalize tag key for reading/writing"""
        key_lower = key.lower()
        if for_write:
            return TagManager.TAG_KEY_MAP.get(key_lower, key_lower)
        else:
            return TagManager.TAG_KEY_REVERSE_MAP.get(key_lower, key_lower)
    
    @staticmethod
    def write_tags(filepath: str, tags: Dict[str, str]) -> bool:
        """Write tags to an audio file"""
        if not HAS_MUTAGEN:
            print("Mutagen not available")
            return False
        
        if not tags:
            print("No tags to write")
            return False
        
        print(f"Writing tags to: {filepath}")
        print(f"Tags to write: {tags}")
        
        # Check if file is writable
        if not os.access(filepath, os.W_OK):
            print(f"ERROR: File is not writable: {filepath}")
            return False
        
        try:
            ext = os.path.splitext(filepath)[1].lower()
            
            # For MP3, use full ID3 interface to preserve APIC frames
            if ext == '.mp3':
                audio = MP3(filepath)
                if audio.tags is None:
                    audio.add_tags()
                
                # Map of tag names to ID3 frame classes
                id3_map = {
                    'title': ('TIT2', TIT2),
                    'artist': ('TPE1', TPE1),
                    'album': ('TALB', TALB),
                    'albumartist': ('TPE2', TPE2),
                    'year': ('TDRC', TDRC),
                    'date': ('TDRC', TDRC),
                    'track': ('TRCK', TRCK),
                    'tracknumber': ('TRCK', TRCK),
                    'genre': ('TCON', TCON),
                    'composer': ('TCOM', TCOM),
                    'discnumber': ('TPOS', TPOS),
                }
                
                for field, value in tags.items():
                    if field.startswith('_'):
                        continue
                    
                    field_lower = field.lower()
                    if field_lower in id3_map:
                        frame_id, frame_class = id3_map[field_lower]
                        print(f"  Writing {field} -> {frame_id} = '{value}'")
                        
                        # Remove existing frame
                        audio.tags.delall(frame_id)
                        
                        if value:
                            # Add new frame
                            audio.tags.add(frame_class(encoding=3, text=value))
                            print(f"    Success")
                    else:
                        print(f"  Skipping unknown field: {field}")
                
                # Save with v2_version=3 for compatibility, preserving all frames including APIC
                print("Saving audio file (preserving APIC)...")
                audio.save(v2_version=3)
                print("Save called!")
                
                # Verify cover art still exists
                verify = MP3(filepath)
                has_cover = any(isinstance(tag, APIC) for tag in verify.tags.values())
                print(f"Cover art preserved: {has_cover}")
                
            else:
                # For other formats, use easy mode
                audio = MutagenFile(filepath, easy=True)
                
                if audio is None:
                    print(f"Could not open audio file: {filepath}")
                    return False
                
                print(f"Audio object type: {type(audio)}")
                
                for field, value in tags.items():
                    if field.startswith('_'):
                        continue
                    
                    normalized_key = TagManager._normalize_tag_key(field, for_write=True)
                    print(f"  Writing {field} -> {normalized_key} = '{value}'")
                    
                    if value:
                        try:
                            audio[normalized_key] = value
                            print(f"    Success")
                        except Exception as e:
                            print(f"    Failed: {e}")
                    elif normalized_key in audio:
                        del audio[normalized_key]
                
                print("Saving audio file...")
                audio.save()
                print("Save called!")
            
            print("Save successful!")
            return True
            
        except Exception as e:
            print(f"Error writing tags to {filepath}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    @staticmethod
    def read_cover_art(filepath: str) -> Optional[bytes]:
        """Extract cover art from audio file"""
        if not HAS_MUTAGEN:
            return None
        
        try:
            ext = os.path.splitext(filepath)[1].lower()
            
            if ext == '.mp3':
                audio = MP3(filepath)
                for tag in audio.tags.values():
                    if isinstance(tag, APIC):
                        return tag.data
                        
            elif ext == '.flac':
                audio = FLAC(filepath)
                if audio.pictures:
                    return audio.pictures[0].data
                    
            elif ext in ['.m4a', '.mp4']:
                audio = MP4(filepath)
                covers = audio.tags.get('covr')
                if covers:
                    return bytes(covers[0])
                    
            elif ext in ['.ogg', '.opus']:
                audio = MutagenFile(filepath)
                if hasattr(audio, 'pictures') and audio.pictures:
                    return audio.pictures[0].data
                # Check for base64 encoded picture in metadata
                if 'metadata_block_picture' in audio:
                    import base64
                    data = base64.b64decode(audio['metadata_block_picture'][0])
                    # Parse FLAC picture block
                    pic = Picture(data)
                    return pic.data
                    
        except Exception as e:
            print(f"Error reading cover art from {filepath}: {e}")
        
        return None
    
    @staticmethod
    def write_cover_art(filepath: str, image_data: bytes, mime_type: str = 'image/jpeg') -> bool:
        """Write cover art to audio file"""
        if not HAS_MUTAGEN:
            print("write_cover_art: Mutagen not available")
            return False
        
        print(f"write_cover_art: Writing to {filepath}")
        print(f"write_cover_art: Image data size: {len(image_data)} bytes, mime: {mime_type}")
        
        try:
            ext = os.path.splitext(filepath)[1].lower()
            
            if ext == '.mp3':
                audio = MP3(filepath)
                if audio.tags is None:
                    print("write_cover_art: Adding ID3 tags")
                    audio.add_tags()
                
                # Remove existing covers
                audio.tags.delall('APIC')
                print("write_cover_art: Removed existing APIC frames")
                
                # Add new cover
                audio.tags.add(APIC(
                    encoding=3,  # UTF-8
                    mime=mime_type,
                    type=3,  # Front cover
                    desc='Cover',
                    data=image_data
                ))
                print("write_cover_art: Added new APIC frame")
                audio.save(v2_version=3)  # Save as ID3v2.3 for compatibility
                print("write_cover_art: Saved successfully")
                
                # Verify it was saved
                verify = MP3(filepath)
                has_cover = False
                for tag in verify.tags.values():
                    if isinstance(tag, APIC):
                        has_cover = True
                        print(f"write_cover_art: VERIFIED - Cover art exists, size: {len(tag.data)} bytes")
                        break
                if not has_cover:
                    print("write_cover_art: WARNING - Cover art NOT found after save!")
                
                return True
                
            elif ext == '.flac':
                audio = FLAC(filepath)
                
                # Clear existing pictures
                audio.clear_pictures()
                
                # Create new picture
                pic = Picture()
                pic.type = 3  # Front cover
                pic.mime = mime_type
                pic.desc = 'Cover'
                pic.data = image_data
                
                # Get image dimensions if PIL available
                if HAS_PIL:
                    img = Image.open(io.BytesIO(image_data))
                    pic.width, pic.height = img.size
                    pic.depth = 24
                
                audio.add_picture(pic)
                audio.save()
                return True
                
            elif ext in ['.m4a', '.mp4']:
                audio = MP4(filepath)
                
                # Determine format
                if mime_type == 'image/png':
                    img_format = MP4Cover.FORMAT_PNG
                else:
                    img_format = MP4Cover.FORMAT_JPEG
                
                audio.tags['covr'] = [MP4Cover(image_data, imageformat=img_format)]
                audio.save()
                return True
                
        except Exception as e:
            print(f"Error writing cover art to {filepath}: {e}")
        
        return False
    
    @staticmethod
    def remove_cover_art(filepath: str) -> bool:
        """Remove cover art from audio file"""
        if not HAS_MUTAGEN:
            return False
        
        try:
            ext = os.path.splitext(filepath)[1].lower()
            
            if ext == '.mp3':
                audio = MP3(filepath)
                if audio.tags:
                    audio.tags.delall('APIC')
                    audio.save()
                return True
                
            elif ext == '.flac':
                audio = FLAC(filepath)
                audio.clear_pictures()
                audio.save()
                return True
                
            elif ext in ['.m4a', '.mp4']:
                audio = MP4(filepath)
                if 'covr' in audio.tags:
                    del audio.tags['covr']
                    audio.save()
                return True
                
        except Exception as e:
            print(f"Error removing cover art from {filepath}: {e}")
        
        return False
    
    @staticmethod
    def remove_all_tags(filepath: str) -> bool:
        """Remove all tags from audio file"""
        if not HAS_MUTAGEN:
            return False
        
        try:
            audio = MutagenFile(filepath)
            if audio is not None:
                audio.delete()
                audio.save()
                return True
        except Exception as e:
            print(f"Error removing tags from {filepath}: {e}")
        
        return False
    
    @staticmethod
    def filename_to_tags(filepath: str, pattern: str) -> Dict[str, str]:
        """Parse filename using pattern and extract tags (Filename -> Tag)
        
        Pattern placeholders: %artist%, %title%, %album%, %year%, %track%, %genre%
        Example: "%artist% - %title%" parses "Pink Floyd - Comfortably Numb.mp3"
        """
        filename = os.path.splitext(os.path.basename(filepath))[0]
        
        # Convert MP3tag-style placeholders to regex groups
        regex_pattern = pattern
        placeholders = re.findall(r'%(\w+)%', pattern)
        
        for placeholder in placeholders:
            # Replace placeholder with named capture group
            regex_pattern = regex_pattern.replace(f'%{placeholder}%', f'(?P<{placeholder}>.+?)')
        
        # Escape special regex chars except our groups
        # First, temporarily replace our groups
        temp_pattern = regex_pattern
        for placeholder in placeholders:
            temp_pattern = temp_pattern.replace(f'(?P<{placeholder}>.+?)', f'__PLACEHOLDER_{placeholder}__')
        
        # Escape special chars
        temp_pattern = re.escape(temp_pattern)
        
        # Restore groups
        for placeholder in placeholders:
            temp_pattern = temp_pattern.replace(f'__PLACEHOLDER_{placeholder}__', f'(?P<{placeholder}>.+?)')
        
        regex_pattern = f'^{temp_pattern}$'
        
        try:
            match = re.match(regex_pattern, filename)
            if match:
                return {k: v.strip() for k, v in match.groupdict().items()}
        except re.error:
            pass
        
        return {}
    
    @staticmethod
    def tags_to_filename(tags: Dict[str, str], pattern: str) -> str:
        """Generate filename from tags using pattern (Tag -> Filename)
        
        Pattern placeholders: %artist%, %title%, %album%, %year%, %track%, %genre%
        Example: "%artist% - %title%" with tags creates "Pink Floyd - Comfortably Numb"
        """
        result = pattern
        
        for field, value in tags.items():
            placeholder = f'%{field}%'
            if placeholder in result and value:
                result = result.replace(placeholder, value)
        
        # Remove any remaining placeholders
        result = re.sub(r'%\w+%', '', result)
        
        # Clean up double spaces and illegal characters
        result = re.sub(r'\s+', ' ', result).strip()
        result = re.sub(r'[<>:"/\\|?*]', '_', result)
        
        # Remove trailing separators
        result = re.sub(r'[\s\-_]+$', '', result)
        result = re.sub(r'^[\s\-_]+', '', result)
        
        return result


class MusicBrainzAPI:
    """MusicBrainz API integration for fetching music metadata"""
    
    BASE_URL = "https://musicbrainz.org/ws/2"
    COVER_ART_URL = "https://coverartarchive.org"
    USER_AGENT = "PyRenamer/1.0 (https://github.com/pyrenamer)"
    
    @staticmethod
    def _make_request(url: str) -> Optional[dict]:
        """Make an API request with proper headers"""
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', MusicBrainzAPI.USER_AGENT)
            req.add_header('Accept', 'application/json')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"MusicBrainz API error: {e}")
            return None
    
    @staticmethod
    def search_recording(title: str, artist: str = "") -> List[Dict[str, Any]]:
        """Search for recordings (songs) by title and optional artist"""
        query_parts = [f'recording:"{title}"']
        if artist:
            query_parts.append(f'artist:"{artist}"')
        
        query = urllib.parse.quote(" AND ".join(query_parts))
        url = f"{MusicBrainzAPI.BASE_URL}/recording/?query={query}&fmt=json&limit=10"
        
        data = MusicBrainzAPI._make_request(url)
        if not data or 'recordings' not in data:
            return []
        
        results = []
        for rec in data['recordings']:
            result = {
                'id': rec.get('id', ''),
                'title': rec.get('title', ''),
                'artist': '',
                'album': '',
                'year': '',
                'track': '',
                'score': rec.get('score', 0),
            }
            
            # Get artist
            if rec.get('artist-credit'):
                artists = [a['name'] for a in rec['artist-credit'] if 'name' in a]
                result['artist'] = ', '.join(artists)
            
            # Get album (first release)
            if rec.get('releases'):
                release = rec['releases'][0]
                result['album'] = release.get('title', '')
                result['release_id'] = release.get('id', '')
                
                if release.get('date'):
                    result['year'] = release['date'][:4]
                
                # Get track number from medium
                if release.get('media'):
                    for medium in release['media']:
                        if medium.get('track'):
                            for track in medium['track']:
                                if track.get('id') == rec.get('id') or track.get('title') == rec.get('title'):
                                    result['track'] = str(track.get('number', ''))
                                    break
            
            results.append(result)
        
        return results
    
    @staticmethod
    def search_release(album: str, artist: str = "") -> List[Dict[str, Any]]:
        """Search for releases (albums) by name and optional artist"""
        query_parts = [f'release:"{album}"']
        if artist:
            query_parts.append(f'artist:"{artist}"')
        
        query = urllib.parse.quote(" AND ".join(query_parts))
        url = f"{MusicBrainzAPI.BASE_URL}/release/?query={query}&fmt=json&limit=10"
        
        data = MusicBrainzAPI._make_request(url)
        if not data or 'releases' not in data:
            return []
        
        results = []
        for rel in data['releases']:
            result = {
                'id': rel.get('id', ''),
                'album': rel.get('title', ''),
                'artist': '',
                'year': '',
                'tracks': rel.get('track-count', 0),
                'country': rel.get('country', ''),
                'score': rel.get('score', 0),
            }
            
            # Get artist
            if rel.get('artist-credit'):
                artists = [a['name'] for a in rel['artist-credit'] if 'name' in a]
                result['artist'] = ', '.join(artists)
            
            # Get year
            if rel.get('date'):
                result['year'] = rel['date'][:4]
            
            results.append(result)
        
        return results
    
    @staticmethod
    def get_release_tracks(release_id: str) -> List[Dict[str, str]]:
        """Get all tracks from a release (album)"""
        url = f"{MusicBrainzAPI.BASE_URL}/release/{release_id}?inc=recordings+artist-credits&fmt=json"
        
        data = MusicBrainzAPI._make_request(url)
        if not data or 'media' not in data:
            return []
        
        tracks = []
        release_artist = ''
        if data.get('artist-credit'):
            release_artist = ', '.join([a['name'] for a in data['artist-credit'] if 'name' in a])
        
        release_year = data.get('date', '')[:4] if data.get('date') else ''
        album_title = data.get('title', '')
        
        for medium in data['media']:
            disc_num = medium.get('position', 1)
            for track in medium.get('tracks', []):
                recording = track.get('recording', {})
                
                # Get track artist (may differ from album artist)
                track_artist = release_artist
                if recording.get('artist-credit'):
                    track_artist = ', '.join([a['name'] for a in recording['artist-credit'] if 'name' in a])
                
                tracks.append({
                    'track': str(track.get('number', '')),
                    'title': recording.get('title', track.get('title', '')),
                    'artist': track_artist,
                    'album': album_title,
                    'year': release_year,
                    'discnumber': str(disc_num) if disc_num > 1 else '',
                    'duration': recording.get('length', 0),  # in milliseconds
                })
        
        return tracks
    
    @staticmethod
    def get_cover_art(release_id: str) -> Optional[bytes]:
        """Fetch cover art for a release from Cover Art Archive"""
        try:
            # First try front cover
            url = f"{MusicBrainzAPI.COVER_ART_URL}/release/{release_id}/front-500"
            req = urllib.request.Request(url)
            req.add_header('User-Agent', MusicBrainzAPI.USER_AGENT)
            
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read()
        except urllib.error.HTTPError:
            # No cover art available
            pass
        except Exception as e:
            print(f"Cover art fetch error: {e}")
        
        return None
    
    @staticmethod
    def search_artist(name: str) -> List[Dict[str, Any]]:
        """Search for artists by name"""
        query = urllib.parse.quote(f'artist:"{name}"')
        url = f"{MusicBrainzAPI.BASE_URL}/artist/?query={query}&fmt=json&limit=10"
        
        data = MusicBrainzAPI._make_request(url)
        if not data or 'artists' not in data:
            return []
        
        results = []
        for artist in data['artists']:
            result = {
                'id': artist.get('id', ''),
                'name': artist.get('name', ''),
                'type': artist.get('type', ''),
                'country': artist.get('country', ''),
                'score': artist.get('score', 0),
                'disambiguation': artist.get('disambiguation', ''),
            }
            results.append(result)
        
        return results


# =============================================================================
# TMDB API - Movies & TV Shows
# =============================================================================

class TMDBAPI:
    """TMDB API for movie and TV show metadata"""
    
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
    
    # API key - can be overridden by user
    _api_key = ""
    
    @classmethod
    def set_api_key(cls, key: str):
        """Set the TMDB API key"""
        cls._api_key = key
    
    @classmethod
    def get_api_key(cls) -> str:
        """Get the current API key"""
        return cls._api_key
    
    @staticmethod
    def _make_request(url: str) -> Optional[Dict]:
        """Make API request with proper headers"""
        if not TMDBAPI._api_key:
            print("TMDB API key not set!")
            return None
        
        # Add API key to URL
        separator = '&' if '?' in url else '?'
        full_url = f"{url}{separator}api_key={TMDBAPI._api_key}"
        
        try:
            req = urllib.request.Request(full_url)
            req.add_header('Accept', 'application/json')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"TMDB API error: {e}")
            return None
    
    @staticmethod
    def search_movie(query: str, year: Optional[str] = None) -> List[Dict]:
        """Search for movies"""
        encoded_query = urllib.parse.quote(query)
        url = f"{TMDBAPI.BASE_URL}/search/movie?query={encoded_query}&include_adult=false"
        
        if year:
            url += f"&year={year}"
        
        data = TMDBAPI._make_request(url)
        if not data or 'results' not in data:
            return []
        
        results = []
        for movie in data['results'][:15]:  # Limit to 15 results
            result = {
                'id': movie.get('id', 0),
                'title': movie.get('title', ''),
                'original_title': movie.get('original_title', ''),
                'year': movie.get('release_date', '')[:4] if movie.get('release_date') else '',
                'overview': movie.get('overview', '')[:200] + '...' if len(movie.get('overview', '')) > 200 else movie.get('overview', ''),
                'poster_path': movie.get('poster_path', ''),
                'backdrop_path': movie.get('backdrop_path', ''),
                'vote_average': movie.get('vote_average', 0),
                'popularity': movie.get('popularity', 0),
                'type': 'movie'
            }
            results.append(result)
        
        return results
    
    @staticmethod
    def search_tv(query: str, year: Optional[str] = None) -> List[Dict]:
        """Search for TV shows"""
        encoded_query = urllib.parse.quote(query)
        url = f"{TMDBAPI.BASE_URL}/search/tv?query={encoded_query}&include_adult=false"
        
        if year:
            url += f"&first_air_date_year={year}"
        
        data = TMDBAPI._make_request(url)
        if not data or 'results' not in data:
            return []
        
        results = []
        for show in data['results'][:15]:
            result = {
                'id': show.get('id', 0),
                'title': show.get('name', ''),
                'original_title': show.get('original_name', ''),
                'year': show.get('first_air_date', '')[:4] if show.get('first_air_date') else '',
                'overview': show.get('overview', '')[:200] + '...' if len(show.get('overview', '')) > 200 else show.get('overview', ''),
                'poster_path': show.get('poster_path', ''),
                'backdrop_path': show.get('backdrop_path', ''),
                'vote_average': show.get('vote_average', 0),
                'popularity': show.get('popularity', 0),
                'type': 'tv'
            }
            results.append(result)
        
        return results
    
    @staticmethod
    def get_movie_details(movie_id: int) -> Optional[Dict]:
        """Get detailed movie information"""
        url = f"{TMDBAPI.BASE_URL}/movie/{movie_id}?append_to_response=credits,images,release_dates&include_image_language=en,null"
        
        data = TMDBAPI._make_request(url)
        if not data:
            return None
        
        # Extract genres
        genres = [g['name'] for g in data.get('genres', [])]
        
        # Extract director and cast
        director = ''
        cast = []
        if 'credits' in data:
            for crew in data['credits'].get('crew', []):
                if crew.get('job') == 'Director':
                    director = crew.get('name', '')
                    break
            
            for actor in data['credits'].get('cast', [])[:10]:
                cast.append({
                    'name': actor.get('name', ''),
                    'character': actor.get('character', ''),
                    'profile_path': actor.get('profile_path', '')
                })
        
        # Extract certification (rating)
        certification = ''
        if 'release_dates' in data:
            for country in data['release_dates'].get('results', []):
                if country.get('iso_3166_1') == 'US':
                    for release in country.get('release_dates', []):
                        if release.get('certification'):
                            certification = release['certification']
                            break
                    break
        
        # Extract additional images (logos, backdrops)
        logo_path = ''
        landscape_path = ''  # Use a backdrop with English text as landscape
        backdrops = []
        
        if 'images' in data:
            # Get logo (prefer English, then any)
            logos = data['images'].get('logos', [])
            if logos:
                # Prefer English logo, then null language
                for logo in logos:
                    if logo.get('iso_639_1') == 'en':
                        logo_path = logo.get('file_path', '')
                        break
                if not logo_path and logos:
                    logo_path = logos[0].get('file_path', '')
            
            # Get backdrops (for landscape - one with text/English)
            all_backdrops = data['images'].get('backdrops', [])
            for bd in all_backdrops:
                backdrops.append(bd.get('file_path', ''))
                # Use English-tagged backdrop as landscape if available
                if bd.get('iso_639_1') == 'en' and not landscape_path:
                    landscape_path = bd.get('file_path', '')
            
            # If no English backdrop, use first backdrop as landscape
            if not landscape_path and backdrops:
                landscape_path = backdrops[0]
        
        return {
            'id': data.get('id', 0),
            'title': data.get('title', ''),
            'original_title': data.get('original_title', ''),
            'tagline': data.get('tagline', ''),
            'year': data.get('release_date', '')[:4] if data.get('release_date') else '',
            'release_date': data.get('release_date', ''),
            'runtime': data.get('runtime', 0),
            'overview': data.get('overview', ''),
            'genres': genres,
            'director': director,
            'cast': cast,
            'certification': certification,
            'vote_average': data.get('vote_average', 0),
            'vote_count': data.get('vote_count', 0),
            'poster_path': data.get('poster_path', ''),
            'backdrop_path': data.get('backdrop_path', ''),
            'logo_path': logo_path,
            'landscape_path': landscape_path,
            'backdrops': backdrops[:5],  # Store up to 5 backdrops
            'imdb_id': data.get('imdb_id', ''),
            'budget': data.get('budget', 0),
            'revenue': data.get('revenue', 0),
            'production_companies': [c['name'] for c in data.get('production_companies', [])],
            'type': 'movie'
        }
    
    @staticmethod
    def get_tv_details(tv_id: int) -> Optional[Dict]:
        """Get detailed TV show information"""
        url = f"{TMDBAPI.BASE_URL}/tv/{tv_id}?append_to_response=credits,images,content_ratings,external_ids"
        
        data = TMDBAPI._make_request(url)
        if not data:
            return None
        
        # Extract genres
        genres = [g['name'] for g in data.get('genres', [])]
        
        # Extract creators and cast
        creators = [c['name'] for c in data.get('created_by', [])]
        cast = []
        if 'credits' in data:
            for actor in data['credits'].get('cast', [])[:10]:
                cast.append({
                    'name': actor.get('name', ''),
                    'character': actor.get('character', ''),
                    'profile_path': actor.get('profile_path', '')
                })
        
        # Extract certification
        certification = ''
        if 'content_ratings' in data:
            for rating in data['content_ratings'].get('results', []):
                if rating.get('iso_3166_1') == 'US':
                    certification = rating.get('rating', '')
                    break
        
        # Season info
        seasons = []
        for season in data.get('seasons', []):
            if season.get('season_number', 0) > 0:  # Skip specials (season 0)
                seasons.append({
                    'season_number': season.get('season_number', 0),
                    'episode_count': season.get('episode_count', 0),
                    'name': season.get('name', ''),
                    'air_date': season.get('air_date', ''),
                    'poster_path': season.get('poster_path', '')
                })
        
        return {
            'id': data.get('id', 0),
            'title': data.get('name', ''),
            'original_title': data.get('original_name', ''),
            'tagline': data.get('tagline', ''),
            'year': data.get('first_air_date', '')[:4] if data.get('first_air_date') else '',
            'first_air_date': data.get('first_air_date', ''),
            'last_air_date': data.get('last_air_date', ''),
            'status': data.get('status', ''),
            'episode_runtime': data.get('episode_run_time', [0])[0] if data.get('episode_run_time') else 0,
            'overview': data.get('overview', ''),
            'genres': genres,
            'creators': creators,
            'cast': cast,
            'certification': certification,
            'vote_average': data.get('vote_average', 0),
            'vote_count': data.get('vote_count', 0),
            'poster_path': data.get('poster_path', ''),
            'backdrop_path': data.get('backdrop_path', ''),
            'number_of_seasons': data.get('number_of_seasons', 0),
            'number_of_episodes': data.get('number_of_episodes', 0),
            'seasons': seasons,
            'networks': [n['name'] for n in data.get('networks', [])],
            'imdb_id': data.get('external_ids', {}).get('imdb_id', ''),
            'tvdb_id': data.get('external_ids', {}).get('tvdb_id', ''),
            'type': 'tv'
        }
    
    @staticmethod
    def get_tv_season(tv_id: int, season_number: int) -> Optional[Dict]:
        """Get season details including all episodes"""
        url = f"{TMDBAPI.BASE_URL}/tv/{tv_id}/season/{season_number}"
        
        data = TMDBAPI._make_request(url)
        if not data:
            return None
        
        episodes = []
        for ep in data.get('episodes', []):
            episodes.append({
                'episode_number': ep.get('episode_number', 0),
                'name': ep.get('name', ''),
                'overview': ep.get('overview', ''),
                'air_date': ep.get('air_date', ''),
                'runtime': ep.get('runtime', 0),
                'still_path': ep.get('still_path', ''),
                'vote_average': ep.get('vote_average', 0),
            })
        
        return {
            'season_number': data.get('season_number', 0),
            'name': data.get('name', ''),
            'overview': data.get('overview', ''),
            'air_date': data.get('air_date', ''),
            'poster_path': data.get('poster_path', ''),
            'episodes': episodes
        }
    
    @staticmethod
    def get_tv_episode(tv_id: int, season_number: int, episode_number: int) -> Optional[Dict]:
        """Get specific episode details including crew and guest stars"""
        # Get episode details with credits appended
        url = f"{TMDBAPI.BASE_URL}/tv/{tv_id}/season/{season_number}/episode/{episode_number}?append_to_response=credits"
        
        data = TMDBAPI._make_request(url)
        if not data:
            return None
        
        # Extract directors and writers from crew
        directors = []
        writers = []
        credits = data.get('credits', {})
        for crew_member in credits.get('crew', []):
            job = crew_member.get('job', '')
            name = crew_member.get('name', '')
            if job == 'Director' and name:
                directors.append(name)
            elif job in ('Writer', 'Screenplay', 'Story', 'Teleplay') and name:
                if name not in writers:  # Avoid duplicates
                    writers.append(name)
        
        # Extract guest stars
        guest_stars = []
        for guest in credits.get('guest_stars', []):
            guest_stars.append({
                'name': guest.get('name', ''),
                'character': guest.get('character', ''),
                'profile_path': guest.get('profile_path', ''),
            })
        
        return {
            'id': data.get('id'),
            'episode_number': data.get('episode_number', 0),
            'season_number': data.get('season_number', 0),
            'name': data.get('name', ''),
            'overview': data.get('overview', ''),
            'air_date': data.get('air_date', ''),
            'runtime': data.get('runtime', 0),
            'still_path': data.get('still_path', ''),
            'vote_average': data.get('vote_average', 0),
            'vote_count': data.get('vote_count', 0),
            'directors': directors,
            'writers': writers,
            'guest_stars': guest_stars,
        }
    
    @staticmethod
    def get_image_url(path: str, size: str = 'w500') -> str:
        """Get full image URL from path"""
        if not path:
            return ''
        return f"{TMDBAPI.IMAGE_BASE_URL}/{size}{path}"
    
    @staticmethod
    def get_movie_images(movie_id: int) -> Dict[str, List[Dict]]:
        """Get all images for a movie (posters, backdrops, logos)"""
        url = f"{TMDBAPI.BASE_URL}/movie/{movie_id}/images?include_image_language=en,null"
        
        data = TMDBAPI._make_request(url)
        if not data:
            return {'posters': [], 'backdrops': [], 'logos': []}
        
        result = {
            'posters': [],
            'backdrops': [],
            'logos': []
        }
        
        # Process posters
        for img in data.get('posters', []):
            result['posters'].append({
                'path': img.get('file_path', ''),
                'width': img.get('width', 0),
                'height': img.get('height', 0),
                'language': img.get('iso_639_1', ''),
                'vote_average': img.get('vote_average', 0)
            })
        
        # Process backdrops (fanart)
        for img in data.get('backdrops', []):
            result['backdrops'].append({
                'path': img.get('file_path', ''),
                'width': img.get('width', 0),
                'height': img.get('height', 0),
                'language': img.get('iso_639_1', ''),
                'vote_average': img.get('vote_average', 0)
            })
        
        # Process logos
        for img in data.get('logos', []):
            result['logos'].append({
                'path': img.get('file_path', ''),
                'width': img.get('width', 0),
                'height': img.get('height', 0),
                'language': img.get('iso_639_1', ''),
                'vote_average': img.get('vote_average', 0)
            })
        
        return result
    
    @staticmethod
    def download_image(path: str, size: str = 'w500') -> Optional[bytes]:
        """Download image and return bytes"""
        if not path:
            return None
        
        url = TMDBAPI.get_image_url(path, size)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read()
        except Exception as e:
            print(f"Error downloading image: {e}")
            return None
    
    @staticmethod
    def get_tv_images(tv_id: int) -> Dict[str, List[Dict]]:
        """Get all images for a TV show (posters, backdrops, logos)"""
        url = f"{TMDBAPI.BASE_URL}/tv/{tv_id}/images?include_image_language=en,null"
        
        data = TMDBAPI._make_request(url)
        if not data:
            return {'posters': [], 'backdrops': [], 'logos': []}
        
        result = {
            'posters': [],
            'backdrops': [],
            'logos': []
        }
        
        # Process posters
        for img in data.get('posters', []):
            result['posters'].append({
                'path': img.get('file_path', ''),
                'width': img.get('width', 0),
                'height': img.get('height', 0),
                'language': img.get('iso_639_1', ''),
                'vote_average': img.get('vote_average', 0)
            })
        
        # Process backdrops (fanart)
        for img in data.get('backdrops', []):
            result['backdrops'].append({
                'path': img.get('file_path', ''),
                'width': img.get('width', 0),
                'height': img.get('height', 0),
                'language': img.get('iso_639_1', ''),
                'vote_average': img.get('vote_average', 0)
            })
        
        # Process logos
        for img in data.get('logos', []):
            result['logos'].append({
                'path': img.get('file_path', ''),
                'width': img.get('width', 0),
                'height': img.get('height', 0),
                'language': img.get('iso_639_1', ''),
                'vote_average': img.get('vote_average', 0)
            })
        
        return result


class FanartTVAPI:
    """Fanart.tv API for additional movie artwork (logos, thumbs, banners, disc art)"""
    
    BASE_URL = "https://webservice.fanart.tv/v3"
    
    # API key - can be overridden by user
    _api_key = ""
    
    @classmethod
    def set_api_key(cls, key: str):
        """Set the Fanart.tv API key"""
        cls._api_key = key
    
    @classmethod
    def get_api_key(cls) -> str:
        """Get the current API key"""
        return cls._api_key
    
    @staticmethod
    def _make_request(url: str) -> Optional[Dict]:
        """Make API request with proper headers"""
        if not FanartTVAPI._api_key:
            print("Fanart.tv API key not set!")
            return None
        
        # Add API key to URL
        separator = '&' if '?' in url else '?'
        full_url = f"{url}{separator}api_key={FanartTVAPI._api_key}"
        
        try:
            req = urllib.request.Request(full_url)
            req.add_header('Accept', 'application/json')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"Fanart.tv: No artwork found for this movie")
            else:
                print(f"Fanart.tv API error: {e}")
            return None
        except Exception as e:
            print(f"Fanart.tv API error: {e}")
            return None
    
    @staticmethod
    def get_movie_images(tmdb_id: int) -> Dict[str, List[Dict]]:
        """Get all images for a movie from Fanart.tv using TMDB ID"""
        url = f"{FanartTVAPI.BASE_URL}/movies/{tmdb_id}"
        
        data = FanartTVAPI._make_request(url)
        if not data:
            return {'posters': [], 'backdrops': [], 'logos': [], 'thumbs': [], 'banners': [], 'discs': []}
        
        result = {
            'posters': [],
            'backdrops': [],
            'logos': [],
            'thumbs': [],      # Landscape/thumb images
            'banners': [],
            'discs': []
        }
        
        # Process HD logos
        for img in data.get('hdmovielogo', []):
            result['logos'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Also include regular movie logos
        for img in data.get('movielogo', []):
            result['logos'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Process posters
        for img in data.get('movieposter', []):
            result['posters'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Process backgrounds (fanart)
        for img in data.get('moviebackground', []):
            result['backdrops'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Process thumbs (landscape) - THIS IS WHAT WE NEED!
        for img in data.get('moviethumb', []):
            result['thumbs'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Process banners
        for img in data.get('moviebanner', []):
            result['banners'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Process disc art
        for img in data.get('moviedisc', []):
            result['discs'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0),
                'disc_type': img.get('disc_type', '')
            })
        
        return result
    
    @staticmethod
    def download_image(url: str) -> Optional[bytes]:
        """Download image from Fanart.tv URL and return bytes"""
        if not url:
            return None
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read()
        except Exception as e:
            print(f"Error downloading Fanart.tv image: {e}")
            return None
    
    @staticmethod
    def get_tv_images(tvdb_id: int) -> Dict[str, List[Dict]]:
        """Get all images for a TV show from Fanart.tv using TVDB ID"""
        url = f"{FanartTVAPI.BASE_URL}/tv/{tvdb_id}"
        
        data = FanartTVAPI._make_request(url)
        if not data:
            return {'posters': [], 'backdrops': [], 'logos': [], 'thumbs': [], 'banners': []}
        
        result = {
            'posters': [],
            'backdrops': [],
            'logos': [],
            'thumbs': [],      # Landscape/thumb images
            'banners': [],
        }
        
        # Process HD logos
        for img in data.get('hdtvlogo', []):
            result['logos'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Also include regular TV logos
        for img in data.get('clearlogo', []):
            result['logos'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Process posters
        for img in data.get('tvposter', []):
            result['posters'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Process backgrounds (fanart/showbackground)
        for img in data.get('showbackground', []):
            result['backdrops'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Process thumbs (landscape) - tvthumb
        for img in data.get('tvthumb', []):
            result['thumbs'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        # Process banners
        for img in data.get('tvbanner', []):
            result['banners'].append({
                'path': img.get('url', ''),
                'language': img.get('lang', ''),
                'likes': img.get('likes', 0)
            })
        
        return result


class NFOGenerator:
    """Generate NFO files for Kodi/Plex/Jellyfin"""
    
    @staticmethod
    def generate_movie_nfo(movie_data: Dict) -> str:
        """Generate movie NFO XML"""
        nfo = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
        nfo.append('<movie>')
        nfo.append(f'  <title>{NFOGenerator._escape_xml(movie_data.get("title", ""))}</title>')
        nfo.append(f'  <originaltitle>{NFOGenerator._escape_xml(movie_data.get("original_title", ""))}</originaltitle>')
        nfo.append(f'  <sorttitle>{NFOGenerator._escape_xml(movie_data.get("title", ""))}</sorttitle>')
        nfo.append(f'  <year>{movie_data.get("year", "")}</year>')
        nfo.append(f'  <releasedate>{movie_data.get("release_date", "")}</releasedate>')
        nfo.append(f'  <runtime>{movie_data.get("runtime", 0)}</runtime>')
        nfo.append(f'  <plot>{NFOGenerator._escape_xml(movie_data.get("overview", ""))}</plot>')
        nfo.append(f'  <tagline>{NFOGenerator._escape_xml(movie_data.get("tagline", ""))}</tagline>')
        nfo.append(f'  <mpaa>{movie_data.get("certification", "")}</mpaa>')
        nfo.append(f'  <rating>{movie_data.get("vote_average", 0)}</rating>')
        nfo.append(f'  <votes>{movie_data.get("vote_count", 0)}</votes>')
        
        # Genres
        for genre in movie_data.get('genres', []):
            nfo.append(f'  <genre>{NFOGenerator._escape_xml(genre)}</genre>')
        
        # Director
        if movie_data.get('director'):
            nfo.append(f'  <director>{NFOGenerator._escape_xml(movie_data["director"])}</director>')
        
        # Cast
        for actor in movie_data.get('cast', []):
            nfo.append('  <actor>')
            nfo.append(f'    <name>{NFOGenerator._escape_xml(actor.get("name", ""))}</name>')
            nfo.append(f'    <role>{NFOGenerator._escape_xml(actor.get("character", ""))}</role>')
            if actor.get('profile_path'):
                nfo.append(f'    <thumb>{TMDBAPI.get_image_url(actor["profile_path"], "w185")}</thumb>')
            nfo.append('  </actor>')
        
        # IDs
        if movie_data.get('imdb_id'):
            nfo.append(f'  <imdbid>{movie_data["imdb_id"]}</imdbid>')
        nfo.append(f'  <tmdbid>{movie_data.get("id", "")}</tmdbid>')
        
        # Artwork
        if movie_data.get('poster_path'):
            nfo.append(f'  <thumb aspect="poster">{TMDBAPI.get_image_url(movie_data["poster_path"], "original")}</thumb>')
        if movie_data.get('backdrop_path'):
            nfo.append(f'  <fanart>')
            nfo.append(f'    <thumb>{TMDBAPI.get_image_url(movie_data["backdrop_path"], "original")}</thumb>')
            nfo.append(f'  </fanart>')
        
        # Studios
        for studio in movie_data.get('production_companies', []):
            nfo.append(f'  <studio>{NFOGenerator._escape_xml(studio)}</studio>')
        
        nfo.append('</movie>')
        return '\n'.join(nfo)
    
    @staticmethod
    def generate_tvshow_nfo(show_data: Dict) -> str:
        """Generate TV show NFO XML"""
        nfo = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
        nfo.append('<tvshow>')
        nfo.append(f'  <title>{NFOGenerator._escape_xml(show_data.get("title", ""))}</title>')
        nfo.append(f'  <originaltitle>{NFOGenerator._escape_xml(show_data.get("original_title", ""))}</originaltitle>')
        nfo.append(f'  <sorttitle>{NFOGenerator._escape_xml(show_data.get("title", ""))}</sorttitle>')
        nfo.append(f'  <year>{show_data.get("year", "")}</year>')
        nfo.append(f'  <premiered>{show_data.get("first_air_date", "")}</premiered>')
        nfo.append(f'  <status>{show_data.get("status", "")}</status>')
        nfo.append(f'  <plot>{NFOGenerator._escape_xml(show_data.get("overview", ""))}</plot>')
        nfo.append(f'  <tagline>{NFOGenerator._escape_xml(show_data.get("tagline", ""))}</tagline>')
        nfo.append(f'  <mpaa>{show_data.get("certification", "")}</mpaa>')
        nfo.append(f'  <rating>{show_data.get("vote_average", 0)}</rating>')
        nfo.append(f'  <votes>{show_data.get("vote_count", 0)}</votes>')
        
        # Genres
        for genre in show_data.get('genres', []):
            nfo.append(f'  <genre>{NFOGenerator._escape_xml(genre)}</genre>')
        
        # Creators
        for creator in show_data.get('creators', []):
            nfo.append(f'  <credits>{NFOGenerator._escape_xml(creator)}</credits>')
        
        # Cast
        for actor in show_data.get('cast', []):
            nfo.append('  <actor>')
            nfo.append(f'    <name>{NFOGenerator._escape_xml(actor.get("name", ""))}</name>')
            nfo.append(f'    <role>{NFOGenerator._escape_xml(actor.get("character", ""))}</role>')
            if actor.get('profile_path'):
                nfo.append(f'    <thumb>{TMDBAPI.get_image_url(actor["profile_path"], "w185")}</thumb>')
            nfo.append('  </actor>')
        
        # IDs
        if show_data.get('imdb_id'):
            nfo.append(f'  <imdbid>{show_data["imdb_id"]}</imdbid>')
        if show_data.get('tvdb_id'):
            nfo.append(f'  <tvdbid>{show_data["tvdb_id"]}</tvdbid>')
        nfo.append(f'  <tmdbid>{show_data.get("id", "")}</tmdbid>')
        
        # UniqueID tags (Kodi v17+ format)
        if show_data.get('id'):
            nfo.append(f'  <uniqueid type="tmdb" default="true">{show_data["id"]}</uniqueid>')
        if show_data.get('imdb_id'):
            nfo.append(f'  <uniqueid type="imdb">{show_data["imdb_id"]}</uniqueid>')
        if show_data.get('tvdb_id'):
            nfo.append(f'  <uniqueid type="tvdb">{show_data["tvdb_id"]}</uniqueid>')
        
        # Episode Guide (helps Kodi find episodes)
        if show_data.get('id'):
            nfo.append('  <episodeguide>')
            nfo.append(f'    {{"tmdb": "{show_data["id"]}"}}')
            nfo.append('  </episodeguide>')
        
        # Artwork
        if show_data.get('poster_path'):
            nfo.append(f'  <thumb aspect="poster">{TMDBAPI.get_image_url(show_data["poster_path"], "original")}</thumb>')
        if show_data.get('backdrop_path'):
            nfo.append(f'  <fanart>')
            nfo.append(f'    <thumb>{TMDBAPI.get_image_url(show_data["backdrop_path"], "original")}</thumb>')
            nfo.append(f'  </fanart>')
        
        # Networks/Studios
        for network in show_data.get('networks', []):
            nfo.append(f'  <studio>{NFOGenerator._escape_xml(network)}</studio>')
        
        # Season count
        nfo.append(f'  <season>{show_data.get("number_of_seasons", 0)}</season>')
        nfo.append(f'  <episode>{show_data.get("number_of_episodes", 0)}</episode>')
        
        nfo.append('</tvshow>')
        return '\n'.join(nfo)
    
    @staticmethod
    def generate_episode_nfo(episode_data: Dict, show_data: Dict) -> str:
        """Generate episode NFO XML (MediaElch/Kodi compatible)"""
        nfo = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
        nfo.append('<episodedetails>')
        nfo.append(f'  <title>{NFOGenerator._escape_xml(episode_data.get("name", ""))}</title>')
        nfo.append(f'  <showtitle>{NFOGenerator._escape_xml(show_data.get("title", ""))}</showtitle>')
        nfo.append(f'  <season>{episode_data.get("season_number", 0)}</season>')
        nfo.append(f'  <episode>{episode_data.get("episode_number", 0)}</episode>')
        nfo.append(f'  <plot>{NFOGenerator._escape_xml(episode_data.get("overview", ""))}</plot>')
        nfo.append(f'  <aired>{episode_data.get("air_date", "")}</aired>')
        nfo.append(f'  <runtime>{episode_data.get("runtime", 0)}</runtime>')
        
        # Ratings
        nfo.append(f'  <rating>{episode_data.get("vote_average", 0)}</rating>')
        if episode_data.get('vote_count'):
            nfo.append(f'  <votes>{episode_data.get("vote_count", 0)}</votes>')
        if episode_data.get('userrating'):
            nfo.append(f'  <userrating>{episode_data.get("userrating", 0)}</userrating>')
        
        # Directors (multiple allowed)
        for director in episode_data.get('directors', []):
            if director:
                nfo.append(f'  <director>{NFOGenerator._escape_xml(director)}</director>')
        
        # Writers/Credits (multiple allowed)
        for writer in episode_data.get('writers', []):
            if writer:
                nfo.append(f'  <credits>{NFOGenerator._escape_xml(writer)}</credits>')
        
        # Guest Stars / Actors (with role if available)
        for actor in episode_data.get('guest_stars', []):
            if isinstance(actor, dict):
                nfo.append('  <actor>')
                nfo.append(f'    <name>{NFOGenerator._escape_xml(actor.get("name", ""))}</name>')
                nfo.append(f'    <role>{NFOGenerator._escape_xml(actor.get("character", ""))}</role>')
                if actor.get('profile_path'):
                    nfo.append(f'    <thumb>{TMDBAPI.get_image_url(actor["profile_path"], "w185")}</thumb>')
                nfo.append('  </actor>')
            elif isinstance(actor, str) and actor:
                nfo.append('  <actor>')
                nfo.append(f'    <name>{NFOGenerator._escape_xml(actor)}</name>')
                nfo.append('    <role>Guest Star</role>')
                nfo.append('  </actor>')
        
        # UniqueID tags (Kodi v17+ format)
        if episode_data.get('tmdb_id') or episode_data.get('id'):
            tmdb_id = episode_data.get('tmdb_id') or episode_data.get('id')
            nfo.append(f'  <uniqueid type="tmdb" default="true">{tmdb_id}</uniqueid>')
        if episode_data.get('imdb_id'):
            nfo.append(f'  <uniqueid type="imdb">{episode_data["imdb_id"]}</uniqueid>')
        if episode_data.get('tvdb_id'):
            nfo.append(f'  <uniqueid type="tvdb">{episode_data["tvdb_id"]}</uniqueid>')
        
        # Episode thumbnail
        if episode_data.get('still_path'):
            nfo.append(f'  <thumb>{TMDBAPI.get_image_url(episode_data["still_path"], "original")}</thumb>')
        
        # Stream details (if available)
        if episode_data.get('fileinfo'):
            nfo.append('  <fileinfo>')
            nfo.append('    <streamdetails>')
            
            video = episode_data['fileinfo'].get('video', {})
            if video:
                nfo.append('      <video>')
                nfo.append(f'        <codec>{video.get("codec", "")}</codec>')
                nfo.append(f'        <aspect>{video.get("aspect", "")}</aspect>')
                nfo.append(f'        <width>{video.get("width", 0)}</width>')
                nfo.append(f'        <height>{video.get("height", 0)}</height>')
                nfo.append(f'        <durationinseconds>{video.get("duration", 0)}</durationinseconds>')
                nfo.append('      </video>')
            
            for audio in episode_data['fileinfo'].get('audio', []):
                nfo.append('      <audio>')
                nfo.append(f'        <codec>{audio.get("codec", "")}</codec>')
                nfo.append(f'        <language>{audio.get("language", "")}</language>')
                nfo.append(f'        <channels>{audio.get("channels", 2)}</channels>')
                nfo.append('      </audio>')
            
            for sub in episode_data['fileinfo'].get('subtitles', []):
                nfo.append('      <subtitle>')
                nfo.append(f'        <language>{sub.get("language", "")}</language>')
                nfo.append('      </subtitle>')
            
            nfo.append('    </streamdetails>')
            nfo.append('  </fileinfo>')
        
        nfo.append('</episodedetails>')
        return '\n'.join(nfo)
    
    @staticmethod
    def _escape_xml(text: str) -> str:
        """Escape XML special characters"""
        if not text:
            return ''
        text = str(text)
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        text = text.replace('"', '&quot;')
        text = text.replace("'", '&apos;')
        return text


class NFOParser:
    """Parse existing NFO files to extract movie/TV show metadata"""
    
    @staticmethod
    def _unescape_xml(text: str) -> str:
        """Unescape XML special characters"""
        if not text:
            return ''
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&apos;', "'")
        return text.strip()
    
    @staticmethod
    def _get_tag_value(content: str, tag: str) -> str:
        """Extract value from XML tag"""
        pattern = f'<{tag}>(.*?)</{tag}>'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return NFOParser._unescape_xml(match.group(1))
        return ''
    
    @staticmethod
    def _get_all_tag_values(content: str, tag: str) -> List[str]:
        """Extract all values from repeated XML tags"""
        pattern = f'<{tag}>(.*?)</{tag}>'
        matches = re.findall(pattern, content, re.DOTALL)
        return [NFOParser._unescape_xml(m) for m in matches]
    
    @staticmethod
    def _get_actor_info(content: str) -> List[Dict]:
        """Extract actor information from NFO"""
        actors = []
        actor_pattern = r'<actor>(.*?)</actor>'
        for actor_match in re.finditer(actor_pattern, content, re.DOTALL):
            actor_content = actor_match.group(1)
            name = NFOParser._get_tag_value(actor_content, 'name')
            role = NFOParser._get_tag_value(actor_content, 'role')
            thumb = NFOParser._get_tag_value(actor_content, 'thumb')
            if name:
                actors.append({'name': name, 'role': role, 'thumb': thumb})
        return actors
    
    @staticmethod
    def parse_movie_nfo(nfo_path: str) -> Optional[Dict]:
        """Parse a movie NFO file and return metadata dict"""
        try:
            with open(nfo_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Check if it's a movie NFO
            if '<movie>' not in content:
                return None
            
            movie_data = {
                'title': NFOParser._get_tag_value(content, 'title'),
                'original_title': NFOParser._get_tag_value(content, 'originaltitle'),
                'year': NFOParser._get_tag_value(content, 'year'),
                'release_date': NFOParser._get_tag_value(content, 'releasedate') or NFOParser._get_tag_value(content, 'premiered'),
                'runtime': NFOParser._get_tag_value(content, 'runtime'),
                'overview': NFOParser._get_tag_value(content, 'plot'),
                'tagline': NFOParser._get_tag_value(content, 'tagline'),
                'certification': NFOParser._get_tag_value(content, 'mpaa') or NFOParser._get_tag_value(content, 'certification'),
                'vote_average': NFOParser._get_tag_value(content, 'rating'),
                'vote_count': NFOParser._get_tag_value(content, 'votes'),
                'genres': NFOParser._get_all_tag_values(content, 'genre'),
                'director': NFOParser._get_tag_value(content, 'director'),
                'writer': NFOParser._get_tag_value(content, 'credits') or NFOParser._get_tag_value(content, 'writer'),
                'studio': NFOParser._get_tag_value(content, 'studio'),
                'countries': NFOParser._get_all_tag_values(content, 'country'),
                'tags': NFOParser._get_all_tag_values(content, 'tag'),
                'actors': NFOParser._get_actor_info(content),
                'set_name': NFOParser._get_tag_value(content, 'set') or NFOParser._get_tag_value(content, 'collectionsname'),
            }
            
            # Try to get TMDB ID from uniqueid tags
            tmdb_id = ''
            # Pattern for <uniqueid type="tmdb">12345</uniqueid> or <uniqueid type="tmdb" default="true">12345</uniqueid>
            uniqueid_pattern = r'<uniqueid[^>]*type=["\']tmdb["\'][^>]*>(.*?)</uniqueid>'
            match = re.search(uniqueid_pattern, content, re.IGNORECASE)
            if match:
                tmdb_id = match.group(1).strip()
            else:
                # Try old format <tmdbid>12345</tmdbid>
                tmdb_id = NFOParser._get_tag_value(content, 'tmdbid')
            
            if tmdb_id and tmdb_id.isdigit():
                movie_data['id'] = int(tmdb_id)
            
            # Try to get IMDB ID
            imdb_id = ''
            # Pattern for <uniqueid type="imdb">tt12345</uniqueid>
            imdb_pattern = r'<uniqueid[^>]*type=["\']imdb["\'][^>]*>(.*?)</uniqueid>'
            match = re.search(imdb_pattern, content, re.IGNORECASE)
            if match:
                imdb_id = match.group(1).strip()
            else:
                # Try <imdbid> or <id> tags
                imdb_id = NFOParser._get_tag_value(content, 'imdbid') or NFOParser._get_tag_value(content, 'imdb')
                # Also check plain <id> if it looks like an IMDB id
                if not imdb_id:
                    plain_id = NFOParser._get_tag_value(content, 'id')
                    if plain_id and plain_id.startswith('tt'):
                        imdb_id = plain_id
            
            if imdb_id:
                movie_data['imdb_id'] = imdb_id
            
            # Convert numeric fields
            try:
                movie_data['runtime'] = int(movie_data['runtime']) if movie_data['runtime'] else 0
            except:
                movie_data['runtime'] = 0
            
            try:
                movie_data['vote_average'] = float(movie_data['vote_average']) if movie_data['vote_average'] else 0.0
            except:
                movie_data['vote_average'] = 0.0
            
            try:
                movie_data['vote_count'] = int(movie_data['vote_count']) if movie_data['vote_count'] else 0
            except:
                movie_data['vote_count'] = 0
            
            # Parse stream details / fileinfo if present
            stream_details = {
                'video': {},
                'audio': [],
                'subtitles': []
            }
            
            # Look for <fileinfo><streamdetails>...</streamdetails></fileinfo>
            streamdetails_match = re.search(r'<streamdetails>(.*?)</streamdetails>', content, re.DOTALL | re.IGNORECASE)
            if streamdetails_match:
                sd_content = streamdetails_match.group(1)
                
                # Parse video info
                video_match = re.search(r'<video>(.*?)</video>', sd_content, re.DOTALL | re.IGNORECASE)
                if video_match:
                    video_content = video_match.group(1)
                    stream_details['video'] = {
                        'codec': NFOParser._get_tag_value(video_content, 'codec'),
                        'width': NFOParser._get_tag_value(video_content, 'width'),
                        'height': NFOParser._get_tag_value(video_content, 'height'),
                        'aspect': NFOParser._get_tag_value(video_content, 'aspect'),
                        'duration': NFOParser._get_tag_value(video_content, 'durationinseconds'),
                        'scantype': NFOParser._get_tag_value(video_content, 'scantype'),
                    }
                
                # Parse audio tracks
                for audio_match in re.finditer(r'<audio>(.*?)</audio>', sd_content, re.DOTALL | re.IGNORECASE):
                    audio_content = audio_match.group(1)
                    stream_details['audio'].append({
                        'codec': NFOParser._get_tag_value(audio_content, 'codec'),
                        'language': NFOParser._get_tag_value(audio_content, 'language'),
                        'channels': NFOParser._get_tag_value(audio_content, 'channels'),
                    })
                
                # Parse subtitles
                for sub_match in re.finditer(r'<subtitle>(.*?)</subtitle>', sd_content, re.DOTALL | re.IGNORECASE):
                    sub_content = sub_match.group(1)
                    stream_details['subtitles'].append({
                        'language': NFOParser._get_tag_value(sub_content, 'language'),
                    })
            
            movie_data['stream_details'] = stream_details
            
            return movie_data
            
        except Exception as e:
            print(f"Error parsing NFO: {e}")
            return None
    
    @staticmethod
    def parse_tvshow_nfo(nfo_path: str) -> Optional[Dict]:
        """Parse a TV show NFO file and return metadata dict"""
        try:
            with open(nfo_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Check if it's a tvshow NFO
            if '<tvshow>' not in content:
                return None
            
            show_data = {
                'title': NFOParser._get_tag_value(content, 'title'),
                'original_title': NFOParser._get_tag_value(content, 'originaltitle'),
                'sort_title': NFOParser._get_tag_value(content, 'sorttitle'),
                'tagline': NFOParser._get_tag_value(content, 'tagline'),
                'year': NFOParser._get_tag_value(content, 'year'),
                'premiered': NFOParser._get_tag_value(content, 'premiered'),
                'overview': NFOParser._get_tag_value(content, 'plot'),
                'certification': NFOParser._get_tag_value(content, 'mpaa'),
                'vote_average': NFOParser._get_tag_value(content, 'rating'),
                'genres': NFOParser._get_all_tag_values(content, 'genre'),
                'studio': NFOParser._get_tag_value(content, 'studio'),
                'actors': NFOParser._get_actor_info(content),
                'status': NFOParser._get_tag_value(content, 'status'),
            }
            
            # Try to get TMDB ID from uniqueid tags first
            tmdb_id = ''
            uniqueid_pattern = r'<uniqueid[^>]*type="tmdb"[^>]*>(.*?)</uniqueid>'
            match = re.search(uniqueid_pattern, content)
            if match:
                tmdb_id = match.group(1).strip()
            # Fallback to legacy <tmdbid> tag
            if not tmdb_id:
                tmdb_id = NFOParser._get_tag_value(content, 'tmdbid')
            
            if tmdb_id and tmdb_id.isdigit():
                show_data['id'] = int(tmdb_id)
                show_data['tmdb_id'] = int(tmdb_id)
            
            # Try to get TVDB ID from uniqueid tags first
            tvdb_id = ''
            tvdb_pattern = r'<uniqueid[^>]*type="tvdb"[^>]*>(.*?)</uniqueid>'
            match = re.search(tvdb_pattern, content)
            if match:
                tvdb_id = match.group(1).strip()
            # Fallback to legacy <tvdbid> tag
            if not tvdb_id:
                tvdb_id = NFOParser._get_tag_value(content, 'tvdbid')
            
            if tvdb_id and tvdb_id.isdigit():
                show_data['tvdb_id'] = int(tvdb_id)
            
            # Try to get IMDB ID from uniqueid tags first
            imdb_id = ''
            imdb_pattern = r'<uniqueid[^>]*type="imdb"[^>]*>(.*?)</uniqueid>'
            match = re.search(imdb_pattern, content)
            if match:
                imdb_id = match.group(1).strip()
            # Fallback to legacy <imdbid> tag
            if not imdb_id:
                imdb_id = NFOParser._get_tag_value(content, 'imdbid')
            
            if imdb_id:
                show_data['imdb_id'] = imdb_id
            
            return show_data
            
        except Exception as e:
            print(f"Error parsing TV show NFO: {e}")
            return None
    
    @staticmethod
    def find_movie_nfo(movie_path: str) -> Optional[str]:
        """Find NFO file for a movie file"""
        folder = os.path.dirname(movie_path)
        basename = os.path.splitext(os.path.basename(movie_path))[0]
        
        # Check for movie-specific NFO (same name as video file)
        nfo_path = os.path.join(folder, f"{basename}.nfo")
        if os.path.exists(nfo_path):
            return nfo_path
        
        # Check for movie.nfo in the folder
        movie_nfo = os.path.join(folder, "movie.nfo")
        if os.path.exists(movie_nfo):
            return movie_nfo
        
        # Check for any .nfo file in the folder
        for f in os.listdir(folder):
            if f.lower().endswith('.nfo'):
                nfo_full = os.path.join(folder, f)
                # Verify it's a movie NFO
                try:
                    with open(nfo_full, 'r', encoding='utf-8', errors='ignore') as file:
                        if '<movie>' in file.read():
                            return nfo_full
                except:
                    pass
        
        return None
    
    @staticmethod
    def find_existing_artwork(movie_path: str) -> Dict[str, str]:
        """Find existing artwork files for a movie"""
        print(f"find_existing_artwork called with: {movie_path}")
        
        folder = os.path.dirname(movie_path)
        basename = os.path.splitext(os.path.basename(movie_path))[0]
        
        print(f"Looking in folder: '{folder}'")
        print(f"Video basename: '{basename}'")
        
        artwork = {
            'poster': None,
            'fanart': None,
            'landscape': None,
            'logo': None,
            'banner': None,
            'disc': None,
            'clearart': None
        }
        
        # Handle empty folder (file in current directory)
        if not folder:
            folder = '.'
        
        # Check if folder exists
        if not os.path.isdir(folder):
            print(f"Folder does not exist: {folder}")
            return artwork
        
        # Get all files in folder for case-insensitive matching
        try:
            folder_files = os.listdir(folder)
            print(f"Total files in folder: {len(folder_files)}")
            # Debug: print all image files found
            image_files = [f for f in folder_files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))]
            print(f"Image files in folder: {image_files}")
        except Exception as e:
            print(f"Error listing folder: {e}")
            return artwork
        
        # Create lowercase lookup
        files_lower = {f.lower(): f for f in folder_files}
        
        # Check for various naming conventions (case-insensitive)
        artwork_patterns = {
            'poster': [
                f'{basename}-poster.jpg', f'{basename}-poster.png',
                'poster.jpg', 'poster.png', 
                f'{basename}.jpg', f'{basename}.png',
                'folder.jpg', 'folder.png',
                'cover.jpg', 'cover.png',
                'movie-poster.jpg', 'movie-poster.png'
            ],
            'fanart': [
                f'{basename}-fanart.jpg', f'{basename}-fanart.png',
                'fanart.jpg', 'fanart.png',
                'backdrop.jpg', 'backdrop.png',
                f'{basename}-backdrop.jpg',
                'background.jpg', 'background.png',
                'art.jpg', 'art.png'
            ],
            'landscape': [
                f'{basename}-landscape.jpg', f'{basename}-landscape.png',
                'landscape.jpg', 'landscape.png',
                'thumb.jpg', 'thumb.png',
                f'{basename}-thumb.jpg', f'{basename}-thumb.png',
                'moviethumb.jpg', 'moviethumb.png'
            ],
            'logo': [
                f'{basename}-logo.png', f'{basename}-logo.jpg',
                'logo.png', 'logo.jpg',
                'clearlogo.png', 'clearlogo.jpg',
                f'{basename}-clearlogo.png',
                'hdmovielogo.png'
            ],
            'banner': [
                f'{basename}-banner.jpg', f'{basename}-banner.png',
                'banner.jpg', 'banner.png'
            ],
            'disc': [
                f'{basename}-disc.png', f'{basename}-disc.jpg',
                'disc.png', 'disc.jpg',
                'discart.png', 'discart.jpg',
                'cdart.png'
            ],
            'clearart': [
                f'{basename}-clearart.png',
                'clearart.png'
            ]
        }
        
        for art_type, patterns in artwork_patterns.items():
            for pattern in patterns:
                # Case-insensitive check
                pattern_lower = pattern.lower()
                if pattern_lower in files_lower:
                    actual_filename = files_lower[pattern_lower]
                    full_path = os.path.join(folder, actual_filename)
                    if os.path.exists(full_path):
                        artwork[art_type] = full_path
                        print(f"✓ Found {art_type}: {pattern} -> {full_path}")
                        break
        
        # Summary
        found = [k for k, v in artwork.items() if v]
        print(f"Artwork found: {found if found else 'None'}")
        
        return artwork
    
    @staticmethod
    def find_tvshow_nfo(episode_path: str) -> Optional[str]:
        """Find tvshow.nfo file for a TV episode file.
        
        TV shows typically have tvshow.nfo in the show's root folder or parent folder.
        """
        folder = os.path.dirname(episode_path)
        
        # Check current folder for tvshow.nfo
        tvshow_nfo = os.path.join(folder, "tvshow.nfo")
        if os.path.exists(tvshow_nfo):
            return tvshow_nfo
        
        # Check parent folder (if episodes are in Season subfolders)
        parent_folder = os.path.dirname(folder)
        tvshow_nfo = os.path.join(parent_folder, "tvshow.nfo")
        if os.path.exists(tvshow_nfo):
            return tvshow_nfo
        
        # Check for any .nfo file containing <tvshow>
        for check_folder in [folder, parent_folder]:
            if os.path.isdir(check_folder):
                try:
                    for f in os.listdir(check_folder):
                        if f.lower().endswith('.nfo'):
                            nfo_full = os.path.join(check_folder, f)
                            try:
                                with open(nfo_full, 'r', encoding='utf-8', errors='ignore') as file:
                                    if '<tvshow>' in file.read():
                                        return nfo_full
                            except:
                                pass
                except:
                    pass
        
        return None
    
    @staticmethod
    def find_tvshow_artwork(episode_path: str) -> Dict[str, str]:
        """Find existing artwork files for a TV show.
        
        Looks in both the episode's folder and parent folder for show-level artwork.
        """
        folder = os.path.dirname(episode_path)
        parent_folder = os.path.dirname(folder)
        
        artwork = {
            'poster': None,
            'fanart': None,
            'landscape': None,
            'logo': None,
            'banner': None,
            'clearart': None
        }
        
        # Artwork patterns for TV shows
        artwork_patterns = {
            'poster': ['poster.jpg', 'poster.png', 'show-poster.jpg', 'folder.jpg', 'cover.jpg'],
            'fanart': ['fanart.jpg', 'fanart.png', 'backdrop.jpg', 'background.jpg'],
            'landscape': ['landscape.jpg', 'landscape.png', 'thumb.jpg'],
            'logo': ['logo.png', 'clearlogo.png'],
            'banner': ['banner.jpg', 'banner.png'],
            'clearart': ['clearart.png']
        }
        
        # Check both folders (episode folder first, then parent)
        for check_folder in [folder, parent_folder]:
            if not os.path.isdir(check_folder):
                continue
            
            try:
                folder_files = os.listdir(check_folder)
                files_lower = {f.lower(): f for f in folder_files}
                
                for art_type, patterns in artwork_patterns.items():
                    if artwork[art_type]:  # Already found
                        continue
                    for pattern in patterns:
                        pattern_lower = pattern.lower()
                        if pattern_lower in files_lower:
                            actual_filename = files_lower[pattern_lower]
                            full_path = os.path.join(check_folder, actual_filename)
                            if os.path.exists(full_path):
                                artwork[art_type] = full_path
                                print(f"✓ Found TV {art_type}: {full_path}")
                                break
            except Exception as e:
                print(f"Error checking folder {check_folder}: {e}")
        
        return artwork
    
    @staticmethod
    def parse_episode_nfo(nfo_path: str) -> Optional[Dict]:
        """Parse an episode NFO file and return metadata dict"""
        try:
            with open(nfo_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Check if it's an episode NFO
            if '<episodedetails>' not in content:
                return None
            
            episode_data = {
                'title': NFOParser._get_tag_value(content, 'title'),
                'showtitle': NFOParser._get_tag_value(content, 'showtitle'),
                'season': NFOParser._get_tag_value(content, 'season'),
                'episode': NFOParser._get_tag_value(content, 'episode'),
                'plot': NFOParser._get_tag_value(content, 'plot'),
                'aired': NFOParser._get_tag_value(content, 'aired'),
                'runtime': NFOParser._get_tag_value(content, 'runtime'),
                'rating': NFOParser._get_tag_value(content, 'rating'),
                'userrating': NFOParser._get_tag_value(content, 'userrating'),
            }
            
            # Get all directors (multiple allowed)
            directors = NFOParser._get_all_tag_values(content, 'director')
            episode_data['directors'] = directors if directors else []
            
            # Get all writers (from credits tags)
            writers = NFOParser._get_all_tag_values(content, 'credits')
            if not writers:
                writers = NFOParser._get_all_tag_values(content, 'writer')
            episode_data['writers'] = writers if writers else []
            
            # Get guest stars/actors
            actors = NFOParser._get_actor_info(content)
            episode_data['guest_stars'] = actors if actors else []
            
            # Convert numeric fields
            try:
                episode_data['season'] = int(episode_data['season']) if episode_data['season'] else 0
            except:
                episode_data['season'] = 0
            
            try:
                episode_data['episode'] = int(episode_data['episode']) if episode_data['episode'] else 0
            except:
                episode_data['episode'] = 0
            
            try:
                episode_data['runtime'] = int(episode_data['runtime']) if episode_data['runtime'] else 0
            except:
                episode_data['runtime'] = 0
            
            try:
                episode_data['userrating'] = float(episode_data['userrating']) if episode_data['userrating'] else 0
            except:
                episode_data['userrating'] = 0
            
            return episode_data
            
        except Exception as e:
            print(f"Error parsing episode NFO: {e}")
            return None
    
    @staticmethod
    def find_episode_nfo(episode_path: str) -> Optional[str]:
        """Find NFO file for a specific episode"""
        folder = os.path.dirname(episode_path)
        basename = os.path.splitext(os.path.basename(episode_path))[0]
        
        # Check for episode-specific NFO (same name as video file)
        nfo_path = os.path.join(folder, f"{basename}.nfo")
        if os.path.exists(nfo_path):
            return nfo_path
        
        return None


class MediaFileParser:
    """Parse media filenames to extract title, year, season, episode info"""
    
    # Common video extensions
    VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.m2ts'}
    
    # Regex patterns for parsing
    MOVIE_PATTERNS = [
        # Movie Name (2024) or Movie Name 2024
        r'^(?P<title>.+?)\s*[\(\[]?(?P<year>(?:19|20)\d{2})[\)\]]?',
        # Movie.Name.2024.1080p.BluRay
        r'^(?P<title>.+?)\.(?P<year>(?:19|20)\d{2})\.',
    ]
    
    TV_PATTERNS = [
        # Show Name - S01E05 - Episode Title
        r'^(?P<show>.+?)\s*-?\s*[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,2})',
        # Show Name S01E05
        r'^(?P<show>.+?)\s*[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,2})',
        # Show Name 1x05
        r'^(?P<show>.+?)\s*(?P<season>\d{1,2})x(?P<episode>\d{2})',
        # Show.Name.S01E05
        r'^(?P<show>.+?)\.+[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,2})',
    ]
    
    @staticmethod
    def is_video_file(filepath: str) -> bool:
        """Check if file is a video file"""
        ext = os.path.splitext(filepath)[1].lower()
        return ext in MediaFileParser.VIDEO_EXTENSIONS
    
    @staticmethod
    def parse_movie(filename: str) -> Dict[str, str]:
        """Parse movie filename to extract title and year"""
        # Remove extension
        name = os.path.splitext(filename)[0]
        
        # Clean up common patterns
        name = re.sub(r'\[.*?\]', '', name)  # Remove [anything]
        name = re.sub(r'\{.*?\}', '', name)  # Remove {anything}
        
        for pattern in MediaFileParser.MOVIE_PATTERNS:
            match = re.match(pattern, name, re.IGNORECASE)
            if match:
                title = match.group('title')
                year = match.group('year')
                
                # Clean up title
                title = re.sub(r'[\._]', ' ', title)
                title = re.sub(r'\s+', ' ', title).strip()
                
                return {'title': title, 'year': year}
        
        # Fallback: use filename as title
        title = re.sub(r'[\._]', ' ', name)
        title = re.sub(r'\s+', ' ', title).strip()
        return {'title': title, 'year': ''}
    
    @staticmethod
    def parse_tv_episode(filename: str) -> Dict[str, str]:
        """Parse TV episode filename to extract show, season, episode"""
        # Remove extension
        name = os.path.splitext(filename)[0]
        
        # Clean up common patterns
        name = re.sub(r'\[.*?\]', '', name)  # Remove [anything]
        name = re.sub(r'\{.*?\}', '', name)  # Remove {anything}
        
        for pattern in MediaFileParser.TV_PATTERNS:
            match = re.match(pattern, name, re.IGNORECASE)
            if match:
                show = match.group('show')
                season = match.group('season')
                episode = match.group('episode')
                
                # Clean up show name
                show = re.sub(r'[\._]', ' ', show)
                show = re.sub(r'\s+', ' ', show).strip()
                
                return {
                    'show': show,
                    'season': int(season),
                    'episode': int(episode)
                }
        
        return {'show': '', 'season': 0, 'episode': 0}
    
    @staticmethod
    def generate_movie_filename(movie_data: Dict, extension: str = '.mkv') -> str:
        """Generate proper movie filename from metadata"""
        title = movie_data.get('title', 'Unknown')
        year = movie_data.get('year', '')
        
        # Clean title for filename
        title = re.sub(r'[<>:"/\\|?*]', '', title)
        title = title.strip()
        
        if year:
            return f"{title} ({year}){extension}"
        return f"{title}{extension}"
    
    @staticmethod
    def generate_tv_filename(show_name: str, season: int, episode: int, 
                            episode_title: str = '', extension: str = '.mkv') -> str:
        """Generate proper TV episode filename from metadata"""
        # Clean names for filename
        show_name = re.sub(r'[<>:"/\\|?*]', '', show_name).strip()
        episode_title = re.sub(r'[<>:"/\\|?*]', '', episode_title).strip()
        
        base = f"{show_name} - S{season:02d}E{episode:02d}"
        
        if episode_title:
            return f"{base} - {episode_title}{extension}"
        return f"{base}{extension}"


# =============================================================================
# CUSTOM WIDGETS - PARAGON STYLE
# =============================================================================

class ParagonFrame(ctk.CTkFrame):
    """Frame with Paragon-style gold border"""
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            fg_color=ParagonTheme.BG_SECONDARY,
            border_color=ParagonTheme.BORDER_GOLD,
            border_width=1,
            corner_radius=8,
            **kwargs
        )


class ParagonButton(ctk.CTkButton):
    """Paragon-style button with red/orange gradient effect"""
    def __init__(self, master, **kwargs):
        defaults = {
            'fg_color': ParagonTheme.RED_PRIMARY,
            'hover_color': ParagonTheme.RED_LIGHT,
            'text_color': ParagonTheme.TEXT_PRIMARY,
            'corner_radius': 6,
            'font': ctk.CTkFont(family="Bebas Neue", size=28),
            'height': 50,
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)


class ParagonSecondaryButton(ctk.CTkButton):
    """Secondary button with subtle styling"""
    def __init__(self, master, **kwargs):
        defaults = {
            'fg_color': ParagonTheme.BG_TERTIARY,
            'hover_color': ParagonTheme.BG_HOVER,
            'text_color': ParagonTheme.GOLD,
            'border_color': ParagonTheme.BORDER_RED,
            'border_width': 1,
            'corner_radius': 6,
            'font': ctk.CTkFont(family="Bebas Neue", size=26),
            'height': 46,
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)


class ParagonGoldButton(ctk.CTkButton):
    """Gold accent button for primary actions"""
    def __init__(self, master, **kwargs):
        defaults = {
            'fg_color': ParagonTheme.GOLD,
            'hover_color': ParagonTheme.GOLD_LIGHT,
            'text_color': "#000000",
            'corner_radius': 6,
            'font': ctk.CTkFont(family="Bebas Neue", size=28),
            'height': 54,
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)


class ParagonEntry(ctk.CTkEntry):
    """Paragon-style entry field"""
    def __init__(self, master, **kwargs):
        defaults = {
            'fg_color': ParagonTheme.BG_TERTIARY,
            'border_color': ParagonTheme.BORDER_DARK,
            'text_color': ParagonTheme.TEXT_PRIMARY,
            'placeholder_text_color': ParagonTheme.TEXT_DISABLED,
            'corner_radius': 6,
            'height': 46,
            'font': ctk.CTkFont(family="Segoe UI", size=18),
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)


class ParagonLabel(ctk.CTkLabel):
    """Paragon-style label"""
    def __init__(self, master, style="normal", **kwargs):
        defaults = {
            'text_color': ParagonTheme.TEXT_PRIMARY,
            'font': ctk.CTkFont(family="Segoe UI", size=18),
        }
        
        if style == "title":
            defaults['text_color'] = ParagonTheme.TEXT_PRIMARY  # White
            defaults['font'] = ctk.CTkFont(family="Bebas Neue", size=48)
        elif style == "header":
            defaults['text_color'] = ParagonTheme.TEXT_PRIMARY  # White
            defaults['font'] = ctk.CTkFont(family="Bebas Neue", size=32)
        elif style == "subheader":
            defaults['text_color'] = ParagonTheme.TEXT_PRIMARY  # White
            defaults['font'] = ctk.CTkFont(family="Bebas Neue", size=26)
        elif style == "accent":
            defaults['text_color'] = ParagonTheme.RED_LIGHT
            defaults['font'] = ctk.CTkFont(family="Bebas Neue", size=28)
        elif style == "muted":
            defaults['text_color'] = ParagonTheme.TEXT_SECONDARY
            defaults['font'] = ctk.CTkFont(family="Segoe UI", size=16)
        
        defaults.update(kwargs)
        super().__init__(master, **defaults)


class ParagonCheckbox(ctk.CTkCheckBox):
    """Paragon-style checkbox"""
    def __init__(self, master, **kwargs):
        defaults = {
            'fg_color': ParagonTheme.RED_PRIMARY,
            'hover_color': ParagonTheme.RED_LIGHT,
            'border_color': ParagonTheme.BORDER_DARK,
            'checkmark_color': ParagonTheme.TEXT_PRIMARY,
            'text_color': ParagonTheme.TEXT_PRIMARY,
            'font': ctk.CTkFont(family="Segoe UI", size=18),
            'corner_radius': 4,
            'checkbox_width': 24,
            'checkbox_height': 24,
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)


class ParagonRadioButton(ctk.CTkRadioButton):
    """Paragon-style radio button"""
    def __init__(self, master, **kwargs):
        defaults = {
            'fg_color': ParagonTheme.RED_PRIMARY,
            'hover_color': ParagonTheme.RED_LIGHT,
            'border_color': ParagonTheme.BORDER_DARK,
            'text_color': ParagonTheme.TEXT_PRIMARY,
            'font': ctk.CTkFont(family="Segoe UI", size=18),
            'radiobutton_width': 24,
            'radiobutton_height': 24,
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)


class ParagonOptionMenu(ctk.CTkOptionMenu):
    """Paragon-style dropdown menu"""
    def __init__(self, master, **kwargs):
        defaults = {
            'fg_color': ParagonTheme.BG_TERTIARY,
            'button_color': ParagonTheme.RED_DARK,
            'button_hover_color': ParagonTheme.RED_PRIMARY,
            'dropdown_fg_color': ParagonTheme.BG_TERTIARY,
            'dropdown_hover_color': ParagonTheme.BG_HOVER,
            'text_color': ParagonTheme.TEXT_PRIMARY,
            'dropdown_text_color': ParagonTheme.TEXT_PRIMARY,
            'corner_radius': 6,
            'font': ctk.CTkFont(family="Segoe UI", size=18),
            'height': 40,
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)


class ParagonTabview(ctk.CTkTabview):
    """Paragon-style tabview"""
    def __init__(self, master, **kwargs):
        defaults = {
            'fg_color': ParagonTheme.BG_SECONDARY,
            'segmented_button_fg_color': ParagonTheme.BG_TERTIARY,
            'segmented_button_selected_color': ParagonTheme.RED_PRIMARY,
            'segmented_button_selected_hover_color': ParagonTheme.RED_LIGHT,
            'segmented_button_unselected_color': ParagonTheme.BG_TERTIARY,
            'segmented_button_unselected_hover_color': ParagonTheme.BG_HOVER,
            'text_color': ParagonTheme.TEXT_PRIMARY,
            'corner_radius': 8,
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)
        # Set tab font after init
        self._segmented_button.configure(font=ctk.CTkFont(family="Segoe UI", size=16))


class ParagonProgressBar(ctk.CTkProgressBar):
    """Paragon-style progress bar"""
    def __init__(self, master, **kwargs):
        defaults = {
            'fg_color': ParagonTheme.BG_TERTIARY,
            'progress_color': ParagonTheme.RED_PRIMARY,
            'corner_radius': 4,
            'height': 8,
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)


# =============================================================================
# PARAGON FILE BROWSER DIALOG
# =============================================================================

class ParagonFileBrowser(ctk.CTkToplevel):
    """Custom Paragon-styled file browser dialog"""
    
    def __init__(self, master, mode="files", title="Select Files", 
                 initial_dir=None, multiple=True, file_types=None):
        super().__init__(master)
        
        # Configuration
        self.mode = mode  # "files", "folder", or "both"
        self.multiple = multiple
        self.file_types = file_types or [("All files", "*")]
        self.result = []
        self.current_path = Path(initial_dir or Path.home())
        self.selected_items = set()
        self.history = [self.current_path]
        self.history_index = 0
        
        # Window setup
        self.title(title)
        self.geometry("900x600")
        self.minsize(700, 450)
        self.configure(fg_color=ParagonTheme.BG_DARK)
        
        # Link to parent
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        # Build UI first
        self._create_ui()
        
        # Center on parent
        self.update_idletasks()
        x = master.winfo_x() + (master.winfo_width() - 900) // 2
        y = master.winfo_y() + (master.winfo_height() - 600) // 2
        self.geometry(f"900x600+{x}+{y}")
        
        # Make sure window is visible before grab
        self.deiconify()
        self.lift()
        self.focus_force()
        
        # Wait for window to be viewable, then grab and load files
        self.after(50, self._on_window_ready)
        
        # Wait for window to close
        self.wait_window()
    
    def _on_window_ready(self):
        """Called when window is ready - set grab and load files"""
        try:
            self.grab_set()
        except Exception:
            # If grab fails, try again after a short delay
            self.after(50, self._try_grab)
        self._refresh_file_list()
    
    def _try_grab(self):
        """Try to grab focus"""
        try:
            self.grab_set()
        except Exception:
            pass
    
    def _create_ui(self):
        """Create the file browser UI"""
        # Main container with gold border
        outer_frame = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=10)
        outer_frame.pack(fill="both", expand=True, padx=3, pady=3)
        
        inner_frame = ctk.CTkFrame(outer_frame, fg_color=ParagonTheme.BG_DARK, corner_radius=8)
        inner_frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Header
        self._create_header(inner_frame)
        
        # Decorative line
        self._create_decorative_line(inner_frame)
        
        # Navigation bar
        self._create_nav_bar(inner_frame)
        
        # File list area
        self._create_file_list(inner_frame)
        
        # Bottom decorative line
        self._create_decorative_line(inner_frame)
        
        # Footer with buttons
        self._create_footer(inner_frame)
    
    def _create_header(self, parent):
        """Create dialog header"""
        header = ctk.CTkFrame(parent, fg_color="transparent", height=70)
        header.pack(fill="x", padx=15, pady=(20, 5))
        header.pack_propagate(False)
        
        # Title
        title_text = "📁  SELECT FOLDER" if self.mode == "folder" else "📄  SELECT FILES"
        title = ctk.CTkLabel(
            header,
            text=title_text,
            font=ctk.CTkFont(family="Bebas Neue", size=40),
            text_color=ParagonTheme.TEXT_PRIMARY
        )
        title.pack(side="left", pady=5)
        
        # Close button
        close_btn = ctk.CTkButton(
            header,
            text="✕",
            width=35,
            height=35,
            corner_radius=6,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.RED_PRIMARY,
            text_color=ParagonTheme.TEXT_PRIMARY,
            font=ctk.CTkFont(size=16),
            command=self._on_cancel
        )
        close_btn.pack(side="right", pady=10)
    
    def _create_decorative_line(self, parent):
        """Create Paragon-style decorative line"""
        container = ctk.CTkFrame(parent, fg_color="transparent", height=6)
        container.pack(fill="x", padx=10, pady=3)
        container.pack_propagate(False)
        
        red_line = ctk.CTkFrame(container, fg_color=ParagonTheme.RED_DARK, height=2, corner_radius=1)
        red_line.pack(fill="x", pady=(0, 1))
        
        gold_line = ctk.CTkFrame(container, fg_color=ParagonTheme.GOLD, height=2, corner_radius=1)
        gold_line.pack(fill="x")
    
    def _create_nav_bar(self, parent):
        """Create navigation bar with breadcrumbs"""
        nav_frame = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=6, height=45)
        nav_frame.pack(fill="x", padx=15, pady=(10, 5))
        nav_frame.pack_propagate(False)
        
        # Navigation buttons
        btn_frame = ctk.CTkFrame(nav_frame, fg_color="transparent")
        btn_frame.pack(side="left", padx=5, pady=5)
        
        # Back button
        self.back_btn = ctk.CTkButton(
            btn_frame, text="◀", width=35, height=30,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_PRIMARY,
            corner_radius=4,
            command=self._go_back
        )
        self.back_btn.pack(side="left", padx=2)
        
        # Forward button
        self.forward_btn = ctk.CTkButton(
            btn_frame, text="▶", width=35, height=30,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_PRIMARY,
            corner_radius=4,
            command=self._go_forward
        )
        self.forward_btn.pack(side="left", padx=2)
        
        # Up button
        up_btn = ctk.CTkButton(
            btn_frame, text="▲", width=35, height=30,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_PRIMARY,
            corner_radius=4,
            command=self._go_up
        )
        up_btn.pack(side="left", padx=2)
        
        # Home button
        home_btn = ctk.CTkButton(
            btn_frame, text="🏠", width=35, height=30,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_PRIMARY,
            corner_radius=4,
            command=self._go_home
        )
        home_btn.pack(side="left", padx=2)
        
        # Refresh button
        refresh_btn = ctk.CTkButton(
            btn_frame, text="🔄", width=35, height=30,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_PRIMARY,
            corner_radius=4,
            command=self._refresh_file_list
        )
        refresh_btn.pack(side="left", padx=2)
        
        # Path entry
        self.path_entry = ctk.CTkEntry(
            nav_frame,
            fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK,
            text_color=ParagonTheme.TEXT_PRIMARY,
            corner_radius=4,
            height=30,
            font=ctk.CTkFont(family="Segoe UI", size=11)
        )
        self.path_entry.pack(side="left", fill="x", expand=True, padx=10, pady=5)
        self.path_entry.bind("<Return>", self._on_path_enter)
        
        # Quick access dropdown - matching header font style
        locations = list(self._quick_access_locations().keys())
        self.quick_access = ctk.CTkOptionMenu(
            nav_frame,
            values=locations,
            width=100,
            height=30,
            fg_color=ParagonTheme.BG_TERTIARY,
            button_color=ParagonTheme.RED_PRIMARY,
            button_hover_color=ParagonTheme.RED_LIGHT,
            dropdown_fg_color=ParagonTheme.BG_SECONDARY,
            dropdown_hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_PRIMARY,
            font=ctk.CTkFont(family="Bebas Neue", size=20),
            dropdown_font=ctk.CTkFont(family="Segoe UI", size=14),
            command=self._on_quick_access
        )
        self.quick_access.pack(side="right", padx=5, pady=5)
        self.quick_access.set("Quick")
    
    def _create_file_list(self, parent):
        """Create the file listing area"""
        # Container with border
        list_outer = ctk.CTkFrame(parent, fg_color=ParagonTheme.BORDER_RED, corner_radius=6)
        list_outer.pack(fill="both", expand=True, padx=15, pady=10)
        
        list_container = ctk.CTkFrame(list_outer, fg_color=ParagonTheme.BG_DARK, corner_radius=4)
        list_container.pack(fill="both", expand=True, padx=1, pady=1)
        
        # Column headers
        header = ctk.CTkFrame(list_container, fg_color=ParagonTheme.BG_TERTIARY, height=35, corner_radius=0)
        header.pack(fill="x", padx=2, pady=(2, 0))
        header.pack_propagate(False)
        
        ctk.CTkLabel(
            header, text="    NAME", 
            font=ctk.CTkFont(family="Bebas Neue", size=24),
            text_color=ParagonTheme.TEXT_PRIMARY
        ).pack(side="left", padx=10)
        
        ctk.CTkLabel(
            header, text="SIZE",
            font=ctk.CTkFont(family="Bebas Neue", size=24),
            text_color=ParagonTheme.TEXT_PRIMARY
        ).pack(side="right", padx=20)
        
        ctk.CTkLabel(
            header, text="MODIFIED",
            font=ctk.CTkFont(family="Bebas Neue", size=24),
            text_color=ParagonTheme.TEXT_PRIMARY
        ).pack(side="right", padx=20)
        
        # Scrollable file list
        self.file_list_frame = ctk.CTkScrollableFrame(
            list_container,
            fg_color=ParagonTheme.BG_DARK,
            corner_radius=0
        )
        self.file_list_frame.pack(fill="both", expand=True, padx=2, pady=2)
    
    def _create_footer(self, parent):
        """Create footer with selection info and buttons"""
        footer = ctk.CTkFrame(parent, fg_color="transparent", height=60)
        footer.pack(fill="x", padx=15, pady=(5, 15))
        footer.pack_propagate(False)
        
        # Selection info
        info_frame = ctk.CTkFrame(footer, fg_color="transparent")
        info_frame.pack(side="left", fill="y")
        
        self.selection_label = ctk.CTkLabel(
            info_frame,
            text="No items selected",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=ParagonTheme.TEXT_SECONDARY
        )
        self.selection_label.pack(side="left", pady=15)
        
        # Buttons
        btn_frame = ctk.CTkFrame(footer, fg_color="transparent")
        btn_frame.pack(side="right", fill="y")
        
        # Cancel button
        cancel_btn = ParagonSecondaryButton(
            btn_frame,
            text="CANCEL",
            width=100,
            command=self._on_cancel
        )
        cancel_btn.pack(side="left", padx=(0, 10), pady=10)
        
        # Select/Open button
        action_text = "SELECT FOLDER" if self.mode == "folder" else "SELECT FILES"
        self.select_btn = ParagonGoldButton(
            btn_frame,
            text=action_text,
            width=140,
            command=self._on_select
        )
        self.select_btn.pack(side="left", pady=10)
    
    def _refresh_file_list(self):
        """Refresh the file listing"""
        # Clear existing items
        for widget in self.file_list_frame.winfo_children():
            widget.destroy()
        self.selected_items.clear()
        
        # Update path entry
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, str(self.current_path))
        
        # Update navigation buttons
        self.back_btn.configure(state="normal" if self.history_index > 0 else "disabled")
        self.forward_btn.configure(state="normal" if self.history_index < len(self.history) - 1 else "disabled")
        
        path_str = str(self.current_path)
        
        # Check for cached classified listing first
        cache_key = f"{path_str}_classified"
        cached = PyRenamerApp.get_cached_listing(cache_key)
        
        if cached is not None:
            # Use cached classification
            dirs, files = cached
        else:
            try:
                # Use os.scandir for much better NFS performance
                # It gets file type info in the same call as listing
                dirs = []
                files = []
                
                with os.scandir(path_str) as scanner:
                    for entry in scanner:
                        if entry.name.startswith('.'):
                            continue
                        try:
                            # entry.is_dir() uses cached info from scandir, much faster
                            if entry.is_dir(follow_symlinks=True):
                                dirs.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=True):
                                files.append(Path(entry.path))
                        except OSError:
                            # If we can't determine, treat as folder for NFS mounts
                            dirs.append(Path(entry.path))
                
                # Sort
                dirs.sort(key=lambda x: x.name.lower())
                files.sort(key=lambda x: x.name.lower())
                
                # Cache the classified result
                PyRenamerApp.cache_listing(cache_key, (dirs, files))
                
            except PermissionError:
                self._show_error_item("Permission denied")
                return
            except OSError as e:
                self._show_error_item(f"Cannot access: {e}")
                return
            except Exception as e:
                self._show_error_item(str(e))
                return
        
        # Add directories first
        for idx, path in enumerate(dirs):
            self._add_file_item(path, idx, is_dir=True)
        
        # Add files (if not in folder-only mode)
        if self.mode != "folder":
            for idx, path in enumerate(files, start=len(dirs)):
                self._add_file_item(path, idx, is_dir=False)
        
        # Update selection label
        self._update_selection_label()
    
    def _add_file_item(self, path: Path, index: int, is_dir: bool):
        """Add a file/folder item to the list"""
        bg_color = ParagonTheme.BG_SECONDARY if index % 2 == 0 else ParagonTheme.BG_DARK
        
        item_frame = ctk.CTkFrame(
            self.file_list_frame,
            fg_color=bg_color,
            corner_radius=4,
            height=36
        )
        item_frame.pack(fill="x", padx=2, pady=1)
        item_frame.pack_propagate(False)
        
        # Store path reference
        item_frame.path = path
        item_frame.is_dir = is_dir
        item_frame.original_bg = bg_color
        
        # Icon and name
        icon = "📁" if is_dir else self._get_file_icon(path.suffix)
        
        name_frame = ctk.CTkFrame(item_frame, fg_color="transparent")
        name_frame.pack(side="left", fill="y", padx=(10, 0))
        
        icon_label = ctk.CTkLabel(
            name_frame,
            text=icon,
            font=ctk.CTkFont(size=14),
            width=25
        )
        icon_label.pack(side="left")
        
        name_label = ctk.CTkLabel(
            name_frame,
            text=path.name,
            font=ctk.CTkFont(family="Segoe UI", size=16),
            text_color=ParagonTheme.TEXT_PRIMARY,
            anchor="w"
        )
        name_label.pack(side="left", padx=5)
        
        # Size (for files)
        if not is_dir:
            try:
                size = path.stat().st_size
                size_str = self._format_size(size)
            except:
                size_str = "—"
            
            size_label = ctk.CTkLabel(
                item_frame,
                text=size_str,
                font=ctk.CTkFont(family="Segoe UI", size=14),
                text_color=ParagonTheme.TEXT_SECONDARY,
                width=80
            )
            size_label.pack(side="right", padx=15)
        
        # Modified date
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            date_str = mtime.strftime("%Y-%m-%d %H:%M")
        except:
            date_str = "—"
        
        date_label = ctk.CTkLabel(
            item_frame,
            text=date_str,
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=ParagonTheme.TEXT_SECONDARY,
            width=120
        )
        date_label.pack(side="right", padx=10)
        
        # Bind events
        for widget in [item_frame, name_frame, icon_label, name_label]:
            widget.bind("<Button-1>", lambda e, f=item_frame: self._on_item_click(f, e))
            widget.bind("<Double-Button-1>", lambda e, f=item_frame: self._on_item_double_click(f))
        
        if not is_dir:
            for widget in [size_label]:
                widget.bind("<Button-1>", lambda e, f=item_frame: self._on_item_click(f, e))
                widget.bind("<Double-Button-1>", lambda e, f=item_frame: self._on_item_double_click(f))
        
        date_label.bind("<Button-1>", lambda e, f=item_frame: self._on_item_click(f, e))
        date_label.bind("<Double-Button-1>", lambda e, f=item_frame: self._on_item_double_click(f))
    
    def _show_error_item(self, message: str):
        """Show an error message in the file list"""
        error_frame = ctk.CTkFrame(self.file_list_frame, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=4)
        error_frame.pack(fill="x", padx=2, pady=20)
        
        ctk.CTkLabel(
            error_frame,
            text=f"⚠️  {message}",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=ParagonTheme.ERROR
        ).pack(pady=20)
    
    def _get_file_icon(self, suffix: str) -> str:
        """Get icon for file type"""
        suffix = suffix.lower()
        icons = {
            '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️', '.bmp': '🖼️', '.webp': '🖼️',
            '.mp3': '🎵', '.flac': '🎵', '.wav': '🎵', '.ogg': '🎵', '.m4a': '🎵',
            '.mp4': '🎬', '.mkv': '🎬', '.avi': '🎬', '.mov': '🎬', '.wmv': '🎬',
            '.pdf': '📕', '.doc': '📘', '.docx': '📘', '.txt': '📝', '.md': '📝',
            '.zip': '📦', '.rar': '📦', '.7z': '📦', '.tar': '📦', '.gz': '📦',
            '.py': '🐍', '.js': '📜', '.html': '🌐', '.css': '🎨', '.json': '📋',
            '.exe': '⚙️', '.sh': '⚙️', '.bat': '⚙️',
        }
        return icons.get(suffix, '📄')
    
    def _format_size(self, size: int) -> str:
        """Format file size"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != 'B' else f"{size} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def _on_item_click(self, frame, event):
        """Handle single click on item"""
        path = frame.path
        
        # Ctrl+click for multi-select
        ctrl_held = event.state & 0x4
        
        if not ctrl_held and self.multiple:
            # Clear previous selection
            for item in self.file_list_frame.winfo_children():
                if hasattr(item, 'path'):
                    item.configure(fg_color=item.original_bg)
            self.selected_items.clear()
        
        if path in self.selected_items:
            # Deselect
            self.selected_items.remove(path)
            frame.configure(fg_color=frame.original_bg)
        else:
            # Select
            if self.mode == "folder" and not frame.is_dir:
                return  # Can't select files in folder mode
            
            if not self.multiple:
                self.selected_items.clear()
                for item in self.file_list_frame.winfo_children():
                    if hasattr(item, 'path'):
                        item.configure(fg_color=item.original_bg)
            
            self.selected_items.add(path)
            frame.configure(fg_color=ParagonTheme.RED_DARK)
        
        self._update_selection_label()
    
    def _on_item_double_click(self, frame):
        """Handle double click - navigate into folder"""
        if frame.is_dir:
            self._navigate_to(frame.path)
    
    def _navigate_to(self, path: Path):
        """Navigate to a directory"""
        if not path.is_dir():
            return
        
        # Update history
        self.history = self.history[:self.history_index + 1]
        self.history.append(path)
        self.history_index = len(self.history) - 1
        
        self.current_path = path
        self._refresh_file_list()
    
    def _go_back(self):
        """Navigate back in history"""
        if self.history_index > 0:
            self.history_index -= 1
            self.current_path = self.history[self.history_index]
            self._refresh_file_list()
    
    def _go_forward(self):
        """Navigate forward in history"""
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.current_path = self.history[self.history_index]
            self._refresh_file_list()
    
    def _go_up(self):
        """Navigate to parent directory"""
        parent = self.current_path.parent
        if parent != self.current_path:
            self._navigate_to(parent)
    
    def _go_home(self):
        """Navigate to home directory"""
        self._navigate_to(Path.home())
    
    def _on_path_enter(self, event):
        """Handle enter key in path entry"""
        path_str = self.path_entry.get().strip()
        path = Path(path_str)
        if path.exists() and path.is_dir():
            self._navigate_to(path)
        else:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, str(self.current_path))
    
    def _quick_access_locations(self):
        """Ordered quick-access label -> Path map, tailored to the platform.

        On Windows the POSIX '/mnt' and '/' roots are replaced with the
        machine's actual drive letters (C:, T:, ...) so the shortcuts point
        somewhere real."""
        locations = {
            "Home": Path.home(),
            "Desktop": Path.home() / "Desktop",
            "Documents": Path.home() / "Documents",
            "Downloads": Path.home() / "Downloads",
        }
        if os.name == 'nt':
            # Enumerate assigned drive letters without touching the drives
            # (GetLogicalDrives is a cheap bitmask - avoids stalling on a
            # disconnected mapped network drive).
            import string
            try:
                import ctypes
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            except Exception:
                bitmask = 0
            for i, letter in enumerate(string.ascii_uppercase):
                if bitmask & (1 << i):
                    locations[f"{letter}:"] = Path(f"{letter}:\\")
        else:
            locations["/mnt"] = Path("/mnt")
            locations["/"] = Path("/")
        return locations

    def _on_quick_access(self, choice):
        """Handle quick access dropdown"""
        locations = self._quick_access_locations()
        if choice in locations:
            path = locations[choice]
            if path.exists():
                self._navigate_to(path)
        self.quick_access.set("Quick")
    
    def _update_selection_label(self):
        """Update the selection info label"""
        count = len(self.selected_items)
        if count == 0:
            text = "No items selected"
        elif count == 1:
            name = list(self.selected_items)[0].name
            text = f"Selected: {name}"
        else:
            text = f"{count} items selected"
        self.selection_label.configure(text=text)
    
    def _on_cancel(self):
        """Handle cancel button"""
        self.result = []
        self.destroy()
    
    def _on_select(self):
        """Handle select button"""
        if self.mode == "folder":
            # In folder mode, return current directory if nothing selected
            if not self.selected_items:
                self.result = [self.current_path]
            else:
                self.result = [p for p in self.selected_items if p.is_dir()]
        else:
            self.result = list(self.selected_items)
        self.destroy()
    
    def get_result(self) -> List[Path]:
        """Get the selected paths"""
        return self.result


# =============================================================================
# FILE LIST WIDGET
# =============================================================================

class FileListWidget(ctk.CTkFrame):
    """Optimized file list using Treeview for better performance"""
    
    def __init__(self, master, on_selection_change=None, **kwargs):
        # Remove height from kwargs if present (we'll handle sizing differently)
        kwargs.pop('height', None)
        
        super().__init__(
            master,
            fg_color=ParagonTheme.BG_DARK,
            corner_radius=8,
        )
        
        self.items: List[Dict] = []
        self._item_ids: List[str] = []  # Treeview item IDs
        self._on_selection_change = on_selection_change
        
        # Create Treeview with custom styling (includes headers)
        self._create_treeview()
    
    def _create_treeview(self):
        """Create the Treeview widget with resizable columns and scrollbars"""
        # Container for treeview and scrollbars
        tree_container = ctk.CTkFrame(self, fg_color=ParagonTheme.BG_DARK)
        tree_container.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Style the Treeview
        style = tk.ttk.Style()
        style.theme_use('clam')
        
        # Configure Treeview colors - SMALLER FONT (12 instead of 16)
        style.configure("Paragon.Treeview",
            background=ParagonTheme.BG_DARK,
            foreground=ParagonTheme.TEXT_PRIMARY,
            fieldbackground=ParagonTheme.BG_DARK,
            borderwidth=0,
            rowheight=32,
            font=('Segoe UI', 12)
        )
        style.configure("Paragon.Treeview.Heading",
            background=ParagonTheme.BG_TERTIARY,
            foreground=ParagonTheme.GOLD,
            borderwidth=1,
            relief="flat",
            font=('Bebas Neue', 20)
        )
        style.map("Paragon.Treeview",
            background=[('selected', ParagonTheme.RED_DARK)],
            foreground=[('selected', ParagonTheme.TEXT_PRIMARY)]
        )
        style.map("Paragon.Treeview.Heading",
            background=[('active', ParagonTheme.BG_HOVER)],
        )
        
        # Create Treeview with visible headings for resizing
        self.tree = tk.ttk.Treeview(
            tree_container,
            columns=('original', 'new', 'status'),
            show='headings',  # Show headings for resizable columns
            style="Paragon.Treeview",
            selectmode='extended'
        )
        
        # Configure columns - resizable with min width
        self.tree.heading('original', text='ORIGINAL NAME', anchor='w')
        self.tree.heading('new', text='NEW NAME', anchor='w')
        self.tree.heading('status', text='STATUS', anchor='center')
        
        self.tree.column('original', width=400, minwidth=150, stretch=True, anchor='w')
        self.tree.column('new', width=400, minwidth=150, stretch=True, anchor='w')
        self.tree.column('status', width=80, minwidth=60, stretch=False, anchor='center')
        
        # Vertical scrollbar
        v_scrollbar = ctk.CTkScrollbar(tree_container, command=self.tree.yview)
        v_scrollbar.pack(side="right", fill="y")
        
        # Horizontal scrollbar
        h_scrollbar = ctk.CTkScrollbar(tree_container, command=self.tree.xview, orientation="horizontal")
        h_scrollbar.pack(side="bottom", fill="x")
        
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        self.tree.pack(fill="both", expand=True)
        
        # Bind selection change
        self.tree.bind('<<TreeviewSelect>>', self._on_select)
        
        # Tags for coloring
        self.tree.tag_configure('changed', foreground=ParagonTheme.SUCCESS)
        self.tree.tag_configure('unchanged', foreground=ParagonTheme.TEXT_SECONDARY)
        self.tree.tag_configure('even', background=ParagonTheme.BG_SECONDARY)
        self.tree.tag_configure('odd', background=ParagonTheme.BG_DARK)
    
    def clear(self):
        """Clear all items"""
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self._item_ids.clear()
    
    def set_items(self, items: List[tuple]):
        """
        Set all items at once (more efficient than adding one by one)
        items: List of (original, new_name, changed) tuples
        """
        # If same number of items, update in place
        if len(items) == len(self._item_ids):
            self._update_items(items)
        else:
            # Different count - rebuild
            self._rebuild_items(items)
    
    def _update_items(self, items: List[tuple]):
        """Update existing items in place (fast)"""
        for i, (original, new_name, changed) in enumerate(items):
            item_id = self._item_ids[i]
            
            # Update values
            status_text = "✓ Changed" if changed else "—"
            self.tree.item(item_id, values=(original, new_name, status_text))
            
            # Update tags
            row_tag = 'even' if i % 2 == 0 else 'odd'
            change_tag = 'changed' if changed else 'unchanged'
            self.tree.item(item_id, tags=(row_tag, change_tag))
            
            # Update stored data
            self.items[i] = {'original': original, 'new_name': new_name, 'changed': changed}
    
    def _rebuild_items(self, items: List[tuple]):
        """Rebuild all items (when count changes)"""
        self.clear()
        
        for i, (original, new_name, changed) in enumerate(items):
            status_text = "✓ Changed" if changed else "—"
            row_tag = 'even' if i % 2 == 0 else 'odd'
            change_tag = 'changed' if changed else 'unchanged'
            
            item_id = self.tree.insert('', 'end', values=(original, new_name, status_text), tags=(row_tag, change_tag))
            self._item_ids.append(item_id)
            self.items.append({'original': original, 'new_name': new_name, 'changed': changed})
    
    def add_item(self, original: str, new_name: str, changed: bool):
        """Add a single item (for compatibility)"""
        idx = len(self.items)
        status_text = "✓ Changed" if changed else "—"
        row_tag = 'even' if idx % 2 == 0 else 'odd'
        change_tag = 'changed' if changed else 'unchanged'
        
        item_id = self.tree.insert('', 'end', values=(original, new_name, status_text), tags=(row_tag, change_tag))
        self._item_ids.append(item_id)
        self.items.append({'original': original, 'new_name': new_name, 'changed': changed})
    
    def get_selected_indices(self) -> List[int]:
        """Get indices of selected items"""
        selected = self.tree.selection()
        return [self._item_ids.index(item_id) for item_id in selected if item_id in self._item_ids]
    
    def _on_select(self, event):
        """Handle selection change"""
        if self._on_selection_change:
            self._on_selection_change()
    
    def get_count(self) -> int:
        return len(self.items)
    
    def get_changed_count(self) -> int:
        return sum(1 for item in self.items if item['changed'])


# =============================================================================
# TAG EDITOR PANEL - MP3TAG STYLE
# =============================================================================

class TagEditorPanel(ctk.CTkFrame):
    """MP3tag-style tag editor panel"""
    
    def __init__(self, master, on_tags_changed=None, **kwargs):
        super().__init__(master, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, **kwargs)
        
        self.on_tags_changed = on_tags_changed
        self.current_files: List[str] = []
        self.cover_image_data: Optional[bytes] = None
        self._cover_photo = None  # Keep reference to prevent garbage collection
        
        self._create_ui()
    
    def _create_ui(self):
        """Create the tag editor UI"""
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(15, 10))
        
        ParagonLabel(header, text="🎵 TAG EDITOR", style="title").pack(side="left")
        
        self.file_count_label = ParagonLabel(header, text="No files selected", style="muted")
        self.file_count_label.pack(side="right")
        
        # Main content - two columns
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        # Left side - Cover art
        left_frame = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=8, width=200)
        left_frame.pack(side="left", fill="y", padx=(0, 15))
        left_frame.pack_propagate(False)
        
        self._create_cover_section(left_frame)
        
        # Right side - Tag fields
        right_frame = ctk.CTkFrame(content, fg_color="transparent")
        right_frame.pack(side="left", fill="both", expand=True)
        
        self._create_tag_fields(right_frame)
        
        # Bottom buttons
        self._create_buttons()
    
    def _create_cover_section(self, parent):
        """Create cover art section"""
        ParagonLabel(parent, text="COVER ART", style="header").pack(pady=(15, 10))
        
        # Cover display area
        self.cover_frame = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_DARK, width=160, height=160, corner_radius=4)
        self.cover_frame.pack(padx=20, pady=5)
        self.cover_frame.pack_propagate(False)
        
        self.cover_label = ctk.CTkLabel(self.cover_frame, text="No Cover", text_color=ParagonTheme.TEXT_SECONDARY)
        self.cover_label.pack(expand=True)
        
        # Cover buttons
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=15)
        
        ctk.CTkButton(
            btn_frame, text="Add", width=55, height=32,
            fg_color=ParagonTheme.BG_HOVER,
            hover_color=ParagonTheme.RED_DARK,
            font=ctk.CTkFont(family="Bebas Neue", size=16),
            command=self._add_cover
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            btn_frame, text="Remove", width=65, height=32,
            fg_color=ParagonTheme.BG_HOVER,
            hover_color=ParagonTheme.RED_DARK,
            font=ctk.CTkFont(family="Bebas Neue", size=16),
            command=self._remove_cover
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            btn_frame, text="Extract", width=65, height=32,
            fg_color=ParagonTheme.BG_HOVER,
            hover_color=ParagonTheme.RED_DARK,
            font=ctk.CTkFont(family="Bebas Neue", size=16),
            command=self._extract_cover
        ).pack(side="left", padx=2)
    
    def _create_tag_fields(self, parent):
        """Create tag input fields"""
        # Scrollable frame for fields
        scroll_frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)
        
        self.tag_entries = {}
        
        # Core fields in two columns
        fields_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        fields_frame.pack(fill="x", pady=5)
        
        # Left column
        left_col = ctk.CTkFrame(fields_frame, fg_color="transparent")
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        # Right column
        right_col = ctk.CTkFrame(fields_frame, fg_color="transparent")
        right_col.pack(side="left", fill="both", expand=True)
        
        left_fields = [
            ('title', 'Title'),
            ('artist', 'Artist'),
            ('album', 'Album'),
            ('albumartist', 'Album Artist'),
        ]
        
        right_fields = [
            ('year', 'Year'),
            ('track', 'Track'),
            ('genre', 'Genre'),
            ('comment', 'Comment'),
        ]
        
        for field, label in left_fields:
            self._add_field(left_col, field, label)
        
        for field, label in right_fields:
            self._add_field(right_col, field, label)
        
        # Extended fields section (collapsible)
        ext_header = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        ext_header.pack(fill="x", pady=(20, 10))
        
        self.extended_visible = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            ext_header,
            text="Show Extended Tags",
            variable=self.extended_visible,
            command=self._toggle_extended,
            fg_color=ParagonTheme.RED_PRIMARY,
            hover_color=ParagonTheme.RED_LIGHT,
            font=ctk.CTkFont(family="Segoe UI", size=16)
        ).pack(side="left")
        
        self.extended_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        # Don't pack yet - will be toggled
        
        ext_fields_container = ctk.CTkFrame(self.extended_frame, fg_color="transparent")
        ext_fields_container.pack(fill="x")
        
        ext_left = ctk.CTkFrame(ext_fields_container, fg_color="transparent")
        ext_left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        ext_right = ctk.CTkFrame(ext_fields_container, fg_color="transparent")
        ext_right.pack(side="left", fill="both", expand=True)
        
        ext_left_fields = [
            ('composer', 'Composer'),
            ('conductor', 'Conductor'),
            ('remixer', 'Remixer'),
            ('publisher', 'Publisher'),
        ]
        
        ext_right_fields = [
            ('discnumber', 'Disc Number'),
            ('bpm', 'BPM'),
            ('copyright', 'Copyright'),
            ('encodedby', 'Encoded By'),
        ]
        
        for field, label in ext_left_fields:
            self._add_field(ext_left, field, label)
        
        for field, label in ext_right_fields:
            self._add_field(ext_right, field, label)
    
    def _add_field(self, parent, field_name: str, label_text: str):
        """Add a tag field"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=4)
        
        label = ctk.CTkLabel(
            frame, text=label_text + ":",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=ParagonTheme.TEXT_SECONDARY,
            width=100,
            anchor="e"
        )
        label.pack(side="left", padx=(0, 10))
        
        entry = ctk.CTkEntry(
            frame,
            fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK,
            text_color=ParagonTheme.TEXT_PRIMARY,
            font=ctk.CTkFont(family="Segoe UI", size=14),
            height=32
        )
        entry.pack(side="left", fill="x", expand=True)
        
        self.tag_entries[field_name] = entry
    
    def _toggle_extended(self):
        """Toggle extended fields visibility"""
        if self.extended_visible.get():
            self.extended_frame.pack(fill="x", pady=5)
        else:
            self.extended_frame.pack_forget()
    
    def _create_buttons(self):
        """Create action buttons"""
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        ParagonButton(
            btn_frame, text="💾 SAVE TAGS", 
            command=self._save_tags,
            width=150
        ).pack(side="left", padx=(0, 10))
        
        ParagonSecondaryButton(
            btn_frame, text="↩ REVERT",
            command=self._revert_tags,
            width=100
        ).pack(side="left", padx=(0, 10))
        
        ParagonSecondaryButton(
            btn_frame, text="🗑 CLEAR ALL",
            command=self._clear_tags,
            width=120
        ).pack(side="left")
        
        # Tag conversion buttons on the right
        ParagonButton(
            btn_frame, text="TAG → FILENAME",
            command=self._tag_to_filename,
            width=180
        ).pack(side="right", padx=(10, 0))
        
        ParagonSecondaryButton(
            btn_frame, text="FILENAME → TAG",
            command=self._filename_to_tag,
            width=180
        ).pack(side="right")
    
    def load_files(self, file_paths: List[str]):
        """Load files into the tag editor"""
        # Filter to audio files only
        self.current_files = [f for f in file_paths if TagManager.is_audio_file(f)]
        
        if not self.current_files:
            self.file_count_label.configure(text="No audio files selected")
            self._clear_fields()
            self._clear_cover_display()
            return
        
        count = len(self.current_files)
        self.file_count_label.configure(text=f"{count} file{'s' if count > 1 else ''} selected")
        
        if count == 1:
            # Single file - load its tags
            self._load_single_file(self.current_files[0])
        else:
            # Multiple files - show common tags
            self._load_multiple_files()
    
    def _load_single_file(self, filepath: str):
        """Load tags from a single file"""
        tags = TagManager.read_tags(filepath)
        
        for field, entry in self.tag_entries.items():
            entry.delete(0, 'end')
            if field in tags:
                entry.insert(0, str(tags[field]))
        
        # Load cover art
        self._load_cover_art(filepath)
    
    def _load_multiple_files(self):
        """Load common tags from multiple files"""
        # Get tags from all files
        all_tags = [TagManager.read_tags(f) for f in self.current_files]
        
        for field, entry in self.tag_entries.items():
            entry.delete(0, 'end')
            
            # Get all values for this field
            values = [tags.get(field, '') for tags in all_tags]
            unique_values = set(v for v in values if v)
            
            if len(unique_values) == 1:
                # All files have same value
                entry.insert(0, unique_values.pop())
            elif len(unique_values) > 1:
                # Mixed values - show placeholder
                entry.configure(placeholder_text="<mixed>")
        
        # Load cover from first file
        self._load_cover_art(self.current_files[0])
    
    def _load_cover_art(self, filepath: str):
        """Load and display cover art"""
        if not HAS_PIL:
            self._clear_cover_display("PIL required")
            return
        
        cover_data = TagManager.read_cover_art(filepath)
        
        if cover_data:
            try:
                # Create thumbnail
                img = Image.open(io.BytesIO(cover_data))
                img.thumbnail((150, 150), Image.Resampling.LANCZOS)
                
                self._cover_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(150, 150))
                self.cover_label.configure(image=self._cover_photo, text="")
                self.cover_image_data = cover_data
            except Exception as e:
                print(f"Error loading cover: {e}")
                self._clear_cover_display()
        else:
            self._clear_cover_display()
    
    def _clear_cover_display(self, text="No Cover"):
        """Clear the cover art display"""
        try:
            parent = self.cover_label.master
            self.cover_label.destroy()
            self.cover_label = ctk.CTkLabel(
                parent, text=text, text_color=ParagonTheme.TEXT_SECONDARY
            )
            self.cover_label.pack(expand=True)
        except:
            pass
        self._cover_photo = None
        self.cover_image_data = None
    
    def _clear_fields(self):
        """Clear all tag fields"""
        for entry in self.tag_entries.values():
            entry.delete(0, 'end')
            entry.configure(placeholder_text="")
    
    def _save_tags(self):
        """Save tags to all selected files"""
        if not self.current_files:
            return
        
        # Collect tag values
        tags = {}
        for field, entry in self.tag_entries.items():
            value = entry.get().strip()
            if value and value != "<mixed>":
                tags[field] = value
        
        # Save to each file
        success_count = 0
        for filepath in self.current_files:
            if TagManager.write_tags(filepath, tags):
                success_count += 1
        
        if self.on_tags_changed:
            self.on_tags_changed()
        
        messagebox.showinfo("Tags Saved", f"Saved tags to {success_count} of {len(self.current_files)} file(s)")
    
    def _revert_tags(self):
        """Reload tags from files"""
        if self.current_files:
            if len(self.current_files) == 1:
                self._load_single_file(self.current_files[0])
            else:
                self._load_multiple_files()
    
    def _clear_tags(self):
        """Clear tags from selected files"""
        if not self.current_files:
            return
        
        if messagebox.askyesno("Clear Tags", f"Remove ALL tags from {len(self.current_files)} file(s)?"):
            for filepath in self.current_files:
                TagManager.remove_all_tags(filepath)
            
            self._clear_fields()
            self._clear_cover_display()
            
            if self.on_tags_changed:
                self.on_tags_changed()
    
    def _add_cover(self):
        """Add cover art from image file"""
        if not self.current_files:
            return
        
        filepath = filedialog.askopenfilename(
            title="Select Cover Image",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.gif *.bmp"),
                ("JPEG", "*.jpg *.jpeg"),
                ("PNG", "*.png"),
                ("All files", "*.*")
            ]
        )
        
        if filepath:
            try:
                with open(filepath, 'rb') as f:
                    image_data = f.read()
                
                # Determine MIME type
                ext = os.path.splitext(filepath)[1].lower()
                mime_type = 'image/png' if ext == '.png' else 'image/jpeg'
                
                # Write to all selected files
                success = 0
                for audio_file in self.current_files:
                    if TagManager.write_cover_art(audio_file, image_data, mime_type):
                        success += 1
                
                # Reload display
                self._load_cover_art(self.current_files[0])
                
                messagebox.showinfo("Cover Added", f"Added cover to {success} file(s)")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add cover: {e}")
    
    def _remove_cover(self):
        """Remove cover art from files"""
        if not self.current_files:
            return
        
        if messagebox.askyesno("Remove Cover", f"Remove cover art from {len(self.current_files)} file(s)?"):
            for filepath in self.current_files:
                TagManager.remove_cover_art(filepath)
            
            self._clear_cover_display()
    
    def _extract_cover(self):
        """Extract cover art to file"""
        if not self.cover_image_data:
            messagebox.showinfo("No Cover", "No cover art to extract")
            return
        
        filepath = filedialog.asksaveasfilename(
            title="Save Cover Image",
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")]
        )
        
        if filepath:
            try:
                with open(filepath, 'wb') as f:
                    f.write(self.cover_image_data)
                messagebox.showinfo("Extracted", f"Cover saved to:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save cover: {e}")
    
    def _tag_to_filename(self):
        """Open Tag -> Filename dialog"""
        if not self.current_files:
            return
        
        dialog = TagFilenameDialog(self, mode="tag_to_filename", files=self.current_files)
        dialog.wait_window()
    
    def _filename_to_tag(self):
        """Open Filename -> Tag dialog"""
        if not self.current_files:
            return
        
        dialog = TagFilenameDialog(self, mode="filename_to_tag", files=self.current_files)
        result = dialog.wait_window()
        
        # Reload tags after conversion
        if self.current_files:
            self._load_single_file(self.current_files[0]) if len(self.current_files) == 1 else self._load_multiple_files()


class TagFilenameDialog(ctk.CTkToplevel):
    """Dialog for Tag <-> Filename conversion"""
    
    def __init__(self, master, mode: str, files: List[str]):
        super().__init__(master)
        
        self.mode = mode  # "tag_to_filename" or "filename_to_tag"
        self.files = files
        
        title = "Tag → Filename" if mode == "tag_to_filename" else "Filename → Tag"
        self.title(title)
        self.geometry("700x500")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        self._create_ui()
        self._update_preview()
        
        # Deferred grab
        self.after(50, lambda: self.grab_set() if self.winfo_exists() else None)
    
    def _create_ui(self):
        """Create the dialog UI"""
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=20)
        
        title = "Tag → Filename" if self.mode == "tag_to_filename" else "Filename → Tag"
        ParagonLabel(header, text=title, style="title").pack(side="left")
        
        # Pattern input
        pattern_frame = ctk.CTkFrame(self, fg_color="transparent")
        pattern_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        ParagonLabel(pattern_frame, text="Pattern:", style="muted").pack(side="left", padx=(0, 10))
        
        self.pattern_var = ctk.StringVar(value="%artist% - %title%")
        self.pattern_entry = ctk.CTkEntry(
            pattern_frame,
            textvariable=self.pattern_var,
            fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK,
            font=ctk.CTkFont(family="Segoe UI", size=16),
            height=40
        )
        self.pattern_entry.pack(side="left", fill="x", expand=True)
        self.pattern_var.trace_add("write", lambda *args: self._update_preview())
        
        # Common patterns
        presets_frame = ctk.CTkFrame(self, fg_color="transparent")
        presets_frame.pack(fill="x", padx=20, pady=(0, 15))
        
        ParagonLabel(presets_frame, text="Presets:", style="muted").pack(side="left", padx=(0, 10))
        
        presets = [
            ("%artist% - %title%", "Artist - Title"),
            ("%track%. %title%", "01. Title"),
            ("%artist% - %album% - %track% - %title%", "Full"),
            ("%album%/%track%. %title%", "Album/Track"),
        ]
        
        for pattern, label in presets:
            ctk.CTkButton(
                presets_frame, text=label, width=100, height=28,
                fg_color=ParagonTheme.BG_TERTIARY,
                hover_color=ParagonTheme.BG_HOVER,
                font=ctk.CTkFont(size=12),
                command=lambda p=pattern: self._set_pattern(p)
            ).pack(side="left", padx=3)
        
        # Help text
        help_text = "Placeholders: %artist%, %title%, %album%, %year%, %track%, %genre%, %albumartist%, %discnumber%"
        ParagonLabel(self, text=help_text, style="muted").pack(padx=20, anchor="w")
        
        # Preview
        preview_frame = ParagonFrame(self)
        preview_frame.pack(fill="both", expand=True, padx=20, pady=15)
        
        ParagonLabel(preview_frame, text="PREVIEW", style="header").pack(anchor="w", padx=15, pady=(10, 5))
        
        self.preview_list = ctk.CTkScrollableFrame(preview_frame, fg_color=ParagonTheme.BG_DARK)
        self.preview_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self.destroy, width=100).pack(side="left")
        
        action_text = "RENAME FILES" if self.mode == "tag_to_filename" else "WRITE TAGS"
        ParagonButton(btn_frame, text=action_text, command=self._apply, width=150).pack(side="right")
    
    def _set_pattern(self, pattern: str):
        """Set pattern from preset"""
        self.pattern_var.set(pattern)
    
    def _update_preview(self):
        """Update the preview list"""
        # Clear existing
        for widget in self.preview_list.winfo_children():
            widget.destroy()
        
        pattern = self.pattern_var.get()
        
        for filepath in self.files[:20]:  # Limit preview to 20 files
            filename = os.path.basename(filepath)
            
            if self.mode == "tag_to_filename":
                # Read tags and generate new filename
                tags = TagManager.read_tags(filepath)
                new_name = TagManager.tags_to_filename(tags, pattern)
                ext = os.path.splitext(filename)[1]
                new_name = new_name + ext if new_name else filename
                
                self._add_preview_row(filename, new_name)
            else:
                # Parse filename and show extracted tags
                extracted = TagManager.filename_to_tags(filepath, pattern)
                if extracted:
                    tag_str = ", ".join(f"{k}={v}" for k, v in extracted.items())
                else:
                    tag_str = "(no match)"
                
                self._add_preview_row(filename, tag_str)
        
        if len(self.files) > 20:
            ParagonLabel(self.preview_list, text=f"... and {len(self.files) - 20} more files", style="muted").pack(pady=5)
    
    def _add_preview_row(self, original: str, result: str):
        """Add a preview row"""
        row = ctk.CTkFrame(self.preview_list, fg_color="transparent")
        row.pack(fill="x", pady=2)
        
        ctk.CTkLabel(
            row, text=original,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=ParagonTheme.TEXT_SECONDARY,
            anchor="w"
        ).pack(side="left", fill="x", expand=True)
        
        ctk.CTkLabel(
            row, text="→",
            font=ctk.CTkFont(size=14),
            text_color=ParagonTheme.GOLD
        ).pack(side="left", padx=10)
        
        ctk.CTkLabel(
            row, text=result,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=ParagonTheme.SUCCESS if result else ParagonTheme.TEXT_SECONDARY,
            anchor="w"
        ).pack(side="left", fill="x", expand=True)
    
    def _apply(self):
        """Apply the conversion"""
        pattern = self.pattern_var.get()
        
        if self.mode == "tag_to_filename":
            # Rename files based on tags
            success = 0
            errors = []
            
            for filepath in self.files:
                tags = TagManager.read_tags(filepath)
                new_name = TagManager.tags_to_filename(tags, pattern)
                
                if new_name:
                    ext = os.path.splitext(filepath)[1]
                    new_path = os.path.join(os.path.dirname(filepath), new_name + ext)
                    
                    try:
                        if filepath != new_path:
                            os.rename(filepath, new_path)
                            success += 1
                    except Exception as e:
                        errors.append(f"{os.path.basename(filepath)}: {e}")
            
            if errors:
                messagebox.showwarning("Partial Success", f"Renamed {success} files.\n\nErrors:\n" + "\n".join(errors[:5]))
            else:
                messagebox.showinfo("Success", f"Renamed {success} file(s)")
        
        else:
            # Write tags from filename
            success = 0
            
            for filepath in self.files:
                extracted = TagManager.filename_to_tags(filepath, pattern)
                if extracted:
                    if TagManager.write_tags(filepath, extracted):
                        success += 1
            
            messagebox.showinfo("Success", f"Updated tags in {success} file(s)")
        
        self.destroy()


class TagEditorDialog(ctk.CTkToplevel):
    """Full tag editor dialog window"""
    
    def __init__(self, master, files: List[str]):
        super().__init__(master)
        
        self.files = files
        self.current_index = 0
        self.cover_image_data: Optional[bytes] = None
        self._cover_photo = None
        
        self.title("🎵 Tag Editor")
        self.geometry("900x700")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        
        # Maximize window and bring to front
        self.after(10, lambda: self.state('zoomed'))
        self.lift()
        self.focus_force()
        
        self._create_ui()
        self._load_current_file()
    
    def _create_ui(self):
        """Create the tag editor UI"""
        # Main container with border
        main_container = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        main_container.pack(fill="both", expand=True, padx=4, pady=4)
        
        inner = ctk.CTkFrame(main_container, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Header
        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 10))
        
        ParagonLabel(header, text="🎵 TAG EDITOR", style="title").pack(side="left")
        
        self.file_label = ParagonLabel(header, text="", style="muted")
        self.file_label.pack(side="right")
        
        # Navigation for multiple files
        if len(self.files) > 1:
            nav_frame = ctk.CTkFrame(inner, fg_color="transparent")
            nav_frame.pack(fill="x", padx=20, pady=(0, 10))
            
            ctk.CTkButton(
                nav_frame, text="◀ Prev", width=80, height=32,
                fg_color=ParagonTheme.BG_TERTIARY,
                hover_color=ParagonTheme.BG_HOVER,
                command=self._prev_file
            ).pack(side="left", padx=(0, 10))
            
            self.nav_label = ParagonLabel(nav_frame, text="1 / 1", style="muted")
            self.nav_label.pack(side="left")
            
            ctk.CTkButton(
                nav_frame, text="Next ▶", width=80, height=32,
                fg_color=ParagonTheme.BG_TERTIARY,
                hover_color=ParagonTheme.BG_HOVER,
                command=self._next_file
            ).pack(side="left", padx=10)
            
            # Apply to all checkbox
            self.apply_all = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(
                nav_frame, text="Apply changes to all files",
                variable=self.apply_all,
                fg_color=ParagonTheme.RED_PRIMARY,
                hover_color=ParagonTheme.RED_LIGHT,
                font=ctk.CTkFont(size=14)
            ).pack(side="right")
        
        # Content - two columns
        content = ctk.CTkFrame(inner, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Left - Cover art
        left_frame = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=220)
        left_frame.pack(side="left", fill="y", padx=(0, 15))
        left_frame.pack_propagate(False)
        
        self._create_cover_section(left_frame)
        
        # Right - Tag fields
        right_frame = ctk.CTkFrame(content, fg_color="transparent")
        right_frame.pack(side="left", fill="both", expand=True)
        
        self._create_tag_fields(right_frame)
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(10, 20))
        
        ParagonSecondaryButton(btn_frame, text="CLOSE", command=self.destroy, width=100).pack(side="left")
        
        # MusicBrainz lookup button
        ParagonButton(
            btn_frame, text="🔍 MUSICBRAINZ LOOKUP",
            command=self._musicbrainz_lookup,
            width=220,
            fg_color=ParagonTheme.ORANGE,
            hover_color=ParagonTheme.GOLD_LIGHT
        ).pack(side="left", padx=(20, 0))
        
        ParagonButton(btn_frame, text="💾 SAVE TAGS", command=self._save_tags, width=150).pack(side="right", padx=(10, 0))
        
        # Save selected fields to all files button
        if len(self.files) > 1:
            ParagonButton(btn_frame, text="💾 SAVE TO ALL...", command=self._save_to_all_dialog, 
                         width=160,
                         fg_color=ParagonTheme.GOLD,
                         hover_color=ParagonTheme.GOLD_LIGHT,
                         text_color=ParagonTheme.BG_DARK).pack(side="right", padx=(10, 0))
        
        ParagonSecondaryButton(btn_frame, text="↩ REVERT", command=self._load_current_file, width=100).pack(side="right")
    
    def _create_cover_section(self, parent):
        """Create cover art section"""
        ParagonLabel(parent, text="COVER ART", style="header").pack(pady=(15, 10))
        
        # Cover display
        self.cover_frame = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_DARK, width=180, height=180, corner_radius=4)
        self.cover_frame.pack(padx=20, pady=5)
        self.cover_frame.pack_propagate(False)
        
        self.cover_label = ctk.CTkLabel(self.cover_frame, text="No Cover", text_color=ParagonTheme.TEXT_SECONDARY)
        self.cover_label.pack(expand=True)
        
        # Cover buttons
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=15)
        
        ctk.CTkButton(
            btn_frame, text="Add", width=55, height=32,
            fg_color=ParagonTheme.BG_HOVER,
            hover_color=ParagonTheme.RED_DARK,
            font=ctk.CTkFont(family="Bebas Neue", size=16),
            command=self._add_cover
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            btn_frame, text="Remove", width=70, height=32,
            fg_color=ParagonTheme.BG_HOVER,
            hover_color=ParagonTheme.RED_DARK,
            font=ctk.CTkFont(family="Bebas Neue", size=16),
            command=self._remove_cover
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            btn_frame, text="Save", width=55, height=32,
            fg_color=ParagonTheme.BG_HOVER,
            hover_color=ParagonTheme.RED_DARK,
            font=ctk.CTkFont(family="Bebas Neue", size=16),
            command=self._extract_cover
        ).pack(side="left", padx=2)
        
        # File info
        self.info_label = ParagonLabel(parent, text="", style="muted")
        self.info_label.pack(pady=10)
    
    def _create_tag_fields(self, parent):
        """Create tag input fields"""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        
        self.tag_entries = {}
        
        # Two columns
        cols = ctk.CTkFrame(scroll, fg_color="transparent")
        cols.pack(fill="x")
        
        left = ctk.CTkFrame(cols, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 15))
        
        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        
        left_fields = [
            ('title', 'Title'),
            ('artist', 'Artist'),
            ('album', 'Album'),
            ('albumartist', 'Album Artist'),
            ('composer', 'Composer'),
        ]
        
        right_fields = [
            ('year', 'Year'),
            ('track', 'Track'),
            ('discnumber', 'Disc'),
            ('genre', 'Genre'),
            ('bpm', 'BPM'),
        ]
        
        for field, label in left_fields:
            self._add_field(left, field, label)
        
        for field, label in right_fields:
            self._add_field(right, field, label)
        
        # Comment (full width)
        self._add_field(scroll, 'comment', 'Comment', full_width=True)
    
    def _add_field(self, parent, field_name: str, label_text: str, full_width: bool = False):
        """Add a tag input field"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=6)
        
        lbl = ctk.CTkLabel(
            frame, text=label_text + ":",
            font=ctk.CTkFont(family="Segoe UI", size=16),
            text_color=ParagonTheme.TEXT_SECONDARY,
            width=120 if not full_width else 100,
            anchor="e"
        )
        lbl.pack(side="left", padx=(0, 10))
        
        entry = ctk.CTkEntry(
            frame,
            fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK,
            text_color=ParagonTheme.TEXT_PRIMARY,
            font=ctk.CTkFont(family="Segoe UI", size=16),
            height=40
        )
        entry.pack(side="left", fill="x", expand=True)
        
        self.tag_entries[field_name] = entry
    
    def _load_current_file(self):
        """Load tags from current file"""
        if not self.files:
            return
        
        filepath = self.files[self.current_index]
        filename = os.path.basename(filepath)
        
        self.file_label.configure(text=filename)
        
        if hasattr(self, 'nav_label'):
            self.nav_label.configure(text=f"{self.current_index + 1} / {len(self.files)}")
        
        # Load tags
        tags = TagManager.read_tags(filepath)
        
        print(f"_load_current_file: Loading {filepath}")
        print(f"_load_current_file: tag_entries keys: {list(self.tag_entries.keys())}")
        
        for field, entry in self.tag_entries.items():
            entry.delete(0, 'end')
            if field in tags:
                print(f"  Setting {field} = '{tags[field]}'")
                entry.insert(0, str(tags[field]))
            else:
                print(f"  Field {field} not in tags")
        
        # Load cover
        self._load_cover(filepath)
        
        # File info
        try:
            size = os.path.getsize(filepath)
            if size > 1024*1024:
                size_str = f"{size/1024/1024:.1f} MB"
            else:
                size_str = f"{size/1024:.1f} KB"
            
            duration = tags.get('_duration', 0)
            if duration:
                mins = int(duration // 60)
                secs = int(duration % 60)
                dur_str = f"{mins}:{secs:02d}"
            else:
                dur_str = "?"
            
            bitrate = tags.get('_bitrate', 0)
            br_str = f"{bitrate//1000}k" if bitrate else "?"
            
            self.info_label.configure(text=f"{size_str} | {dur_str} | {br_str}")
        except:
            self.info_label.configure(text="")
    
    def _clear_cover_label(self, text="No Cover"):
        """Safely clear the cover label"""
        try:
            parent = self.cover_label.master
            self.cover_label.destroy()
            self.cover_label = ctk.CTkLabel(
                parent, text=text, text_color=ParagonTheme.TEXT_SECONDARY
            )
            self.cover_label.pack(expand=True)
            self._cover_photo = None
            self.cover_image_data = None
        except:
            pass
    
    def _load_cover(self, filepath: str):
        """Load cover art"""
        if not HAS_PIL:
            self._clear_cover_label("PIL required")
            return
        
        cover_data = TagManager.read_cover_art(filepath)
        
        if cover_data:
            try:
                img = Image.open(io.BytesIO(cover_data))
                img.thumbnail((170, 170), Image.Resampling.LANCZOS)
                
                self._cover_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(170, 170))
                self.cover_label.configure(image=self._cover_photo, text="")
                self.cover_image_data = cover_data
            except:
                self._clear_cover_label("No Cover")
        else:
            self._clear_cover_label("No Cover")
    
    def _prev_file(self):
        """Go to previous file"""
        if self.current_index > 0:
            self.current_index -= 1
            self._load_current_file()
    
    def _next_file(self):
        """Go to next file"""
        if self.current_index < len(self.files) - 1:
            self.current_index += 1
            self._load_current_file()
    
    def _save_tags(self):
        """Save tags to file(s)"""
        tags = {}
        for field, entry in self.tag_entries.items():
            value = entry.get().strip()
            if value:
                tags[field] = value
        
        if hasattr(self, 'apply_all') and self.apply_all.get():
            # Apply to all files
            success = 0
            for filepath in self.files:
                if TagManager.write_tags(filepath, tags):
                    success += 1
                # Also save cover art if we have it
                if hasattr(self, 'cover_image_data') and self.cover_image_data:
                    TagManager.write_cover_art(filepath, self.cover_image_data, 'image/jpeg')
            messagebox.showinfo("Saved", f"Tags saved to {success} file(s)")
        else:
            # Apply to current file only
            filepath = self.files[self.current_index]
            
            # Save cover art FIRST (before tags) if we have it
            if hasattr(self, 'cover_image_data') and self.cover_image_data:
                print(f"_save_tags: Also saving cover art ({len(self.cover_image_data)} bytes)")
                TagManager.write_cover_art(filepath, self.cover_image_data, 'image/jpeg')
            
            if TagManager.write_tags(filepath, tags):
                messagebox.showinfo("Saved", "Tags saved successfully")
            else:
                messagebox.showerror("Error", "Failed to save tags")
    
    def _save_to_all_dialog(self):
        """Show dialog to select which fields to save to all files"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Save to All Files")
        dialog.geometry("400x500")
        dialog.configure(fg_color=ParagonTheme.BG_DARK)
        dialog.transient(self)
        dialog.grab_set()
        
        # Center on parent
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 400) // 2
        y = self.winfo_y() + (self.winfo_height() - 500) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # Header
        ctk.CTkLabel(dialog, text="SELECT FIELDS TO SAVE",
                    font=ctk.CTkFont(family="Bebas Neue", size=28),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(pady=(20, 5))
        
        ctk.CTkLabel(dialog, text=f"Save selected fields to all {len(self.files)} files",
                    font=ctk.CTkFont(size=14),
                    text_color=ParagonTheme.TEXT_MUTED).pack(pady=(0, 15))
        
        # Field checkboxes
        fields_frame = ctk.CTkScrollableFrame(dialog, fg_color=ParagonTheme.BG_SECONDARY)
        fields_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        field_vars = {}
        field_labels = {
            'title': 'Title',
            'artist': 'Artist', 
            'album': 'Album',
            'albumartist': 'Album Artist',
            'composer': 'Composer',
            'year': 'Year',
            'track': 'Track',
            'discnumber': 'Disc',
            'genre': 'Genre',
            'bpm': 'BPM',
            'comment': 'Comment'
        }
        
        for field, label in field_labels.items():
            if field in self.tag_entries:
                value = self.tag_entries[field].get().strip()
                var = ctk.BooleanVar(value=False)
                field_vars[field] = var
                
                frame = ctk.CTkFrame(fields_frame, fg_color="transparent")
                frame.pack(fill="x", pady=3)
                
                cb = ctk.CTkCheckBox(frame, text=label, variable=var,
                                    fg_color=ParagonTheme.RED_PRIMARY,
                                    hover_color=ParagonTheme.RED_LIGHT,
                                    font=ctk.CTkFont(size=16))
                cb.pack(side="left")
                
                # Show current value
                display_value = value if len(value) < 30 else value[:27] + "..."
                ctk.CTkLabel(frame, text=f"= {display_value}" if value else "(empty)",
                            font=ctk.CTkFont(size=14),
                            text_color=ParagonTheme.TEXT_MUTED if value else ParagonTheme.TEXT_SECONDARY).pack(side="left", padx=(10, 0))
        
        # Cover art checkbox
        cover_var = ctk.BooleanVar(value=False)
        cover_frame = ctk.CTkFrame(fields_frame, fg_color="transparent")
        cover_frame.pack(fill="x", pady=3)
        
        ctk.CTkCheckBox(cover_frame, text="Cover Art", variable=cover_var,
                       fg_color=ParagonTheme.RED_PRIMARY,
                       hover_color=ParagonTheme.RED_LIGHT,
                       font=ctk.CTkFont(size=16)).pack(side="left")
        
        has_cover = hasattr(self, 'cover_image_data') and self.cover_image_data
        ctk.CTkLabel(cover_frame, text="(loaded)" if has_cover else "(none)",
                    font=ctk.CTkFont(size=14),
                    text_color=ParagonTheme.TEXT_MUTED).pack(side="left", padx=(10, 0))
        
        # Select all / none buttons
        select_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        select_frame.pack(fill="x", padx=20, pady=10)
        
        def select_all():
            for var in field_vars.values():
                var.set(True)
            cover_var.set(True)
        
        def select_none():
            for var in field_vars.values():
                var.set(False)
            cover_var.set(False)
        
        ctk.CTkButton(select_frame, text="Select All", width=100, height=32,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER,
                     command=select_all).pack(side="left", padx=(0, 10))
        
        ctk.CTkButton(select_frame, text="Select None", width=100, height=32,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER,
                     command=select_none).pack(side="left")
        
        # Buttons
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(10, 20))
        
        def do_save():
            # Gather selected fields
            tags_to_save = {}
            for field, var in field_vars.items():
                if var.get():
                    value = self.tag_entries[field].get().strip()
                    if value:
                        tags_to_save[field] = value
            
            save_cover = cover_var.get() and has_cover
            
            if not tags_to_save and not save_cover:
                messagebox.showwarning("Nothing Selected", "Please select at least one field to save.")
                return
            
            # Save to all files
            success = 0
            for filepath in self.files:
                saved = False
                if tags_to_save:
                    if TagManager.write_tags(filepath, tags_to_save):
                        saved = True
                if save_cover:
                    if TagManager.write_cover_art(filepath, self.cover_image_data, 'image/jpeg'):
                        saved = True
                if saved:
                    success += 1
            
            dialog.destroy()
            
            fields_saved = list(tags_to_save.keys())
            if save_cover:
                fields_saved.append("cover art")
            
            messagebox.showinfo("Saved", f"Saved {', '.join(fields_saved)} to {success} file(s)")
        
        ctk.CTkButton(btn_frame, text="Cancel", width=100, height=40,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER,
                     command=dialog.destroy).pack(side="left")
        
        ParagonButton(btn_frame, text="💾 SAVE TO ALL", width=160, height=40,
                     command=do_save).pack(side="right")
    
    def _add_cover(self):
        """Add cover art"""
        filepath = filedialog.askopenfilename(
            title="Select Cover Image",
            filetypes=[("Images", "*.jpg *.jpeg *.png"), ("All", "*.*")]
        )
        
        if filepath:
            try:
                with open(filepath, 'rb') as f:
                    image_data = f.read()
                
                ext = os.path.splitext(filepath)[1].lower()
                mime = 'image/png' if ext == '.png' else 'image/jpeg'
                
                if hasattr(self, 'apply_all') and self.apply_all.get():
                    for audio_file in self.files:
                        TagManager.write_cover_art(audio_file, image_data, mime)
                else:
                    TagManager.write_cover_art(self.files[self.current_index], image_data, mime)
                
                self._load_cover(self.files[self.current_index])
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add cover: {e}")
    
    def _remove_cover(self):
        """Remove cover art"""
        if hasattr(self, 'apply_all') and self.apply_all.get():
            for filepath in self.files:
                TagManager.remove_cover_art(filepath)
        else:
            TagManager.remove_cover_art(self.files[self.current_index])
        
        self._clear_cover_label("No Cover")
    
    def _extract_cover(self):
        """Save cover art to file"""
        if not self.cover_image_data:
            messagebox.showinfo("No Cover", "No cover art to save")
            return
        
        filepath = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")]
        )
        
        if filepath:
            with open(filepath, 'wb') as f:
                f.write(self.cover_image_data)
            messagebox.showinfo("Saved", f"Cover saved to {filepath}")
    
    def _musicbrainz_lookup(self):
        """Open MusicBrainz lookup dialog"""
        # Get current values for search
        current_tags = {
            'title': self.tag_entries.get('title', ctk.CTkEntry(self)).get(),
            'artist': self.tag_entries.get('artist', ctk.CTkEntry(self)).get(),
            'album': self.tag_entries.get('album', ctk.CTkEntry(self)).get(),
        }
        
        dialog = MusicBrainzDialog(self, current_tags, self._apply_musicbrainz_result)
    
    def _apply_musicbrainz_result(self, tags: Dict[str, str], cover_data: Optional[bytes] = None):
        """Apply tags from MusicBrainz result"""
        # Update tag fields
        for field, value in tags.items():
            if field in self.tag_entries and value:
                self.tag_entries[field].delete(0, 'end')
                self.tag_entries[field].insert(0, value)
        
        # Update cover art if provided
        if cover_data and HAS_PIL:
            try:
                img = Image.open(io.BytesIO(cover_data))
                img.thumbnail((170, 170), Image.Resampling.LANCZOS)
                
                self._cover_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(170, 170))
                self.cover_label.configure(image=self._cover_photo, text="")
                self.cover_image_data = cover_data
            except:
                pass


class MusicBrainzDialog(ctk.CTkToplevel):
    """MusicBrainz search and lookup dialog"""
    
    def __init__(self, master, initial_tags: Dict[str, str], on_apply: Callable):
        super().__init__(master)
        
        self.on_apply = on_apply
        self.search_results = []
        self.selected_result = None
        self.cover_data = None
        self._cover_photo = None
        
        self.title("🔍 MusicBrainz Lookup")
        self.geometry("950x700")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        self._create_ui(initial_tags)
        
        # Auto-search if we have data
        if initial_tags.get('title') or initial_tags.get('artist'):
            self.after(100, self._search)
        
        self.after(50, lambda: self.grab_set() if self.winfo_exists() else None)
    
    def _create_ui(self, initial_tags: Dict[str, str]):
        """Create the MusicBrainz dialog UI"""
        # Main container
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        main.pack(fill="both", expand=True, padx=4, pady=4)
        
        inner = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Header
        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 15))
        
        ParagonLabel(header, text="🔍 MUSICBRAINZ LOOKUP", style="title").pack(side="left")
        
        # Search options
        search_frame = ctk.CTkFrame(inner, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        search_frame.pack(fill="x", padx=20, pady=(0, 15))
        
        # Search type
        type_frame = ctk.CTkFrame(search_frame, fg_color="transparent")
        type_frame.pack(fill="x", padx=15, pady=(15, 10))
        
        ParagonLabel(type_frame, text="Search Type:", style="muted").pack(side="left", padx=(0, 15))
        
        self.search_type = ctk.StringVar(value="recording")
        ctk.CTkRadioButton(
            type_frame, text="Song/Recording", variable=self.search_type, value="recording",
            fg_color=ParagonTheme.RED_PRIMARY, hover_color=ParagonTheme.RED_LIGHT,
            font=ctk.CTkFont(size=14)
        ).pack(side="left", padx=(0, 20))
        
        ctk.CTkRadioButton(
            type_frame, text="Album/Release", variable=self.search_type, value="release",
            fg_color=ParagonTheme.RED_PRIMARY, hover_color=ParagonTheme.RED_LIGHT,
            font=ctk.CTkFont(size=14)
        ).pack(side="left")
        
        # Search fields
        fields_frame = ctk.CTkFrame(search_frame, fg_color="transparent")
        fields_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        # Title/Album field
        title_frame = ctk.CTkFrame(fields_frame, fg_color="transparent")
        title_frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ParagonLabel(title_frame, text="Title/Album:", style="muted").pack(anchor="w")
        self.title_entry = ctk.CTkEntry(
            title_frame, 
            fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK,
            font=ctk.CTkFont(size=16),
            height=40
        )
        self.title_entry.pack(fill="x")
        self.title_entry.insert(0, initial_tags.get('title', '') or initial_tags.get('album', ''))
        self.title_entry.bind('<Return>', lambda e: self._search())
        
        # Artist field
        artist_frame = ctk.CTkFrame(fields_frame, fg_color="transparent")
        artist_frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ParagonLabel(artist_frame, text="Artist:", style="muted").pack(anchor="w")
        self.artist_entry = ctk.CTkEntry(
            artist_frame,
            fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK,
            font=ctk.CTkFont(size=16),
            height=40
        )
        self.artist_entry.pack(fill="x")
        self.artist_entry.insert(0, initial_tags.get('artist', ''))
        self.artist_entry.bind('<Return>', lambda e: self._search())
        
        # Search button
        btn_frame = ctk.CTkFrame(fields_frame, fg_color="transparent")
        btn_frame.pack(side="left")
        
        ParagonLabel(btn_frame, text=" ", style="muted").pack()  # Spacer
        ParagonButton(
            btn_frame, text="🔍 SEARCH",
            command=self._search,
            width=120, height=40
        ).pack()
        
        # Results section
        results_frame = ctk.CTkFrame(inner, fg_color="transparent")
        results_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        
        # Left - Results list
        left_results = ctk.CTkFrame(results_frame, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        left_results.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        ParagonLabel(left_results, text="RESULTS", style="header").pack(anchor="w", padx=15, pady=(10, 5))
        
        self.results_list = ctk.CTkScrollableFrame(left_results, fg_color=ParagonTheme.BG_DARK)
        self.results_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.status_label = ParagonLabel(self.results_list, text="Enter search terms and click Search", style="muted")
        self.status_label.pack(pady=20)
        
        # Right - Preview/Details
        right_preview = ctk.CTkFrame(results_frame, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=280)
        right_preview.pack(side="right", fill="y")
        right_preview.pack_propagate(False)
        
        ParagonLabel(right_preview, text="PREVIEW", style="header").pack(anchor="w", padx=15, pady=(10, 5))
        
        # Cover art preview
        self.preview_cover_frame = ctk.CTkFrame(right_preview, fg_color=ParagonTheme.BG_DARK, width=150, height=150, corner_radius=4)
        self.preview_cover_frame.pack(padx=15, pady=10)
        self.preview_cover_frame.pack_propagate(False)
        
        self.preview_cover_label = ctk.CTkLabel(self.preview_cover_frame, text="No Cover", text_color=ParagonTheme.TEXT_SECONDARY)
        self.preview_cover_label.pack(expand=True)
        
        # Tag preview
        self.preview_text = ctk.CTkTextbox(
            right_preview, 
            fg_color=ParagonTheme.BG_DARK,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            height=200
        )
        self.preview_text.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        self.preview_text.configure(state="disabled")
        
        # Fetch cover checkbox
        self.fetch_cover = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            right_preview, text="Fetch cover art",
            variable=self.fetch_cover,
            fg_color=ParagonTheme.RED_PRIMARY,
            font=ctk.CTkFont(size=14)
        ).pack(padx=15, pady=(0, 10))
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self.destroy, width=100).pack(side="left")
        
        ParagonButton(btn_frame, text="✓ APPLY TAGS", command=self._apply_selected, width=150).pack(side="right")
    
    def _search(self):
        """Perform MusicBrainz search"""
        title = self.title_entry.get().strip()
        artist = self.artist_entry.get().strip()
        
        if not title and not artist:
            messagebox.showinfo("Search", "Please enter a title or artist to search")
            return
        
        # Clear results
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        self.status_label = ParagonLabel(self.results_list, text="Searching MusicBrainz...", style="muted")
        self.status_label.pack(pady=20)
        self.update()
        
        # Perform search in background
        def do_search():
            if self.search_type.get() == "recording":
                results = MusicBrainzAPI.search_recording(title, artist)
            else:
                results = MusicBrainzAPI.search_release(title, artist)
            
            self.after(0, lambda: self._display_results(results))
        
        threading.Thread(target=do_search, daemon=True).start()
    
    def _display_results(self, results: List[Dict]):
        """Display search results"""
        # Clear
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        self.search_results = results
        
        if not results:
            ParagonLabel(self.results_list, text="No results found. Try different search terms.", style="muted").pack(pady=20)
            return
        
        for i, result in enumerate(results):
            self._add_result_row(i, result)
    
    def _add_result_row(self, index: int, result: Dict):
        """Add a result row"""
        is_recording = 'title' in result
        
        frame = ctk.CTkFrame(
            self.results_list,
            fg_color=ParagonTheme.BG_TERTIARY if index % 2 == 0 else ParagonTheme.BG_SECONDARY,
            corner_radius=4
        )
        frame.pack(fill="x", pady=2)
        
        # Make clickable
        frame.bind("<Button-1>", lambda e, idx=index: self._select_result(idx))
        
        # Content
        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="x", padx=10, pady=8)
        content.bind("<Button-1>", lambda e, idx=index: self._select_result(idx))
        
        if is_recording:
            # Song result
            title_text = result.get('title', 'Unknown')
            artist_text = result.get('artist', 'Unknown Artist')
            album_text = result.get('album', '')
            
            title_lbl = ctk.CTkLabel(
                content, text=title_text,
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                text_color=ParagonTheme.TEXT_PRIMARY,
                anchor="w"
            )
            title_lbl.pack(fill="x")
            title_lbl.bind("<Button-1>", lambda e, idx=index: self._select_result(idx))
            
            info_text = f"by {artist_text}"
            if album_text:
                info_text += f" • {album_text}"
            if result.get('year'):
                info_text += f" ({result['year']})"
            
            info_lbl = ctk.CTkLabel(
                content, text=info_text,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=ParagonTheme.TEXT_SECONDARY,
                anchor="w"
            )
            info_lbl.pack(fill="x")
            info_lbl.bind("<Button-1>", lambda e, idx=index: self._select_result(idx))
        else:
            # Album result
            album_text = result.get('album', 'Unknown Album')
            artist_text = result.get('artist', 'Unknown Artist')
            
            title_lbl = ctk.CTkLabel(
                content, text=album_text,
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                text_color=ParagonTheme.TEXT_PRIMARY,
                anchor="w"
            )
            title_lbl.pack(fill="x")
            title_lbl.bind("<Button-1>", lambda e, idx=index: self._select_result(idx))
            
            info_text = f"by {artist_text}"
            if result.get('year'):
                info_text += f" • {result['year']}"
            if result.get('tracks'):
                info_text += f" • {result['tracks']} tracks"
            
            info_lbl = ctk.CTkLabel(
                content, text=info_text,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=ParagonTheme.TEXT_SECONDARY,
                anchor="w"
            )
            info_lbl.pack(fill="x")
            info_lbl.bind("<Button-1>", lambda e, idx=index: self._select_result(idx))
        
        # Score indicator
        score = result.get('score', 0)
        if score >= 90:
            score_color = ParagonTheme.SUCCESS
        elif score >= 70:
            score_color = ParagonTheme.GOLD
        else:
            score_color = ParagonTheme.TEXT_SECONDARY
        
        ctk.CTkLabel(
            frame, text=f"{score}%",
            font=ctk.CTkFont(size=11),
            text_color=score_color,
            width=40
        ).pack(side="right", padx=10)
    
    def _select_result(self, index: int):
        """Select a search result"""
        if index >= len(self.search_results):
            return
        
        self.selected_result = self.search_results[index]
        
        # Highlight selected
        for i, widget in enumerate(self.results_list.winfo_children()):
            if isinstance(widget, ctk.CTkFrame):
                if i == index:
                    widget.configure(fg_color=ParagonTheme.RED_DARK)
                else:
                    widget.configure(fg_color=ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY)
        
        # Update preview
        self._update_preview(self.selected_result)
    
    def _update_preview(self, result: Dict):
        """Update the preview panel"""
        # Update text preview
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        
        is_recording = 'title' in result
        
        if is_recording:
            preview = f"Title: {result.get('title', '')}\n"
            preview += f"Artist: {result.get('artist', '')}\n"
            preview += f"Album: {result.get('album', '')}\n"
            preview += f"Year: {result.get('year', '')}\n"
            preview += f"Track: {result.get('track', '')}\n"
        else:
            preview = f"Album: {result.get('album', '')}\n"
            preview += f"Artist: {result.get('artist', '')}\n"
            preview += f"Year: {result.get('year', '')}\n"
            preview += f"Tracks: {result.get('tracks', '')}\n"
            preview += f"Country: {result.get('country', '')}\n"
        
        self.preview_text.insert("1.0", preview)
        self.preview_text.configure(state="disabled")
        
        # Fetch cover art
        release_id = result.get('release_id') or result.get('id')
        if release_id and self.fetch_cover.get():
            self._clear_preview_cover("Loading...")
            self._cover_photo = None
            
            def fetch_cover():
                cover = MusicBrainzAPI.get_cover_art(release_id)
                self.after(0, lambda: self._display_cover(cover))
            
            threading.Thread(target=fetch_cover, daemon=True).start()
    
    def _clear_preview_cover(self, text="No Cover"):
        """Safely clear the preview cover label"""
        try:
            parent = self.preview_cover_label.master
            self.preview_cover_label.destroy()
            self.preview_cover_label = ctk.CTkLabel(
                parent, text=text, text_color=ParagonTheme.TEXT_SECONDARY
            )
            self.preview_cover_label.pack(expand=True)
        except:
            pass
    
    def _display_cover(self, cover_data: Optional[bytes]):
        """Display fetched cover art"""
        if cover_data and HAS_PIL:
            try:
                img = Image.open(io.BytesIO(cover_data))
                img.thumbnail((140, 140), Image.Resampling.LANCZOS)
                
                self._cover_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(140, 140))
                self.preview_cover_label.configure(image=self._cover_photo, text="")
                self.cover_data = cover_data
                return
            except:
                pass
        
        self._clear_preview_cover("No Cover")
        self.cover_data = None
    
    def _apply_selected(self):
        """Apply selected result's tags"""
        if not self.selected_result:
            messagebox.showinfo("Select Result", "Please select a search result first")
            return
        
        result = self.selected_result
        is_recording = 'title' in result
        
        tags = {}
        if is_recording:
            tags['title'] = result.get('title', '')
            tags['artist'] = result.get('artist', '')
            tags['album'] = result.get('album', '')
            tags['year'] = result.get('year', '')
            tags['track'] = result.get('track', '')
        else:
            tags['album'] = result.get('album', '')
            tags['artist'] = result.get('artist', '')
            tags['year'] = result.get('year', '')
        
        # Pass cover data if available and checkbox is checked
        cover = self.cover_data if self.fetch_cover.get() else None
        
        self.on_apply(tags, cover)
        self.destroy()


class MusicBrainzAlbumLookup(ctk.CTkToplevel):
    """MP3tag-style MusicBrainz album lookup with track matching"""
    
    def __init__(self, master, files: List[str], on_complete: Callable = None):
        super().__init__(master)
        
        self.files = files  # List of file paths
        self.on_complete = on_complete
        self.album_results = []
        self.selected_album = None
        self.album_tracks = []  # Track data from MusicBrainz
        self.track_mapping = {}  # Maps MB track index -> file index
        self.cover_data = None
        self._cover_photo = None
        
        self.title("🎵 MusicBrainz Album Lookup")
        self.geometry("1100x750")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        self._create_ui()
        
        self.after(50, lambda: self.grab_set() if self.winfo_exists() else None)
    
    def _create_ui(self):
        """Create the album lookup UI"""
        # Main container with gold border
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        main.pack(fill="both", expand=True, padx=4, pady=4)
        
        inner = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Header
        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 10))
        
        ParagonLabel(header, text="🎵 MUSICBRAINZ ALBUM LOOKUP", style="title").pack(side="left")
        ParagonLabel(header, text=f"{len(self.files)} files selected", style="muted").pack(side="right")
        
        # Search section
        search_frame = ctk.CTkFrame(inner, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        search_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        search_inner = ctk.CTkFrame(search_frame, fg_color="transparent")
        search_inner.pack(fill="x", padx=15, pady=12)
        
        # Artist field
        artist_frame = ctk.CTkFrame(search_inner, fg_color="transparent")
        artist_frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ParagonLabel(artist_frame, text="Artist:", style="muted").pack(anchor="w")
        self.artist_entry = ctk.CTkEntry(
            artist_frame, fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK, font=ctk.CTkFont(size=15), height=38
        )
        self.artist_entry.pack(fill="x")
        self.artist_entry.bind('<Return>', lambda e: self._search_albums())
        
        # Album field
        album_frame = ctk.CTkFrame(search_inner, fg_color="transparent")
        album_frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ParagonLabel(album_frame, text="Album:", style="muted").pack(anchor="w")
        self.album_entry = ctk.CTkEntry(
            album_frame, fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK, font=ctk.CTkFont(size=15), height=38
        )
        self.album_entry.pack(fill="x")
        self.album_entry.bind('<Return>', lambda e: self._search_albums())
        
        # Search button
        btn_frame = ctk.CTkFrame(search_inner, fg_color="transparent")
        btn_frame.pack(side="left")
        ParagonLabel(btn_frame, text=" ", style="muted").pack()
        ParagonButton(btn_frame, text="🔍 SEARCH", command=self._search_albums, width=120, height=38).pack()
        
        # Try to pre-fill from first file's tags
        if self.files:
            tags = TagManager.read_tags(self.files[0])
            self.artist_entry.insert(0, tags.get('artist', ''))
            self.album_entry.insert(0, tags.get('album', ''))
        
        # Main content - two panels
        content = ctk.CTkFrame(inner, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        
        # Left panel - Album results
        left_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=350)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)
        
        ParagonLabel(left_panel, text="ALBUM RESULTS", style="header").pack(anchor="w", padx=15, pady=(10, 5))
        
        self.album_list = ctk.CTkScrollableFrame(left_panel, fg_color=ParagonTheme.BG_DARK)
        self.album_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.album_status = ParagonLabel(self.album_list, text="Enter artist/album and search", style="muted")
        self.album_status.pack(pady=20)
        
        # Right panel - Track matching
        right_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        right_panel.pack(side="left", fill="both", expand=True)
        
        # Right header with cover art
        right_header = ctk.CTkFrame(right_panel, fg_color="transparent")
        right_header.pack(fill="x", padx=15, pady=10)
        
        # Cover art
        self.cover_frame = ctk.CTkFrame(right_header, fg_color=ParagonTheme.BG_DARK, width=100, height=100, corner_radius=4)
        self.cover_frame.pack(side="left", padx=(0, 15))
        self.cover_frame.pack_propagate(False)
        
        self.cover_label = ctk.CTkLabel(self.cover_frame, text="No\nCover", text_color=ParagonTheme.TEXT_SECONDARY)
        self.cover_label.pack(expand=True)
        
        # Album info
        info_frame = ctk.CTkFrame(right_header, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True)
        
        self.album_title_label = ParagonLabel(info_frame, text="Select an album", style="header")
        self.album_title_label.pack(anchor="w")
        
        self.album_info_label = ParagonLabel(info_frame, text="", style="muted")
        self.album_info_label.pack(anchor="w")
        
        # Track matching area
        ParagonLabel(right_panel, text="TRACK MATCHING", style="header").pack(anchor="w", padx=15, pady=(5, 5))
        
        # Column headers
        header_frame = ctk.CTkFrame(right_panel, fg_color=ParagonTheme.BG_TERTIARY, height=35)
        header_frame.pack(fill="x", padx=15)
        header_frame.pack_propagate(False)
        
        ctk.CTkLabel(header_frame, text="#", width=30, font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=ParagonTheme.GOLD).pack(side="left", padx=5)
        ctk.CTkLabel(header_frame, text="MusicBrainz Track", width=250, font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=ParagonTheme.GOLD, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(header_frame, text="→", width=30, font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=ParagonTheme.TEXT_SECONDARY).pack(side="left")
        ctk.CTkLabel(header_frame, text="Your File", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=ParagonTheme.GOLD, anchor="w").pack(side="left", padx=5, fill="x", expand=True)
        
        # Track list
        self.track_list = ctk.CTkScrollableFrame(right_panel, fg_color=ParagonTheme.BG_DARK)
        self.track_list.pack(fill="both", expand=True, padx=15, pady=(5, 10))
        
        self.track_status = ParagonLabel(self.track_list, text="Select an album to see tracks", style="muted")
        self.track_status.pack(pady=20)
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 15))
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self.destroy, width=100).pack(side="left")
        
        # Auto-match button
        ParagonSecondaryButton(
            btn_frame, text="🔄 AUTO-MATCH", 
            command=self._auto_match_tracks, width=130
        ).pack(side="left", padx=(15, 0))
        
        # Fetch cover checkbox
        self.fetch_cover = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            btn_frame, text="Include cover art",
            variable=self.fetch_cover,
            fg_color=ParagonTheme.RED_PRIMARY,
            font=ctk.CTkFont(size=14)
        ).pack(side="left", padx=(20, 0))
        
        ParagonButton(btn_frame, text="✓ APPLY TO FILES", command=self._apply_tags, width=160).pack(side="right")
    
    def _search_albums(self):
        """Search for albums"""
        artist = self.artist_entry.get().strip()
        album = self.album_entry.get().strip()
        
        if not artist and not album:
            messagebox.showinfo("Search", "Please enter artist or album name")
            return
        
        # Clear results
        for widget in self.album_list.winfo_children():
            widget.destroy()
        
        self.album_status = ParagonLabel(self.album_list, text="Searching...", style="muted")
        self.album_status.pack(pady=20)
        self.update()
        
        def do_search():
            results = MusicBrainzAPI.search_release(album, artist)
            self.after(0, lambda: self._display_album_results(results))
        
        threading.Thread(target=do_search, daemon=True).start()
    
    def _display_album_results(self, results: List[Dict]):
        """Display album search results"""
        for widget in self.album_list.winfo_children():
            widget.destroy()
        
        self.album_results = results
        
        if not results:
            ParagonLabel(self.album_list, text="No albums found", style="muted").pack(pady=20)
            return
        
        for i, album in enumerate(results):
            self._add_album_row(i, album)
    
    def _add_album_row(self, index: int, album: Dict):
        """Add an album result row"""
        frame = ctk.CTkFrame(
            self.album_list,
            fg_color=ParagonTheme.BG_TERTIARY if index % 2 == 0 else ParagonTheme.BG_SECONDARY,
            corner_radius=4
        )
        frame.pack(fill="x", pady=2)
        frame.bind("<Button-1>", lambda e, idx=index: self._select_album(idx))
        
        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="x", padx=10, pady=8)
        content.bind("<Button-1>", lambda e, idx=index: self._select_album(idx))
        
        # Album title
        title_lbl = ctk.CTkLabel(
            content, text=album.get('album', 'Unknown'),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=ParagonTheme.TEXT_PRIMARY, anchor="w"
        )
        title_lbl.pack(fill="x")
        title_lbl.bind("<Button-1>", lambda e, idx=index: self._select_album(idx))
        
        # Artist and info
        info = f"{album.get('artist', 'Unknown Artist')}"
        if album.get('year'):
            info += f" • {album['year']}"
        if album.get('tracks'):
            info += f" • {album['tracks']} tracks"
        
        info_lbl = ctk.CTkLabel(
            content, text=info,
            font=ctk.CTkFont(size=11),
            text_color=ParagonTheme.TEXT_SECONDARY, anchor="w"
        )
        info_lbl.pack(fill="x")
        info_lbl.bind("<Button-1>", lambda e, idx=index: self._select_album(idx))
        
        # Score
        score = album.get('score', 0)
        score_color = ParagonTheme.SUCCESS if score >= 90 else (ParagonTheme.GOLD if score >= 70 else ParagonTheme.TEXT_SECONDARY)
        ctk.CTkLabel(frame, text=f"{score}%", font=ctk.CTkFont(size=10),
                    text_color=score_color, width=35).pack(side="right", padx=5)
    
    def _select_album(self, index: int):
        """Select an album and load its tracks"""
        if index >= len(self.album_results):
            return
        
        self.selected_album = self.album_results[index]
        
        # Highlight selected
        for i, widget in enumerate(self.album_list.winfo_children()):
            if isinstance(widget, ctk.CTkFrame):
                widget.configure(fg_color=ParagonTheme.RED_DARK if i == index else 
                               (ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY))
        
        # Update album info
        self.album_title_label.configure(text=self.selected_album.get('album', 'Unknown'))
        info = f"{self.selected_album.get('artist', '')} • {self.selected_album.get('year', '')}"
        self.album_info_label.configure(text=info)
        
        # Clear track list
        for widget in self.track_list.winfo_children():
            widget.destroy()
        
        self.track_status = ParagonLabel(self.track_list, text="Loading tracks...", style="muted")
        self.track_status.pack(pady=20)
        self.update()
        
        # Fetch tracks and cover
        release_id = self.selected_album.get('id')
        
        def fetch_data():
            tracks = MusicBrainzAPI.get_release_tracks(release_id)
            cover = MusicBrainzAPI.get_cover_art(release_id) if self.fetch_cover.get() else None
            self.after(0, lambda: self._display_tracks(tracks, cover))
        
        threading.Thread(target=fetch_data, daemon=True).start()
    
    def _display_tracks(self, tracks: List[Dict], cover_data: Optional[bytes]):
        """Display tracks for matching"""
        for widget in self.track_list.winfo_children():
            widget.destroy()
        
        self.album_tracks = tracks
        self.track_mapping = {}
        self.track_file_labels = {}
        
        # Display cover
        if cover_data and HAS_PIL:
            try:
                img = Image.open(io.BytesIO(cover_data))
                img.thumbnail((95, 95), Image.Resampling.LANCZOS)
                self._cover_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(95, 95))
                self.cover_label.configure(image=self._cover_photo, text="")
                self.cover_data = cover_data
            except:
                self.cover_data = None
        else:
            self.cover_data = None
        
        if not tracks:
            ParagonLabel(self.track_list, text="No tracks found", style="muted").pack(pady=20)
            return
        
        # Create track rows
        for i, track in enumerate(tracks):
            self._add_track_row(i, track)
        
        # Auto-match by track number
        self._auto_match_tracks()
    
    def _add_track_row(self, index: int, track: Dict):
        """Add a track matching row"""
        frame = ctk.CTkFrame(
            self.track_list,
            fg_color=ParagonTheme.BG_TERTIARY if index % 2 == 0 else ParagonTheme.BG_SECONDARY,
            corner_radius=4, height=40
        )
        frame.pack(fill="x", pady=1)
        frame.pack_propagate(False)
        
        # Track number
        track_num = track.get('track', str(index + 1))
        ctk.CTkLabel(frame, text=track_num, width=30, font=ctk.CTkFont(size=12),
                    text_color=ParagonTheme.GOLD).pack(side="left", padx=5)
        
        # MusicBrainz track title
        title = track.get('title', 'Unknown')
        ctk.CTkLabel(frame, text=title, width=250, font=ctk.CTkFont(size=12),
                    text_color=ParagonTheme.TEXT_PRIMARY, anchor="w").pack(side="left", padx=5)
        
        # Arrow
        ctk.CTkLabel(frame, text="→", width=30, font=ctk.CTkFont(size=12),
                    text_color=ParagonTheme.TEXT_SECONDARY).pack(side="left")
        
        # File dropdown
        file_options = ["(not matched)"] + [os.path.basename(f) for f in self.files]
        
        file_var = ctk.StringVar(value="(not matched)")
        dropdown = ctk.CTkOptionMenu(
            frame, values=file_options, variable=file_var,
            fg_color=ParagonTheme.BG_DARK, button_color=ParagonTheme.RED_PRIMARY,
            button_hover_color=ParagonTheme.RED_LIGHT,
            font=ctk.CTkFont(size=11), width=280,
            command=lambda val, idx=index: self._on_file_selected(idx, val)
        )
        dropdown.pack(side="left", padx=5, fill="x", expand=True)
        
        self.track_file_labels[index] = (file_var, dropdown)
    
    def _on_file_selected(self, track_index: int, filename: str):
        """Handle file selection for a track"""
        if filename == "(not matched)":
            if track_index in self.track_mapping:
                del self.track_mapping[track_index]
        else:
            # Find file index
            for i, f in enumerate(self.files):
                if os.path.basename(f) == filename:
                    self.track_mapping[track_index] = i
                    break
    
    def _auto_match_tracks(self):
        """Auto-match tracks to files by track number or name similarity"""
        if not self.album_tracks:
            return
        
        self.track_mapping = {}
        used_files = set()
        
        # First pass: Match by track number in filename or tags
        for track_idx, track in enumerate(self.album_tracks):
            mb_track_num = track.get('track', str(track_idx + 1))
            mb_title = track.get('title', '').lower()
            
            best_match = None
            best_score = 0
            
            for file_idx, filepath in enumerate(self.files):
                if file_idx in used_files:
                    continue
                
                filename = os.path.basename(filepath).lower()
                file_tags = TagManager.read_tags(filepath)
                file_track = file_tags.get('track', file_tags.get('tracknumber', ''))
                file_title = file_tags.get('title', '').lower()
                
                score = 0
                
                # Check track number match
                if file_track and str(file_track).split('/')[0] == str(mb_track_num):
                    score += 50
                
                # Check if track number in filename
                if mb_track_num.zfill(2) in filename or f"track{mb_track_num}" in filename.replace(' ', ''):
                    score += 30
                
                # Check title similarity
                if mb_title and file_title:
                    # Simple word matching
                    mb_words = set(mb_title.split())
                    file_words = set(file_title.split())
                    common = len(mb_words & file_words)
                    if common > 0:
                        score += common * 10
                
                # Check if title in filename
                if mb_title and mb_title.replace(' ', '') in filename.replace(' ', '').replace('-', '').replace('_', ''):
                    score += 40
                
                if score > best_score:
                    best_score = score
                    best_match = file_idx
            
            if best_match is not None and best_score > 20:
                self.track_mapping[track_idx] = best_match
                used_files.add(best_match)
        
        # Second pass: Match remaining by position
        remaining_files = [i for i in range(len(self.files)) if i not in used_files]
        remaining_tracks = [i for i in range(len(self.album_tracks)) if i not in self.track_mapping]
        
        for track_idx, file_idx in zip(remaining_tracks, remaining_files):
            self.track_mapping[track_idx] = file_idx
        
        # Update UI
        for track_idx, (file_var, dropdown) in self.track_file_labels.items():
            if track_idx in self.track_mapping:
                file_idx = self.track_mapping[track_idx]
                file_var.set(os.path.basename(self.files[file_idx]))
            else:
                file_var.set("(not matched)")
    
    def _apply_tags(self):
        """Apply tags to matched files"""
        if not self.album_tracks or not self.track_mapping:
            messagebox.showinfo("No Matches", "No tracks are matched to files")
            return
        
        print(f"=== APPLYING TAGS ===")
        print(f"Album tracks count: {len(self.album_tracks)}")
        print(f"Files count: {len(self.files)}")
        print(f"Track mapping: {self.track_mapping}")
        
        success = 0
        errors = []
        
        album_data = {
            'album': self.selected_album.get('album', ''),
            'artist': self.selected_album.get('artist', ''),
            'albumartist': self.selected_album.get('artist', ''),
            'year': self.selected_album.get('year', ''),
        }
        
        print(f"Album data: {album_data}")
        
        for track_idx, file_idx in self.track_mapping.items():
            print(f"\n--- Processing track_idx={track_idx}, file_idx={file_idx} ---")
            
            if track_idx >= len(self.album_tracks) or file_idx >= len(self.files):
                print(f"  SKIPPING: out of bounds")
                continue
            
            track = self.album_tracks[track_idx]
            filepath = self.files[file_idx]
            
            print(f"  Track from MB: {track}")
            print(f"  File: {filepath}")
            
            tags = {
                **album_data,
                'title': track.get('title', ''),
                'track': track.get('track', str(track_idx + 1)),
                'artist': track.get('artist', album_data['artist']),  # Use track artist if different
            }
            
            print(f"  Tags to write: {tags}")
            
            if track.get('discnumber'):
                tags['discnumber'] = track['discnumber']
            
            try:
                # Save cover art first if available
                if self.cover_data and self.fetch_cover.get():
                    TagManager.write_cover_art(filepath, self.cover_data, 'image/jpeg')
                
                # Save tags
                if TagManager.write_tags(filepath, tags):
                    success += 1
                else:
                    errors.append(os.path.basename(filepath))
            except Exception as e:
                errors.append(f"{os.path.basename(filepath)}: {e}")
        
        if errors:
            messagebox.showwarning("Complete", f"Tagged {success} files.\n\nErrors:\n" + "\n".join(errors[:5]))
        else:
            messagebox.showinfo("Success", f"Successfully tagged {success} files!")
        
        if self.on_complete:
            self.on_complete()
        
        self.destroy()


class MovieScraperDialog(ctk.CTkToplevel):
    """MediaElch-style movie scraper dialog"""
    
    def __init__(self, master, files: List[str]):
        print("DEBUG: MovieScraperDialog __init__ START")
        super().__init__(master)
        
        self.files = files
        self.search_results = []
        self.selected_movie = None
        self.movie_details = None
        self.poster_data = None
        self._poster_photo = None
        
        print("DEBUG: Setting window properties")
        self.title("🎬 Movie Scraper")
        self.geometry("1100x750")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        print("DEBUG: Creating UI")
        self._create_ui()
        print("DEBUG: UI created")
        
        # Auto-parse first file
        if files:
            print(f"DEBUG: Parsing first file: {files[0]}")
            parsed = MediaFileParser.parse_movie(os.path.basename(files[0]))
            if parsed.get('title'):
                self.search_entry.insert(0, parsed['title'])
                if parsed.get('year'):
                    self.year_entry.insert(0, parsed['year'])
        
        print("DEBUG: MovieScraperDialog __init__ END")
        self.after(50, lambda: self.grab_set() if self.winfo_exists() else None)
    
    def _create_ui(self):
        """Create the movie scraper UI"""
        print("DEBUG: _create_ui START")
        import sys
        sys.stdout.flush()
        
        # Main container with gold border
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        main.pack(fill="both", expand=True, padx=4, pady=4)
        
        inner = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        print("DEBUG: Created main containers")
        sys.stdout.flush()
        
        # Header
        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 10))
        
        ParagonLabel(header, text="🎬 MOVIE SCRAPER", style="title").pack(side="left")
        ParagonLabel(header, text=f"{len(self.files)} file(s)", style="muted").pack(side="right")
        
        print("DEBUG: Created header")
        sys.stdout.flush()
        
        # Search section
        search_frame = ctk.CTkFrame(inner, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        search_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        search_inner = ctk.CTkFrame(search_frame, fg_color="transparent")
        search_inner.pack(fill="x", padx=15, pady=12)
        
        print("DEBUG: Created search frame")
        sys.stdout.flush()
        
        # Movie title
        title_frame = ctk.CTkFrame(search_inner, fg_color="transparent")
        title_frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ParagonLabel(title_frame, text="Movie Title:", style="muted").pack(anchor="w")
        self.search_entry = ctk.CTkEntry(
            title_frame, fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK, font=ctk.CTkFont(size=15), height=38
        )
        self.search_entry.pack(fill="x")
        self.search_entry.bind('<Return>', lambda e: self._search())
        
        print("DEBUG: Created search entry")
        sys.stdout.flush()
        
        # Year
        year_frame = ctk.CTkFrame(search_inner, fg_color="transparent")
        year_frame.pack(side="left", padx=(0, 10))
        ParagonLabel(year_frame, text="Year:", style="muted").pack(anchor="w")
        self.year_entry = ctk.CTkEntry(
            year_frame, fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK, font=ctk.CTkFont(size=15), height=38, width=80
        )
        self.year_entry.pack()
        
        print("DEBUG: Created year entry")
        sys.stdout.flush()
        
        # Search button
        btn_frame = ctk.CTkFrame(search_inner, fg_color="transparent")
        btn_frame.pack(side="left")
        ParagonLabel(btn_frame, text=" ", style="muted").pack()
        ParagonButton(btn_frame, text="🔍 SEARCH", command=self._search, width=120, height=38).pack()
        
        print("DEBUG: Created search button")
        sys.stdout.flush()
        
        # Content area - two panels
        content = ctk.CTkFrame(inner, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        
        print("DEBUG: Created content frame")
        sys.stdout.flush()
        
        # Left panel - Search results (SIMPLIFIED - no scrollable frame)
        left_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=350)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)
        
        ParagonLabel(left_panel, text="SEARCH RESULTS", style="header").pack(anchor="w", padx=15, pady=(10, 5))
        
        print("DEBUG: About to create scrollable frame...")
        sys.stdout.flush()
        
        # Use regular frame instead of scrollable to test
        self.results_list = ctk.CTkFrame(left_panel, fg_color=ParagonTheme.BG_DARK)
        self.results_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        print("DEBUG: Created results list frame")
        sys.stdout.flush()
        
        self.results_status = ParagonLabel(self.results_list, text="Enter movie title and search", style="muted")
        self.results_status.pack(pady=20)
        
        print("DEBUG: Created results status")
        sys.stdout.flush()
        
        # Right panel - Movie details
        right_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        right_panel.pack(side="left", fill="both", expand=True)
        
        print("DEBUG: Created right panel")
        sys.stdout.flush()
        
        # Movie info header
        info_header = ctk.CTkFrame(right_panel, fg_color="transparent")
        info_header.pack(fill="x", padx=15, pady=10)
        
        # Poster placeholder
        self.poster_frame = ctk.CTkFrame(info_header, fg_color=ParagonTheme.BG_DARK, width=120, height=180, corner_radius=4)
        self.poster_frame.pack(side="left", padx=(0, 15))
        self.poster_frame.pack_propagate(False)
        
        self.poster_label = ctk.CTkLabel(self.poster_frame, text="No\nPoster", text_color=ParagonTheme.TEXT_SECONDARY)
        self.poster_label.pack(expand=True)
        
        print("DEBUG: Created poster frame")
        sys.stdout.flush()
        
        # Movie title and info
        title_info = ctk.CTkFrame(info_header, fg_color="transparent")
        title_info.pack(side="left", fill="both", expand=True)
        
        self.movie_title_label = ParagonLabel(title_info, text="Select a movie", style="title")
        self.movie_title_label.pack(anchor="w")
        
        self.movie_year_label = ParagonLabel(title_info, text="", style="muted")
        self.movie_year_label.pack(anchor="w")
        
        self.movie_rating_label = ParagonLabel(title_info, text="", style="muted")
        self.movie_rating_label.pack(anchor="w")
        
        self.movie_genres_label = ParagonLabel(title_info, text="", style="muted")
        self.movie_genres_label.pack(anchor="w")
        
        print("DEBUG: Created movie info labels")
        sys.stdout.flush()
        
        # Overview/plot
        ParagonLabel(right_panel, text="OVERVIEW", style="header").pack(anchor="w", padx=15, pady=(5, 5))
        
        self.overview_text = ctk.CTkTextbox(
            right_panel, fg_color=ParagonTheme.BG_DARK, height=120,
            font=ctk.CTkFont(size=12)
        )
        self.overview_text.pack(fill="x", padx=15, pady=(0, 10))
        self.overview_text.configure(state="disabled")
        
        print("DEBUG: Created overview textbox")
        sys.stdout.flush()
        
        # Cast
        ParagonLabel(right_panel, text="CAST", style="header").pack(anchor="w", padx=15, pady=(0, 5))
        
        self.cast_label = ParagonLabel(right_panel, text="", style="muted")
        self.cast_label.pack(anchor="w", padx=15, pady=(0, 10))
        
        print("DEBUG: Created cast label")
        sys.stdout.flush()
        
        # Options - Row 1
        options_frame1 = ctk.CTkFrame(right_panel, fg_color="transparent")
        options_frame1.pack(fill="x", padx=15, pady=(0, 5))
        
        self.download_poster = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame1, text="poster.jpg",
            variable=self.download_poster,
            fg_color=ParagonTheme.RED_PRIMARY
        ).pack(side="left", padx=(0, 15))
        
        self.download_fanart = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame1, text="fanart.jpg",
            variable=self.download_fanart,
            fg_color=ParagonTheme.RED_PRIMARY
        ).pack(side="left", padx=(0, 15))
        
        self.download_landscape = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame1, text="landscape.jpg",
            variable=self.download_landscape,
            fg_color=ParagonTheme.RED_PRIMARY
        ).pack(side="left", padx=(0, 15))
        
        self.download_logo = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame1, text="logo.png",
            variable=self.download_logo,
            fg_color=ParagonTheme.RED_PRIMARY
        ).pack(side="left")
        
        # Options - Row 2
        options_frame2 = ctk.CTkFrame(right_panel, fg_color="transparent")
        options_frame2.pack(fill="x", padx=15, pady=(0, 10))
        
        self.create_nfo = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame2, text="Create NFO",
            variable=self.create_nfo,
            fg_color=ParagonTheme.RED_PRIMARY
        ).pack(side="left", padx=(0, 15))
        
        self.rename_file = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options_frame2, text="Rename file",
            variable=self.rename_file,
            fg_color=ParagonTheme.RED_PRIMARY
        ).pack(side="left")
        
        print("DEBUG: Created options checkboxes")
        sys.stdout.flush()
        
        # Bottom buttons
        btn_frame2 = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame2.pack(fill="x", padx=20, pady=(0, 15))
        
        ParagonSecondaryButton(btn_frame2, text="CANCEL", command=self.destroy, width=100).pack(side="left")
        ParagonButton(btn_frame2, text="✓ APPLY TO FILES", command=self._apply, width=160).pack(side="right")
        
        print("DEBUG: _create_ui END")
        sys.stdout.flush()
    
    def _search(self):
        """Search for movies"""
        query = self.search_entry.get().strip()
        year = self.year_entry.get().strip()
        
        if not query:
            messagebox.showinfo("Search", "Please enter a movie title")
            return
        
        # Clear results
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        self.results_status = ParagonLabel(self.results_list, text="Searching...", style="muted")
        self.results_status.pack(pady=20)
        self.update()
        
        def do_search():
            results = TMDBAPI.search_movie(query, year if year else None)
            self.after(0, lambda: self._display_results(results))
        
        threading.Thread(target=do_search, daemon=True).start()
    
    def _display_results(self, results: List[Dict]):
        """Display search results"""
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        self.search_results = results
        
        if not results:
            ParagonLabel(self.results_list, text="No movies found", style="muted").pack(pady=20)
            return
        
        for i, movie in enumerate(results):
            self._add_result_row(i, movie)
    
    def _add_result_row(self, index: int, movie: Dict):
        """Add a movie result row"""
        frame = ctk.CTkFrame(
            self.results_list,
            fg_color=ParagonTheme.BG_TERTIARY if index % 2 == 0 else ParagonTheme.BG_SECONDARY,
            corner_radius=4
        )
        frame.pack(fill="x", pady=2)
        frame.bind("<Button-1>", lambda e, idx=index: self._select_movie(idx))
        
        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="x", padx=10, pady=8)
        content.bind("<Button-1>", lambda e, idx=index: self._select_movie(idx))
        
        # Title
        title_text = movie.get('title', 'Unknown')
        if movie.get('year'):
            title_text += f" ({movie['year']})"
        
        title_lbl = ctk.CTkLabel(
            content, text=title_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=ParagonTheme.TEXT_PRIMARY, anchor="w"
        )
        title_lbl.pack(fill="x")
        title_lbl.bind("<Button-1>", lambda e, idx=index: self._select_movie(idx))
        
        # Rating
        rating = movie.get('vote_average', 0)
        rating_text = f"★ {rating:.1f}" if rating else ""
        
        rating_lbl = ctk.CTkLabel(
            content, text=rating_text,
            font=ctk.CTkFont(size=11),
            text_color=ParagonTheme.GOLD, anchor="w"
        )
        rating_lbl.pack(fill="x")
        rating_lbl.bind("<Button-1>", lambda e, idx=index: self._select_movie(idx))
    
    def _select_movie(self, index: int):
        """Select a movie and load details"""
        if index >= len(self.search_results):
            return
        
        self.selected_movie = self.search_results[index]
        
        # Highlight selected
        for i, widget in enumerate(self.results_list.winfo_children()):
            if isinstance(widget, ctk.CTkFrame):
                widget.configure(fg_color=ParagonTheme.RED_DARK if i == index else 
                               (ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY))
        
        # Update basic info immediately
        self.movie_title_label.configure(text=self.selected_movie.get('title', 'Unknown'))
        self.movie_year_label.configure(text=f"Year: {self.selected_movie.get('year', 'N/A')}")
        
        # Fetch full details in background
        movie_id = self.selected_movie.get('id')
        
        def fetch_details():
            details = TMDBAPI.get_movie_details(movie_id)
            poster = None
            if details and details.get('poster_path'):
                poster = TMDBAPI.download_image(details['poster_path'], 'w342')
            self.after(0, lambda: self._display_details(details, poster))
        
        threading.Thread(target=fetch_details, daemon=True).start()
    
    def _display_details(self, details: Optional[Dict], poster_data: Optional[bytes]):
        """Display movie details"""
        if not details:
            return
        
        self.movie_details = details
        self.poster_data = poster_data
        
        # Update labels
        self.movie_title_label.configure(text=details.get('title', 'Unknown'))
        
        year_runtime = f"Year: {details.get('year', 'N/A')}"
        if details.get('runtime'):
            year_runtime += f" | Runtime: {details['runtime']} min"
        self.movie_year_label.configure(text=year_runtime)
        
        rating = details.get('vote_average', 0)
        votes = details.get('vote_count', 0)
        cert = details.get('certification', '')
        rating_text = f"★ {rating:.1f} ({votes} votes)"
        if cert:
            rating_text += f" | {cert}"
        self.movie_rating_label.configure(text=rating_text)
        
        genres = ', '.join(details.get('genres', []))
        self.movie_genres_label.configure(text=genres)
        
        # Overview
        self.overview_text.configure(state="normal")
        self.overview_text.delete("1.0", "end")
        self.overview_text.insert("1.0", details.get('overview', 'No overview available'))
        self.overview_text.configure(state="disabled")
        
        # Cast
        cast_names = [a['name'] for a in details.get('cast', [])[:5]]
        self.cast_label.configure(text=', '.join(cast_names))
        
        # Poster
        if poster_data and HAS_PIL:
            try:
                img = Image.open(io.BytesIO(poster_data))
                img.thumbnail((115, 175), Image.Resampling.LANCZOS)
                self._poster_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(115, 175))
                self.poster_label.configure(image=self._poster_photo, text="")
            except:
                pass
    
    def _apply(self):
        """Apply scraped data to files"""
        print("DEBUG: _apply called")
        
        if not self.movie_details:
            messagebox.showinfo("Select Movie", "Please search and select a movie first")
            return
        
        print(f"DEBUG: movie_details keys: {self.movie_details.keys()}")
        print(f"DEBUG: poster_path: {self.movie_details.get('poster_path')}")
        print(f"DEBUG: backdrop_path: {self.movie_details.get('backdrop_path')}")
        print(f"DEBUG: download_poster checkbox: {self.download_poster.get()}")
        print(f"DEBUG: download_fanart checkbox: {self.download_fanart.get()}")
        
        success = 0
        errors = []
        
        for filepath in self.files:
            try:
                folder = os.path.dirname(filepath)
                basename = os.path.basename(filepath)
                name, ext = os.path.splitext(basename)
                
                print(f"DEBUG: Processing file: {basename}")
                print(f"DEBUG: Folder: {folder}")
                
                # Create NFO
                if self.create_nfo.get():
                    nfo_content = NFOGenerator.generate_movie_nfo(self.movie_details)
                    nfo_path = os.path.join(folder, f"{name}.nfo")
                    with open(nfo_path, 'w', encoding='utf-8') as f:
                        f.write(nfo_content)
                    print(f"Created NFO: {nfo_path}")
                
                # Download poster
                if self.download_poster.get() and self.movie_details.get('poster_path'):
                    print(f"DEBUG: Downloading poster from: {self.movie_details['poster_path']}")
                    poster_data = TMDBAPI.download_image(self.movie_details['poster_path'], 'original')
                    print(f"DEBUG: Poster data received: {len(poster_data) if poster_data else 'None'} bytes")
                    if poster_data:
                        poster_path = os.path.join(folder, "poster.jpg")
                        with open(poster_path, 'wb') as f:
                            f.write(poster_data)
                        print(f"Downloaded poster: {poster_path}")
                    else:
                        print("DEBUG: No poster data received!")
                else:
                    print(f"DEBUG: Skipping poster - checkbox: {self.download_poster.get()}, path: {self.movie_details.get('poster_path')}")
                
                # Download fanart
                if self.download_fanart.get() and self.movie_details.get('backdrop_path'):
                    print(f"DEBUG: Downloading fanart from: {self.movie_details['backdrop_path']}")
                    fanart_data = TMDBAPI.download_image(self.movie_details['backdrop_path'], 'original')
                    print(f"DEBUG: Fanart data received: {len(fanart_data) if fanart_data else 'None'} bytes")
                    if fanart_data:
                        fanart_path = os.path.join(folder, "fanart.jpg")
                        with open(fanart_path, 'wb') as f:
                            f.write(fanart_data)
                        print(f"Downloaded fanart: {fanart_path}")
                    else:
                        print("DEBUG: No fanart data received!")
                else:
                    print(f"DEBUG: Skipping fanart - checkbox: {self.download_fanart.get()}, path: {self.movie_details.get('backdrop_path')}")
                
                # Download landscape
                if self.download_landscape.get() and self.movie_details.get('landscape_path'):
                    print(f"DEBUG: Downloading landscape from: {self.movie_details['landscape_path']}")
                    landscape_data = TMDBAPI.download_image(self.movie_details['landscape_path'], 'original')
                    if landscape_data:
                        landscape_path = os.path.join(folder, "landscape.jpg")
                        with open(landscape_path, 'wb') as f:
                            f.write(landscape_data)
                        print(f"Downloaded landscape: {landscape_path}")
                elif self.download_landscape.get() and self.movie_details.get('backdrop_path'):
                    # Fallback to backdrop if no specific landscape
                    print("DEBUG: No landscape, using backdrop as landscape")
                    landscape_data = TMDBAPI.download_image(self.movie_details['backdrop_path'], 'original')
                    if landscape_data:
                        landscape_path = os.path.join(folder, "landscape.jpg")
                        with open(landscape_path, 'wb') as f:
                            f.write(landscape_data)
                        print(f"Downloaded landscape (from backdrop): {landscape_path}")
                
                # Download logo
                if self.download_logo.get() and self.movie_details.get('logo_path'):
                    print(f"DEBUG: Downloading logo from: {self.movie_details['logo_path']}")
                    logo_data = TMDBAPI.download_image(self.movie_details['logo_path'], 'original')
                    if logo_data:
                        # Logos are usually PNG
                        logo_ext = '.png' if self.movie_details['logo_path'].endswith('.png') else '.png'
                        logo_path = os.path.join(folder, f"logo{logo_ext}")
                        with open(logo_path, 'wb') as f:
                            f.write(logo_data)
                        print(f"Downloaded logo: {logo_path}")
                else:
                    if self.download_logo.get():
                        print(f"DEBUG: No logo available for this movie")
                
                # Rename file
                if self.rename_file.get():
                    new_name = MediaFileParser.generate_movie_filename(self.movie_details, ext)
                    new_path = os.path.join(folder, new_name)
                    if new_path != filepath and not os.path.exists(new_path):
                        os.rename(filepath, new_path)
                        print(f"Renamed: {basename} -> {new_name}")
                
                success += 1
                
            except Exception as e:
                import traceback
                traceback.print_exc()
                errors.append(f"{os.path.basename(filepath)}: {e}")
        
        if errors:
            messagebox.showwarning("Complete", f"Processed {success} file(s).\n\nErrors:\n" + "\n".join(errors[:5]))
        else:
            messagebox.showinfo("Success", f"Successfully processed {success} file(s)!")
        
        self.destroy()


class ImageChooserDialog(ctk.CTkToplevel):
    """Dialog to choose from available images from TMDB and Fanart.tv"""
    
    def __init__(self, master, movie_id: int, image_type: str = "posters", movie_title: str = "", display_type: str = None, media_type: str = "movie", tvdb_id: int = None):
        super().__init__(master)
        
        self.movie_id = movie_id  # TMDB ID
        self.tvdb_id = tvdb_id    # TVDB ID (for Fanart.tv TV shows)
        self.image_type = image_type  # 'posters', 'backdrops', 'logos', 'thumbs' - API type
        self.display_type = display_type or image_type  # For UI display (e.g., 'landscape')
        self.movie_title = movie_title
        self.media_type = media_type  # 'movie' or 'tv'
        self.images = []
        self.selected_path = None
        self.selected_source = None  # 'tmdb' or 'fanart'
        self._image_refs = []  # Keep references to prevent garbage collection
        self.current_source = "tmdb"  # Default source
        
        # Type to display name mapping
        type_names = {
            'posters': 'Posters',
            'backdrops': 'Fanart / Backdrops',
            'logos': 'Logos',
            'landscape': 'Landscape',
            'thumbs': 'Landscape'
        }
        
        self.title(f"Choose {type_names.get(self.display_type, 'Image')}")
        self.geometry("1200x800")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        self._create_ui()
        self._load_images()
        
        self.after(50, lambda: self.grab_set() if self.winfo_exists() else None)
    
    def _create_ui(self):
        """Create the image chooser UI"""
        # Main container
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        main.pack(fill="both", expand=True, padx=4, pady=4)
        
        inner = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Header
        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(15, 10))
        
        type_names = {'posters': 'Posters', 'backdrops': 'Fanart / Backdrops', 'logos': 'Logos', 'landscape': 'Landscape', 'thumbs': 'Landscape'}
        title_text = f"Choose {type_names.get(self.display_type, 'Image')}"
        if self.movie_title:
            title_text += f" - {self.movie_title}"
        
        ctk.CTkLabel(
            header,
            text=title_text,
            font=ctk.CTkFont(family="Bebas Neue", size=36, weight="bold"),
            text_color=ParagonTheme.RED_LIGHT
        ).pack(side="left")
        
        # Source selector (TMDB / Fanart.tv)
        source_frame = ctk.CTkFrame(header, fg_color="transparent")
        source_frame.pack(side="right")
        
        ctk.CTkLabel(
            source_frame,
            text="Source:",
            font=ctk.CTkFont(size=14),
            text_color=ParagonTheme.TEXT_SECONDARY
        ).pack(side="left", padx=(0, 10))
        
        self.source_var = ctk.StringVar(value="TMDB")
        self.source_menu = ctk.CTkOptionMenu(
            source_frame,
            variable=self.source_var,
            values=["TMDB", "Fanart.tv"],
            command=self._on_source_change,
            fg_color=ParagonTheme.BG_TERTIARY,
            button_color=ParagonTheme.RED_PRIMARY,
            width=120
        )
        self.source_menu.pack(side="left")
        
        # Image grid area
        self.grid_frame = ctk.CTkScrollableFrame(inner, fg_color=ParagonTheme.BG_SECONDARY)
        self.grid_frame.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        
        # Loading label
        self.loading_label = ctk.CTkLabel(
            self.grid_frame,
            text="Loading images...",
            font=ctk.CTkFont(size=18),
            text_color=ParagonTheme.TEXT_SECONDARY
        )
        self.loading_label.pack(pady=50)
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self.destroy, width=120).pack(side="left")
        
        self.select_btn = ParagonButton(btn_frame, text="SELECT", command=self._select_image, width=120, state="disabled")
        self.select_btn.pack(side="right")
    
    def _on_source_change(self, value):
        """Handle source change"""
        self.current_source = "tmdb" if value == "TMDB" else "fanart"
        self._load_images()
    
    def _load_images(self):
        """Load images from selected source in background thread"""
        # Clear existing
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        
        self._image_refs = []
        self.images = []
        self.selected_path = None
        self.selected_source = None
        self.select_btn.configure(state="disabled")
        
        loading = ctk.CTkLabel(
            self.grid_frame,
            text="Loading images...",
            font=ctk.CTkFont(size=18),
            text_color=ParagonTheme.TEXT_SECONDARY
        )
        loading.pack(pady=50)
        
        # Check if this is for a TV show
        is_tv = getattr(self, 'media_type', 'movie') == 'tv'
        
        def fetch():
            if self.current_source == "tmdb":
                if is_tv:
                    images = TMDBAPI.get_tv_images(self.movie_id)
                else:
                    images = TMDBAPI.get_movie_images(self.movie_id)
                # TMDB doesn't have 'thumbs', use backdrops as fallback for landscape
                tmdb_type = 'backdrops' if self.image_type == 'thumbs' else self.image_type
                image_list = images.get(tmdb_type, [])
                source = "tmdb"
            else:
                # Fanart.tv
                if not FanartTVAPI.get_api_key():
                    self.after(0, lambda: self._show_no_api_key())
                    return
                if is_tv:
                    # Fanart.tv uses TVDB ID for TV shows
                    fanart_id = self.tvdb_id if self.tvdb_id else self.movie_id
                    print(f"Fanart.tv TV lookup with ID: {fanart_id} (TVDB: {self.tvdb_id}, TMDB: {self.movie_id})")
                    images = FanartTVAPI.get_tv_images(fanart_id)
                else:
                    images = FanartTVAPI.get_movie_images(self.movie_id)
                # Map our image_type to fanart.tv types
                fanart_type_map = {
                    'posters': 'posters',
                    'backdrops': 'backdrops',
                    'logos': 'logos',
                    'thumbs': 'thumbs',  # Landscape images!
                }
                image_list = images.get(fanart_type_map.get(self.image_type, self.image_type), [])
                source = "fanart"
                
                # If no images found and we don't have TVDB ID, show message
                if not image_list and is_tv and not self.tvdb_id:
                    self.after(0, lambda: self._show_no_tvdb_id())
                    return
            
            self.after(0, lambda: self._display_images(image_list, source))
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _show_no_api_key(self):
        """Show message when Fanart.tv API key is not set"""
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        
        msg_frame = ctk.CTkFrame(self.grid_frame, fg_color="transparent")
        msg_frame.pack(expand=True, pady=50)
        
        ctk.CTkLabel(
            msg_frame,
            text="Fanart.tv API Key Required",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=ParagonTheme.RED_LIGHT
        ).pack(pady=(0, 10))
        
        ctk.CTkLabel(
            msg_frame,
            text="To use Fanart.tv, please enter your API key in the\nFanart.tv API Key field in the main window.",
            font=ctk.CTkFont(size=14),
            text_color=ParagonTheme.TEXT_SECONDARY
        ).pack()
        
        ctk.CTkLabel(
            msg_frame,
            text="Get a free API key at: https://fanart.tv/get-an-api-key/",
            font=ctk.CTkFont(size=12),
            text_color=ParagonTheme.TEXT_MUTED
        ).pack(pady=(10, 0))
    
    def _show_no_tvdb_id(self):
        """Show message when TVDB ID is not available for Fanart.tv TV lookup"""
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        
        msg_frame = ctk.CTkFrame(self.grid_frame, fg_color="transparent")
        msg_frame.pack(expand=True, pady=50)
        
        ctk.CTkLabel(
            msg_frame,
            text="TVDB ID Required for Fanart.tv",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=ParagonTheme.RED_LIGHT
        ).pack(pady=(0, 10))
        
        ctk.CTkLabel(
            msg_frame,
            text="Fanart.tv requires a TVDB ID to look up TV show artwork.\n\n"
                 "Try searching for the show in SHOW mode to get the TVDB ID,\n"
                 "or use TMDB as the source instead.",
            font=ctk.CTkFont(size=14),
            text_color=ParagonTheme.TEXT_SECONDARY
        ).pack()
    
    def _display_images(self, images: List[Dict], source: str):
        """Display images in a grid"""
        self.images = images
        
        # Clear grid
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        
        if not images:
            ctk.CTkLabel(
                self.grid_frame,
                text="No images found from this source",
                font=ctk.CTkFont(size=18),
                text_color=ParagonTheme.TEXT_SECONDARY
            ).pack(pady=50)
            return
        
        # Determine thumbnail size based on type
        if self.image_type == 'posters':
            thumb_width, thumb_height = 150, 225
            cols = 6
        elif self.image_type == 'logos':
            thumb_width, thumb_height = 200, 80
            cols = 5
        elif self.image_type == 'thumbs':
            thumb_width, thumb_height = 280, 158  # 16:9 ratio for landscape
            cols = 4
        else:  # backdrops
            thumb_width, thumb_height = 250, 140
            cols = 4
        
        row_frame = None
        for i, img_data in enumerate(images):
            if i % cols == 0:
                row_frame = ctk.CTkFrame(self.grid_frame, fg_color="transparent")
                row_frame.pack(fill="x", pady=5, padx=5)
            
            self._create_image_tile(row_frame, img_data, i, thumb_width, thumb_height, source)
    
    def _create_image_tile(self, parent, img_data: Dict, index: int, width: int, height: int, source: str = "tmdb"):
        """Create a clickable image tile"""
        tile = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        tile.pack(side="left", padx=5, pady=5)
        
        # Image container
        img_container = ctk.CTkFrame(tile, fg_color=ParagonTheme.BG_DARK, width=width, height=height, corner_radius=4)
        img_container.pack(padx=5, pady=5)
        img_container.pack_propagate(False)
        
        # Placeholder while loading
        placeholder = ctk.CTkLabel(img_container, text="Loading...", text_color=ParagonTheme.TEXT_SECONDARY)
        placeholder.pack(expand=True)
        
        # Size/info text
        if source == "tmdb":
            size_text = f"{img_data.get('width', '?')} x {img_data.get('height', '?')}"
            lang = img_data.get('language', '')
            if lang:
                size_text += f" ({lang})"
        else:
            # Fanart.tv doesn't include dimensions, just language
            lang = img_data.get('language', '')
            likes = img_data.get('likes', 0)
            size_text = f"({lang})" if lang else ""
            if likes:
                size_text += f" ♥{likes}"
        
        ctk.CTkLabel(
            tile,
            text=size_text,
            font=ctk.CTkFont(size=11),
            text_color=ParagonTheme.TEXT_SECONDARY
        ).pack(pady=(0, 5))
        
        # Make clickable - pass source too
        tile.bind("<Button-1>", lambda e, idx=index, src=source: self._select_tile(idx, src))
        img_container.bind("<Button-1>", lambda e, idx=index, src=source: self._select_tile(idx, src))
        placeholder.bind("<Button-1>", lambda e, idx=index, src=source: self._select_tile(idx, src))
        
        # Store tile reference for selection highlighting
        img_data['_tile'] = tile
        img_data['_container'] = img_container
        img_data['_placeholder'] = placeholder
        img_data['_source'] = source
        
        # Load thumbnail in background
        def load_thumb():
            path = img_data.get('path', '')
            if not path:
                return
            
            if source == "tmdb":
                # Use smaller size for thumbnails from TMDB
                thumb_size = 'w342' if self.image_type == 'posters' else 'w500'
                data = TMDBAPI.download_image(path, thumb_size)
            else:
                # Fanart.tv - path is the full URL
                data = FanartTVAPI.download_image(path)
            
            if data and HAS_PIL:
                try:
                    img = Image.open(io.BytesIO(data))
                    img.thumbnail((width - 10, height - 10), Image.Resampling.LANCZOS)
                    photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                    self._image_refs.append(photo)  # Keep reference
                    
                    def update_ui():
                        if placeholder.winfo_exists():
                            placeholder.configure(image=photo, text="")
                    
                    self.after(0, update_ui)
                except Exception as e:
                    print(f"Error loading thumbnail: {e}")
        
        threading.Thread(target=load_thumb, daemon=True).start()
    
    def _select_tile(self, index: int, source: str = "tmdb"):
        """Select an image tile"""
        # Deselect all
        for img_data in self.images:
            tile = img_data.get('_tile')
            if tile and tile.winfo_exists():
                tile.configure(fg_color=ParagonTheme.BG_TERTIARY)
        
        # Select this one
        if index < len(self.images):
            self.selected_path = self.images[index].get('path')
            self.selected_source = source
            tile = self.images[index].get('_tile')
            if tile and tile.winfo_exists():
                tile.configure(fg_color=ParagonTheme.RED_PRIMARY)
            
            self.select_btn.configure(state="normal")
    
    def _select_image(self):
        """Confirm selection and close"""
        self.destroy()
    
    def get_selected_path(self) -> Optional[str]:
        """Get the selected image path"""
        return self.selected_path


class MovieEditorDialog(ctk.CTkToplevel):
    """MediaElch-style movie editor with Information, Extended, and Stream Details tabs"""
    
    # Font sizes (doubled for readability)
    FONT_SMALL = 16
    FONT_NORMAL = 18
    FONT_LARGE = 22
    FONT_TITLE = 28
    FONT_HEADER = 20
    
    # Default genres for selection
    DEFAULT_GENRES = [
        "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary",
        "Drama", "Family", "Fantasy", "History", "Horror", "Music", "Mystery",
        "Romance", "Science Fiction", "Thriller", "War", "Western"
    ]
    
    # Custom genres loaded from config (class-level, shared across instances)
    _custom_genres = None
    
    @classmethod
    def get_all_genres(cls) -> List[str]:
        """Get all genres including custom ones"""
        if cls._custom_genres is None:
            cls._load_custom_genres()
        all_genres = list(cls.DEFAULT_GENRES) + list(cls._custom_genres)
        return sorted(set(all_genres), key=str.lower)
    
    @classmethod
    def _load_custom_genres(cls):
        """Load custom genres from config file"""
        cls._custom_genres = set()
        config_path = Path.home() / ".pyrenamer_config.json"
        try:
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    custom = config.get('custom_genres', [])
                    cls._custom_genres = set(custom)
        except Exception as e:
            print(f"Could not load custom genres: {e}")
    
    @classmethod
    def add_custom_genre(cls, genre: str):
        """Add a custom genre and save to config"""
        if cls._custom_genres is None:
            cls._load_custom_genres()
        
        genre = genre.strip()
        if not genre:
            return False
        
        # Check if already exists (case-insensitive)
        existing = [g.lower() for g in cls.DEFAULT_GENRES] + [g.lower() for g in cls._custom_genres]
        if genre.lower() in existing:
            return False
        
        cls._custom_genres.add(genre)
        
        # Save to config
        config_path = Path.home() / ".pyrenamer_config.json"
        try:
            config = {}
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
            
            config['custom_genres'] = list(cls._custom_genres)
            
            with open(config_path, 'w') as f:
                json.dump(config, f)
            
            return True
        except Exception as e:
            print(f"Could not save custom genre: {e}")
            return False
    
    # Available certifications
    CERTIFICATIONS = ["G", "PG", "PG-13", "R", "NC-17", "NR", "TV-Y", "TV-Y7", "TV-G", "TV-PG", "TV-14", "TV-MA"]
    
    def __init__(self, master, files: List[str]):
        super().__init__(master)
        
        self.files = files
        self.current_file = files[0] if files else None
        self.search_results = []
        self.selected_movie = None
        self.movie_details = None
        self.stream_info = None
        self._poster_photo = None
        self._fanart_photo = None
        self._logo_photo = None
        self._landscape_photo = None
        self.existing_artwork = {}  # Store paths to existing artwork
        
        # Editable fields
        self.field_vars = {}
        self.selected_genres = set()
        self.selected_tags = set()
        self.selected_countries = set()
        self.selected_studios = set()
        
        self.title("Movie Editor")
        self.geometry("1600x950")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        self.after(10, lambda: self.state('zoomed'))  # Maximize window
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        self._create_ui()
        self._extract_stream_info()
        
        # Try to load existing NFO and artwork first
        if files:
            loaded = self._load_existing_data()
            
            # If no existing data, auto-parse filename for search
            if not loaded:
                parsed = MediaFileParser.parse_movie(os.path.basename(files[0]))
                if parsed.get('title'):
                    self.search_entry.insert(0, parsed['title'])
                    if parsed.get('year'):
                        self.year_entry.insert(0, parsed['year'])
        
        self.after(50, lambda: self.grab_set() if self.winfo_exists() else None)
    
    def _load_existing_data(self) -> bool:
        """Load existing NFO file and artwork. Returns True if NFO was found."""
        if not self.current_file:
            return False
        
        folder = os.path.dirname(self.current_file)
        print(f"Looking for NFO and artwork in: {folder}")
        
        # Find existing NFO
        nfo_path = NFOParser.find_movie_nfo(self.current_file)
        
        # Find existing artwork
        self.existing_artwork = NFOParser.find_existing_artwork(self.current_file)
        
        # Debug: print what artwork was found
        for art_type, art_path in self.existing_artwork.items():
            if art_path:
                print(f"Found {art_type}: {art_path}")
        
        if nfo_path:
            print(f"Found existing NFO: {nfo_path}")
            movie_data = NFOParser.parse_movie_nfo(nfo_path)
            
            if movie_data and movie_data.get('title'):
                # Set movie_details from NFO data
                self.movie_details = movie_data
                
                # Store existing artwork paths in movie_details so they're not re-downloaded
                # Use 'existing_' prefix to mark local files vs TMDB paths
                if self.existing_artwork.get('poster'):
                    self.movie_details['existing_poster'] = self.existing_artwork['poster']
                if self.existing_artwork.get('fanart'):
                    self.movie_details['existing_fanart'] = self.existing_artwork['fanart']
                if self.existing_artwork.get('logo'):
                    self.movie_details['existing_logo'] = self.existing_artwork['logo']
                if self.existing_artwork.get('landscape'):
                    self.movie_details['existing_landscape'] = self.existing_artwork['landscape']
                
                # Populate the UI with the loaded data
                self._populate_from_nfo(movie_data)
                
                # Load existing artwork previews
                self._load_existing_artwork_previews()
                
                return True
        
        # Even if no NFO, load artwork previews if they exist
        if any(self.existing_artwork.values()):
            print("No NFO found, but loading existing artwork")
            self._load_existing_artwork_previews()
        
        return False
    
    def _populate_from_nfo(self, movie_data: Dict):
        """Populate the editor UI with data from NFO"""
        # Fill in search fields
        if movie_data.get('title'):
            self.search_entry.delete(0, 'end')
            self.search_entry.insert(0, movie_data['title'])
        if movie_data.get('year'):
            self.year_entry.delete(0, 'end')
            self.year_entry.insert(0, str(movie_data['year']))
        
        # Populate field variables - map NFO data keys to UI field keys
        field_mapping = {
            'title': 'title',
            'original_title': 'original_title',
            'sort_title': 'title',  # Use title as sort_title if not set
            'tagline': 'tagline',
            'release_date': 'release_date',
            'runtime': 'runtime',
            'certification': 'certification',
            'director': 'director',
            'writer': 'writer',
            'set': 'set_name',  # UI uses 'set', NFO uses 'set_name'
            'imdb_id': 'imdb_id',
        }
        
        for ui_key, data_key in field_mapping.items():
            if ui_key in self.field_vars and movie_data.get(data_key):
                var = self.field_vars[ui_key]
                value = str(movie_data[data_key])
                if hasattr(var, 'set'):
                    var.set(value)
        
        # Set TMDB ID if we have it
        if movie_data.get('id') and 'tmdb_id' in self.field_vars:
            self.field_vars['tmdb_id'].set(str(movie_data['id']))
        
        # Set rating label
        if hasattr(self, 'rating_label'):
            rating = movie_data.get('vote_average', 0)
            votes = movie_data.get('vote_count', 0)
            try:
                rating_val = float(rating) if rating else 0
                votes_val = int(votes) if votes else 0
                self.rating_label.configure(text=f"TMDB: {rating_val:.1f} | Votes: {votes_val}")
            except:
                pass
        
        # Set plot/overview in the textbox
        if hasattr(self, 'plot_text') and movie_data.get('overview'):
            self.plot_text.delete("1.0", "end")
            self.plot_text.insert("1.0", movie_data['overview'])
        
        # Set genres
        self.selected_genres = set(movie_data.get('genres', []))
        self._create_genre_chips()
        
        # Set tags
        self.selected_tags = set(movie_data.get('tags', []))
        
        # Set countries
        self.selected_countries = set(movie_data.get('countries', []))
        
        # Set studio - update the label
        if movie_data.get('studio'):
            self.selected_studios = {movie_data['studio']}
            if hasattr(self, 'studios_label'):
                self.studios_label.configure(text=movie_data['studio'])
        
        # Update stream info from NFO if available
        stream_details = movie_data.get('stream_details', {})
        print(f"Stream details from NFO: {stream_details}")
        
        # Check if stream_details has actual video info
        has_nfo_stream_info = stream_details and stream_details.get('video', {}).get('codec')
        
        if has_nfo_stream_info and hasattr(self, 'video_info_labels'):
            print("Using stream info from NFO")
            video_info = stream_details.get('video', {})
            
            # Update video info
            if video_info.get('codec'):
                self.video_info_labels.get('codec', ctk.CTkLabel(self)).configure(
                    text=video_info['codec'].upper()
                )
            
            if video_info.get('width') and video_info.get('height'):
                self.video_info_labels.get('resolution', ctk.CTkLabel(self)).configure(
                    text=f"{video_info['width']} x {video_info['height']}"
                )
            
            if video_info.get('aspect'):
                self.video_info_labels.get('aspect_ratio', ctk.CTkLabel(self)).configure(
                    text=video_info['aspect']
                )
            
            if video_info.get('scantype'):
                self.video_info_labels.get('scantype', ctk.CTkLabel(self)).configure(
                    text=video_info['scantype']
                )
            
            # Duration from stream details or runtime
            duration_secs = video_info.get('duration')
            if duration_secs:
                try:
                    secs = int(duration_secs)
                    hours = secs // 3600
                    mins = (secs % 3600) // 60
                    self.video_info_labels.get('duration', ctk.CTkLabel(self)).configure(
                        text=f"{hours}h {mins}m"
                    )
                except:
                    pass
            elif movie_data.get('runtime'):
                try:
                    runtime = int(movie_data['runtime'])
                    hours = runtime // 60
                    mins = runtime % 60
                    self.video_info_labels.get('duration', ctk.CTkLabel(self)).configure(
                        text=f"{hours}h {mins}m"
                    )
                except:
                    pass
            
            # Update audio tracks
            audio_tracks = stream_details.get('audio', [])
            if audio_tracks and hasattr(self, 'audio_frame'):
                for widget in self.audio_frame.winfo_children():
                    widget.destroy()
                
                for i, track in enumerate(audio_tracks):
                    lang = track.get('language', 'Unknown').upper()
                    codec = track.get('codec', '').upper()
                    channels = track.get('channels', '')
                    track_text = f"Track {i+1}: {lang} - {codec}"
                    if channels:
                        track_text += f" ({channels}ch)"
                    
                    ctk.CTkLabel(
                        self.audio_frame,
                        text=track_text,
                        text_color=ParagonTheme.TEXT_PRIMARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)
                    ).pack(padx=15, pady=5, anchor="w")
            
            # Update subtitles
            subtitles = stream_details.get('subtitles', [])
            if subtitles and hasattr(self, 'subs_frame'):
                for widget in self.subs_frame.winfo_children():
                    widget.destroy()
                
                for i, sub in enumerate(subtitles):
                    lang = sub.get('language', 'Unknown').upper()
                    ctk.CTkLabel(
                        self.subs_frame,
                        text=f"Subtitle {i+1}: {lang}",
                        text_color=ParagonTheme.TEXT_PRIMARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)
                    ).pack(padx=15, pady=5, anchor="w")
        
        # Fallback: use ffprobe stream_info if available
        elif self.stream_info and hasattr(self, 'video_info_labels'):
            print(f"Using stream info from ffprobe: {self.stream_info}")
            self._update_stream_display()
        
        # Last fallback: Update duration from runtime if no stream details
        elif movie_data.get('runtime') and hasattr(self, 'video_info_labels'):
            print("Using runtime from NFO for duration only")
            try:
                runtime = int(movie_data['runtime'])
                hours = runtime // 60
                mins = runtime % 60
                if 'duration' in self.video_info_labels:
                    self.video_info_labels['duration'].configure(text=f"{hours}h {mins}m")
            except:
                pass
        
        # Show in results list that data was loaded from NFO
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        loaded_label = ctk.CTkFrame(self.results_list, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        loaded_label.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkLabel(
            loaded_label, 
            text="📁 Loaded from NFO",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=ParagonTheme.SUCCESS
        ).pack(padx=10, pady=(8, 2))
        
        ctk.CTkLabel(
            loaded_label,
            text=movie_data.get('title', 'Unknown'),
            font=ctk.CTkFont(size=12),
            text_color=ParagonTheme.TEXT_PRIMARY
        ).pack(padx=10, pady=(0, 8))
        
        # Add a "Search Online" option
        ctk.CTkLabel(
            self.results_list,
            text="Search online to update:",
            font=ctk.CTkFont(size=11),
            text_color=ParagonTheme.TEXT_MUTED
        ).pack(pady=(10, 5))
    
    def _load_existing_artwork_previews(self):
        """Load existing artwork files as previews"""
        print(f"Loading artwork previews. Existing artwork: {self.existing_artwork}")
        
        def load_local_image(path: str, label, max_size: tuple, photo_attr: str, art_type: str):
            """Load a local image file and display it"""
            if not path:
                print(f"No path for {art_type}")
                return
            if not os.path.exists(path):
                print(f"File not found for {art_type}: {path}")
                return
            
            print(f"Loading {art_type} from: {path}")
            
            def load():
                try:
                    if HAS_PIL:
                        img = Image.open(path)
                        img.thumbnail(max_size, Image.Resampling.LANCZOS)
                        photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                        setattr(self, photo_attr, photo)
                        self.after(0, lambda: label.configure(image=photo, text=""))
                        print(f"Successfully loaded {art_type}")
                    else:
                        print("PIL not available for image loading")
                except Exception as e:
                    print(f"Error loading {art_type} preview: {e}")
            
            threading.Thread(target=load, daemon=True).start()
        
        # Load poster
        if self.existing_artwork.get('poster'):
            load_local_image(
                self.existing_artwork['poster'],
                self.poster_label,
                (120, 170),
                '_poster_photo',
                'poster'
            )
        
        # Load fanart
        if self.existing_artwork.get('fanart'):
            load_local_image(
                self.existing_artwork['fanart'],
                self.fanart_label,
                (260, 110),
                '_fanart_photo',
                'fanart'
            )
        
        # Load logo
        if self.existing_artwork.get('logo'):
            load_local_image(
                self.existing_artwork['logo'],
                self.logo_label,
                (260, 60),
                '_logo_photo',
                'logo'
            )
        
        # Load landscape
        if self.existing_artwork.get('landscape'):
            load_local_image(
                self.existing_artwork['landscape'],
                self.landscape_label,
                (260, 90),
                '_landscape_photo',
                'landscape'
            )
    
    def _extract_stream_info(self):
        """Extract stream info from video file using ffprobe if available"""
        if not self.current_file:
            return
        
        self.stream_info = {
            'video': {'codec': '', 'resolution': '', 'aspect': '', 'scantype': '', 'duration': ''},
            'audio': [],
            'subtitles': []
        }
        
        try:
            import subprocess
            cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-show_format', self.current_file]
            print(f"Running ffprobe on: {self.current_file}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                
                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        self.stream_info['video'] = {
                            'codec': stream.get('codec_name', '').upper(),
                            'resolution': f"{stream.get('width', '')} x {stream.get('height', '')}",
                            'aspect': str(round(stream.get('width', 0) / stream.get('height', 1), 3)) if stream.get('height') else '',
                            'scantype': 'Progressive' if stream.get('field_order', 'progressive') == 'progressive' else 'Interlaced',
                            'duration': ''
                        }
                    elif stream.get('codec_type') == 'audio':
                        lang = stream.get('tags', {}).get('language', 'und')
                        codec = stream.get('codec_name', '').upper()
                        channels = stream.get('channels', 2)
                        self.stream_info['audio'].append({'language': lang, 'codec': codec, 'channels': channels})
                    elif stream.get('codec_type') == 'subtitle':
                        lang = stream.get('tags', {}).get('language', 'und')
                        self.stream_info['subtitles'].append({'language': lang})
                
                duration_secs = float(data.get('format', {}).get('duration', 0))
                hours = int(duration_secs // 3600)
                mins = int((duration_secs % 3600) // 60)
                secs = int(duration_secs % 60)
                self.stream_info['video']['duration'] = f"{hours:02d}:{mins:02d}:{secs:02d}"
                print(f"ffprobe stream info: {self.stream_info}")
            else:
                print(f"ffprobe failed with return code: {result.returncode}")
                print(f"ffprobe stderr: {result.stderr}")
        except FileNotFoundError:
            print("ffprobe not found - stream info will not be available")
        except Exception as e:
            print(f"Could not extract stream info: {e}")
    
    def _create_ui(self):
        """Create the movie editor UI"""
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        main.pack(fill="both", expand=True, padx=4, pady=4)
        
        inner = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        self._create_header(inner)
        
        content = ctk.CTkFrame(inner, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        
        # Left side - Movie list (resizable with PanedWindow)
        # We'll use a frame with a drag handle for resizing
        self.left_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=250)
        self.left_panel.pack(side="left", fill="y", padx=(0, 10))
        self.left_panel.pack_propagate(False)
        
        # Store initial width for resize
        self._left_panel_width = 250
        self._resize_start_x = 0
        
        ParagonLabel(self.left_panel, text="SEARCH RESULTS", style="header").pack(anchor="w", padx=10, pady=(10, 5))
        
        self.results_list = ctk.CTkScrollableFrame(self.left_panel, fg_color=ParagonTheme.BG_DARK)
        self.results_list.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        
        ParagonLabel(self.results_list, text="Search for a movie", style="muted").pack(pady=20)
        
        # Resize handle on right edge of left panel
        resize_handle = ctk.CTkFrame(self.left_panel, fg_color=ParagonTheme.BORDER_GOLD, width=4, corner_radius=2)
        resize_handle.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")
        resize_handle.configure(cursor="sb_h_double_arrow")
        resize_handle.bind("<Button-1>", self._start_resize)
        resize_handle.bind("<B1-Motion>", self._do_resize)
        
        # Center - Tabs
        center_panel = ctk.CTkFrame(content, fg_color="transparent")
        center_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        self.tabs = ctk.CTkTabview(center_panel, fg_color=ParagonTheme.BG_SECONDARY,
                                   segmented_button_fg_color=ParagonTheme.BG_TERTIARY,
                                   segmented_button_selected_color=ParagonTheme.RED_PRIMARY,
                                   segmented_button_unselected_color=ParagonTheme.BG_TERTIARY)
        self.tabs.pack(fill="both", expand=True)
        
        self.tabs.add("Information")
        self.tabs.add("Extended")
        self.tabs.add("Stream Details")
        
        self._create_info_tab(self.tabs.tab("Information"))
        self._create_extended_tab(self.tabs.tab("Extended"))
        self._create_stream_tab(self.tabs.tab("Stream Details"))
        
        # Right side - Artwork
        right_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=300)
        right_panel.pack(side="right", fill="y")
        right_panel.pack_propagate(False)
        
        self._create_artwork_panel(right_panel)
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self.destroy, width=120).pack(side="left")
        ParagonButton(btn_frame, text="SAVE ALL", command=self._save_all, width=160).pack(side="right")
    
    def _start_resize(self, event):
        """Start resizing left panel"""
        self._resize_start_x = event.x_root
        self._left_panel_width = self.left_panel.winfo_width()
    
    def _do_resize(self, event):
        """Resize left panel"""
        delta = event.x_root - self._resize_start_x
        new_width = max(150, min(500, self._left_panel_width + delta))
        self.left_panel.configure(width=new_width)
    
    def _create_header(self, parent):
        # Title row with Bebas Neue font
        title_frame = ctk.CTkFrame(parent, fg_color="transparent")
        title_frame.pack(fill="x", padx=15, pady=(15, 5))
        
        # Big title in Bebas Neue
        title_label = ctk.CTkLabel(
            title_frame, 
            text="MOVIE EDITOR",
            font=ctk.CTkFont(family="Bebas Neue", size=48, weight="bold"),
            text_color=ParagonTheme.RED_LIGHT
        )
        title_label.pack(side="left")
        
        # Maximize button on the right
        max_btn = ctk.CTkButton(
            title_frame,
            text="⬜",
            width=40,
            height=40,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            command=self._toggle_maximize,
            font=ctk.CTkFont(size=20)
        )
        max_btn.pack(side="right", padx=5)
        
        # Search bar - centered
        search_container = ctk.CTkFrame(parent, fg_color="transparent")
        search_container.pack(fill="x", padx=15, pady=(5, 15))
        
        # Center the search frame
        search_frame = ctk.CTkFrame(search_container, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=8)
        search_frame.pack(anchor="center")
        
        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="Movie title...",
                                         fg_color="transparent", border_width=0, width=350,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL), height=45)
        self.search_entry.pack(side="left", padx=(15, 5), pady=10)
        self.search_entry.bind('<Return>', lambda e: self._search())
        
        self.year_entry = ctk.CTkEntry(search_frame, placeholder_text="Year",
                                       fg_color="transparent", border_width=0, width=100,
                                       font=ctk.CTkFont(size=self.FONT_NORMAL), height=45)
        self.year_entry.pack(side="left", padx=5, pady=10)
        
        ParagonButton(search_frame, text="SEARCH", command=self._search, width=120, height=45).pack(side="left", padx=(5, 15), pady=10)
    
    def _toggle_maximize(self):
        """Toggle window maximize state"""
        try:
            current_state = self.state()
            if current_state == 'zoomed' or current_state == 'maximized':
                self.state('normal')
            else:
                self.state('zoomed')
        except:
            # Fallback for systems that don't support 'zoomed'
            self.attributes('-fullscreen', not self.attributes('-fullscreen'))
    
    def _create_info_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        self._add_field(scroll, "Files", "files", readonly=True)
        
        id_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        id_frame.pack(fill="x", pady=4)
        
        ctk.CTkLabel(id_frame, text="IMDB ID", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['imdb_id'] = ctk.StringVar()
        ctk.CTkEntry(id_frame, textvariable=self.field_vars['imdb_id'], width=150,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", padx=(0, 20))
        
        ctk.CTkLabel(id_frame, text="TMDB ID", width=100, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['tmdb_id'] = ctk.StringVar()
        ctk.CTkEntry(id_frame, textvariable=self.field_vars['tmdb_id'], width=120,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left")
        
        self._add_field(scroll, "Name", "title")
        self._add_field(scroll, "Original Name", "original_title")
        self._add_field(scroll, "Sort Title", "sort_title")
        
        set_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        set_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(set_frame, text="Set", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['set'] = ctk.StringVar()
        ctk.CTkEntry(set_frame, textvariable=self.field_vars['set'],
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", fill="x", expand=True)
        
        self._add_field(scroll, "Tagline", "tagline")
        
        rating_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        rating_frame.pack(fill="x", pady=6)
        ctk.CTkLabel(rating_frame, text="Ratings", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        rating_info = ctk.CTkFrame(rating_frame, fg_color=ParagonTheme.BG_DARK, corner_radius=4)
        rating_info.pack(side="left", fill="x", expand=True)
        self.rating_label = ctk.CTkLabel(rating_info, text="TMDB: -- | Votes: --",
                                         text_color=ParagonTheme.TEXT_PRIMARY,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.rating_label.pack(padx=10, pady=8, anchor="w")
        
        release_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        release_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(release_frame, text="Released", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['release_date'] = ctk.StringVar()
        ctk.CTkEntry(release_frame, textvariable=self.field_vars['release_date'], width=130,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(release_frame, text="Runtime", width=80, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['runtime'] = ctk.StringVar()
        ctk.CTkEntry(release_frame, textvariable=self.field_vars['runtime'], width=100,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left")
        ctk.CTkLabel(release_frame, text="Minutes", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=5)
        
        self._add_field(scroll, "Director", "director")
        self._add_field(scroll, "Writer", "writer")
        
        cert_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        cert_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(cert_frame, text="Certification", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['certification'] = ctk.StringVar()
        ctk.CTkOptionMenu(cert_frame, variable=self.field_vars['certification'],
                         values=[""] + self.CERTIFICATIONS,
                         fg_color=ParagonTheme.BG_DARK,
                         button_color=ParagonTheme.RED_PRIMARY,
                         font=ctk.CTkFont(size=self.FONT_NORMAL),
                         height=36).pack(side="left")
        
        self._add_field(scroll, "Trailer", "trailer")
        
        plot_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        plot_frame.pack(fill="x", pady=6)
        ctk.CTkLabel(plot_frame, text="Plot", width=120, anchor="ne",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10), anchor="n")
        self.plot_text = ctk.CTkTextbox(plot_frame, height=120, fg_color=ParagonTheme.BG_DARK,
                                        font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.plot_text.pack(side="left", fill="x", expand=True)
    
    def _add_field(self, parent, label, key, readonly=False):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=4)
        ctk.CTkLabel(frame, text=label, width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars[key] = ctk.StringVar()
        entry = ctk.CTkEntry(frame, textvariable=self.field_vars[key],
                            fg_color=ParagonTheme.BG_DARK,
                            font=ctk.CTkFont(size=self.FONT_NORMAL),
                            height=36,
                            state="disabled" if readonly else "normal")
        entry.pack(side="left", fill="x", expand=True)
    
    def _create_extended_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        ParagonLabel(scroll, text="Genres", style="header").pack(anchor="w", pady=(0, 8))
        self.genres_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.genres_frame.pack(fill="x", pady=(0, 20))
        self._create_genre_chips()
        
        ParagonLabel(scroll, text="Studios", style="header").pack(anchor="w", pady=(0, 8))
        self.studios_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6, height=80)
        self.studios_frame.pack(fill="x", pady=(0, 15))
        self.studios_label = ctk.CTkLabel(self.studios_frame, text="No studios", 
                                          text_color=ParagonTheme.TEXT_SECONDARY,
                                          font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.studios_label.pack(padx=15, pady=15, anchor="w")
    
    def _create_genre_chips(self):
        for widget in self.genres_frame.winfo_children():
            widget.destroy()
        
        all_genres = self.get_all_genres()
        row_frame = None
        for i, genre in enumerate(all_genres):
            if i % 5 == 0:  # 5 per row for larger buttons
                row_frame = ctk.CTkFrame(self.genres_frame, fg_color="transparent")
                row_frame.pack(fill="x", padx=8, pady=4)
            
            is_selected = genre in self.selected_genres
            btn = ctk.CTkButton(
                row_frame, text=genre, height=36,
                fg_color=ParagonTheme.RED_PRIMARY if is_selected else ParagonTheme.BG_TERTIARY,
                hover_color=ParagonTheme.RED_LIGHT if is_selected else ParagonTheme.BG_HOVER,
                text_color=ParagonTheme.TEXT_PRIMARY,
                corner_radius=18,
                font=ctk.CTkFont(size=self.FONT_SMALL),
                command=lambda g=genre: self._toggle_genre(g)
            )
            btn.pack(side="left", padx=3, pady=3)
        
        # Add "+" button for custom genre on a new row
        add_row = ctk.CTkFrame(self.genres_frame, fg_color="transparent")
        add_row.pack(fill="x", padx=8, pady=8)
        
        self.custom_genre_entry = ctk.CTkEntry(
            add_row, width=200, height=36,
            placeholder_text="New genre...",
            fg_color=ParagonTheme.BG_DARK,
            border_color=ParagonTheme.BORDER_DARK,
            font=ctk.CTkFont(size=self.FONT_SMALL)
        )
        self.custom_genre_entry.pack(side="left", padx=3)
        self.custom_genre_entry.bind("<Return>", lambda e: self._add_custom_genre())
        
        ctk.CTkButton(
            add_row, text="+ ADD", height=36, width=80,
            fg_color=ParagonTheme.GOLD,
            hover_color=ParagonTheme.GOLD_LIGHT,
            text_color=ParagonTheme.BG_DARK,
            corner_radius=18,
            font=ctk.CTkFont(size=self.FONT_SMALL, weight="bold"),
            command=self._add_custom_genre
        ).pack(side="left", padx=3)
    
    def _add_custom_genre(self):
        """Add a custom genre"""
        genre = self.custom_genre_entry.get().strip()
        if not genre:
            return
        
        # Add to custom genres
        if self.add_custom_genre(genre):
            # Also select it
            self.selected_genres.add(genre)
            # Refresh the genre chips
            self._create_genre_chips()
            messagebox.showinfo("Genre Added", f"'{genre}' has been added and will be available for all movies/TV shows.")
        else:
            # Genre already exists, just select it
            # Find the proper case version
            for g in self.get_all_genres():
                if g.lower() == genre.lower():
                    self.selected_genres.add(g)
                    break
            self._create_genre_chips()
    
    def _toggle_genre(self, genre):
        if genre in self.selected_genres:
            self.selected_genres.remove(genre)
        else:
            self.selected_genres.add(genre)
        self._create_genre_chips()
    
    def _create_stream_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        ParagonLabel(scroll, text="Video", style="header").pack(anchor="w", pady=(0, 8))
        video_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        video_frame.pack(fill="x", pady=(0, 20))
        
        self.video_info_labels = {}
        for field in ["Codec", "Resolution", "Aspect Ratio", "Scantype", "Duration"]:
            row = ctk.CTkFrame(video_frame, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(row, text=field, width=140, anchor="w",
                        text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
            lbl = ctk.CTkLabel(row, text="--", anchor="w", text_color=ParagonTheme.TEXT_PRIMARY,
                              font=ctk.CTkFont(size=self.FONT_NORMAL))
            lbl.pack(side="left", fill="x", expand=True)
            self.video_info_labels[field.lower().replace(" ", "_")] = lbl
        
        ParagonLabel(scroll, text="Audio", style="header").pack(anchor="w", pady=(15, 8))
        self.audio_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.audio_frame.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(self.audio_frame, text="No audio tracks", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=15)
        
        ParagonLabel(scroll, text="Subtitles", style="header").pack(anchor="w", pady=(0, 8))
        self.subs_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.subs_frame.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(self.subs_frame, text="No subtitles", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=15)
    
    def _create_artwork_panel(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=5, pady=10)
        
        # Poster - clickable
        ctk.CTkLabel(scroll, text="Poster (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.poster_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=180, corner_radius=4,
                                         cursor="hand2")
        self.poster_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.poster_frame.pack_propagate(False)
        self.poster_label = ctk.CTkLabel(self.poster_frame, text="No Poster\n(Click to choose)", 
                                         text_color=ParagonTheme.TEXT_SECONDARY,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL), cursor="hand2")
        self.poster_label.pack(expand=True)
        self.poster_frame.bind("<Button-1>", lambda e: self._open_image_chooser("posters"))
        self.poster_label.bind("<Button-1>", lambda e: self._open_image_chooser("posters"))
        
        # Logo - clickable
        ctk.CTkLabel(scroll, text="Logo (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.logo_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=70, corner_radius=4,
                                       cursor="hand2")
        self.logo_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.logo_frame.pack_propagate(False)
        self.logo_label = ctk.CTkLabel(self.logo_frame, text="No Logo\n(Click to choose)", 
                                       text_color=ParagonTheme.TEXT_SECONDARY,
                                       font=ctk.CTkFont(size=self.FONT_NORMAL), cursor="hand2")
        self.logo_label.pack(expand=True)
        self.logo_frame.bind("<Button-1>", lambda e: self._open_image_chooser("logos"))
        self.logo_label.bind("<Button-1>", lambda e: self._open_image_chooser("logos"))
        
        # Fanart - clickable
        ctk.CTkLabel(scroll, text="Fanart (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.fanart_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=100, corner_radius=4,
                                         cursor="hand2")
        self.fanart_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.fanart_frame.pack_propagate(False)
        self.fanart_label = ctk.CTkLabel(self.fanart_frame, text="No Fanart\n(Click to choose)", 
                                         text_color=ParagonTheme.TEXT_SECONDARY,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL), cursor="hand2")
        self.fanart_label.pack(expand=True)
        self.fanart_frame.bind("<Button-1>", lambda e: self._open_image_chooser("backdrops"))
        self.fanart_label.bind("<Button-1>", lambda e: self._open_image_chooser("backdrops"))
        
        # Landscape - clickable (uses backdrops but saves as landscape.jpg)
        ctk.CTkLabel(scroll, text="Landscape (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.landscape_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=100, corner_radius=4,
                                            cursor="hand2")
        self.landscape_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.landscape_frame.pack_propagate(False)
        self.landscape_label = ctk.CTkLabel(self.landscape_frame, text="No Landscape\n(Click to choose)", 
                                            text_color=ParagonTheme.TEXT_SECONDARY,
                                            font=ctk.CTkFont(size=self.FONT_NORMAL), cursor="hand2")
        self.landscape_label.pack(expand=True)
        self.landscape_frame.bind("<Button-1>", lambda e: self._open_image_chooser("landscape"))
        self.landscape_label.bind("<Button-1>", lambda e: self._open_image_chooser("landscape"))
        
        ParagonLabel(scroll, text="Download", style="header").pack(anchor="w", padx=8, pady=(15, 8))
        opts = ctk.CTkFrame(scroll, fg_color="transparent")
        opts.pack(fill="x", padx=8)
        
        self.dl_poster = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts, text="Poster", variable=self.dl_poster, fg_color=ParagonTheme.RED_PRIMARY,
                       font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", pady=3)
        self.dl_fanart = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts, text="Fanart", variable=self.dl_fanart, fg_color=ParagonTheme.RED_PRIMARY,
                       font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", pady=3)
        self.dl_logo = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts, text="Logo", variable=self.dl_logo, fg_color=ParagonTheme.RED_PRIMARY,
                       font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", pady=3)
        self.dl_landscape = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts, text="Landscape", variable=self.dl_landscape, fg_color=ParagonTheme.RED_PRIMARY,
                       font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", pady=3)
        self.create_nfo = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts, text="Create NFO", variable=self.create_nfo, fg_color=ParagonTheme.RED_PRIMARY,
                       font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", pady=(12, 3))
    
    def _open_image_chooser(self, image_type: str):
        """Open image chooser dialog"""
        if not self.movie_details:
            messagebox.showinfo("Select Movie", "Please search and select a movie first")
            return
        
        movie_id = self.movie_details.get('id')
        movie_title = self.movie_details.get('title', '')
        
        # For landscape, use 'thumbs' which will work with Fanart.tv
        # TMDB doesn't have thumbs, so it will use backdrops as fallback
        api_type = 'thumbs' if image_type == 'landscape' else image_type
        
        dialog = ImageChooserDialog(self, movie_id, api_type, movie_title, display_type=image_type)
        self.wait_window(dialog)
        
        selected_path = dialog.get_selected_path()
        selected_source = dialog.selected_source
        
        if selected_path:
            # Store both path and source for downloading later
            if image_type == 'posters':
                self.movie_details['poster_path'] = selected_path
                self.movie_details['poster_source'] = selected_source
                self._update_poster_preview(selected_path, selected_source)
            elif image_type == 'backdrops':
                self.movie_details['backdrop_path'] = selected_path
                self.movie_details['backdrop_source'] = selected_source
                self._update_fanart_preview(selected_path, selected_source)
            elif image_type == 'logos':
                self.movie_details['logo_path'] = selected_path
                self.movie_details['logo_source'] = selected_source
                self._update_logo_preview(selected_path, selected_source)
            elif image_type == 'landscape':
                self.movie_details['landscape_path'] = selected_path
                self.movie_details['landscape_source'] = selected_source
                self._update_landscape_preview(selected_path, selected_source)
    
    def _update_poster_preview(self, path: str, source: str = "tmdb"):
        """Update poster preview thumbnail"""
        def load():
            if source == "fanart":
                data = FanartTVAPI.download_image(path)
            else:
                data = TMDBAPI.download_image(path, 'w342')
            if data and HAS_PIL:
                try:
                    img = Image.open(io.BytesIO(data))
                    img.thumbnail((120, 170), Image.Resampling.LANCZOS)
                    photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                    self._poster_photo = photo
                    self.after(0, lambda: self.poster_label.configure(image=photo, text=""))
                except Exception as e:
                    print(f"Error updating poster preview: {e}")
        threading.Thread(target=load, daemon=True).start()
    
    def _update_fanart_preview(self, path: str, source: str = "tmdb"):
        """Update fanart preview thumbnail"""
        def load():
            if source == "fanart":
                data = FanartTVAPI.download_image(path)
            else:
                data = TMDBAPI.download_image(path, 'w500')
            if data and HAS_PIL:
                try:
                    img = Image.open(io.BytesIO(data))
                    img.thumbnail((260, 110), Image.Resampling.LANCZOS)
                    photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                    self._fanart_photo = photo
                    self.after(0, lambda: self.fanart_label.configure(image=photo, text=""))
                except Exception as e:
                    print(f"Error updating fanart preview: {e}")
        threading.Thread(target=load, daemon=True).start()
    
    def _update_logo_preview(self, path: str, source: str = "tmdb"):
        """Update logo preview thumbnail"""
        def load():
            if source == "fanart":
                data = FanartTVAPI.download_image(path)
            else:
                data = TMDBAPI.download_image(path, 'w300')
            if data and HAS_PIL:
                try:
                    img = Image.open(io.BytesIO(data))
                    img.thumbnail((260, 60), Image.Resampling.LANCZOS)
                    photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                    self._logo_photo = photo
                    self.after(0, lambda: self.logo_label.configure(image=photo, text=""))
                except Exception as e:
                    print(f"Error updating logo preview: {e}")
        threading.Thread(target=load, daemon=True).start()
    
    def _update_landscape_preview(self, path: str, source: str = "tmdb"):
        """Update landscape preview thumbnail"""
        def load():
            if source == "fanart":
                data = FanartTVAPI.download_image(path)
            else:
                data = TMDBAPI.download_image(path, 'w500')
            if data and HAS_PIL:
                try:
                    img = Image.open(io.BytesIO(data))
                    img.thumbnail((260, 90), Image.Resampling.LANCZOS)
                    photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                    self._landscape_photo = photo
                    self.after(0, lambda: self.landscape_label.configure(image=photo, text=""))
                except Exception as e:
                    print(f"Error updating landscape preview: {e}")
        threading.Thread(target=load, daemon=True).start()
    
    def _search(self):
        query = self.search_entry.get().strip()
        year = self.year_entry.get().strip()
        if not query:
            return
        
        for widget in self.results_list.winfo_children():
            widget.destroy()
        ParagonLabel(self.results_list, text="Searching...", style="muted").pack(pady=20)
        self.update()
        
        def do_search():
            results = TMDBAPI.search_movie(query, year if year else None)
            self.after(0, lambda: self._display_results(results))
        
        threading.Thread(target=do_search, daemon=True).start()
    
    def _display_results(self, results):
        for widget in self.results_list.winfo_children():
            widget.destroy()
        self.search_results = results
        if not results:
            ParagonLabel(self.results_list, text="No movies found", style="muted").pack(pady=20)
            return
        for i, movie in enumerate(results):
            self._add_result_row(i, movie)
    
    def _add_result_row(self, index, movie):
        frame = ctk.CTkFrame(self.results_list,
            fg_color=ParagonTheme.BG_TERTIARY if index % 2 == 0 else ParagonTheme.BG_SECONDARY,
            corner_radius=4)
        frame.pack(fill="x", pady=2)
        frame.bind("<Button-1>", lambda e, idx=index: self._select_movie(idx))
        
        title_text = movie.get('title', 'Unknown')[:30]
        if movie.get('year'):
            title_text += f" ({movie['year']})"
        lbl = ctk.CTkLabel(frame, text=title_text, anchor="w", font=ctk.CTkFont(size=self.FONT_SMALL),
                          text_color=ParagonTheme.TEXT_PRIMARY)
        lbl.pack(fill="x", padx=10, pady=10)
        lbl.bind("<Button-1>", lambda e, idx=index: self._select_movie(idx))
    
    def _select_movie(self, index):
        if index >= len(self.search_results):
            return
        self.selected_movie = self.search_results[index]
        movie_id = self.selected_movie.get('id')
        
        for i, widget in enumerate(self.results_list.winfo_children()):
            if isinstance(widget, ctk.CTkFrame):
                widget.configure(fg_color=ParagonTheme.RED_DARK if i == index else
                               (ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY))
        
        def fetch_details():
            details = TMDBAPI.get_movie_details(movie_id)
            poster = None
            if details and details.get('poster_path'):
                poster = TMDBAPI.download_image(details['poster_path'], 'w342')
            self.after(0, lambda: self._populate_fields(details, poster))
        
        threading.Thread(target=fetch_details, daemon=True).start()
    
    def _populate_fields(self, details, poster_data):
        if not details:
            return
        self.movie_details = details
        
        self.field_vars['files'].set(self.current_file or "")
        self.field_vars['imdb_id'].set(details.get('imdb_id', ''))
        self.field_vars['tmdb_id'].set(str(details.get('id', '')))
        self.field_vars['title'].set(details.get('title', ''))
        self.field_vars['original_title'].set(details.get('original_title', ''))
        self.field_vars['sort_title'].set(details.get('title', ''))
        self.field_vars['tagline'].set(details.get('tagline', ''))
        self.field_vars['release_date'].set(details.get('release_date', ''))
        self.field_vars['runtime'].set(str(details.get('runtime', '')))
        self.field_vars['director'].set(details.get('director', ''))
        self.field_vars['certification'].set(details.get('certification', ''))
        self.field_vars['trailer'].set('')
        
        rating = details.get('vote_average', 0)
        votes = details.get('vote_count', 0)
        self.rating_label.configure(text=f"TMDB: {rating:.1f} | Votes: {votes}")
        
        self.plot_text.delete("1.0", "end")
        self.plot_text.insert("1.0", details.get('overview', ''))
        
        self.selected_genres = set(details.get('genres', []))
        self._create_genre_chips()
        
        studios = details.get('production_companies', [])
        if studios:
            self.studios_label.configure(text=", ".join(studios[:5]))
        
        self._update_stream_display()
        
        if poster_data and HAS_PIL:
            try:
                img = Image.open(io.BytesIO(poster_data))
                img.thumbnail((120, 180), Image.Resampling.LANCZOS)
                self._poster_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(120, 140))
                self.poster_label.configure(image=self._poster_photo, text="")
            except:
                pass
    
    def _update_stream_display(self):
        if not self.stream_info:
            return
        
        video = self.stream_info.get('video', {})
        if 'codec' in self.video_info_labels:
            self.video_info_labels['codec'].configure(text=video.get('codec', '--'))
        if 'resolution' in self.video_info_labels:
            self.video_info_labels['resolution'].configure(text=video.get('resolution', '--'))
        if 'aspect_ratio' in self.video_info_labels:
            self.video_info_labels['aspect_ratio'].configure(text=video.get('aspect', '--'))
        if 'scantype' in self.video_info_labels:
            self.video_info_labels['scantype'].configure(text=video.get('scantype', '--'))
        if 'duration' in self.video_info_labels:
            self.video_info_labels['duration'].configure(text=video.get('duration', '--'))
        
        for widget in self.audio_frame.winfo_children():
            widget.destroy()
        audio_tracks = self.stream_info.get('audio', [])
        if audio_tracks:
            for i, track in enumerate(audio_tracks):
                row = ctk.CTkFrame(self.audio_frame, fg_color="transparent")
                row.pack(fill="x", padx=15, pady=4)
                ctk.CTkLabel(row, text=f"Track {i+1}", width=80, text_color=ParagonTheme.TEXT_SECONDARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
                ctk.CTkLabel(row, text=track.get('language', 'und'), text_color=ParagonTheme.TEXT_PRIMARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=15)
                ctk.CTkLabel(row, text=track.get('codec', ''), text_color=ParagonTheme.TEXT_PRIMARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=15)
        else:
            ctk.CTkLabel(self.audio_frame, text="No audio tracks", text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=10)
        
        for widget in self.subs_frame.winfo_children():
            widget.destroy()
        sub_tracks = self.stream_info.get('subtitles', [])
        if sub_tracks:
            for i, track in enumerate(sub_tracks):
                row = ctk.CTkFrame(self.subs_frame, fg_color="transparent")
                row.pack(fill="x", padx=15, pady=4)
                ctk.CTkLabel(row, text=f"Track {i+1}", width=80, text_color=ParagonTheme.TEXT_SECONDARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
                ctk.CTkLabel(row, text=track.get('language', 'und'), text_color=ParagonTheme.TEXT_PRIMARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=15)
        else:
            ctk.CTkLabel(self.subs_frame, text="No subtitles", text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=10)
    
    def _save_all(self):
        if not self.movie_details:
            messagebox.showinfo("Select Movie", "Please search and select a movie first")
            return
        
        self.movie_details['title'] = self.field_vars['title'].get()
        self.movie_details['original_title'] = self.field_vars['original_title'].get()
        self.movie_details['tagline'] = self.field_vars['tagline'].get()
        self.movie_details['release_date'] = self.field_vars['release_date'].get()
        self.movie_details['runtime'] = int(self.field_vars['runtime'].get() or 0)
        self.movie_details['director'] = self.field_vars['director'].get()
        self.movie_details['certification'] = self.field_vars['certification'].get()
        self.movie_details['overview'] = self.plot_text.get("1.0", "end").strip()
        self.movie_details['genres'] = list(self.selected_genres)
        
        success = 0
        errors = []
        
        for filepath in self.files:
            try:
                folder = os.path.dirname(filepath)
                basename = os.path.basename(filepath)
                name, ext = os.path.splitext(basename)
                
                if self.create_nfo.get():
                    nfo_content = NFOGenerator.generate_movie_nfo(self.movie_details)
                    with open(os.path.join(folder, f"{name}.nfo"), 'w', encoding='utf-8') as f:
                        f.write(nfo_content)
                
                if self.dl_poster.get() and self.movie_details.get('poster_path'):
                    data = TMDBAPI.download_image(self.movie_details['poster_path'], 'original')
                    if data:
                        with open(os.path.join(folder, "poster.jpg"), 'wb') as f:
                            f.write(data)
                
                if self.dl_fanart.get() and self.movie_details.get('backdrop_path'):
                    data = TMDBAPI.download_image(self.movie_details['backdrop_path'], 'original')
                    if data:
                        with open(os.path.join(folder, "fanart.jpg"), 'wb') as f:
                            f.write(data)
                
                if self.dl_logo.get() and self.movie_details.get('logo_path'):
                    data = TMDBAPI.download_image(self.movie_details['logo_path'], 'original')
                    if data:
                        with open(os.path.join(folder, "logo.png"), 'wb') as f:
                            f.write(data)
                
                if self.dl_landscape.get():
                    path = self.movie_details.get('landscape_path') or self.movie_details.get('backdrop_path')
                    if path:
                        data = TMDBAPI.download_image(path, 'original')
                        if data:
                            with open(os.path.join(folder, "landscape.jpg"), 'wb') as f:
                                f.write(data)
                
                success += 1
            except Exception as e:
                errors.append(f"{os.path.basename(filepath)}: {e}")
        
        if errors:
            messagebox.showwarning("Complete", f"Saved {success} file(s).\n\nErrors:\n" + "\n".join(errors[:5]))
        else:
            messagebox.showinfo("Success", f"Successfully saved {success} file(s)!")
        
        self.destroy()


class TVScraperDialog(ctk.CTkToplevel):
    """MediaElch-style TV show scraper dialog"""
    
    def __init__(self, master, files: List[str]):
        super().__init__(master)
        
        self.files = files
        self.current_file = files[0] if files else None
        self.search_results = []
        self.selected_show = None
        self.show_details = None
        self.season_data = {}
        self.poster_data = None
        self._poster_photo = None
        self._fanart_photo = None
        self._logo_photo = None
        self._landscape_photo = None
        self.existing_artwork = {}
        
        self.title("📺 TV Show Scraper")
        self.geometry("1200x800")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        self._create_ui()
        
        # Try to load existing NFO and artwork first
        if files:
            loaded = self._load_existing_data()
            
            # If no existing data, auto-parse first file
            if not loaded:
                parsed = MediaFileParser.parse_tv_episode(os.path.basename(files[0]))
                if parsed.get('show'):
                    self.search_entry.insert(0, parsed['show'])
        
        self.after(50, lambda: self.grab_set() if self.winfo_exists() else None)
    
    def _load_existing_data(self) -> bool:
        """Load existing tvshow.nfo and artwork. Returns True if NFO was found."""
        if not self.current_file:
            return False
        
        folder = os.path.dirname(self.current_file)
        print(f"Looking for TV show NFO and artwork in: {folder}")
        
        # Find existing tvshow.nfo
        nfo_path = NFOParser.find_tvshow_nfo(self.current_file)
        
        # Find existing artwork
        self.existing_artwork = NFOParser.find_tvshow_artwork(self.current_file)
        
        if nfo_path:
            print(f"Found existing tvshow.nfo: {nfo_path}")
            show_data = NFOParser.parse_tvshow_nfo(nfo_path)
            
            if show_data and show_data.get('title'):
                # Store show details
                self.show_details = show_data
                
                # Populate the UI with the loaded data
                self._populate_from_nfo(show_data)
                
                # Load existing artwork previews
                self._load_existing_artwork_previews()
                
                return True
        
        # Even if no NFO, load artwork previews if they exist
        if any(self.existing_artwork.values()):
            print("No tvshow.nfo found, but loading existing artwork")
            self._load_existing_artwork_previews()
        
        return False
    
    def _populate_from_nfo(self, show_data: Dict):
        """Populate the editor UI with data from tvshow.nfo"""
        # Fill in search field with show name
        if show_data.get('title'):
            self.search_entry.delete(0, 'end')
            self.search_entry.insert(0, show_data['title'])
        
        # Update show info display
        self.show_title_label.configure(text=show_data.get('title', 'Unknown'))
        
        # Build info text
        info_parts = []
        if show_data.get('year'):
            info_parts.append(show_data['year'])
        if show_data.get('premiered'):
            info_parts.append(f"Premiered: {show_data['premiered']}")
        if show_data.get('certification'):
            info_parts.append(show_data['certification'])
        
        self.show_info_label.configure(text=" | ".join(info_parts) if info_parts else "")
        
        if show_data.get('status'):
            self.show_status_label.configure(text=f"Status: {show_data['status']}")
        
        # Show in results list that data was loaded from NFO
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        loaded_label = ctk.CTkFrame(self.results_list, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        loaded_label.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkLabel(
            loaded_label, 
            text="📁 Loaded from NFO",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=ParagonTheme.SUCCESS
        ).pack(padx=10, pady=(8, 2))
        
        ctk.CTkLabel(
            loaded_label,
            text=show_data.get('title', 'Unknown'),
            font=ctk.CTkFont(size=12),
            text_color=ParagonTheme.TEXT_PRIMARY
        ).pack(padx=10, pady=(0, 8))
        
        # Add a "Search Online" option
        ctk.CTkLabel(
            self.results_list,
            text="Search online to update:",
            font=ctk.CTkFont(size=11),
            text_color=ParagonTheme.TEXT_MUTED
        ).pack(pady=(10, 5))
    
    def _load_existing_artwork_previews(self):
        """Load existing artwork files as previews"""
        print(f"Loading TV artwork previews. Existing artwork: {self.existing_artwork}")
        
        def load_local_image(path: str, label, max_size: tuple, photo_attr: str, art_type: str):
            """Load a local image file and display it"""
            if not path:
                return
            if not os.path.exists(path):
                print(f"File not found for {art_type}: {path}")
                return
            
            print(f"Loading {art_type} from: {path}")
            
            def load():
                try:
                    if HAS_PIL:
                        img = Image.open(path)
                        img.thumbnail(max_size, Image.Resampling.LANCZOS)
                        photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                        setattr(self, photo_attr, photo)
                        self.after(0, lambda: label.configure(image=photo, text=""))
                        print(f"Successfully loaded {art_type}")
                except Exception as e:
                    print(f"Error loading {art_type} preview: {e}")
            
            threading.Thread(target=load, daemon=True).start()
        
        # Load poster
        if self.existing_artwork.get('poster'):
            load_local_image(
                self.existing_artwork['poster'],
                self.poster_label,
                (100, 150),
                '_poster_photo',
                'poster'
            )
    
    def _create_ui(self):
        """Create the TV scraper UI"""
        # Main container with gold border
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        main.pack(fill="both", expand=True, padx=4, pady=4)
        
        inner = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Header
        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 10))
        
        ParagonLabel(header, text="📺 TV SHOW SCRAPER", style="title").pack(side="left")
        ParagonLabel(header, text=f"{len(self.files)} file(s)", style="muted").pack(side="right")
        
        # Search section
        search_frame = ctk.CTkFrame(inner, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        search_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        search_inner = ctk.CTkFrame(search_frame, fg_color="transparent")
        search_inner.pack(fill="x", padx=15, pady=12)
        
        # Show title
        title_frame = ctk.CTkFrame(search_inner, fg_color="transparent")
        title_frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ParagonLabel(title_frame, text="Show Name:", style="muted").pack(anchor="w")
        self.search_entry = ctk.CTkEntry(
            title_frame, fg_color=ParagonTheme.BG_TERTIARY,
            border_color=ParagonTheme.BORDER_DARK, font=ctk.CTkFont(size=15), height=38
        )
        self.search_entry.pack(fill="x")
        self.search_entry.bind('<Return>', lambda e: self._search())
        
        # Search button
        btn_frame = ctk.CTkFrame(search_inner, fg_color="transparent")
        btn_frame.pack(side="left")
        ParagonLabel(btn_frame, text=" ", style="muted").pack()
        ParagonButton(btn_frame, text="🔍 SEARCH", command=self._search, width=120, height=38).pack()
        
        # Content area - three panels
        content = ctk.CTkFrame(inner, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        
        # Left panel - Search results
        left_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=280)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)
        
        ParagonLabel(left_panel, text="SHOWS", style="header").pack(anchor="w", padx=15, pady=(10, 5))
        
        self.results_list = ctk.CTkScrollableFrame(left_panel, fg_color=ParagonTheme.BG_DARK)
        self.results_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        ParagonLabel(self.results_list, text="Search for a show", style="muted").pack(pady=20)
        
        # Middle panel - Show info and seasons
        middle_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=350)
        middle_panel.pack(side="left", fill="y", padx=(0, 10))
        middle_panel.pack_propagate(False)
        
        # Show info
        info_frame = ctk.CTkFrame(middle_panel, fg_color="transparent")
        info_frame.pack(fill="x", padx=15, pady=10)
        
        self.poster_frame = ctk.CTkFrame(info_frame, fg_color=ParagonTheme.BG_DARK, width=100, height=150, corner_radius=4)
        self.poster_frame.pack(side="left", padx=(0, 10))
        self.poster_frame.pack_propagate(False)
        
        self.poster_label = ctk.CTkLabel(self.poster_frame, text="No\nPoster", text_color=ParagonTheme.TEXT_SECONDARY)
        self.poster_label.pack(expand=True)
        
        info_text = ctk.CTkFrame(info_frame, fg_color="transparent")
        info_text.pack(side="left", fill="both", expand=True)
        
        self.show_title_label = ParagonLabel(info_text, text="Select a show", style="header")
        self.show_title_label.pack(anchor="w")
        
        self.show_info_label = ParagonLabel(info_text, text="", style="muted")
        self.show_info_label.pack(anchor="w")
        
        self.show_status_label = ParagonLabel(info_text, text="", style="muted")
        self.show_status_label.pack(anchor="w")
        
        # Season list
        ParagonLabel(middle_panel, text="SEASONS", style="header").pack(anchor="w", padx=15, pady=(5, 5))
        
        self.season_list = ctk.CTkScrollableFrame(middle_panel, fg_color=ParagonTheme.BG_DARK, height=200)
        self.season_list.pack(fill="x", padx=10, pady=(0, 10))
        
        ParagonLabel(self.season_list, text="Select a show first", style="muted").pack(pady=10)
        
        # Right panel - Episode matching
        right_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        right_panel.pack(side="left", fill="both", expand=True)
        
        ParagonLabel(right_panel, text="FILE ↔ EPISODE MATCHING", style="header").pack(anchor="w", padx=15, pady=(10, 5))
        
        # Episode matching list
        self.match_list = ctk.CTkScrollableFrame(right_panel, fg_color=ParagonTheme.BG_DARK)
        self.match_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        ParagonLabel(self.match_list, text="Select a show and season", style="muted").pack(pady=20)
        
        # Options
        options_frame = ctk.CTkFrame(inner, fg_color="transparent")
        options_frame.pack(fill="x", padx=20, pady=(0, 5))
        
        self.download_poster = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame, text="Download poster",
            variable=self.download_poster,
            fg_color=ParagonTheme.RED_PRIMARY
        ).pack(side="left", padx=(0, 15))
        
        self.create_nfo = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame, text="Create NFO files",
            variable=self.create_nfo,
            fg_color=ParagonTheme.RED_PRIMARY
        ).pack(side="left", padx=(0, 15))
        
        self.rename_files = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options_frame, text="Rename files",
            variable=self.rename_files,
            fg_color=ParagonTheme.RED_PRIMARY
        ).pack(side="left")
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(5, 15))
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self.destroy, width=100).pack(side="left")
        
        ParagonSecondaryButton(
            btn_frame, text="🔄 AUTO-MATCH",
            command=self._auto_match, width=130
        ).pack(side="left", padx=15)
        
        ParagonButton(btn_frame, text="✓ APPLY TO FILES", command=self._apply, width=160).pack(side="right")
    
    def _search(self):
        """Search for TV shows"""
        query = self.search_entry.get().strip()
        
        if not query:
            messagebox.showinfo("Search", "Please enter a show name")
            return
        
        # Clear results
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        ParagonLabel(self.results_list, text="Searching...", style="muted").pack(pady=20)
        self.update()
        
        def do_search():
            results = TMDBAPI.search_tv(query)
            self.after(0, lambda: self._display_results(results))
        
        threading.Thread(target=do_search, daemon=True).start()
    
    def _display_results(self, results: List[Dict]):
        """Display search results"""
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        self.search_results = results
        
        if not results:
            ParagonLabel(self.results_list, text="No shows found", style="muted").pack(pady=20)
            return
        
        for i, show in enumerate(results):
            self._add_result_row(i, show)
    
    def _add_result_row(self, index: int, show: Dict):
        """Add a show result row"""
        frame = ctk.CTkFrame(
            self.results_list,
            fg_color=ParagonTheme.BG_TERTIARY if index % 2 == 0 else ParagonTheme.BG_SECONDARY,
            corner_radius=4
        )
        frame.pack(fill="x", pady=2)
        frame.bind("<Button-1>", lambda e, idx=index: self._select_show(idx))
        
        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="x", padx=10, pady=6)
        content.bind("<Button-1>", lambda e, idx=index: self._select_show(idx))
        
        title_text = show.get('title', 'Unknown')
        if show.get('year'):
            title_text += f" ({show['year']})"
        
        title_lbl = ctk.CTkLabel(
            content, text=title_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=ParagonTheme.TEXT_PRIMARY, anchor="w"
        )
        title_lbl.pack(fill="x")
        title_lbl.bind("<Button-1>", lambda e, idx=index: self._select_show(idx))
    
    def _select_show(self, index: int):
        """Select a show and load details"""
        if index >= len(self.search_results):
            return
        
        self.selected_show = self.search_results[index]
        
        # Highlight selected
        for i, widget in enumerate(self.results_list.winfo_children()):
            if isinstance(widget, ctk.CTkFrame):
                widget.configure(fg_color=ParagonTheme.RED_DARK if i == index else 
                               (ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY))
        
        # Update basic info
        self.show_title_label.configure(text=self.selected_show.get('title', 'Unknown'))
        
        # Fetch full details
        show_id = self.selected_show.get('id')
        
        def fetch_details():
            details = TMDBAPI.get_tv_details(show_id)
            poster = None
            if details and details.get('poster_path'):
                poster = TMDBAPI.download_image(details['poster_path'], 'w342')
            self.after(0, lambda: self._display_show_details(details, poster))
        
        threading.Thread(target=fetch_details, daemon=True).start()
    
    def _display_show_details(self, details: Optional[Dict], poster_data: Optional[bytes]):
        """Display show details and seasons"""
        if not details:
            return
        
        self.show_details = details
        self.poster_data = poster_data
        
        # Update labels
        self.show_title_label.configure(text=details.get('title', 'Unknown'))
        
        info_text = f"{details.get('year', 'N/A')} | {details.get('number_of_seasons', 0)} seasons | {details.get('number_of_episodes', 0)} episodes"
        self.show_info_label.configure(text=info_text)
        
        status = details.get('status', '')
        rating = details.get('vote_average', 0)
        self.show_status_label.configure(text=f"★ {rating:.1f} | {status}")
        
        # Poster
        if poster_data and HAS_PIL:
            try:
                img = Image.open(io.BytesIO(poster_data))
                img.thumbnail((95, 145), Image.Resampling.LANCZOS)
                self._poster_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(95, 145))
                self.poster_label.configure(image=self._poster_photo, text="")
            except:
                pass
        
        # Season list
        for widget in self.season_list.winfo_children():
            widget.destroy()
        
        for season in details.get('seasons', []):
            self._add_season_row(season)
    
    def _add_season_row(self, season: Dict):
        """Add a season row"""
        frame = ctk.CTkFrame(self.season_list, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=4)
        frame.pack(fill="x", pady=2)
        
        season_num = season.get('season_number', 0)
        ep_count = season.get('episode_count', 0)
        
        btn = ctk.CTkButton(
            frame,
            text=f"Season {season_num} ({ep_count} eps)",
            fg_color="transparent",
            hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_PRIMARY,
            anchor="w",
            command=lambda s=season_num: self._load_season(s)
        )
        btn.pack(fill="x", padx=5, pady=2)
    
    def _load_season(self, season_number: int):
        """Load season episodes and set up matching"""
        if not self.show_details:
            return
        
        show_id = self.show_details.get('id')
        
        # Clear match list
        for widget in self.match_list.winfo_children():
            widget.destroy()
        
        ParagonLabel(self.match_list, text="Loading episodes...", style="muted").pack(pady=20)
        self.update()
        
        def fetch_season():
            season_data = TMDBAPI.get_tv_season(show_id, season_number)
            self.after(0, lambda: self._display_episode_matching(season_data, season_number))
        
        threading.Thread(target=fetch_season, daemon=True).start()
    
    def _display_episode_matching(self, season_data: Optional[Dict], season_number: int):
        """Display episode matching interface"""
        for widget in self.match_list.winfo_children():
            widget.destroy()
        
        if not season_data:
            ParagonLabel(self.match_list, text="Could not load season", style="muted").pack(pady=20)
            return
        
        self.season_data[season_number] = season_data
        self.current_season = season_number
        self.episode_vars = {}
        
        episodes = season_data.get('episodes', [])
        
        # Header
        header = ctk.CTkFrame(self.match_list, fg_color=ParagonTheme.BG_TERTIARY, height=30)
        header.pack(fill="x", pady=(0, 5))
        header.pack_propagate(False)
        
        ctk.CTkLabel(header, text="Ep", width=30, font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=ParagonTheme.GOLD).pack(side="left", padx=5)
        ctk.CTkLabel(header, text="Episode Title", width=200, font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=ParagonTheme.GOLD, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(header, text="Your File", font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=ParagonTheme.GOLD, anchor="w").pack(side="left", padx=5)
        
        for ep in episodes:
            self._add_episode_match_row(ep, season_number)
        
        # Auto-match
        self._auto_match()
    
    def _add_episode_match_row(self, episode: Dict, season_number: int):
        """Add an episode matching row"""
        ep_num = episode.get('episode_number', 0)
        
        frame = ctk.CTkFrame(self.match_list, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=4, height=35)
        frame.pack(fill="x", pady=1)
        frame.pack_propagate(False)
        
        # Episode number
        ctk.CTkLabel(frame, text=str(ep_num), width=30, font=ctk.CTkFont(size=11),
                    text_color=ParagonTheme.GOLD).pack(side="left", padx=5)
        
        # Episode title
        title = episode.get('name', 'Unknown')[:30]
        ctk.CTkLabel(frame, text=title, width=200, font=ctk.CTkFont(size=11),
                    text_color=ParagonTheme.TEXT_PRIMARY, anchor="w").pack(side="left", padx=5)
        
        # File dropdown
        file_options = ["(not matched)"] + [os.path.basename(f) for f in self.files]
        
        file_var = ctk.StringVar(value="(not matched)")
        dropdown = ctk.CTkOptionMenu(
            frame, values=file_options, variable=file_var,
            fg_color=ParagonTheme.BG_DARK, button_color=ParagonTheme.RED_PRIMARY,
            button_hover_color=ParagonTheme.RED_LIGHT,
            font=ctk.CTkFont(size=10), width=250
        )
        dropdown.pack(side="left", padx=5)
        
        self.episode_vars[(season_number, ep_num)] = (file_var, episode)
    
    def _auto_match(self):
        """Auto-match files to episodes"""
        if not hasattr(self, 'episode_vars') or not self.episode_vars:
            return
        
        used_files = set()
        
        for (season_num, ep_num), (file_var, episode) in self.episode_vars.items():
            # Try to find matching file
            for filepath in self.files:
                if filepath in used_files:
                    continue
                
                parsed = MediaFileParser.parse_tv_episode(os.path.basename(filepath))
                if parsed.get('season') == season_num and parsed.get('episode') == ep_num:
                    file_var.set(os.path.basename(filepath))
                    used_files.add(filepath)
                    break
    
    def _apply(self):
        """Apply scraped data to files"""
        if not self.show_details:
            messagebox.showinfo("Select Show", "Please search and select a TV show first")
            return
        
        if not hasattr(self, 'episode_vars') or not self.episode_vars:
            messagebox.showinfo("Select Season", "Please select a season first")
            return
        
        success = 0
        errors = []
        
        # Create show NFO in folder
        if self.files and self.create_nfo.get():
            folder = os.path.dirname(self.files[0])
            tvshow_nfo_path = os.path.join(folder, "tvshow.nfo")
            try:
                nfo_content = NFOGenerator.generate_tvshow_nfo(self.show_details)
                with open(tvshow_nfo_path, 'w', encoding='utf-8') as f:
                    f.write(nfo_content)
                print(f"Created tvshow.nfo: {tvshow_nfo_path}")
            except Exception as e:
                errors.append(f"tvshow.nfo: {e}")
        
        # Download show poster
        if self.download_poster.get() and self.show_details.get('poster_path') and self.files:
            folder = os.path.dirname(self.files[0])
            try:
                poster_data = TMDBAPI.download_image(self.show_details['poster_path'], 'original')
                if poster_data:
                    poster_path = os.path.join(folder, "poster.jpg")
                    with open(poster_path, 'wb') as f:
                        f.write(poster_data)
                    print(f"Downloaded poster: {poster_path}")
            except Exception as e:
                errors.append(f"poster: {e}")
        
        # Process each matched file
        for (season_num, ep_num), (file_var, episode) in self.episode_vars.items():
            filename = file_var.get()
            if filename == "(not matched)":
                continue
            
            # Find full path
            filepath = None
            for f in self.files:
                if os.path.basename(f) == filename:
                    filepath = f
                    break
            
            if not filepath:
                continue
            
            try:
                folder = os.path.dirname(filepath)
                basename = os.path.basename(filepath)
                name, ext = os.path.splitext(basename)
                
                # Create episode NFO
                if self.create_nfo.get():
                    ep_nfo = NFOGenerator.generate_episode_nfo(
                        {'episode_number': ep_num, 'season_number': season_num, **episode},
                        self.show_details
                    )
                    nfo_path = os.path.join(folder, f"{name}.nfo")
                    with open(nfo_path, 'w', encoding='utf-8') as f:
                        f.write(ep_nfo)
                
                # Rename file
                if self.rename_files.get():
                    new_name = MediaFileParser.generate_tv_filename(
                        self.show_details.get('title', ''),
                        season_num, ep_num,
                        episode.get('name', ''),
                        ext
                    )
                    new_path = os.path.join(folder, new_name)
                    if new_path != filepath and not os.path.exists(new_path):
                        os.rename(filepath, new_path)
                
                success += 1
                
            except Exception as e:
                errors.append(f"{filename}: {e}")
        
        if errors:
            messagebox.showwarning("Complete", f"Processed {success} file(s).\n\nErrors:\n" + "\n".join(errors[:5]))
        else:
            messagebox.showinfo("Success", f"Successfully processed {success} file(s)!")
        
        self.destroy()



class TVLibraryDialog(ctk.CTkToplevel):
    """MediaElch-style TV Library browser for managing multiple TV shows"""
    
    def __init__(self, parent, library_path: str):
        super().__init__(parent)
        
        self.library_path = library_path
        self.shows = []
        self.selected_show = None
        self.show_widgets = {}
        
        self.title("TV Library")
        self.geometry("1400x850")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        self.after(10, lambda: self.state('zoomed'))  # Maximize window
        
        self._create_ui()
        self._load_library()
    
    def _create_ui(self):
        # Main container
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BG_DARK)
        main.pack(fill="both", expand=True)
        
        # Header
        header = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_SECONDARY, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        header_inner = ctk.CTkFrame(header, fg_color="transparent")
        header_inner.pack(fill="both", expand=True, padx=20, pady=15)
        
        ctk.CTkLabel(header_inner, text="📺 TV LIBRARY", 
                    font=ctk.CTkFont(family="Bebas Neue", size=42),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(side="left")
        
        self.path_label = ctk.CTkLabel(header_inner, text=self.library_path,
                                       text_color=ParagonTheme.TEXT_MUTED,
                                       font=ctk.CTkFont(size=16))
        self.path_label.pack(side="left", padx=(20, 0))
        
        # Buttons - using ParagonButton like Movie Library
        ParagonButton(header_inner, text="🔄 RESCAN", command=self._rescan,
                     width=140, height=40).pack(side="right", padx=(10, 0))
        
        ParagonButton(header_inner, text="📁 CHANGE FOLDER", command=self._change_folder,
                     width=180, height=40,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="right")
        
        self.status_label = ctk.CTkLabel(header_inner, text="Loading...",
                                         text_color=ParagonTheme.TEXT_SECONDARY,
                                         font=ctk.CTkFont(size=18))
        self.status_label.pack(side="right", padx=(0, 20))
        
        # Content
        content = ctk.CTkFrame(main, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Left panel
        left_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=400)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)
        
        # Filter
        filter_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        filter_frame.pack(fill="x", padx=10, pady=10)
        
        self.filter_entry = ctk.CTkEntry(filter_frame, placeholder_text="🔍 Filter shows...",
                                        fg_color=ParagonTheme.BG_DARK,
                                        font=ctk.CTkFont(size=18), height=40)
        self.filter_entry.pack(fill="x")
        self.filter_entry.bind('<KeyRelease>', lambda e: self._filter_shows())
        
        # Show count
        self.count_label = ctk.CTkLabel(left_panel, text="0 TV Shows",
                                        text_color=ParagonTheme.TEXT_SECONDARY,
                                        font=ctk.CTkFont(family="Bebas Neue", size=24))
        self.count_label.pack(anchor="w", padx=15, pady=(0, 5))
        
        # Show list
        self.show_list = ctk.CTkScrollableFrame(left_panel, fg_color=ParagonTheme.BG_DARK)
        self.show_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Right panel
        self.right_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        self.right_panel.pack(side="left", fill="both", expand=True)
        
        self.placeholder = ctk.CTkLabel(self.right_panel, 
                                        text="Select a TV show from the list\nto view and edit details",
                                        text_color=ParagonTheme.TEXT_MUTED,
                                        font=ctk.CTkFont(size=24))
        self.placeholder.pack(expand=True)
        
        # Bottom
        bottom = ctk.CTkFrame(main, fg_color="transparent", height=60)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        
        ParagonButton(bottom, text="CLOSE", command=self.destroy,
                     width=120, height=44,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="right")
    
    def _load_library(self):
        cached = LibraryCache.load_cache('tv', self.library_path)
        if cached:
            self.shows = cached
            self.status_label.configure(text=f"Loaded {len(cached)} shows (cached)")
            self.count_label.configure(text=f"{len(cached)} TV SHOWS")
            for show in cached:
                self._add_show_item(show)
        else:
            self._rescan()
    
    def _rescan(self):
        """Rescan the library folder"""
        self.status_label.configure(text="Scanning...")
        self.update_idletasks()
        
        # Clear current list
        for widget in self.show_list.winfo_children():
            widget.destroy()
        self.show_widgets = {}
        
        def scan():
            shows = []
            try:
                for item in os.listdir(self.library_path):
                    item_path = os.path.join(self.library_path, item)
                    if os.path.isdir(item_path):
                        show_info = self._analyze_folder(item_path)
                        if show_info:
                            shows.append(show_info)
            except Exception as e:
                print(f"Error scanning: {e}")
            
            shows.sort(key=lambda x: x['name'].lower())
            LibraryCache.save_cache('tv', self.library_path, shows)
            
            if self.winfo_exists():
                self.after(0, lambda: self._on_scan_complete(shows))
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _analyze_folder(self, folder_path: str) -> Optional[Dict]:
        """Analyze a TV show folder"""
        folder_name = os.path.basename(folder_path)
        
        video_extensions = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.m4v', '.ts', '.m2ts'}
        episode_count = 0
        video_files = []
        
        for root, dirs, files in os.walk(folder_path):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in video_extensions:
                    episode_count += 1
                    video_files.append(os.path.join(root, f))
        
        if episode_count == 0:
            return None
        
        name = folder_name
        year = None
        year_match = re.search(r'\((\d{4})\)', folder_name)
        if year_match:
            year = year_match.group(1)
            name = folder_name[:year_match.start()].strip()
        
        nfo_path = os.path.join(folder_path, "tvshow.nfo")
        has_nfo = os.path.exists(nfo_path)
        
        poster_path = None
        has_poster = False
        for pname in ['poster.jpg', 'poster.png', 'folder.jpg']:
            p = os.path.join(folder_path, pname)
            if os.path.exists(p):
                poster_path = p
                has_poster = True
                break
        
        has_fanart = os.path.exists(os.path.join(folder_path, 'fanart.jpg'))
        has_logo = os.path.exists(os.path.join(folder_path, 'logo.png')) or \
                   os.path.exists(os.path.join(folder_path, 'clearlogo.png'))
        
        tmdb_id = None
        tvdb_id = None
        if has_nfo:
            try:
                with open(nfo_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    m = re.search(r'<tmdbid>(\d+)</tmdbid>', content)
                    if m: tmdb_id = m.group(1)
                    m = re.search(r'<tvdbid>(\d+)</tvdbid>', content)
                    if m: tvdb_id = m.group(1)
            except:
                pass
        
        return {
            'name': name,
            'year': year,
            'path': folder_path,
            'episode_count': episode_count,
            'has_nfo': has_nfo,
            'has_poster': has_poster,
            'has_fanart': has_fanart,
            'has_logo': has_logo,
            'poster_path': poster_path,
            'tmdb_id': tmdb_id,
            'tvdb_id': tvdb_id,
            'video_files': video_files
        }
    
    def _on_scan_complete(self, shows):
        self.shows = shows
        self.status_label.configure(text=f"Found {len(shows)} shows")
        self.count_label.configure(text=f"{len(shows)} TV SHOWS")
        for show in shows:
            self._add_show_item(show)
    
    def _add_show_item(self, show):
        """Create a show entry - simple button approach"""
        year_str = f" ({show['year']})" if show.get('year') else ""
        
        # Status indicators as text
        nfo = "✓" if show['has_nfo'] else "✗"
        p = "P" if show['has_poster'] else "-"
        f = "F" if show['has_fanart'] else "-"
        l = "L" if show['has_logo'] else "-"
        
        btn_text = f"{show['name']}{year_str}  •  {show['episode_count']} ep  [{nfo}{p}{f}{l}]"
        
        btn = ctk.CTkButton(
            self.show_list, 
            text=btn_text,
            anchor="w",
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            font=ctk.CTkFont(family="Bebas Neue", size=22),
            height=48,
            command=lambda s=show: self._on_show_click(s)
        )
        btn.pack(fill="x", pady=2)
        self.show_widgets[show['path']] = btn
    
    def _on_show_click(self, show):
        # Update selection highlighting
        prev = getattr(self, '_prev_selected', None)
        if prev and prev in self.show_widgets:
            try:
                self.show_widgets[prev].configure(fg_color=ParagonTheme.BG_TERTIARY)
            except:
                pass
        
        if show['path'] in self.show_widgets:
            try:
                self.show_widgets[show['path']].configure(fg_color=ParagonTheme.RED_PRIMARY)
            except:
                pass
        
        self._prev_selected = show['path']
        
        # Clear right panel
        for widget in self.right_panel.winfo_children():
            widget.destroy()
        
        # Header
        header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=15)
        
        year_str = f" ({show.get('year')})" if show.get('year') else ""
        ctk.CTkLabel(header, text=f"{show['name']}{year_str}",
                    font=ctk.CTkFont(family="Bebas Neue", size=36),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(side="left")
        
        ctk.CTkLabel(header, text=f"{show['episode_count']} episodes",
                    font=ctk.CTkFont(family="Bebas Neue", size=24),
                    text_color=ParagonTheme.TEXT_MUTED).pack(side="left", padx=(15, 0))
        
        ParagonButton(header, text="📝 OPEN FULL EDITOR",
                     command=lambda s=show: self._open_editor(s),
                     width=200, height=44).pack(side="right")
        
        # Info section with poster
        info_frame = ctk.CTkFrame(self.right_panel, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        info_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        info_inner = ctk.CTkFrame(info_frame, fg_color="transparent")
        info_inner.pack(fill="x", padx=15, pady=15)
        
        # Poster
        poster_frame = ctk.CTkFrame(info_inner, fg_color=ParagonTheme.BG_TERTIARY, width=120, height=180, corner_radius=6)
        poster_frame.pack(side="left", padx=(0, 20))
        poster_frame.pack_propagate(False)
        
        if show.get('poster_path') and HAS_PIL:
            try:
                img = Image.open(show['poster_path'])
                img.thumbnail((120, 180), Image.Resampling.LANCZOS)
                photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                lbl = ctk.CTkLabel(poster_frame, image=photo, text="")
                lbl.pack(expand=True)
                lbl._img = photo
                self._poster_ref = photo
            except:
                ctk.CTkLabel(poster_frame, text="No\nPoster", text_color=ParagonTheme.TEXT_MUTED).pack(expand=True)
        else:
            ctk.CTkLabel(poster_frame, text="No\nPoster", text_color=ParagonTheme.TEXT_MUTED).pack(expand=True)
        
        # Info text
        info_text = ctk.CTkFrame(info_inner, fg_color="transparent")
        info_text.pack(side="left", fill="both", expand=True)
        
        ctk.CTkLabel(info_text, text=f"Path: {show['path']}",
                    font=ctk.CTkFont(family="Bebas Neue", size=18),
                    text_color=ParagonTheme.TEXT_MUTED,
                    wraplength=600, anchor="w", justify="left").pack(anchor="w")
        
        # Status
        status = []
        status.append("✓ NFO" if show.get('has_nfo') else "✗ No NFO")
        if show.get('tmdb_id'): status.append(f"TMDB: {show['tmdb_id']}")
        if show.get('tvdb_id'): status.append(f"TVDB: {show['tvdb_id']}")
        
        ctk.CTkLabel(info_text, text=" | ".join(status),
                    font=ctk.CTkFont(family="Bebas Neue", size=20),
                    text_color=ParagonTheme.TEXT_SECONDARY).pack(anchor="w", pady=(8, 0))
        
        # Artwork
        artwork = []
        artwork.append("✓ Poster" if show.get('has_poster') else "✗ Poster")
        artwork.append("✓ Fanart" if show.get('has_fanart') else "✗ Fanart")
        artwork.append("✓ Logo" if show.get('has_logo') else "✗ Logo")
        
        ctk.CTkLabel(info_text, text=" | ".join(artwork),
                    font=ctk.CTkFont(family="Bebas Neue", size=20),
                    text_color=ParagonTheme.TEXT_SECONDARY).pack(anchor="w", pady=(4, 0))
        
        # Quick Actions
        ctk.CTkLabel(self.right_panel, text="QUICK ACTIONS",
                    font=ctk.CTkFont(family="Bebas Neue", size=28),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(anchor="w", padx=15, pady=(20, 10))
        
        actions_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        actions_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        ParagonButton(actions_frame, text="🔍 SEARCH TMDB",
                     command=lambda s=show: self._search_tmdb(s),
                     width=180, height=44).pack(side="left", padx=(0, 10))
        
        ParagonButton(actions_frame, text="🔄 RESCAN SHOW",
                     command=lambda s=show: self._rescan_show(s),
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER,
                     width=180, height=44).pack(side="left", padx=(0, 10))
        
        if not show.get('has_nfo'):
            ParagonButton(actions_frame, text="📄 CREATE NFO",
                         command=lambda s=show: self._open_editor(s),
                         fg_color=ParagonTheme.BG_TERTIARY,
                         hover_color=ParagonTheme.BG_HOVER,
                         width=160, height=44).pack(side="left", padx=(0, 10))
    
    def _open_editor(self, show):
        if show.get('video_files'):
            dialog = open_child_window(TVEditorDialog(self.master, show['video_files']), self)
    
    def _rescan_show(self, show):
        """Rescan just this show's folder"""
        self.status_label.configure(text=f"Rescanning {show['name']}...")
        self.update_idletasks()
        
        def scan():
            # Re-analyze just this folder
            new_info = self._analyze_folder(show['path'])
            if self.winfo_exists():
                self.after(0, lambda: self._on_show_rescan_complete(show, new_info))
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _on_show_rescan_complete(self, old_show, new_info):
        """Update the show after rescan"""
        if not new_info:
            self.status_label.configure(text="Rescan complete (no changes)")
            return
        
        # Update in the shows list
        for i, s in enumerate(self.shows):
            if s['path'] == old_show['path']:
                self.shows[i] = new_info
                break
        
        # Update the button text
        if old_show['path'] in self.show_widgets:
            btn = self.show_widgets[old_show['path']]
            year_str = f" ({new_info['year']})" if new_info.get('year') else ""
            nfo = "✓" if new_info['has_nfo'] else "✗"
            p = "P" if new_info['has_poster'] else "-"
            f = "F" if new_info['has_fanart'] else "-"
            l = "L" if new_info['has_logo'] else "-"
            btn_text = f"{new_info['name']}{year_str}  •  {new_info['episode_count']} ep  [{nfo}{p}{f}{l}]"
            btn.configure(text=btn_text)
        
        # Update cache
        LibraryCache.save_cache('tv', self.library_path, self.shows)
        
        # Refresh the details panel
        self._on_show_click(new_info)
        self.status_label.configure(text=f"Rescanned {new_info['name']}")
    
    def _search_tmdb(self, show):
        """Quick TMDB search"""
        def search():
            results = TMDBAPI.search_tv(show['name'])
            if self.winfo_exists():
                self.after(0, lambda: self._show_search_results(show, results))
        
        threading.Thread(target=search, daemon=True).start()
    
    def _show_search_results(self, show, results):
        """Show TMDB search results"""
        if not results:
            messagebox.showinfo("No Results", f"No TMDB results found for '{show['name']}'")
            return
        
        top = results[0]
        msg = f"Top result:\n\n{top.get('name', 'Unknown')}"
        if top.get('first_air_date'):
            msg += f" ({top['first_air_date'][:4]})"
        msg += f"\n\nTMDB ID: {top.get('id')}"
        if top.get('overview'):
            overview = top['overview'][:200] + "..." if len(top.get('overview', '')) > 200 else top.get('overview', '')
            msg += f"\n\n{overview}"
        
        if messagebox.askyesno("TMDB Result", f"{msg}\n\nOpen full editor to scrape this show?"):
            self._open_editor(show)
    
    def _filter_shows(self):
        """Filter show list based on search text"""
        filter_text = self.filter_entry.get().lower().strip()
        
        for show in self.shows:
            widget = self.show_widgets.get(show['path'])
            if widget:
                if not filter_text or filter_text in show['name'].lower():
                    widget.pack(fill="x", pady=2)
                else:
                    widget.pack_forget()
    
    def _change_folder(self):
        """Change library folder"""
        folder = filedialog.askdirectory(title="Select TV Library Folder", 
                                        initialdir=self.library_path)
        if folder:
            self.library_path = folder
            path_display = folder if len(folder) < 40 else "..." + folder[-37:]
            self.path_label.configure(text=path_display)
            self._rescan()

class FileLibraryDialog(ctk.CTkToplevel):
    """File Library browser for general file management and bulk renaming"""
    
    def __init__(self, parent, library_path: str):
        super().__init__(parent)
        
        self.parent = parent
        self.library_path = library_path
        self.all_files = []  # All files in folder
        self.filtered_files = []  # Files after filter
        self.selected_files = set()  # Selected file indices
        self.file_widgets = {}
        
        self.title("File Library")
        self.geometry("1200x800")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        self.after(10, lambda: self.state('zoomed'))  # Maximize window
        
        # Make modal - but delay grab_set until window is visible
        # self.transient(parent)  # Disabled - causes window issues on Windows
        
        self._create_ui()
        self._scan_folder()
        
        # Delay grab_set until window is fully visible
        self.after(100, self._do_grab)
    
    def _do_grab(self):
        """Set grab after window is visible"""
        try:
            if self.winfo_exists() and self.winfo_viewable():
                self.grab_set()
        except:
            pass
    
    def _create_ui(self):
        """Create the file browser UI"""
        # Main container
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BG_DARK)
        main.pack(fill="both", expand=True)
        
        # Header
        header = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_SECONDARY, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        header_inner = ctk.CTkFrame(header, fg_color="transparent")
        header_inner.pack(fill="both", expand=True, padx=20, pady=15)
        
        ctk.CTkLabel(header_inner, text="📁 FILE LIBRARY", 
                    font=ctk.CTkFont(family="Bebas Neue", size=42),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(side="left")
        
        self.library_path_label = ctk.CTkLabel(header_inner, text=self.library_path,
                                               text_color=ParagonTheme.TEXT_MUTED,
                                               font=ctk.CTkFont(size=16))
        self.library_path_label.pack(side="left", padx=(20, 0))
        
        # Refresh button
        ParagonButton(header_inner, text="🔄 REFRESH", command=self._scan_folder,
                     width=140, height=40).pack(side="right", padx=(10, 0))
        
        # Change folder button
        ParagonButton(header_inner, text="📁 CHANGE FOLDER", command=self._change_folder,
                     width=180, height=40,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="right")
        
        # Status label
        self.status_label = ctk.CTkLabel(header_inner, text="Scanning...",
                                         text_color=ParagonTheme.TEXT_SECONDARY,
                                         font=ctk.CTkFont(size=18))
        self.status_label.pack(side="right", padx=(0, 20))
        
        # Toolbar
        toolbar = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_SECONDARY, height=60)
        toolbar.pack(fill="x", pady=(10, 0))
        toolbar.pack_propagate(False)
        
        toolbar_inner = ctk.CTkFrame(toolbar, fg_color="transparent")
        toolbar_inner.pack(fill="both", expand=True, padx=15, pady=10)
        
        # Filter/search
        self.filter_entry = ctk.CTkEntry(toolbar_inner, placeholder_text="🔍 Filter files...",
                                        fg_color=ParagonTheme.BG_DARK,
                                        font=ctk.CTkFont(size=16), width=250, height=38)
        self.filter_entry.pack(side="left", padx=(0, 15))
        self.filter_entry.bind('<KeyRelease>', lambda e: self._filter_files())
        
        # Filter type buttons
        self.filter_type = ctk.StringVar(value="all")
        
        filter_types = [
            ("All", "all"),
            ("Video", "video"),
            ("Audio", "audio"),
            ("Images", "images"),
            ("Documents", "docs"),
        ]
        
        for label, value in filter_types:
            btn = ctk.CTkRadioButton(toolbar_inner, text=label, variable=self.filter_type, value=value,
                                    command=self._filter_files,
                                    fg_color=ParagonTheme.RED_PRIMARY,
                                    font=ctk.CTkFont(size=14))
            btn.pack(side="left", padx=(0, 10))
        
        # Select all / none buttons
        ctk.CTkFrame(toolbar_inner, fg_color=ParagonTheme.BORDER_DARK, width=2).pack(side="left", fill="y", padx=15)
        
        ParagonSecondaryButton(toolbar_inner, text="Select All", width=90, height=32,
                              command=self._select_all).pack(side="left", padx=(0, 5))
        ParagonSecondaryButton(toolbar_inner, text="Select None", width=100, height=32,
                              command=self._select_none).pack(side="left")
        
        # Action buttons on right
        ParagonButton(toolbar_inner, text="📤 SEND TO RENAMER", 
                     command=self._send_to_renamer,
                     width=180, height=38).pack(side="right")
        
        # Content - file list
        content = ctk.CTkFrame(main, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=10, pady=10)
        
        # File list panel
        file_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        file_panel.pack(fill="both", expand=True)
        
        # File count header
        count_frame = ctk.CTkFrame(file_panel, fg_color="transparent")
        count_frame.pack(fill="x", padx=15, pady=10)
        
        self.file_count_label = ctk.CTkLabel(count_frame, text="0 Files",
                                            text_color=ParagonTheme.TEXT_PRIMARY,
                                            font=ctk.CTkFont(family="Bebas Neue", size=24))
        self.file_count_label.pack(side="left")
        
        self.selected_count_label = ctk.CTkLabel(count_frame, text="0 selected",
                                                text_color=ParagonTheme.TEXT_MUTED,
                                                font=ctk.CTkFont(size=14))
        self.selected_count_label.pack(side="left", padx=(15, 0))
        
        # Include subfolders checkbox
        self.include_subfolders = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(count_frame, text="Include subfolders", variable=self.include_subfolders,
                       command=self._scan_folder,
                       fg_color=ParagonTheme.RED_PRIMARY,
                       font=ctk.CTkFont(size=14)).pack(side="right")
        
        # File list
        self.file_list = ctk.CTkScrollableFrame(file_panel, fg_color=ParagonTheme.BG_DARK)
        self.file_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Bottom buttons
        bottom = ctk.CTkFrame(main, fg_color="transparent", height=60)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        
        ParagonButton(bottom, text="CLOSE", command=self.destroy,
                     width=120, height=44,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="right")
    
    def _scan_folder(self):
        """Scan the folder for files"""
        self.all_files = []
        self.status_label.configure(text="Scanning...")
        self.update_idletasks()
        
        def scan():
            files = []
            include_subs = self.include_subfolders.get()
            
            try:
                if include_subs:
                    for root, dirs, filenames in os.walk(self.library_path):
                        for f in filenames:
                            if not f.startswith('.'):
                                filepath = os.path.join(root, f)
                                files.append(self._analyze_file(filepath))
                else:
                    for f in os.listdir(self.library_path):
                        filepath = os.path.join(self.library_path, f)
                        if os.path.isfile(filepath) and not f.startswith('.'):
                            files.append(self._analyze_file(filepath))
            except Exception as e:
                print(f"Error scanning folder: {e}")
            
            # Sort by name
            files.sort(key=lambda x: x['name'].lower())
            
            # Only update if dialog still exists
            self.after(0, lambda: self._populate_file_list(files) if self.winfo_exists() else None)
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _analyze_file(self, filepath: str) -> Dict:
        """Analyze a file and return info"""
        name = os.path.basename(filepath)
        ext = os.path.splitext(name)[1].lower()
        
        # Determine file type
        video_exts = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.m4v', '.ts', '.m2ts', '.webm'}
        audio_exts = {'.mp3', '.flac', '.m4a', '.ogg', '.opus', '.wav', '.aac', '.wma'}
        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}
        doc_exts = {'.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt', '.xls', '.xlsx'}
        
        if ext in video_exts:
            file_type = "video"
            icon = "🎬"
        elif ext in audio_exts:
            file_type = "audio"
            icon = "🎵"
        elif ext in image_exts:
            file_type = "images"
            icon = "🖼️"
        elif ext in doc_exts:
            file_type = "docs"
            icon = "📄"
        else:
            file_type = "other"
            icon = "📁"
        
        # Get file size
        try:
            size = os.path.getsize(filepath)
            if size >= 1073741824:  # GB
                size_str = f"{size / 1073741824:.1f} GB"
            elif size >= 1048576:  # MB
                size_str = f"{size / 1048576:.1f} MB"
            elif size >= 1024:  # KB
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
        except:
            size_str = "?"
            size = 0
        
        return {
            'name': name,
            'path': filepath,
            'ext': ext,
            'type': file_type,
            'icon': icon,
            'size': size,
            'size_str': size_str,
        }
    
    def _populate_file_list(self, files: List[Dict]):
        """Populate the file list"""
        # Check if dialog still exists
        if not self.winfo_exists():
            return
            
        self.all_files = files
        self.selected_files = set()
        self._filter_files()
    
    def _filter_files(self):
        """Filter files based on search and type"""
        filter_text = self.filter_entry.get().lower().strip()
        filter_type = self.filter_type.get()
        
        self.filtered_files = []
        for f in self.all_files:
            # Type filter
            if filter_type != "all" and f['type'] != filter_type:
                continue
            
            # Text filter
            if filter_text and filter_text not in f['name'].lower():
                continue
            
            self.filtered_files.append(f)
        
        # Update UI
        self._update_file_list_ui()
    
    def _update_file_list_ui(self):
        """Update the file list UI"""
        # Clear existing
        for widget in self.file_list.winfo_children():
            widget.destroy()
        self.file_widgets = {}
        
        # Update count
        self.file_count_label.configure(text=f"{len(self.filtered_files)} Files")
        self.status_label.configure(text=f"{len(self.all_files)} total files")
        self._update_selected_count()
        
        # Create file entries
        for i, f in enumerate(self.filtered_files):
            self._create_file_entry(i, f)
    
    def _create_file_entry(self, index: int, file_info: Dict):
        """Create a file entry in the list"""
        is_selected = file_info['path'] in self.selected_files
        bg_color = ParagonTheme.RED_PRIMARY if is_selected else ParagonTheme.BG_TERTIARY
        
        frame = ctk.CTkFrame(self.file_list, fg_color=bg_color, corner_radius=4)
        frame.pack(fill="x", pady=1)
        frame.bind("<Button-1>", lambda e, f=file_info: self._toggle_file_selection(f))
        
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=4)
        inner.bind("<Button-1>", lambda e, f=file_info: self._toggle_file_selection(f))
        
        # Checkbox
        var = ctk.BooleanVar(value=is_selected)
        cb = ctk.CTkCheckBox(inner, text="", variable=var, width=20,
                            fg_color=ParagonTheme.RED_PRIMARY,
                            command=lambda f=file_info: self._toggle_file_selection(f))
        cb.pack(side="left", padx=(0, 10))
        
        # Icon
        icon_lbl = ctk.CTkLabel(inner, text=file_info['icon'],
                               font=ctk.CTkFont(size=16), width=25)
        icon_lbl.pack(side="left")
        icon_lbl.bind("<Button-1>", lambda e, f=file_info: self._toggle_file_selection(f))
        
        # Filename
        name_lbl = ctk.CTkLabel(inner, text=file_info['name'],
                               font=ctk.CTkFont(size=14),
                               text_color=ParagonTheme.TEXT_PRIMARY,
                               anchor="w")
        name_lbl.pack(side="left", fill="x", expand=True, padx=(5, 10))
        name_lbl.bind("<Button-1>", lambda e, f=file_info: self._toggle_file_selection(f))
        
        # Size
        size_lbl = ctk.CTkLabel(inner, text=file_info['size_str'],
                               font=ctk.CTkFont(size=12),
                               text_color=ParagonTheme.TEXT_MUTED,
                               width=80)
        size_lbl.pack(side="right")
        size_lbl.bind("<Button-1>", lambda e, f=file_info: self._toggle_file_selection(f))
        
        # Extension
        ext_lbl = ctk.CTkLabel(inner, text=file_info['ext'],
                              font=ctk.CTkFont(size=12),
                              text_color=ParagonTheme.TEXT_MUTED,
                              width=60)
        ext_lbl.pack(side="right")
        ext_lbl.bind("<Button-1>", lambda e, f=file_info: self._toggle_file_selection(f))
        
        self.file_widgets[file_info['path']] = (frame, var)
    
    def _toggle_file_selection(self, file_info: Dict):
        """Toggle selection for a file"""
        path = file_info['path']
        if path in self.selected_files:
            self.selected_files.remove(path)
        else:
            self.selected_files.add(path)
        
        # Update UI
        if path in self.file_widgets:
            frame, var = self.file_widgets[path]
            is_selected = path in self.selected_files
            var.set(is_selected)
            frame.configure(fg_color=ParagonTheme.RED_PRIMARY if is_selected else ParagonTheme.BG_TERTIARY)
        
        self._update_selected_count()
    
    def _update_selected_count(self):
        """Update the selected count label"""
        count = len(self.selected_files)
        self.selected_count_label.configure(text=f"{count} selected")
    
    def _select_all(self):
        """Select all visible files"""
        for f in self.filtered_files:
            self.selected_files.add(f['path'])
        self._update_file_list_ui()
    
    def _select_none(self):
        """Deselect all files"""
        self.selected_files.clear()
        self._update_file_list_ui()
    
    def _send_to_renamer(self):
        """Send selected files to the main renamer"""
        if not self.selected_files:
            messagebox.showinfo("No Selection", "Please select files to send to the renamer")
            return
        
        # Get the file paths
        files = list(self.selected_files)
        
        # Add to parent's file list
        if hasattr(self.parent, '_add_files_to_list'):
            self.parent._add_files_to_list(files)
            messagebox.showinfo("Files Added", f"Added {len(files)} files to the renamer.\n\nClose this dialog to continue renaming.")
        else:
            # Fallback - just use the add_folder method logic
            for filepath in files:
                self.parent.files.append(FileItem(filepath))
            self.parent._update_preview()
            messagebox.showinfo("Files Added", f"Added {len(files)} files to the renamer.")
    
    def _change_folder(self):
        """Change the folder"""
        folder = filedialog.askdirectory(title="Select Folder to Browse", initialdir=self.library_path)
        if folder:
            self.library_path = folder
            self.library_path_label.configure(text=folder)
            self._scan_folder()


class MovieLibraryDialog(ctk.CTkToplevel):
    """MediaElch-style Movie Library browser for managing multiple movies"""
    
    def __init__(self, parent, library_path: str):
        super().__init__(parent)
        
        self.library_path = library_path
        self.movies = []  # List of {name, path, year, has_nfo, poster_path, etc}
        self.selected_movie = None
        self.movie_widgets = {}
        
        self.title("Movie Library")
        self.geometry("1400x850")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        self.after(10, lambda: self.state('zoomed'))  # Maximize window
        
        self._create_ui()
        self._load_library()  # Try cache first
    
    def _create_ui(self):
        """Create the library browser UI"""
        # Main container
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BG_DARK)
        main.pack(fill="both", expand=True)
        
        # Header
        header = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_SECONDARY, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        header_inner = ctk.CTkFrame(header, fg_color="transparent")
        header_inner.pack(fill="both", expand=True, padx=20, pady=15)
        
        ctk.CTkLabel(header_inner, text="🎬 MOVIE LIBRARY", 
                    font=ctk.CTkFont(family="Bebas Neue", size=42),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(side="left")
        
        self.library_path_label = ctk.CTkLabel(header_inner, text=self.library_path,
                                               text_color=ParagonTheme.TEXT_MUTED,
                                               font=ctk.CTkFont(size=16))
        self.library_path_label.pack(side="left", padx=(20, 0))
        
        # Refresh button (force rescan)
        ParagonButton(header_inner, text="🔄 RESCAN", command=lambda: self._scan_library(force=True),
                     width=140, height=40).pack(side="right", padx=(10, 0))
        
        # Change folder button
        ParagonButton(header_inner, text="📁 CHANGE FOLDER", command=self._change_folder,
                     width=180, height=40,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="right")
        
        # Status label
        self.status_label = ctk.CTkLabel(header_inner, text="Loading...",
                                         text_color=ParagonTheme.TEXT_SECONDARY,
                                         font=ctk.CTkFont(size=18))
        self.status_label.pack(side="right", padx=(0, 20))
        
        # Content - split into movie list and details
        content = ctk.CTkFrame(main, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Left panel - Movie list
        left_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=400)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)
        
        # Search/filter
        filter_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        filter_frame.pack(fill="x", padx=10, pady=10)
        
        self.filter_entry = ctk.CTkEntry(filter_frame, placeholder_text="🔍 Filter movies...",
                                        fg_color=ParagonTheme.BG_DARK,
                                        font=ctk.CTkFont(size=18), height=40)
        self.filter_entry.pack(fill="x")
        self.filter_entry.bind('<KeyRelease>', lambda e: self._filter_movies())
        
        # Movie count
        self.movie_count_label = ctk.CTkLabel(left_panel, text="0 Movies",
                                             text_color=ParagonTheme.TEXT_SECONDARY,
                                             font=ctk.CTkFont(family="Bebas Neue", size=24))
        self.movie_count_label.pack(anchor="w", padx=15, pady=(0, 5))
        
        # Movie list
        self.movie_list = ctk.CTkScrollableFrame(left_panel, fg_color=ParagonTheme.BG_DARK)
        self.movie_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Right panel - Movie details placeholder
        self.right_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        self.right_panel.pack(side="left", fill="both", expand=True)
        
        # Initial placeholder
        self.detail_placeholder = ctk.CTkLabel(self.right_panel, 
                                               text="Select a movie from the list\nto view and edit details",
                                               text_color=ParagonTheme.TEXT_MUTED,
                                               font=ctk.CTkFont(size=24))
        self.detail_placeholder.pack(expand=True)
        
        # Bottom buttons
        bottom = ctk.CTkFrame(main, fg_color="transparent", height=60)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        
        ParagonButton(bottom, text="CLOSE", command=self.destroy,
                     width=120, height=44,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="right")
    
    def _load_library(self):
        """Load library from cache or scan if needed"""
        cached = LibraryCache.load_cache('movie', self.library_path)
        if cached:
            self.status_label.configure(text="Loading from cache...")
            self.update_idletasks()
            self._populate_movie_list(cached)
            self.status_label.configure(text=f"Loaded {len(cached)} movies (cached)")
        else:
            self._scan_library(force=True)
    
    def _scan_library(self, force=False):
        """Scan the library folder for movies"""
        self.movies = []
        self.status_label.configure(text="Scanning...")
        self.update_idletasks()
        
        def scan():
            movies = []
            try:
                for item in os.listdir(self.library_path):
                    item_path = os.path.join(self.library_path, item)
                    if os.path.isdir(item_path):
                        # Check if it looks like a movie folder
                        movie_info = self._analyze_movie_folder(item_path)
                        if movie_info:
                            movies.append(movie_info)
            except Exception as e:
                print(f"Error scanning library: {e}")
            
            # Sort by name
            movies.sort(key=lambda x: x['name'].lower())
            
            # Save to cache
            LibraryCache.save_cache('movie', self.library_path, movies)
            
            # Only update if dialog still exists
            self.after(0, lambda: self._populate_movie_list(movies) if self.winfo_exists() else None)
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _analyze_movie_folder(self, folder_path: str) -> Optional[Dict]:
        """Analyze a folder to determine if it's a movie and extract info"""
        folder_name = os.path.basename(folder_path)
        
        # Count video files
        video_extensions = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.m4v', '.ts', '.m2ts'}
        video_files = []
        
        for f in os.listdir(folder_path):
            ext = os.path.splitext(f)[1].lower()
            if ext in video_extensions:
                video_files.append(os.path.join(folder_path, f))
        
        # Skip if no video files found
        if not video_files:
            return None
        
        # Get the main video file (largest one)
        main_video = max(video_files, key=lambda x: os.path.getsize(x)) if video_files else None
        
        # Check for movie.nfo or <moviename>.nfo
        nfo_path = None
        has_nfo = False
        for nfo_name in ['movie.nfo', folder_name + '.nfo']:
            test_path = os.path.join(folder_path, nfo_name)
            if os.path.exists(test_path):
                nfo_path = test_path
                has_nfo = True
                break
        
        # Also check for nfo matching video filename
        if not has_nfo and main_video:
            video_nfo = os.path.splitext(main_video)[0] + '.nfo'
            if os.path.exists(video_nfo):
                nfo_path = video_nfo
                has_nfo = True
        
        # Try to get movie info from NFO
        movie_name = folder_name
        tmdb_id = None
        imdb_id = None
        year = None
        
        if has_nfo and nfo_path:
            try:
                nfo_data = NFOParser.parse_movie_nfo(nfo_path)
                if nfo_data:
                    movie_name = nfo_data.get('title', folder_name) or folder_name
                    tmdb_id = nfo_data.get('tmdb_id')
                    imdb_id = nfo_data.get('imdb_id')
                    year = nfo_data.get('year')
            except:
                pass
        
        # Try to parse year from folder name if not in NFO
        if not year:
            import re
            year_match = re.search(r'\((\d{4})\)', folder_name)
            if year_match:
                year = year_match.group(1)
                # Clean movie name
                movie_name = re.sub(r'\s*\(\d{4}\)\s*', '', folder_name).strip()
        
        # Check for poster
        poster_path = None
        for poster_name in ['poster.jpg', 'poster.png', 'folder.jpg', movie_name + '-poster.jpg']:
            p = os.path.join(folder_path, poster_name)
            if os.path.exists(p):
                poster_path = p
                break
        
        # Check artwork status
        has_poster = poster_path is not None
        has_fanart = any(os.path.exists(os.path.join(folder_path, f)) for f in ['fanart.jpg', 'backdrop.jpg'])
        has_logo = os.path.exists(os.path.join(folder_path, 'logo.png')) or os.path.exists(os.path.join(folder_path, 'clearlogo.png'))
        
        return {
            'name': movie_name,
            'path': folder_path,
            'video_file': main_video,
            'video_count': len(video_files),
            'has_nfo': has_nfo,
            'nfo_path': nfo_path,
            'poster_path': poster_path,
            'tmdb_id': tmdb_id,
            'imdb_id': imdb_id,
            'year': year,
            'has_poster': has_poster,
            'has_fanart': has_fanart,
            'has_logo': has_logo,
        }
    
    def _populate_movie_list(self, movies: List[Dict]):
        """Populate the movie list with scanned movies"""
        # Check if dialog still exists
        if not self.winfo_exists():
            return
            
        self.movies = movies
        
        # Clear existing
        try:
            for widget in self.movie_list.winfo_children():
                widget.destroy()
        except:
            return
        self.movie_widgets = {}
        
        # Update count
        self.movie_count_label.configure(text=f"{len(movies)} Movies")
        self.status_label.configure(text=f"Found {len(movies)} movies")
        
        # Create movie entries
        for movie in movies:
            self._create_movie_entry(movie)
    
    def _create_movie_entry(self, movie: Dict):
        """Create a movie entry - simple button approach like TV Library"""
        year_str = f" ({movie['year']})" if movie.get('year') else ""
        
        # Status indicators as text
        nfo = "✓" if movie['has_nfo'] else "✗"
        p = "P" if movie['has_poster'] else "-"
        f = "F" if movie['has_fanart'] else "-"
        l = "L" if movie['has_logo'] else "-"
        
        btn_text = f"{movie['name']}{year_str}  [{nfo}{p}{f}{l}]"
        
        btn = ctk.CTkButton(
            self.movie_list, 
            text=btn_text,
            anchor="w",
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            font=ctk.CTkFont(family="Bebas Neue", size=22),
            height=48,
            command=lambda m=movie: self._select_movie(m)
        )
        btn.pack(fill="x", pady=2)
        self.movie_widgets[movie['path']] = btn
    
    def _select_movie(self, movie: Dict):
        """Select a movie and show its details"""
        # Update selection highlighting
        prev = getattr(self, '_prev_selected', None)
        if prev and prev in self.movie_widgets:
            try:
                self.movie_widgets[prev].configure(fg_color=ParagonTheme.BG_TERTIARY)
            except:
                pass
        
        if movie['path'] in self.movie_widgets:
            try:
                self.movie_widgets[movie['path']].configure(fg_color=ParagonTheme.RED_PRIMARY)
            except:
                pass
        
        self._prev_selected = movie['path']
        self.selected_movie = movie
        
        # Clear right panel
        for widget in self.right_panel.winfo_children():
            widget.destroy()
        
        # Create movie details view
        self._create_movie_details(movie)
    
    def _create_movie_details(self, movie: Dict):
        """Create movie details view in the right panel"""
        # Header with movie name
        header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=15)
        
        year_str = f" ({movie['year']})" if movie.get('year') else ""
        ctk.CTkLabel(header, text=f"{movie['name']}{year_str}",
                    font=ctk.CTkFont(family="Bebas Neue", size=36),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(side="left")
        
        # Open full editor button
        ParagonButton(header, text="📝 OPEN FULL EDITOR", 
                     command=lambda: self._open_full_editor(movie),
                     width=200, height=44).pack(side="right")
        
        # Info section
        info_frame = ctk.CTkFrame(self.right_panel, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        info_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        info_inner = ctk.CTkFrame(info_frame, fg_color="transparent")
        info_inner.pack(fill="x", padx=15, pady=15)
        
        # Poster placeholder - will be replaced async
        poster_frame = ctk.CTkFrame(info_inner, fg_color=ParagonTheme.BG_TERTIARY, width=120, height=180, corner_radius=6)
        poster_frame.pack(side="left", padx=(0, 20))
        poster_frame.pack_propagate(False)
        
        self._poster_label = ctk.CTkLabel(poster_frame, text="Loading...", 
                                         text_color=ParagonTheme.TEXT_MUTED,
                                         font=ctk.CTkFont(size=12))
        self._poster_label.pack(expand=True)
        
        # Load poster asynchronously
        if movie.get('poster_path') and HAS_PIL:
            self._load_poster_async(movie['poster_path'], poster_frame)
        
        # Info text
        info_text = ctk.CTkFrame(info_inner, fg_color="transparent")
        info_text.pack(side="left", fill="both", expand=True)
        
        ctk.CTkLabel(info_text, text=f"Path: {movie['path']}",
                    font=ctk.CTkFont(size=16),
                    text_color=ParagonTheme.TEXT_MUTED,
                    wraplength=600, anchor="w", justify="left").pack(anchor="w")
        
        if movie.get('video_file'):
            ctk.CTkLabel(info_text, text=f"File: {os.path.basename(movie['video_file'])}",
                        font=ctk.CTkFont(size=16),
                        text_color=ParagonTheme.TEXT_MUTED).pack(anchor="w", pady=(5, 0))
        
        status_parts = []
        if movie['has_nfo']:
            status_parts.append("✓ NFO")
        else:
            status_parts.append("✗ No NFO")
        
        if movie.get('tmdb_id'):
            status_parts.append(f"TMDB: {movie['tmdb_id']}")
        if movie.get('imdb_id'):
            status_parts.append(f"IMDB: {movie['imdb_id']}")
        
        ctk.CTkLabel(info_text, text=" | ".join(status_parts),
                    font=ctk.CTkFont(size=18),
                    text_color=ParagonTheme.TEXT_SECONDARY).pack(anchor="w", pady=(8, 0))
        
        # Artwork status
        artwork_status = []
        if movie['has_poster']: artwork_status.append("✓ Poster")
        else: artwork_status.append("✗ Poster")
        if movie['has_fanart']: artwork_status.append("✓ Fanart")
        else: artwork_status.append("✗ Fanart")
        if movie['has_logo']: artwork_status.append("✓ Logo")
        else: artwork_status.append("✗ Logo")
        
        ctk.CTkLabel(info_text, text=" | ".join(artwork_status),
                    font=ctk.CTkFont(size=18),
                    text_color=ParagonTheme.TEXT_SECONDARY).pack(anchor="w", pady=(4, 0))
        
        # Quick actions section
        actions_header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        actions_header.pack(fill="x", padx=15, pady=(20, 10))
        
        ctk.CTkLabel(actions_header, text="QUICK ACTIONS",
                    font=ctk.CTkFont(family="Bebas Neue", size=28),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(side="left")
        
        actions_frame = ctk.CTkFrame(self.right_panel, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        actions_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        actions_inner = ctk.CTkFrame(actions_frame, fg_color="transparent")
        actions_inner.pack(fill="x", padx=15, pady=15)
        
        # Quick action buttons
        ParagonButton(actions_inner, text="🔍 SEARCH TMDB", 
                     command=lambda: self._quick_search_tmdb(movie),
                     width=160, height=40).pack(side="left", padx=(0, 10))
        
        ParagonButton(actions_inner, text="🔄 RESCAN MOVIE", 
                     command=lambda: self._rescan_movie(movie),
                     width=180, height=40,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="left", padx=(0, 10))
        
        if not movie['has_nfo']:
            ParagonButton(actions_inner, text="📄 CREATE NFO", 
                         command=lambda: self._quick_create_nfo(movie),
                         width=140, height=40,
                         fg_color=ParagonTheme.BG_TERTIARY,
                         hover_color=ParagonTheme.BG_HOVER).pack(side="left", padx=(0, 10))
    
    def _load_poster_async(self, poster_path: str, poster_frame):
        """Load poster image in background thread"""
        def load():
            try:
                img = Image.open(poster_path)
                img.thumbnail((120, 180), Image.Resampling.LANCZOS)
                # Schedule UI update on main thread
                self.after(0, lambda: self._update_poster(img, poster_frame))
            except Exception as e:
                print(f"Error loading poster: {e}")
                self.after(0, lambda: self._update_poster(None, poster_frame))
        
        threading.Thread(target=load, daemon=True).start()
    
    def _update_poster(self, img, poster_frame):
        """Update poster image on main thread"""
        if not self.winfo_exists():
            return
        try:
            # Clear placeholder
            for widget in poster_frame.winfo_children():
                widget.destroy()
            
            if img:
                photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                poster_lbl = ctk.CTkLabel(poster_frame, image=photo, text="")
                poster_lbl.pack(expand=True)
                poster_lbl._img = photo  # Keep reference
                self._current_poster = photo  # Also keep on self
            else:
                ctk.CTkLabel(poster_frame, text="No\nPoster", 
                            text_color=ParagonTheme.TEXT_MUTED,
                            font=ctk.CTkFont(size=12)).pack(expand=True)
        except:
            pass
    
    def _open_full_editor(self, movie: Dict):
        """Open the full Movie Editor for this movie"""
        if movie.get('video_file'):
            self.grab_release()
            dialog = open_child_window(MovieEditorDialog(self.master, [movie['video_file']]), self)
    
    def _quick_search_tmdb(self, movie: Dict):
        """Quick search TMDB for movie info"""
        search_term = movie['name']
        year = movie.get('year')
        
        def search():
            results = TMDBAPI.search_movie(search_term, year)
            self.after(0, lambda: self._show_search_results(movie, results))
        
        threading.Thread(target=search, daemon=True).start()
    
    def _show_search_results(self, movie: Dict, results: List[Dict]):
        """Show TMDB search results"""
        if not results:
            messagebox.showinfo("No Results", f"No TMDB results found for '{movie['name']}'")
            return
        
        # For now, just show a message with the top result
        top = results[0]
        msg = f"Top result:\n\n{top.get('title', 'Unknown')}"
        if top.get('release_date'):
            msg += f" ({top['release_date'][:4]})"
        msg += f"\n\nTMDB ID: {top.get('id')}"
        
        if messagebox.askyesno("TMDB Result", f"{msg}\n\nOpen full editor to scrape this movie?"):
            self._open_full_editor(movie)
    
    def _quick_create_nfo(self, movie: Dict):
        """Quick create a basic NFO file"""
        messagebox.showinfo("Create NFO", "Use the full editor to search TMDB and create a complete NFO file.")
        self._open_full_editor(movie)
    
    def _rescan_movie(self, movie: Dict):
        """Rescan just this movie's folder"""
        self.status_label.configure(text=f"Rescanning {movie['name']}...")
        self.update_idletasks()
        
        def scan():
            new_info = self._analyze_movie_folder(movie['path'])
            if self.winfo_exists():
                self.after(0, lambda: self._on_movie_rescan_complete(movie, new_info))
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _on_movie_rescan_complete(self, old_movie: Dict, new_info: Dict):
        """Update the movie after rescan"""
        if not new_info:
            self.status_label.configure(text="Rescan complete (no changes)")
            return
        
        # Update in the movies list
        for i, m in enumerate(self.movies):
            if m['path'] == old_movie['path']:
                self.movies[i] = new_info
                break
        
        # Update the button text
        if old_movie['path'] in self.movie_widgets:
            btn = self.movie_widgets[old_movie['path']]
            year_str = f" ({new_info['year']})" if new_info.get('year') else ""
            nfo = "✓" if new_info['has_nfo'] else "✗"
            p = "P" if new_info['has_poster'] else "-"
            f = "F" if new_info['has_fanart'] else "-"
            l = "L" if new_info['has_logo'] else "-"
            btn_text = f"{new_info['name']}{year_str}  [{nfo}{p}{f}{l}]"
            btn.configure(text=btn_text)
        
        # Update cache
        LibraryCache.save_cache('movie', self.library_path, self.movies)
        
        # Refresh the details panel
        self._select_movie(new_info)
        self.status_label.configure(text=f"Rescanned {new_info['name']}")
    
    def _filter_movies(self):
        """Filter movies based on search text"""
        filter_text = self.filter_entry.get().lower().strip()
        
        for movie in self.movies:
            widget = self.movie_widgets.get(movie['path'])
            if widget:
                if not filter_text or filter_text in movie['name'].lower():
                    widget.pack(fill="x", pady=3)
                else:
                    widget.pack_forget()
    
    def _change_folder(self):
        """Change the library folder"""
        folder = filedialog.askdirectory(title="Select Movie Library Folder", initialdir=self.library_path)
        if folder:
            self.library_path = folder
            self.library_path_label.configure(text=folder)
            self._scan_library()


class MusicLibraryDialog(ctk.CTkToplevel):
    """Music Library browser for managing music collection by artist/album"""
    
    def __init__(self, parent, library_path: str):
        super().__init__(parent)
        
        self.library_path = library_path
        self.artists = []  # List of {name, path, album_count, track_count}
        self.albums = []   # Albums for selected artist
        self.selected_artist = None
        self.selected_album = None
        self.artist_widgets = {}
        self.album_widgets = {}
        
        self.title("Music Library")
        self.geometry("1500x900")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        self.after(10, lambda: self.state('zoomed'))  # Maximize window
        
        self._create_ui()
        self._load_library()  # Try cache first
    
    def _create_ui(self):
        """Create the library browser UI"""
        # Main container
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BG_DARK)
        main.pack(fill="both", expand=True)
        
        # Header
        header = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_SECONDARY, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        header_inner = ctk.CTkFrame(header, fg_color="transparent")
        header_inner.pack(fill="both", expand=True, padx=20, pady=15)
        
        ctk.CTkLabel(header_inner, text="🎵 MUSIC LIBRARY", 
                    font=ctk.CTkFont(family="Bebas Neue", size=42),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(side="left")
        
        self.library_path_label = ctk.CTkLabel(header_inner, text=self.library_path,
                                               text_color=ParagonTheme.TEXT_MUTED,
                                               font=ctk.CTkFont(size=16))
        self.library_path_label.pack(side="left", padx=(20, 0))
        
        # Refresh button (force rescan)
        ParagonButton(header_inner, text="🔄 RESCAN", command=lambda: self._scan_library(force=True),
                     width=140, height=40).pack(side="right", padx=(10, 0))
        
        # Change folder button
        ParagonButton(header_inner, text="📁 CHANGE FOLDER", command=self._change_folder,
                     width=180, height=40,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="right")
        
        # Status label
        self.status_label = ctk.CTkLabel(header_inner, text="Scanning...",
                                         text_color=ParagonTheme.TEXT_SECONDARY,
                                         font=ctk.CTkFont(size=18))
        self.status_label.pack(side="right", padx=(0, 20))
        
        # Content - three panels: Artists, Albums, Tracks
        content = ctk.CTkFrame(main, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Left panel - Artist list
        left_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=300)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)
        
        # Search/filter for artists
        filter_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        filter_frame.pack(fill="x", padx=10, pady=10)
        
        self.artist_filter_entry = ctk.CTkEntry(filter_frame, placeholder_text="🔍 Filter artists...",
                                        fg_color=ParagonTheme.BG_DARK,
                                        font=ctk.CTkFont(size=16), height=36)
        self.artist_filter_entry.pack(fill="x")
        self.artist_filter_entry.bind('<KeyRelease>', lambda e: self._filter_artists())
        
        # Artist count
        self.artist_count_label = ctk.CTkLabel(left_panel, text="0 Artists",
                                             text_color=ParagonTheme.TEXT_SECONDARY,
                                             font=ctk.CTkFont(family="Bebas Neue", size=22))
        self.artist_count_label.pack(anchor="w", padx=15, pady=(0, 5))
        
        # Artist list
        self.artist_list = ctk.CTkScrollableFrame(left_panel, fg_color=ParagonTheme.BG_DARK)
        self.artist_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Middle panel - Album list
        middle_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=350)
        middle_panel.pack(side="left", fill="y", padx=(0, 10))
        middle_panel.pack_propagate(False)
        
        # Album header
        album_header = ctk.CTkFrame(middle_panel, fg_color="transparent")
        album_header.pack(fill="x", padx=10, pady=10)
        
        self.album_header_label = ctk.CTkLabel(album_header, text="ALBUMS",
                                              font=ctk.CTkFont(family="Bebas Neue", size=22),
                                              text_color=ParagonTheme.TEXT_PRIMARY)
        self.album_header_label.pack(anchor="w")
        
        # Album count
        self.album_count_label = ctk.CTkLabel(middle_panel, text="Select an artist",
                                             text_color=ParagonTheme.TEXT_MUTED,
                                             font=ctk.CTkFont(size=14))
        self.album_count_label.pack(anchor="w", padx=15, pady=(0, 5))
        
        # Album list
        self.album_list = ctk.CTkScrollableFrame(middle_panel, fg_color=ParagonTheme.BG_DARK)
        self.album_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Right panel - Album/Track details
        self.right_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8)
        self.right_panel.pack(side="left", fill="both", expand=True)
        
        # Initial placeholder
        self.detail_placeholder = ctk.CTkLabel(self.right_panel, 
                                               text="Select an artist and album\nto view tracks and details",
                                               text_color=ParagonTheme.TEXT_MUTED,
                                               font=ctk.CTkFont(size=24))
        self.detail_placeholder.pack(expand=True)
        
        # Bottom buttons
        bottom = ctk.CTkFrame(main, fg_color="transparent", height=60)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        
        ParagonButton(bottom, text="CLOSE", command=self.destroy,
                     width=120, height=44,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="right")
    
    def _load_library(self):
        """Load library from cache or scan if needed"""
        cached = LibraryCache.load_cache('music', self.library_path)
        if cached:
            self.status_label.configure(text="Loading from cache...")
            self.update_idletasks()
            self._populate_artist_list(cached)
            self.status_label.configure(text=f"Loaded {len(cached)} artists (cached)")
        else:
            self._scan_library(force=True)
    
    def _scan_library(self, force=False):
        """Scan the library folder for artists"""
        self.artists = []
        self.status_label.configure(text="Scanning...")
        self.update_idletasks()
        
        def scan():
            artists = []
            audio_extensions = {'.mp3', '.flac', '.m4a', '.ogg', '.opus', '.wav', '.aac', '.wma'}
            
            try:
                for item in os.listdir(self.library_path):
                    item_path = os.path.join(self.library_path, item)
                    if os.path.isdir(item_path):
                        # Check if it's an artist folder (contains albums or audio files)
                        artist_info = self._analyze_artist_folder(item_path, audio_extensions)
                        if artist_info:
                            artists.append(artist_info)
            except Exception as e:
                print(f"Error scanning library: {e}")
            
            # Sort by name
            artists.sort(key=lambda x: x['name'].lower())
            
            # Save to cache
            LibraryCache.save_cache('music', self.library_path, artists)
            
            # Only update if dialog still exists
            self.after(0, lambda: self._populate_artist_list(artists) if self.winfo_exists() else None)
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _analyze_artist_folder(self, folder_path: str, audio_extensions: set) -> Optional[Dict]:
        """Analyze a folder to determine if it's an artist folder"""
        folder_name = os.path.basename(folder_path)
        
        album_count = 0
        track_count = 0
        albums = []
        loose_tracks = 0  # Tracks directly in artist folder
        
        # Check for subfolders (albums) and loose tracks
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            if os.path.isdir(item_path):
                # Check if subfolder contains audio files (album)
                album_tracks = 0
                has_cover = False
                for f in os.listdir(item_path):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in audio_extensions:
                        album_tracks += 1
                    if f.lower() in ['cover.jpg', 'cover.png', 'folder.jpg', 'album.jpg', 'front.jpg']:
                        has_cover = True
                
                if album_tracks > 0:
                    album_count += 1
                    track_count += album_tracks
                    albums.append({
                        'name': item,
                        'path': item_path,
                        'track_count': album_tracks,
                        'has_cover': has_cover
                    })
            else:
                # Check for audio files directly in artist folder
                ext = os.path.splitext(item)[1].lower()
                if ext in audio_extensions:
                    track_count += 1
                    loose_tracks += 1
        
        # If there are loose tracks, create a virtual album for them
        if loose_tracks > 0:
            has_cover = any(os.path.exists(os.path.join(folder_path, f)) 
                          for f in ['cover.jpg', 'cover.png', 'folder.jpg', 'album.jpg', 'front.jpg'])
            albums.insert(0, {
                'name': folder_name,  # Use artist/folder name as album name
                'path': folder_path,
                'track_count': loose_tracks,
                'has_cover': has_cover
            })
            album_count += 1
        
        # Skip if no tracks found
        if track_count == 0:
            return None
        
        # Check for artist image
        has_artist_image = any(os.path.exists(os.path.join(folder_path, f)) 
                              for f in ['artist.jpg', 'folder.jpg', 'artist.png'])
        
        return {
            'name': folder_name,
            'path': folder_path,
            'album_count': album_count,
            'track_count': track_count,
            'albums': albums,
            'has_artist_image': has_artist_image,
        }
    
    def _populate_artist_list(self, artists: List[Dict]):
        """Populate the artist list with scanned artists"""
        # Check if dialog still exists
        if not self.winfo_exists():
            return
            
        self.artists = artists
        
        # Clear existing
        try:
            for widget in self.artist_list.winfo_children():
                widget.destroy()
        except:
            return
        self.artist_widgets = {}
        
        # Update count
        total_albums = sum(a['album_count'] for a in artists)
        total_tracks = sum(a['track_count'] for a in artists)
        self.artist_count_label.configure(text=f"{len(artists)} Artists")
        self.status_label.configure(text=f"{len(artists)} artists, {total_albums} albums, {total_tracks} tracks")
        
        # Create artist entries
        for artist in artists:
            self._create_artist_entry(artist)
    
    def _create_artist_entry(self, artist: Dict):
        """Create an artist entry in the list"""
        frame = ctk.CTkFrame(self.artist_list, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        frame.pack(fill="x", pady=2)
        frame.bind("<Button-1>", lambda e, a=artist: self._select_artist(a))
        
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=6)
        inner.bind("<Button-1>", lambda e, a=artist: self._select_artist(a))
        
        # Artist name
        name_lbl = ctk.CTkLabel(inner, text=artist['name'],
                               font=ctk.CTkFont(size=16, weight="bold"),
                               text_color=ParagonTheme.TEXT_PRIMARY,
                               anchor="w")
        name_lbl.pack(fill="x")
        name_lbl.bind("<Button-1>", lambda e, a=artist: self._select_artist(a))
        
        # Album/track count
        info_text = f"{artist['album_count']} albums • {artist['track_count']} tracks"
        info_lbl = ctk.CTkLabel(inner, text=info_text,
                               font=ctk.CTkFont(size=12),
                               text_color=ParagonTheme.TEXT_MUTED,
                               anchor="w")
        info_lbl.pack(fill="x")
        info_lbl.bind("<Button-1>", lambda e, a=artist: self._select_artist(a))
        
        self.artist_widgets[artist['path']] = frame
    
    def _select_artist(self, artist: Dict):
        """Select an artist and show their albums"""
        # Update selection highlight
        for path, widget in self.artist_widgets.items():
            if path == artist['path']:
                widget.configure(fg_color=ParagonTheme.RED_PRIMARY)
            else:
                widget.configure(fg_color=ParagonTheme.BG_TERTIARY)
        
        self.selected_artist = artist
        self.selected_album = None
        
        # Update album header
        self.album_header_label.configure(text=f"ALBUMS - {artist['name']}")
        self.album_count_label.configure(text=f"{artist['album_count']} albums")
        
        # Clear and populate album list
        for widget in self.album_list.winfo_children():
            widget.destroy()
        self.album_widgets = {}
        
        for album in artist.get('albums', []):
            self._create_album_entry(album)
        
        # Clear right panel
        for widget in self.right_panel.winfo_children():
            widget.destroy()
        
        # Show artist summary
        self._show_artist_summary(artist)
    
    def _create_album_entry(self, album: Dict):
        """Create an album entry in the list"""
        frame = ctk.CTkFrame(self.album_list, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        frame.pack(fill="x", pady=2)
        frame.bind("<Button-1>", lambda e, a=album: self._select_album(a))
        
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=6)
        inner.bind("<Button-1>", lambda e, a=album: self._select_album(a))
        
        # Album name
        name_lbl = ctk.CTkLabel(inner, text=album['name'],
                               font=ctk.CTkFont(size=15, weight="bold"),
                               text_color=ParagonTheme.TEXT_PRIMARY,
                               anchor="w")
        name_lbl.pack(fill="x")
        name_lbl.bind("<Button-1>", lambda e, a=album: self._select_album(a))
        
        # Track count and cover status
        status_frame = ctk.CTkFrame(inner, fg_color="transparent")
        status_frame.pack(fill="x", pady=(2, 0))
        status_frame.bind("<Button-1>", lambda e, a=album: self._select_album(a))
        
        track_lbl = ctk.CTkLabel(status_frame, text=f"{album['track_count']} tracks",
                                font=ctk.CTkFont(size=12),
                                text_color=ParagonTheme.TEXT_MUTED)
        track_lbl.pack(side="left")
        track_lbl.bind("<Button-1>", lambda e, a=album: self._select_album(a))
        
        # Cover indicator
        cover_color = "#2d5a27" if album.get('has_cover') else "#5a2727"
        cover_lbl = ctk.CTkLabel(status_frame, text="ART", width=32, height=18,
                                fg_color=cover_color, corner_radius=3,
                                font=ctk.CTkFont(size=10),
                                text_color="white")
        cover_lbl.pack(side="right")
        cover_lbl.bind("<Button-1>", lambda e, a=album: self._select_album(a))
        
        self.album_widgets[album['path']] = frame
    
    def _show_artist_summary(self, artist: Dict):
        """Show artist summary in right panel"""
        header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=15)
        
        ctk.CTkLabel(header, text=artist['name'],
                    font=ctk.CTkFont(family="Bebas Neue", size=36),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(side="left")
        
        # Artist info
        info_frame = ctk.CTkFrame(self.right_panel, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        info_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        info_inner = ctk.CTkFrame(info_frame, fg_color="transparent")
        info_inner.pack(fill="x", padx=15, pady=15)
        
        ctk.CTkLabel(info_inner, text=f"Path: {artist['path']}",
                    font=ctk.CTkFont(size=14),
                    text_color=ParagonTheme.TEXT_MUTED,
                    wraplength=600, anchor="w", justify="left").pack(anchor="w")
        
        ctk.CTkLabel(info_inner, text=f"{artist['album_count']} albums • {artist['track_count']} tracks",
                    font=ctk.CTkFont(size=18),
                    text_color=ParagonTheme.TEXT_SECONDARY).pack(anchor="w", pady=(8, 0))
        
        # Placeholder for album list
        ctk.CTkLabel(self.right_panel, text="← Select an album to view tracks",
                    font=ctk.CTkFont(size=18),
                    text_color=ParagonTheme.TEXT_MUTED).pack(expand=True)
    
    def _select_album(self, album: Dict):
        """Select an album and show its tracks"""
        # Update album selection highlight
        for path, widget in self.album_widgets.items():
            if path == album['path']:
                widget.configure(fg_color=ParagonTheme.RED_PRIMARY)
            else:
                widget.configure(fg_color=ParagonTheme.BG_TERTIARY)
        
        self.selected_album = album
        
        # Clear right panel
        for widget in self.right_panel.winfo_children():
            widget.destroy()
        
        # Show album details
        self._show_album_details(album)
    
    def _show_album_details(self, album: Dict):
        """Show album details and track list in right panel"""
        # Header
        header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=15)
        
        # Album cover if exists
        cover_frame = ctk.CTkFrame(header, fg_color="transparent")
        cover_frame.pack(side="left")
        
        cover_loaded = False
        if HAS_PIL:
            for cover_name in ['cover.jpg', 'cover.png', 'folder.jpg', 'album.jpg', 'front.jpg']:
                cover_path = os.path.join(album['path'], cover_name)
                if os.path.exists(cover_path):
                    try:
                        img = Image.open(cover_path)
                        img.thumbnail((120, 120), Image.Resampling.LANCZOS)
                        photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                        cover_lbl = ctk.CTkLabel(cover_frame, image=photo, text="")
                        cover_lbl.pack(side="left", padx=(0, 15))
                        cover_lbl._img = photo
                        cover_loaded = True
                        break
                    except:
                        pass
        
        if not cover_loaded:
            placeholder = ctk.CTkFrame(cover_frame, fg_color=ParagonTheme.BG_TERTIARY, 
                                      width=120, height=120, corner_radius=6)
            placeholder.pack(side="left", padx=(0, 15))
            placeholder.pack_propagate(False)
            ctk.CTkLabel(placeholder, text="No\nCover", 
                        text_color=ParagonTheme.TEXT_MUTED,
                        font=ctk.CTkFont(size=14)).pack(expand=True)
        
        # Album title and info
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left", fill="both", expand=True)
        
        ctk.CTkLabel(title_frame, text=album['name'],
                    font=ctk.CTkFont(family="Bebas Neue", size=32),
                    text_color=ParagonTheme.TEXT_PRIMARY,
                    anchor="w").pack(anchor="w")
        
        if self.selected_artist:
            ctk.CTkLabel(title_frame, text=self.selected_artist['name'],
                        font=ctk.CTkFont(size=18),
                        text_color=ParagonTheme.GOLD_LIGHT,
                        anchor="w").pack(anchor="w")
        
        ctk.CTkLabel(title_frame, text=f"{album['track_count']} tracks",
                    font=ctk.CTkFont(size=16),
                    text_color=ParagonTheme.TEXT_MUTED,
                    anchor="w").pack(anchor="w", pady=(5, 0))
        
        # Open editor button
        ParagonButton(header, text="📝 OPEN TAG EDITOR", 
                     command=lambda: self._open_album_editor(album),
                     width=180, height=40).pack(side="right", anchor="n")
        
        # Rescan album button
        ParagonButton(header, text="🔄 RESCAN ALBUM", 
                     command=lambda: self._rescan_album(album),
                     width=160, height=40,
                     fg_color=ParagonTheme.BG_TERTIARY,
                     hover_color=ParagonTheme.BG_HOVER).pack(side="right", anchor="n", padx=(0, 10))
        
        # Track list header
        track_header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        track_header.pack(fill="x", padx=15, pady=(10, 5))
        
        ctk.CTkLabel(track_header, text="TRACKS",
                    font=ctk.CTkFont(family="Bebas Neue", size=24),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(side="left")
        
        # Track list
        track_list = ctk.CTkScrollableFrame(self.right_panel, fg_color=ParagonTheme.BG_DARK)
        track_list.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        
        # Get and display tracks
        audio_extensions = {'.mp3', '.flac', '.m4a', '.ogg', '.opus', '.wav', '.aac', '.wma'}
        tracks = []
        
        for f in os.listdir(album['path']):
            ext = os.path.splitext(f)[1].lower()
            if ext in audio_extensions:
                tracks.append(f)
        
        tracks.sort()
        
        for i, track in enumerate(tracks, 1):
            track_frame = ctk.CTkFrame(track_list, fg_color="transparent")
            track_frame.pack(fill="x", pady=1)
            
            # Track number
            ctk.CTkLabel(track_frame, text=f"{i:02d}",
                        font=ctk.CTkFont(size=14),
                        text_color=ParagonTheme.TEXT_MUTED,
                        width=30).pack(side="left")
            
            # Track name
            track_name = os.path.splitext(track)[0]
            ctk.CTkLabel(track_frame, text=track_name,
                        font=ctk.CTkFont(size=15),
                        text_color=ParagonTheme.TEXT_PRIMARY,
                        anchor="w").pack(side="left", fill="x", expand=True, padx=(5, 0))
    
    def _open_album_editor(self, album: Dict):
        """Open tag editor for album tracks"""
        audio_extensions = {'.mp3', '.flac', '.m4a', '.ogg', '.opus', '.wav', '.aac', '.wma'}
        files = []
        
        for f in os.listdir(album['path']):
            ext = os.path.splitext(f)[1].lower()
            if ext in audio_extensions:
                files.append(os.path.join(album['path'], f))
        
        if files:
            dialog = open_child_window(TagEditorDialog(self.master, sorted(files)), self)
    
    def _rescan_album(self, album: Dict):
        """Rescan just this album's folder"""
        self.status_label.configure(text=f"Rescanning {album['name']}...")
        self.update_idletasks()
        
        def scan():
            new_info = self._analyze_album_folder(album['path'])
            if self.winfo_exists():
                self.after(0, lambda: self._on_album_rescan_complete(album, new_info))
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _analyze_album_folder(self, album_path: str) -> Optional[Dict]:
        """Analyze a single album folder"""
        audio_extensions = {'.mp3', '.flac', '.m4a', '.ogg', '.opus', '.wav', '.aac', '.wma'}
        
        album_name = os.path.basename(album_path)
        tracks = []
        
        try:
            for f in os.listdir(album_path):
                ext = os.path.splitext(f)[1].lower()
                if ext in audio_extensions:
                    tracks.append(os.path.join(album_path, f))
        except:
            return None
        
        if not tracks:
            return None
        
        # Check for cover art
        has_cover = any(os.path.exists(os.path.join(album_path, c)) 
                       for c in ['cover.jpg', 'cover.png', 'folder.jpg', 'album.jpg', 'front.jpg'])
        
        return {
            'name': album_name,
            'path': album_path,
            'track_count': len(tracks),
            'has_cover': has_cover
        }
    
    def _on_album_rescan_complete(self, old_album: Dict, new_info: Dict):
        """Update the album after rescan"""
        if not new_info:
            self.status_label.configure(text="Rescan complete (no changes)")
            return
        
        # Update in the albums list for this artist
        for i, a in enumerate(self.albums):
            if a['path'] == old_album['path']:
                self.albums[i] = new_info
                break
        
        # Refresh the details panel
        self._select_album(new_info)
        self.status_label.configure(text=f"Rescanned {new_info['name']}")
    
    def _filter_artists(self):
        """Filter artists based on search text"""
        filter_text = self.artist_filter_entry.get().lower().strip()
        
        for artist in self.artists:
            widget = self.artist_widgets.get(artist['path'])
            if widget:
                if not filter_text or filter_text in artist['name'].lower():
                    widget.pack(fill="x", pady=2)
                else:
                    widget.pack_forget()
    
    def _change_folder(self):
        """Change the library folder"""
        folder = filedialog.askdirectory(title="Select Music Library Folder", initialdir=self.library_path)
        if folder:
            self.library_path = folder
            self.library_path_label.configure(text=folder)
            self._scan_library()


class TVEditorDialog(ctk.CTkToplevel):
    """MediaElch-style TV show editor with Show/Episode modes and full editing capabilities"""
    
    # Font sizes
    FONT_SMALL = 16
    FONT_NORMAL = 18
    FONT_LARGE = 22
    FONT_TITLE = 28
    FONT_HEADER = 20
    
    # Default genres
    DEFAULT_GENRES = [
        "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary",
        "Drama", "Family", "Fantasy", "History", "Horror", "Music", "Mystery",
        "Romance", "Science Fiction", "Thriller", "War", "Western"
    ]
    
    CERTIFICATIONS = ["TV-Y", "TV-Y7", "TV-G", "TV-PG", "TV-14", "TV-MA", "G", "PG", "PG-13", "R", "NC-17", "NR"]
    
    def __init__(self, master, files: List[str]):
        super().__init__(master)
        
        self.files = files
        self.current_file = files[0] if files else None
        self.search_results = []
        self.selected_show = None
        self.show_details = None
        self.episodes_data = {}  # {filename: episode_data}
        self.current_episode = None  # Currently selected episode
        self.edit_mode = "show"  # "show" or "episode"
        self.stream_info = None
        self._poster_photo = None
        self._fanart_photo = None
        self._logo_photo = None
        self._landscape_photo = None
        self._episode_thumb_photo = None
        self.existing_artwork = {}
        
        # Editable fields
        self.field_vars = {}
        self.episode_field_vars = {}
        self.selected_genres = set()
        self.selected_studios = set()
        
        self.title("TV Show Editor")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        self.after(10, lambda: self.state('zoomed'))  # Maximize window
        
        # FORCE window size BEFORE creating UI
        self.geometry("1700x1000+100+50")
        self.update_idletasks()
        self.minsize(1200, 800)
        
        try:
            self._create_ui()
        except Exception as e:
            print(f"ERROR in TVEditorDialog._create_ui: {e}")
            import traceback
            traceback.print_exc()
            return
        
        try:
            self._parse_episode_files()
        except Exception as e:
            print(f"ERROR in _parse_episode_files: {e}")
        
        try:
            self._extract_stream_info()
        except Exception as e:
            print(f"ERROR in _extract_stream_info: {e}")
        
        # Try to load existing NFO and artwork
        if files:
            try:
                loaded = self._load_existing_data()
                if not loaded:
                    parsed = MediaFileParser.parse_tv_episode(os.path.basename(files[0]))
                    if parsed.get('show'):
                        self.search_entry.insert(0, parsed['show'])
            except Exception as e:
                print(f"ERROR loading existing data: {e}")
        
        # Force window size AGAIN after creating UI
        self.update_idletasks()
        self.geometry("1700x1000+100+50")
        self.lift()
        self.focus_force()
    
    def _parse_episode_files(self):
        """Parse all files to extract episode info"""
        for f in self.files:
            basename = os.path.basename(f)
            parsed = MediaFileParser.parse_tv_episode(basename)
            self.episodes_data[f] = {
                'file': f,
                'filename': basename,
                'show': parsed.get('show', ''),
                'season': parsed.get('season', 1),
                'episode': parsed.get('episode', 1),
                'title': '',
                'plot': '',
                'aired': '',
                'rating': 0,
                'runtime': 0,
                'userrating': 0,
                'directors': [],
                'writers': [],
                'guest_stars': [],
                'thumb_path': None,
                'still_path': '',
            }
            
            # Try to load episode NFO if exists
            episode_nfo = NFOParser.find_episode_nfo(f)
            if episode_nfo:
                ep_data = NFOParser.parse_episode_nfo(episode_nfo)
                if ep_data:
                    self.episodes_data[f].update({
                        'title': ep_data.get('title', ''),
                        'plot': ep_data.get('plot', ''),
                        'aired': ep_data.get('aired', ''),
                        'rating': ep_data.get('rating', 0),
                        'runtime': ep_data.get('runtime', 0),
                        'userrating': ep_data.get('userrating', 0),
                        'directors': ep_data.get('directors', []),
                        'writers': ep_data.get('writers', []),
                        'guest_stars': ep_data.get('guest_stars', []),
                        'season': ep_data.get('season', self.episodes_data[f]['season']),
                        'episode': ep_data.get('episode', self.episodes_data[f]['episode']),
                    })
    
    def _load_existing_data(self) -> bool:
        """Load existing tvshow.nfo and artwork"""
        if not self.current_file:
            return False
        
        folder = os.path.dirname(self.current_file)
        print(f"Looking for TV show NFO and artwork in: {folder}")
        
        nfo_path = NFOParser.find_tvshow_nfo(self.current_file)
        self.existing_artwork = NFOParser.find_tvshow_artwork(self.current_file)
        
        if nfo_path:
            print(f"Found existing tvshow.nfo: {nfo_path}")
            show_data = NFOParser.parse_tvshow_nfo(nfo_path)
            
            if show_data and show_data.get('title'):
                self.show_details = show_data
                self._populate_from_nfo(show_data)
                self._load_existing_artwork_previews()
                
                # If no TMDB ID in NFO, try to auto-search
                if not show_data.get('id'):
                    print("No TMDB ID in NFO, searching TMDB...")
                    self._auto_search_tmdb(show_data.get('title'), show_data.get('year'))
                
                return True
        
        if any(self.existing_artwork.values()):
            self._load_existing_artwork_previews()
        
        return False
    
    def _auto_search_tmdb(self, title: str, year: str = None):
        """Auto-search TMDB to get show ID for episode scraping"""
        def search():
            results = TMDBAPI.search_tv(title, year)
            if results:
                # Take the first result
                best_match = results[0]
                print(f"Auto-matched to TMDB: {best_match.get('title')} (ID: {best_match.get('id')})")
                
                # Get full details
                details = TMDBAPI.get_tv_details(best_match['id'])
                if details:
                    self.after(0, lambda: self._merge_tmdb_details(details))
        
        threading.Thread(target=search, daemon=True).start()
    
    def _merge_tmdb_details(self, details: Dict):
        """Merge TMDB details into show_details (without overwriting NFO data)"""
        if not self.show_details:
            self.show_details = details
        else:
            # Only add TMDB ID and other missing fields
            self.show_details['id'] = details.get('id')
            self.show_details['tmdb_id'] = details.get('id')
            
            # Add paths for artwork if not already present
            if not self.show_details.get('poster_path'):
                self.show_details['poster_path'] = details.get('poster_path')
            if not self.show_details.get('backdrop_path'):
                self.show_details['backdrop_path'] = details.get('backdrop_path')
            
            # Update TMDB ID field in UI
            if 'tmdb_id' in self.field_vars:
                self.field_vars['tmdb_id'].set(str(details.get('id', '')))
        
        print(f"Show linked to TMDB ID: {self.show_details.get('id')}")
    
    def _create_ui(self):
        """Create the TV editor UI"""
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        main.pack(fill="both", expand=True, padx=4, pady=4)
        
        inner = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        self._create_header(inner)
        
        content = ctk.CTkFrame(inner, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        
        # Left panel - Episodes list
        self.left_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=280)
        self.left_panel.pack(side="left", fill="y", padx=(0, 10))
        self.left_panel.pack_propagate(False)
        
        # Mode switcher at top of left panel
        mode_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        mode_frame.pack(fill="x", padx=10, pady=10)
        
        self.show_mode_btn = ctk.CTkButton(
            mode_frame, text="📺 SHOW", height=35,
            fg_color=ParagonTheme.RED_PRIMARY,
            hover_color=ParagonTheme.RED_LIGHT,
            command=lambda: self._switch_mode("show")
        )
        self.show_mode_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        self.episode_mode_btn = ctk.CTkButton(
            mode_frame, text="🎬 EPISODES", height=35,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            command=lambda: self._switch_mode("episode")
        )
        self.episode_mode_btn.pack(side="left", expand=True, fill="x", padx=(5, 0))
        
        # Search results (for show mode)
        self.results_container = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.results_container.pack(fill="both", expand=True)
        
        ParagonLabel(self.results_container, text="SEARCH RESULTS", style="header").pack(anchor="w", padx=10, pady=(0, 5))
        self.results_list = ctk.CTkScrollableFrame(self.results_container, fg_color=ParagonTheme.BG_DARK)
        self.results_list.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        ParagonLabel(self.results_list, text="Search for a TV show", style="muted").pack(pady=20)
        
        # Episodes list (for episode mode) - hidden initially
        self.episodes_container = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        
        ParagonLabel(self.episodes_container, text="EPISODES", style="header").pack(anchor="w", padx=10, pady=(0, 5))
        
        # Scrape all button
        scrape_btn_frame = ctk.CTkFrame(self.episodes_container, fg_color="transparent")
        scrape_btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ParagonButton(scrape_btn_frame, text="🔄 SCRAPE ALL EPISODES", 
                     command=self._scrape_all_episodes,
                     width=220, height=35).pack(side="left")
        
        self.episodes_list = ctk.CTkScrollableFrame(self.episodes_container, fg_color=ParagonTheme.BG_DARK)
        self.episodes_list.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        
        # Middle - Tabs (will switch between show tabs and episode tabs)
        middle_frame = ctk.CTkFrame(content, fg_color="transparent")
        middle_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        # Show tabs
        self.show_tabs = ctk.CTkTabview(middle_frame, fg_color=ParagonTheme.BG_SECONDARY,
                                        segmented_button_fg_color=ParagonTheme.BG_TERTIARY,
                                        segmented_button_selected_color=ParagonTheme.RED_PRIMARY)
        self.show_tabs.pack(fill="both", expand=True)
        
        self.show_tabs.add("Information")
        self.show_tabs.add("Extended")
        self.show_tabs.add("Stream Details")
        
        self._create_show_info_tab(self.show_tabs.tab("Information"))
        self._create_show_extended_tab(self.show_tabs.tab("Extended"))
        self._create_stream_tab(self.show_tabs.tab("Stream Details"))
        
        # Episode tabs - hidden initially
        self.episode_tabs = ctk.CTkTabview(middle_frame, fg_color=ParagonTheme.BG_SECONDARY,
                                           segmented_button_fg_color=ParagonTheme.BG_TERTIARY,
                                           segmented_button_selected_color=ParagonTheme.RED_PRIMARY)
        
        self.episode_tabs.add("Episode Info")
        self.episode_tabs.add("Stream Details")
        
        self._create_episode_info_tab(self.episode_tabs.tab("Episode Info"))
        self._create_episode_stream_tab(self.episode_tabs.tab("Stream Details"))
        
        # Right side - Artwork
        right_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=300)
        right_panel.pack(side="right", fill="y")
        right_panel.pack_propagate(False)
        
        self._create_artwork_panel(right_panel)
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(5, 12))
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self.destroy, width=100).pack(side="left")
        ParagonButton(btn_frame, text="SAVE ALL", command=self._save_all, width=130).pack(side="right")
    
    def _switch_mode(self, mode: str):
        """Switch between show and episode editing modes"""
        self.edit_mode = mode
        
        if mode == "show":
            self.show_mode_btn.configure(fg_color=ParagonTheme.RED_PRIMARY)
            self.episode_mode_btn.configure(fg_color=ParagonTheme.BG_TERTIARY)
            
            self.episodes_container.pack_forget()
            self.results_container.pack(fill="both", expand=True)
            
            self.episode_tabs.pack_forget()
            self.show_tabs.pack(fill="both", expand=True)
        else:
            self.show_mode_btn.configure(fg_color=ParagonTheme.BG_TERTIARY)
            self.episode_mode_btn.configure(fg_color=ParagonTheme.RED_PRIMARY)
            
            self.results_container.pack_forget()
            self.episodes_container.pack(fill="both", expand=True)
            self._populate_episodes_list()
            
            self.show_tabs.pack_forget()
            self.episode_tabs.pack(fill="both", expand=True)
    
    def _populate_episodes_list(self):
        """Populate the episodes list"""
        for widget in self.episodes_list.winfo_children():
            widget.destroy()
        
        # Sort episodes by season and episode number
        sorted_files = sorted(self.files, key=lambda f: (
            self.episodes_data.get(f, {}).get('season', 0),
            self.episodes_data.get(f, {}).get('episode', 0)
        ))
        
        current_season = None
        for f in sorted_files:
            ep_data = self.episodes_data.get(f, {})
            season = ep_data.get('season', 1)
            episode = ep_data.get('episode', 1)
            title = ep_data.get('title', '') or os.path.basename(f)
            
            # Season header
            if season != current_season:
                current_season = season
                season_lbl = ctk.CTkLabel(
                    self.episodes_list, text=f"Season {season}",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=ParagonTheme.GOLD
                )
                season_lbl.pack(fill="x", padx=5, pady=(10, 5))
            
            # Episode row
            ep_frame = ctk.CTkFrame(self.episodes_list, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=4)
            ep_frame.pack(fill="x", pady=2, padx=5)
            ep_frame.bind("<Button-1>", lambda e, file=f: self._select_episode(file))
            
            ep_text = f"E{episode:02d}: {title[:30]}{'...' if len(title) > 30 else ''}"
            ep_lbl = ctk.CTkLabel(ep_frame, text=ep_text, font=ctk.CTkFont(size=13),
                                 text_color=ParagonTheme.TEXT_PRIMARY, anchor="w")
            ep_lbl.pack(fill="x", padx=10, pady=6)
            ep_lbl.bind("<Button-1>", lambda e, file=f: self._select_episode(file))
    
    def _select_episode(self, file: str):
        """Select an episode for editing"""
        self.current_episode = file
        self.current_file = file
        
        # Highlight in list
        for widget in self.episodes_list.winfo_children():
            if isinstance(widget, ctk.CTkFrame):
                widget.configure(fg_color=ParagonTheme.BG_TERTIARY)
        
        # Populate episode fields from local data first
        ep_data = self.episodes_data.get(file, {})
        
        if 'ep_season' in self.episode_field_vars:
            self.episode_field_vars['ep_season'].set(str(ep_data.get('season', 1)))
        if 'ep_episode' in self.episode_field_vars:
            self.episode_field_vars['ep_episode'].set(str(ep_data.get('episode', 1)))
        if 'ep_title' in self.episode_field_vars:
            self.episode_field_vars['ep_title'].set(ep_data.get('title', ''))
        if 'ep_aired' in self.episode_field_vars:
            self.episode_field_vars['ep_aired'].set(ep_data.get('aired', ''))
        if 'ep_rating' in self.episode_field_vars:
            self.episode_field_vars['ep_rating'].set(str(ep_data.get('rating', '') or ''))
        
        # Populate extended fields from cache
        if 'ep_runtime' in self.episode_field_vars:
            runtime = ep_data.get('runtime', '')
            self.episode_field_vars['ep_runtime'].set(str(runtime) if runtime else '')
        if 'ep_userrating' in self.episode_field_vars:
            userrating = ep_data.get('userrating', '')
            self.episode_field_vars['ep_userrating'].set(str(userrating) if userrating else '')
        if 'ep_directors' in self.episode_field_vars:
            directors = ep_data.get('directors', [])
            if isinstance(directors, list):
                self.episode_field_vars['ep_directors'].set(', '.join(directors))
            else:
                self.episode_field_vars['ep_directors'].set(str(directors) if directors else '')
        if 'ep_writers' in self.episode_field_vars:
            writers = ep_data.get('writers', [])
            if isinstance(writers, list):
                self.episode_field_vars['ep_writers'].set(', '.join(writers))
            else:
                self.episode_field_vars['ep_writers'].set(str(writers) if writers else '')
        if 'ep_guests' in self.episode_field_vars:
            guests = ep_data.get('guest_stars', [])
            if isinstance(guests, list):
                if guests and isinstance(guests[0], dict):
                    guest_names = [g.get('name', '') for g in guests if g.get('name')]
                    self.episode_field_vars['ep_guests'].set(', '.join(guest_names))
                else:
                    self.episode_field_vars['ep_guests'].set(', '.join(guests))
            else:
                self.episode_field_vars['ep_guests'].set(str(guests) if guests else '')
        
        if hasattr(self, 'ep_plot_text'):
            self.ep_plot_text.delete("1.0", "end")
            self.ep_plot_text.insert("1.0", ep_data.get('plot', ''))
        
        if hasattr(self, 'ep_file_label'):
            self.ep_file_label.configure(text=os.path.basename(file))
        
        # Reset thumbnail to placeholder
        self._safe_update_ep_thumb(image=None, text="Loading...")
        
        # Extract stream info for this episode
        self._extract_stream_info()
        self._update_episode_stream_display()
        
        # Check for local thumbnail first (episode-thumb.jpg)
        local_thumb = self._find_local_episode_thumb(file)
        if local_thumb:
            self._load_local_episode_thumb(local_thumb)
        # If we have cached still_path from TMDB, load it
        elif ep_data.get('still_path'):
            self._load_episode_thumbnail(ep_data['still_path'])
        # Otherwise, if we have a show selected, fetch episode data from TMDB
        elif self.show_details and self.show_details.get('id'):
            self._fetch_episode_data(ep_data.get('season', 1), ep_data.get('episode', 1))
        # No show selected and no cached data
        else:
            self._safe_update_ep_thumb(image=None, text="No thumbnail\navailable")
    
    def _find_local_episode_thumb(self, episode_path: str) -> Optional[str]:
        """Find local thumbnail for an episode (episodename-thumb.jpg)"""
        if not episode_path:
            return None
        
        folder = os.path.dirname(episode_path)
        basename = os.path.splitext(os.path.basename(episode_path))[0]
        
        # Check for episode-thumb.jpg (our format and MediaElch format)
        thumb_path = os.path.join(folder, f"{basename}-thumb.jpg")
        if os.path.exists(thumb_path):
            return thumb_path
        
        # Also check for .png variant
        thumb_path_png = os.path.join(folder, f"{basename}-thumb.png")
        if os.path.exists(thumb_path_png):
            return thumb_path_png
        
        return None
    
    def _load_local_episode_thumb(self, thumb_path: str):
        """Load episode thumbnail from local file"""
        if not thumb_path or not os.path.exists(thumb_path):
            self._safe_update_ep_thumb(image=None, text="No thumbnail\navailable")
            return
        
        try:
            pil_img = Image.open(thumb_path)
            pil_img.thumbnail((280, 160), Image.Resampling.LANCZOS)
            
            # Store PIL image to prevent garbage collection
            self._current_pil_thumb = pil_img
            
            photo = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, 
                                size=(pil_img.width, pil_img.height))
            # Store CTkImage reference
            self._episode_thumb_photo = photo
            
            self._safe_update_ep_thumb(image=photo, text="")
            
            # Update cache
            if self.current_episode in self.episodes_data:
                self.episodes_data[self.current_episode]['local_thumb'] = thumb_path
                
        except Exception as e:
            print(f"Error loading local thumbnail: {e}")
            self._safe_update_ep_thumb(image=None, text="Error loading\nthumbnail")
    
    def _fetch_episode_data(self, season: int, episode: int):
        """Fetch episode data from TMDB and populate fields"""
        if not self.show_details or not self.show_details.get('id'):
            return
        
        show_id = self.show_details['id']
        
        def fetch():
            ep_info = TMDBAPI.get_tv_episode(show_id, season, episode)
            if ep_info:
                self.after(0, lambda: self._populate_episode_from_tmdb(ep_info))
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _populate_episode_from_tmdb(self, ep_info: Dict):
        """Populate episode fields from TMDB data"""
        if not ep_info:
            return
        
        # Only populate if fields are empty (don't overwrite existing data)
        current_title = self.episode_field_vars.get('ep_title', ctk.StringVar()).get()
        current_plot = self.ep_plot_text.get("1.0", "end-1c").strip() if hasattr(self, 'ep_plot_text') else ''
        
        if not current_title and ep_info.get('name'):
            self.episode_field_vars['ep_title'].set(ep_info['name'])
        
        if not current_plot and ep_info.get('overview'):
            if hasattr(self, 'ep_plot_text'):
                self.ep_plot_text.delete("1.0", "end")
                self.ep_plot_text.insert("1.0", ep_info['overview'])
        
        current_aired = self.episode_field_vars.get('ep_aired', ctk.StringVar()).get()
        if not current_aired and ep_info.get('air_date'):
            self.episode_field_vars['ep_aired'].set(ep_info['air_date'])
        
        current_rating = self.episode_field_vars.get('ep_rating', ctk.StringVar()).get()
        if not current_rating and ep_info.get('vote_average'):
            self.episode_field_vars['ep_rating'].set(str(round(ep_info['vote_average'], 1)))
        
        # Populate runtime if empty
        current_runtime = self.episode_field_vars.get('ep_runtime', ctk.StringVar()).get()
        if not current_runtime and ep_info.get('runtime'):
            self.episode_field_vars['ep_runtime'].set(str(ep_info['runtime']))
        
        # Populate directors if empty
        current_directors = self.episode_field_vars.get('ep_directors', ctk.StringVar()).get()
        if not current_directors and ep_info.get('directors'):
            self.episode_field_vars['ep_directors'].set(', '.join(ep_info['directors']))
        
        # Populate writers if empty
        current_writers = self.episode_field_vars.get('ep_writers', ctk.StringVar()).get()
        if not current_writers and ep_info.get('writers'):
            self.episode_field_vars['ep_writers'].set(', '.join(ep_info['writers']))
        
        # Populate guest stars if empty
        current_guests = self.episode_field_vars.get('ep_guests', ctk.StringVar()).get()
        if not current_guests and ep_info.get('guest_stars'):
            guest_names = [g.get('name', '') for g in ep_info['guest_stars'] if g.get('name')]
            self.episode_field_vars['ep_guests'].set(', '.join(guest_names[:10]))  # Limit to 10
        
        # Update local episode data cache
        if self.current_episode:
            self.episodes_data[self.current_episode].update({
                'title': self.episode_field_vars.get('ep_title', ctk.StringVar()).get(),
                'plot': self.ep_plot_text.get("1.0", "end-1c") if hasattr(self, 'ep_plot_text') else '',
                'aired': self.episode_field_vars.get('ep_aired', ctk.StringVar()).get(),
                'rating': ep_info.get('vote_average', 0),
                'runtime': ep_info.get('runtime', 0),
                'still_path': ep_info.get('still_path', ''),
                'directors': ep_info.get('directors', []),
                'writers': ep_info.get('writers', []),
                'guest_stars': ep_info.get('guest_stars', []),
            })
        
        # Always load episode thumbnail if available (regardless of other field states)
        if ep_info.get('still_path') and hasattr(self, 'ep_thumb_label'):
            self._load_episode_thumbnail(ep_info['still_path'])
        elif hasattr(self, 'ep_thumb_label'):
            # No thumbnail available from TMDB
            self.ep_thumb_label.configure(image=None, text="No thumbnail\navailable")
        
        # Update status label
        if hasattr(self, 'ep_status_label'):
            self.ep_status_label.configure(
                text=f"✓ TMDB: {ep_info.get('name', 'Loaded')}",
                text_color=ParagonTheme.SUCCESS
            )
    
    def _safe_update_ep_thumb(self, image=None, text=""):
        """Safely update episode thumbnail, recreating label if corrupted"""
        try:
            if hasattr(self, 'ep_thumb_label') and self.ep_thumb_label.winfo_exists():
                # Store image reference on the label itself to prevent garbage collection
                self.ep_thumb_label._current_image = image
                self.ep_thumb_label.configure(image=image, text=text)
        except Exception as e:
            # Only log if it's not the expected image error
            if "pyimage" not in str(e):
                print(f"Thumbnail label error: {e}")
            # Recreate the label
            if hasattr(self, 'ep_thumb_frame'):
                try:
                    # Destroy old label if it exists
                    if hasattr(self, 'ep_thumb_label'):
                        try:
                            self.ep_thumb_label.destroy()
                        except:
                            pass
                    # Create new label
                    self.ep_thumb_label = ctk.CTkLabel(
                        self.ep_thumb_frame, 
                        text=text if text else "Episode Thumbnail",
                        image=image,
                        text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=12)
                    )
                    # Store image reference on the label
                    self.ep_thumb_label._current_image = image
                    self.ep_thumb_label.pack(expand=True)
                except Exception as e2:
                    print(f"Failed to recreate thumbnail label: {e2}")
    
    def _load_episode_thumbnail(self, still_path: str):
        """Load episode thumbnail from TMDB"""
        if not still_path:
            self.after(0, lambda: self._safe_update_ep_thumb(image=None, text="No thumbnail\navailable"))
            return
        
        def load():
            try:
                print(f"Loading episode thumbnail: {still_path}")
                data = TMDBAPI.download_image(still_path, 'w300')
                if data and HAS_PIL:
                    img = Image.open(io.BytesIO(data))
                    img.thumbnail((280, 160), Image.Resampling.LANCZOS)
                    
                    # Store PIL image to prevent garbage collection
                    self._current_pil_thumb = img
                    
                    photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                    # Store CTkImage reference to prevent garbage collection
                    self._episode_thumb_photo = photo
                    
                    self.after(0, lambda p=photo: self._safe_update_ep_thumb(image=p, text=""))
                    print(f"Episode thumbnail loaded successfully")
                else:
                    print(f"No image data returned for thumbnail")
                    self.after(0, lambda: self._safe_update_ep_thumb(image=None, text="No thumbnail\navailable"))
            except Exception as e:
                print(f"Error loading episode thumbnail: {e}")
                self.after(0, lambda: self._safe_update_ep_thumb(image=None, text="Error loading\nthumbnail"))
        
        threading.Thread(target=load, daemon=True).start()
    
    def _capture_episode_frame(self):
        """Capture a random frame from the video file using ffmpeg"""
        if not self.current_episode:
            messagebox.showwarning("No Episode", "Please select an episode first")
            return
        
        if not os.path.exists(self.current_episode):
            messagebox.showerror("File Not Found", f"Video file not found:\n{self.current_episode}")
            return
        
        # Check if ffmpeg is available
        import shutil
        import subprocess
        import random
        import tempfile
        
        ffmpeg_path = shutil.which('ffmpeg')
        ffprobe_path = shutil.which('ffprobe')
        
        if not ffmpeg_path or not ffprobe_path:
            messagebox.showerror("FFmpeg Required", 
                "FFmpeg is required to capture frames from video.\n\n"
                "Install with: sudo apt install ffmpeg")
            return
        
        # Update UI to show capturing
        self._safe_update_ep_thumb(image=None, text="Capturing frame...")
        
        # Store video path before thread
        video_path = self.current_episode
        
        def capture():
            try:
                # Get video duration using ffprobe
                probe_cmd = [
                    ffprobe_path, '-v', 'error', 
                    '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    video_path
                ]
                result = subprocess.run(probe_cmd, capture_output=True, text=True)
                duration = float(result.stdout.strip()) if result.stdout.strip() else 0
                
                if duration <= 0:
                    # Fallback: try to get duration from stream
                    probe_cmd2 = [
                        ffprobe_path, '-v', 'error',
                        '-select_streams', 'v:0',
                        '-show_entries', 'stream=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1',
                        video_path
                    ]
                    result2 = subprocess.run(probe_cmd2, capture_output=True, text=True)
                    duration = float(result2.stdout.strip()) if result2.stdout.strip() else 600
                
                # Pick a random time between 10% and 90% of the video
                min_time = duration * 0.1
                max_time = duration * 0.9
                random_time = random.uniform(min_time, max_time)
                
                # Create temp file for the frame
                temp_dir = tempfile.gettempdir()
                temp_frame = os.path.join(temp_dir, f"pyrenamer_frame_{os.getpid()}.jpg")
                
                # Extract frame using ffmpeg
                ffmpeg_cmd = [
                    ffmpeg_path, '-y',
                    '-ss', str(random_time),
                    '-i', video_path,
                    '-vframes', '1',
                    '-q:v', '2',
                    temp_frame
                ]
                result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
                
                if result.returncode != 0 or not os.path.exists(temp_frame):
                    raise Exception(f"FFmpeg failed: {result.stderr}")
                
                # Load the captured frame
                if HAS_PIL:
                    img = Image.open(temp_frame)
                    
                    # Save as episode thumbnail
                    folder = os.path.dirname(video_path)
                    basename = os.path.splitext(os.path.basename(video_path))[0]
                    thumb_path = os.path.join(folder, f"{basename}-thumb.jpg")
                    
                    # Resize to standard thumbnail size (typically 400x225 for 16:9)
                    thumb_img = img.copy()
                    thumb_img.thumbnail((400, 225), Image.Resampling.LANCZOS)
                    thumb_img.save(thumb_path, "JPEG", quality=90)
                    
                    # Clean up temp file
                    try:
                        os.remove(temp_frame)
                    except:
                        pass
                    
                    # Store values for UI callback
                    time_str = f"{int(random_time//60)}:{int(random_time%60):02d}"
                    thumb_name = os.path.basename(thumb_path)
                    
                    # Store thumb_path in class for UI update
                    self._pending_thumb_path = thumb_path
                    self._pending_thumb_info = (thumb_name, time_str)
                    
                    # Update UI in main thread - load from saved file
                    self.after(0, self._update_captured_thumb)
                
            except Exception as exc:
                error_msg = str(exc)
                print(f"Error capturing frame: {error_msg}")
                self._pending_capture_error = error_msg
                self.after(0, self._show_capture_error)
        
        threading.Thread(target=capture, daemon=True).start()
    
    def _update_captured_thumb(self):
        """Update UI with captured thumbnail - runs in main thread"""
        try:
            thumb_path = getattr(self, '_pending_thumb_path', None)
            thumb_info = getattr(self, '_pending_thumb_info', ('', ''))
            
            if thumb_path and os.path.exists(thumb_path):
                # Load from saved file in main thread
                pil_img = Image.open(thumb_path)
                pil_img.thumbnail((280, 160), Image.Resampling.LANCZOS)
                
                # Keep PIL image alive by storing it
                self._current_pil_thumb = pil_img
                
                photo = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, 
                                    size=(pil_img.width, pil_img.height))
                # Store CTkImage reference to prevent garbage collection
                self._episode_thumb_photo = photo
                
                self._safe_update_ep_thumb(image=photo, text="")
                
                # Update cache
                if self.current_episode in self.episodes_data:
                    self.episodes_data[self.current_episode]['local_thumb'] = thumb_path
                
                # Show time in status label instead of dialog
                thumb_name, time_str = thumb_info
                if hasattr(self, 'ep_status_label'):
                    self.ep_status_label.configure(
                        text=f"✓ Frame captured at {time_str}\nClick again for different frame",
                        text_color=ParagonTheme.SUCCESS
                    )
        except Exception as e:
            print(f"Error updating thumbnail UI: {e}")
            self._safe_update_ep_thumb(image=None, text="Error displaying")
    
    def _show_capture_error(self):
        """Show capture error - runs in main thread"""
        error_msg = getattr(self, '_pending_capture_error', 'Unknown error')
        self._safe_update_ep_thumb(image=None, text="Capture failed")
        messagebox.showerror("Capture Error", f"Failed to capture frame:\n{error_msg}")
    
    def _capture_new_frame(self):
        """Capture another random frame (for use by a 'next' button)"""
        self._capture_episode_frame()
    
    def _fetch_all_episodes_for_season(self, season: int):
        """Fetch all episode data for a season from TMDB"""
        if not self.show_details or not self.show_details.get('id'):
            return
        
        show_id = self.show_details['id']
        
        def fetch():
            season_data = TMDBAPI.get_tv_season(show_id, season)
            if season_data and season_data.get('episodes'):
                self.after(0, lambda: self._cache_season_episodes(season, season_data['episodes']))
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _cache_season_episodes(self, season: int, episodes: List[Dict]):
        """Cache episode data from TMDB for quick access"""
        if not hasattr(self, 'tmdb_episodes'):
            self.tmdb_episodes = {}
        
        for ep in episodes:
            key = (season, ep.get('episode_number', 0))
            self.tmdb_episodes[key] = ep
        
        # Update any matching files in our episode data
        for file, ep_data in self.episodes_data.items():
            if ep_data.get('season') == season:
                ep_num = ep_data.get('episode', 0)
                tmdb_ep = self.tmdb_episodes.get((season, ep_num))
                if tmdb_ep:
                    # Update with TMDB data if local data is empty
                    if not ep_data.get('title'):
                        ep_data['title'] = tmdb_ep.get('name', '')
                    if not ep_data.get('plot'):
                        ep_data['plot'] = tmdb_ep.get('overview', '')
                    if not ep_data.get('aired'):
                        ep_data['aired'] = tmdb_ep.get('air_date', '')
                    if not ep_data.get('rating'):
                        ep_data['rating'] = tmdb_ep.get('vote_average', 0)
                    # Always update still_path for thumbnails
                    if tmdb_ep.get('still_path'):
                        ep_data['still_path'] = tmdb_ep.get('still_path', '')
        
        # Refresh the episodes list to show updated titles
        self._populate_episodes_list()
    
    def _scrape_all_episodes(self):
        """Scrape all episode data from TMDB for all seasons"""
        if not self.show_details or not self.show_details.get('id'):
            messagebox.showwarning("No Show Selected", 
                                   "Please search and select a TV show first (in SHOW mode).")
            return
        
        show_id = self.show_details['id']
        
        # Find all unique seasons in our files
        seasons = set()
        for ep_data in self.episodes_data.values():
            seasons.add(ep_data.get('season', 1))
        
        if not seasons:
            messagebox.showinfo("No Episodes", "No episodes found to scrape.")
            return
        
        # Show progress
        total_seasons = len(seasons)
        
        def scrape_seasons():
            scraped = 0
            for season in sorted(seasons):
                season_data = TMDBAPI.get_tv_season(show_id, season)
                if season_data and season_data.get('episodes'):
                    self.after(0, lambda s=season, eps=season_data['episodes']: 
                              self._cache_season_episodes(s, eps))
                scraped += 1
            
            self.after(0, lambda: messagebox.showinfo(
                "Scraping Complete", 
                f"Scraped {scraped} season(s) from TMDB.\n\n"
                f"Episode titles and plots have been updated."
            ))
        
        threading.Thread(target=scrape_seasons, daemon=True).start()
        messagebox.showinfo("Scraping", f"Scraping {total_seasons} season(s) from TMDB...\n\nThis may take a moment.")
    
    def _create_header(self, parent):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(10, 5))
        
        ctk.CTkLabel(
            header, text="TV SHOW EDITOR",
            font=ctk.CTkFont(family="Bebas Neue", size=self.FONT_TITLE, weight="bold"),
            text_color=ParagonTheme.RED_LIGHT
        ).pack(side="left")
        
        ctk.CTkButton(
            header, text="□", width=35, height=35,
            fg_color="transparent", hover_color=ParagonTheme.BG_HOVER,
            command=self._toggle_maximize
        ).pack(side="right", padx=5)
        
        # Search bar
        search_container = ctk.CTkFrame(parent, fg_color="transparent")
        search_container.pack(fill="x", padx=15, pady=(5, 15))
        
        search_frame = ctk.CTkFrame(search_container, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=8)
        search_frame.pack(anchor="center")
        
        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="TV Show title...",
                                         fg_color="transparent", border_width=0, width=350,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL), height=45)
        self.search_entry.pack(side="left", padx=(15, 5), pady=10)
        self.search_entry.bind('<Return>', lambda e: self._search())
        
        self.year_entry = ctk.CTkEntry(search_frame, placeholder_text="Year",
                                       fg_color="transparent", border_width=0, width=100,
                                       font=ctk.CTkFont(size=self.FONT_NORMAL), height=45)
        self.year_entry.pack(side="left", padx=5, pady=10)
        
        ParagonButton(search_frame, text="SEARCH", command=self._search, width=120, height=45).pack(side="left", padx=(5, 15), pady=10)
    
    def _toggle_maximize(self):
        try:
            current_state = self.state()
            if current_state == 'zoomed' or current_state == 'maximized':
                self.state('normal')
            else:
                self.state('zoomed')
        except:
            self.attributes('-fullscreen', not self.attributes('-fullscreen'))
    
    def _create_show_info_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        self._add_field(scroll, "Files", "files", readonly=True)
        
        id_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        id_frame.pack(fill="x", pady=4)
        
        ctk.CTkLabel(id_frame, text="TMDB ID", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['tmdb_id'] = ctk.StringVar()
        ctk.CTkEntry(id_frame, textvariable=self.field_vars['tmdb_id'], width=150,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", padx=(0, 20))
        
        ctk.CTkLabel(id_frame, text="TVDB ID", width=100, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['tvdb_id'] = ctk.StringVar()
        ctk.CTkEntry(id_frame, textvariable=self.field_vars['tvdb_id'], width=120,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left")
        
        self._add_field(scroll, "Name", "title")
        self._add_field(scroll, "Original Name", "original_title")
        self._add_field(scroll, "Sort Title", "sort_title")
        self._add_field(scroll, "Tagline", "tagline")
        
        rating_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        rating_frame.pack(fill="x", pady=6)
        ctk.CTkLabel(rating_frame, text="Rating", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        rating_info = ctk.CTkFrame(rating_frame, fg_color=ParagonTheme.BG_DARK, corner_radius=4)
        rating_info.pack(side="left", fill="x", expand=True)
        self.rating_label = ctk.CTkLabel(rating_info, text="TMDB: --",
                                         text_color=ParagonTheme.TEXT_PRIMARY,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.rating_label.pack(padx=10, pady=8, anchor="w")
        
        premiere_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        premiere_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(premiere_frame, text="Premiered", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['premiered'] = ctk.StringVar()
        ctk.CTkEntry(premiere_frame, textvariable=self.field_vars['premiered'], width=130,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(premiere_frame, text="Status", width=80, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['status'] = ctk.StringVar()
        ctk.CTkOptionMenu(premiere_frame, variable=self.field_vars['status'],
                         values=["", "Continuing", "Ended", "Canceled", "In Production"],
                         fg_color=ParagonTheme.BG_DARK,
                         button_color=ParagonTheme.RED_PRIMARY,
                         font=ctk.CTkFont(size=self.FONT_NORMAL),
                         height=36).pack(side="left")
        
        cert_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        cert_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(cert_frame, text="Certification", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['certification'] = ctk.StringVar()
        ctk.CTkOptionMenu(cert_frame, variable=self.field_vars['certification'],
                         values=[""] + self.CERTIFICATIONS,
                         fg_color=ParagonTheme.BG_DARK,
                         button_color=ParagonTheme.RED_PRIMARY,
                         font=ctk.CTkFont(size=self.FONT_NORMAL),
                         height=36).pack(side="left")
        
        self._add_field(scroll, "Network", "studio")
        
        plot_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        plot_frame.pack(fill="x", pady=6)
        ctk.CTkLabel(plot_frame, text="Plot", width=120, anchor="ne",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10), anchor="n")
        self.plot_text = ctk.CTkTextbox(plot_frame, height=120, fg_color=ParagonTheme.BG_DARK,
                                        font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.plot_text.pack(side="left", fill="x", expand=True)
    
    def _add_field(self, parent, label, key, readonly=False):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=4)
        ctk.CTkLabel(frame, text=label, width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars[key] = ctk.StringVar()
        entry = ctk.CTkEntry(frame, textvariable=self.field_vars[key],
                            fg_color=ParagonTheme.BG_DARK,
                            font=ctk.CTkFont(size=self.FONT_NORMAL),
                            height=36,
                            state="disabled" if readonly else "normal")
        entry.pack(side="left", fill="x", expand=True)
    
    def _create_show_extended_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        ParagonLabel(scroll, text="Genres", style="header").pack(anchor="w", pady=(0, 8))
        self.genres_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.genres_frame.pack(fill="x", pady=(0, 20))
        self._create_genre_chips()
        
        ParagonLabel(scroll, text="Network/Studio", style="header").pack(anchor="w", pady=(0, 8))
        self.studios_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6, height=80)
        self.studios_frame.pack(fill="x", pady=(0, 15))
        self.studios_label = ctk.CTkLabel(self.studios_frame, text="No network/studio", 
                                          text_color=ParagonTheme.TEXT_SECONDARY,
                                          font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.studios_label.pack(padx=15, pady=15, anchor="w")
    
    def _create_genre_chips(self):
        for widget in self.genres_frame.winfo_children():
            widget.destroy()
        
        # Get all genres including custom ones
        try:
            all_genres = MovieEditorDialog.get_all_genres()
        except:
            all_genres = self.DEFAULT_GENRES
        
        row_frame = None
        for i, genre in enumerate(all_genres):
            if i % 5 == 0:
                row_frame = ctk.CTkFrame(self.genres_frame, fg_color="transparent")
                row_frame.pack(fill="x", padx=8, pady=4)
            
            is_selected = genre in self.selected_genres
            btn = ctk.CTkButton(
                row_frame, text=genre, height=36,
                fg_color=ParagonTheme.RED_PRIMARY if is_selected else ParagonTheme.BG_TERTIARY,
                hover_color=ParagonTheme.RED_LIGHT if is_selected else ParagonTheme.BG_HOVER,
                text_color=ParagonTheme.TEXT_PRIMARY,
                corner_radius=18,
                font=ctk.CTkFont(size=self.FONT_SMALL),
                command=lambda g=genre: self._toggle_genre(g)
            )
            btn.pack(side="left", padx=3, pady=3)
        
        # Add custom genre entry row
        add_row = ctk.CTkFrame(self.genres_frame, fg_color="transparent")
        add_row.pack(fill="x", padx=8, pady=8)
        
        self.custom_genre_entry = ctk.CTkEntry(
            add_row, width=200, height=36,
            placeholder_text="New genre...",
            fg_color=ParagonTheme.BG_DARK,
            border_color=ParagonTheme.BORDER_DARK,
            font=ctk.CTkFont(size=self.FONT_SMALL)
        )
        self.custom_genre_entry.pack(side="left", padx=3)
        self.custom_genre_entry.bind("<Return>", lambda e: self._add_custom_genre())
        
        ctk.CTkButton(
            add_row, text="+ ADD", height=36, width=80,
            fg_color=ParagonTheme.GOLD,
            hover_color=ParagonTheme.GOLD_LIGHT,
            text_color=ParagonTheme.BG_DARK,
            corner_radius=18,
            font=ctk.CTkFont(size=self.FONT_SMALL, weight="bold"),
            command=self._add_custom_genre
        ).pack(side="left", padx=3)
    
    def _add_custom_genre(self):
        """Add a custom genre for TV shows"""
        genre = self.custom_genre_entry.get().strip()
        if not genre:
            return
        
        try:
            if MovieEditorDialog.add_custom_genre(genre):
                self.selected_genres.add(genre)
                self._create_genre_chips()
                messagebox.showinfo("Genre Added", f"'{genre}' has been added and will be available for all movies/TV shows.")
            else:
                for g in MovieEditorDialog.get_all_genres():
                    if g.lower() == genre.lower():
                        self.selected_genres.add(g)
                        break
                self._create_genre_chips()
        except Exception as e:
            self.selected_genres.add(genre)
            self._create_genre_chips()
    
    def _toggle_genre(self, genre):
        if genre in self.selected_genres:
            self.selected_genres.remove(genre)
        else:
            self.selected_genres.add(genre)
        self._create_genre_chips()
    
    def _create_episode_info_tab(self, parent):
        """Create the episode editing tab"""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Top section with thumbnail and fetch button
        top_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        top_frame.pack(fill="x", pady=(0, 15))
        
        # Episode thumbnail
        # Episode thumbnail with capture button
        thumb_container = ctk.CTkFrame(top_frame, fg_color="transparent")
        thumb_container.pack(side="left", padx=(0, 15))
        
        self.ep_thumb_frame = ctk.CTkFrame(thumb_container, fg_color=ParagonTheme.BG_DARK, width=280, height=160, corner_radius=6)
        self.ep_thumb_frame.pack()
        self.ep_thumb_frame.pack_propagate(False)
        self.ep_thumb_label = ctk.CTkLabel(self.ep_thumb_frame, text="Episode Thumbnail\n(Auto-loads from TMDB)",
                                           text_color=ParagonTheme.TEXT_SECONDARY,
                                           font=ctk.CTkFont(size=12))
        self.ep_thumb_label.pack(expand=True)
        
        # Camera button to capture frame from video
        capture_btn = ctk.CTkButton(
            thumb_container, text="📷 Capture Frame", 
            command=self._capture_episode_frame,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_PRIMARY,
            font=ctk.CTkFont(size=11),
            height=28, width=140
        )
        capture_btn.pack(pady=(5, 0))
        
        # Fetch button and status
        fetch_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        fetch_frame.pack(side="left", fill="y")
        
        ParagonButton(fetch_frame, text="🔄 FETCH FROM TMDB", 
                     command=self._manual_fetch_episode,
                     width=180, height=40).pack(anchor="nw", pady=(0, 10))
        
        self.ep_status_label = ctk.CTkLabel(fetch_frame, text="Select an episode\nfrom the list",
                                            text_color=ParagonTheme.TEXT_MUTED,
                                            font=ctk.CTkFont(size=12),
                                            justify="left")
        self.ep_status_label.pack(anchor="nw")
        
        # File info
        file_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        file_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(file_frame, text="File", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.ep_file_label = ctk.CTkLabel(file_frame, text="Select an episode",
                                          text_color=ParagonTheme.TEXT_PRIMARY,
                                          font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.ep_file_label.pack(side="left", fill="x", expand=True)
        
        # Season/Episode
        se_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        se_frame.pack(fill="x", pady=4)
        
        ctk.CTkLabel(se_frame, text="Season", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_season'] = ctk.StringVar()
        ctk.CTkEntry(se_frame, textvariable=self.episode_field_vars['ep_season'], width=80,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", padx=(0, 20))
        
        ctk.CTkLabel(se_frame, text="Episode", width=80, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_episode'] = ctk.StringVar()
        ctk.CTkEntry(se_frame, textvariable=self.episode_field_vars['ep_episode'], width=80,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left")
        
        # Title
        title_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        title_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(title_frame, text="Title", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_title'] = ctk.StringVar()
        ctk.CTkEntry(title_frame, textvariable=self.episode_field_vars['ep_title'],
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", fill="x", expand=True)
        
        # Aired date and rating
        aired_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        aired_frame.pack(fill="x", pady=4)
        
        ctk.CTkLabel(aired_frame, text="Aired", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_aired'] = ctk.StringVar()
        ctk.CTkEntry(aired_frame, textvariable=self.episode_field_vars['ep_aired'], width=130,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", padx=(0, 20))
        
        ctk.CTkLabel(aired_frame, text="Rating", width=80, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_rating'] = ctk.StringVar()
        ctk.CTkEntry(aired_frame, textvariable=self.episode_field_vars['ep_rating'], width=80,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left")
        
        # Plot
        plot_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        plot_frame.pack(fill="x", pady=6)
        ctk.CTkLabel(plot_frame, text="Plot", width=120, anchor="ne",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10), anchor="n")
        self.ep_plot_text = ctk.CTkTextbox(plot_frame, height=100, fg_color=ParagonTheme.BG_DARK,
                                           font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.ep_plot_text.pack(side="left", fill="x", expand=True)
        
        # Runtime and User Rating row
        runtime_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        runtime_frame.pack(fill="x", pady=4)
        
        ctk.CTkLabel(runtime_frame, text="Runtime", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_runtime'] = ctk.StringVar()
        runtime_entry = ctk.CTkEntry(runtime_frame, textvariable=self.episode_field_vars['ep_runtime'], width=80,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36)
        runtime_entry.pack(side="left")
        ctk.CTkLabel(runtime_frame, text="min", text_color=ParagonTheme.TEXT_MUTED,
                    font=ctk.CTkFont(size=self.FONT_SMALL)).pack(side="left", padx=(5, 20))
        
        ctk.CTkLabel(runtime_frame, text="User Rating", width=100, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_userrating'] = ctk.StringVar()
        ctk.CTkEntry(runtime_frame, textvariable=self.episode_field_vars['ep_userrating'], width=60,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left")
        ctk.CTkLabel(runtime_frame, text="/10", text_color=ParagonTheme.TEXT_MUTED,
                    font=ctk.CTkFont(size=self.FONT_SMALL)).pack(side="left", padx=(5, 0))
        
        # Directors
        directors_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        directors_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(directors_frame, text="Director(s)", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_directors'] = ctk.StringVar()
        ctk.CTkEntry(directors_frame, textvariable=self.episode_field_vars['ep_directors'],
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36, placeholder_text="Comma-separated names").pack(side="left", fill="x", expand=True)
        
        # Writers
        writers_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        writers_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(writers_frame, text="Writer(s)", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_writers'] = ctk.StringVar()
        ctk.CTkEntry(writers_frame, textvariable=self.episode_field_vars['ep_writers'],
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36, placeholder_text="Comma-separated names").pack(side="left", fill="x", expand=True)
        
        # Guest Stars
        guests_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        guests_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(guests_frame, text="Guest Stars", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.episode_field_vars['ep_guests'] = ctk.StringVar()
        ctk.CTkEntry(guests_frame, textvariable=self.episode_field_vars['ep_guests'],
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36, placeholder_text="Comma-separated names").pack(side="left", fill="x", expand=True)
        
        # Buttons
        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_frame.pack(fill="x", pady=15)
        ParagonButton(btn_frame, text="💾 SAVE EPISODE NFO", command=self._save_current_episode, width=200).pack(side="right")
    
    def _manual_fetch_episode(self):
        """Manually fetch episode data from TMDB"""
        if not self.show_details or not self.show_details.get('id'):
            messagebox.showwarning("No Show Selected", 
                                   "Please search and select a TV show first (in SHOW mode) before fetching episode data.")
            return
        
        if not self.current_episode:
            messagebox.showwarning("No Episode Selected", "Please select an episode from the list first.")
            return
        
        try:
            season = int(self.episode_field_vars.get('ep_season', ctk.StringVar()).get() or 1)
            episode = int(self.episode_field_vars.get('ep_episode', ctk.StringVar()).get() or 1)
        except ValueError:
            messagebox.showerror("Invalid Input", "Season and Episode must be numbers.")
            return
        
        self.ep_status_label.configure(text=f"Fetching S{season:02d}E{episode:02d}...")
        
        def fetch():
            ep_info = TMDBAPI.get_tv_episode(self.show_details['id'], season, episode)
            if ep_info:
                self.after(0, lambda: self._populate_episode_from_tmdb_force(ep_info))
            else:
                self.after(0, lambda: self.ep_status_label.configure(
                    text=f"Episode not found:\nS{season:02d}E{episode:02d}",
                    text_color=ParagonTheme.RED_LIGHT
                ))
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _populate_episode_from_tmdb_force(self, ep_info: Dict):
        """Force populate episode fields from TMDB (overwrites existing)"""
        if not ep_info:
            return
        
        # Overwrite all fields
        if ep_info.get('name'):
            self.episode_field_vars['ep_title'].set(ep_info['name'])
        
        if ep_info.get('overview') and hasattr(self, 'ep_plot_text'):
            self.ep_plot_text.delete("1.0", "end")
            self.ep_plot_text.insert("1.0", ep_info['overview'])
        
        if ep_info.get('air_date'):
            self.episode_field_vars['ep_aired'].set(ep_info['air_date'])
        
        if ep_info.get('vote_average'):
            self.episode_field_vars['ep_rating'].set(str(round(ep_info['vote_average'], 1)))
        
        # Set runtime
        if ep_info.get('runtime'):
            self.episode_field_vars['ep_runtime'].set(str(ep_info['runtime']))
        
        # Set directors
        if ep_info.get('directors'):
            self.episode_field_vars['ep_directors'].set(', '.join(ep_info['directors']))
        
        # Set writers
        if ep_info.get('writers'):
            self.episode_field_vars['ep_writers'].set(', '.join(ep_info['writers']))
        
        # Set guest stars
        if ep_info.get('guest_stars'):
            guest_names = [g.get('name', '') for g in ep_info['guest_stars'] if g.get('name')]
            self.episode_field_vars['ep_guests'].set(', '.join(guest_names[:10]))
        
        # Update status
        self.ep_status_label.configure(
            text=f"✓ Loaded: {ep_info.get('name', 'Unknown')}\n"
                 f"Aired: {ep_info.get('air_date', 'Unknown')}",
            text_color=ParagonTheme.SUCCESS
        )
        
        # Update local cache
        if self.current_episode:
            self.episodes_data[self.current_episode].update({
                'title': ep_info.get('name', ''),
                'plot': ep_info.get('overview', ''),
                'aired': ep_info.get('air_date', ''),
                'rating': ep_info.get('vote_average', 0),
                'runtime': ep_info.get('runtime', 0),
                'still_path': ep_info.get('still_path', ''),
                'directors': ep_info.get('directors', []),
                'writers': ep_info.get('writers', []),
                'guest_stars': ep_info.get('guest_stars', []),
            })
        
        # Refresh episode list to show new title
        self._populate_episodes_list()
        
        # Load thumbnail
        if ep_info.get('still_path'):
            self._load_episode_thumbnail(ep_info['still_path'])
    
    def _create_stream_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        ParagonLabel(scroll, text="Video", style="header").pack(anchor="w", pady=(0, 8))
        video_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        video_frame.pack(fill="x", pady=(0, 20))
        
        self.video_info_labels = {}
        for field in ["Codec", "Resolution", "Aspect Ratio", "Scantype", "Duration"]:
            row = ctk.CTkFrame(video_frame, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(row, text=field, width=140, anchor="w",
                        text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
            lbl = ctk.CTkLabel(row, text="--", anchor="w", text_color=ParagonTheme.TEXT_PRIMARY,
                              font=ctk.CTkFont(size=self.FONT_NORMAL))
            lbl.pack(side="left", fill="x", expand=True)
            self.video_info_labels[field.lower().replace(" ", "_")] = lbl
        
        ParagonLabel(scroll, text="Audio", style="header").pack(anchor="w", pady=(15, 8))
        self.audio_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.audio_frame.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(self.audio_frame, text="No audio tracks", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=15)
        
        ParagonLabel(scroll, text="Subtitles", style="header").pack(anchor="w", pady=(0, 8))
        self.subs_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.subs_frame.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(self.subs_frame, text="No subtitles", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=15)
    
    def _create_episode_stream_tab(self, parent):
        """Create stream details tab for episodes"""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        ParagonLabel(scroll, text="Video", style="header").pack(anchor="w", pady=(0, 8))
        video_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        video_frame.pack(fill="x", pady=(0, 20))
        
        self.ep_video_info_labels = {}
        for field in ["Codec", "Resolution", "Aspect Ratio", "Scantype", "Duration"]:
            row = ctk.CTkFrame(video_frame, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(row, text=field, width=140, anchor="w",
                        text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
            lbl = ctk.CTkLabel(row, text="--", anchor="w", text_color=ParagonTheme.TEXT_PRIMARY,
                              font=ctk.CTkFont(size=self.FONT_NORMAL))
            lbl.pack(side="left", fill="x", expand=True)
            self.ep_video_info_labels[field.lower().replace(" ", "_")] = lbl
        
        ParagonLabel(scroll, text="Audio", style="header").pack(anchor="w", pady=(15, 8))
        self.ep_audio_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.ep_audio_frame.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(self.ep_audio_frame, text="Select an episode", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=15)
        
        ParagonLabel(scroll, text="Subtitles", style="header").pack(anchor="w", pady=(0, 8))
        self.ep_subs_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.ep_subs_frame.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(self.ep_subs_frame, text="Select an episode", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=15)
    
    def _update_episode_stream_display(self):
        """Update stream display for current episode"""
        if not self.stream_info or not hasattr(self, 'ep_video_info_labels'):
            return
        
        video = self.stream_info.get('video', {})
        for key, lbl in self.ep_video_info_labels.items():
            lbl.configure(text=video.get(key.replace('_', ''), video.get(key, '--')))
        
        # Audio
        for widget in self.ep_audio_frame.winfo_children():
            widget.destroy()
        audio_tracks = self.stream_info.get('audio', [])
        if audio_tracks:
            for i, track in enumerate(audio_tracks):
                row = ctk.CTkFrame(self.ep_audio_frame, fg_color="transparent")
                row.pack(fill="x", padx=15, pady=4)
                ctk.CTkLabel(row, text=f"Track {i+1}", width=80, text_color=ParagonTheme.TEXT_SECONDARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
                ctk.CTkLabel(row, text=track.get('language', 'und').upper(), text_color=ParagonTheme.TEXT_PRIMARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=15)
                ctk.CTkLabel(row, text=track.get('codec', ''), text_color=ParagonTheme.TEXT_PRIMARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=15)
        else:
            ctk.CTkLabel(self.ep_audio_frame, text="No audio tracks", text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=10)
        
        # Subtitles
        for widget in self.ep_subs_frame.winfo_children():
            widget.destroy()
        sub_tracks = self.stream_info.get('subtitles', [])
        if sub_tracks:
            for i, track in enumerate(sub_tracks):
                row = ctk.CTkFrame(self.ep_subs_frame, fg_color="transparent")
                row.pack(fill="x", padx=15, pady=4)
                ctk.CTkLabel(row, text=f"Track {i+1}", width=80, text_color=ParagonTheme.TEXT_SECONDARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
                ctk.CTkLabel(row, text=track.get('language', 'und').upper(), text_color=ParagonTheme.TEXT_PRIMARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=15)
        else:
            ctk.CTkLabel(self.ep_subs_frame, text="No subtitles", text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=10)
    
    def _populate_from_nfo(self, show_data: Dict):
        """Populate the editor UI with data from tvshow.nfo"""
        if show_data.get('title'):
            self.search_entry.delete(0, 'end')
            self.search_entry.insert(0, show_data['title'])
        if show_data.get('year'):
            self.year_entry.delete(0, 'end')
            self.year_entry.insert(0, str(show_data['year']))
        
        field_mapping = {
            'title': 'title',
            'original_title': 'original_title',
            'sort_title': 'sort_title',
            'tagline': 'tagline',
            'premiered': 'premiered',
            'certification': 'certification',
            'status': 'status',
            'studio': 'studio',
        }
        
        for ui_key, data_key in field_mapping.items():
            if ui_key in self.field_vars and show_data.get(data_key):
                self.field_vars[ui_key].set(str(show_data[data_key]))
        
        # Set TMDB ID and TVDB ID fields
        if 'tmdb_id' in self.field_vars:
            tmdb_id = show_data.get('tmdb_id') or show_data.get('id') or ''
            self.field_vars['tmdb_id'].set(str(tmdb_id) if tmdb_id else '')
        
        if 'tvdb_id' in self.field_vars:
            tvdb_id = show_data.get('tvdb_id') or ''
            self.field_vars['tvdb_id'].set(str(tvdb_id) if tvdb_id else '')
        
        if hasattr(self, 'rating_label'):
            rating = show_data.get('vote_average', 0)
            try:
                self.rating_label.configure(text=f"TMDB: {float(rating):.1f}")
            except:
                pass
        
        if hasattr(self, 'plot_text') and show_data.get('overview'):
            self.plot_text.delete("1.0", "end")
            self.plot_text.insert("1.0", show_data['overview'])
        
        self.selected_genres = set(show_data.get('genres', []))
        self._create_genre_chips()
        
        if show_data.get('studio'):
            self.selected_studios = {show_data['studio']}
            if hasattr(self, 'studios_label'):
                self.studios_label.configure(text=show_data['studio'])
        
        if self.stream_info and hasattr(self, 'video_info_labels'):
            self._update_stream_display()
        
        # Show loaded from NFO indicator
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        loaded_label = ctk.CTkFrame(self.results_list, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        loaded_label.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkLabel(loaded_label, text="📁 Loaded from NFO",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=ParagonTheme.SUCCESS).pack(padx=10, pady=(8, 2))
        ctk.CTkLabel(loaded_label, text=show_data.get('title', 'Unknown'),
                    font=ctk.CTkFont(size=12),
                    text_color=ParagonTheme.TEXT_PRIMARY).pack(padx=10, pady=(0, 2))
        
        # Show TMDB link status
        if show_data.get('id') or show_data.get('tmdb_id'):
            tmdb_id = show_data.get('tmdb_id') or show_data.get('id')
            ctk.CTkLabel(loaded_label, text=f"✓ TMDB ID: {tmdb_id}",
                        font=ctk.CTkFont(size=11),
                        text_color=ParagonTheme.SUCCESS).pack(padx=10, pady=(0, 8))
        else:
            self.tmdb_status_label = ctk.CTkLabel(loaded_label, text="🔄 Linking to TMDB...",
                        font=ctk.CTkFont(size=11),
                        text_color=ParagonTheme.GOLD).pack(padx=10, pady=(0, 8))
        
        ctk.CTkLabel(self.results_list, text="Search online to update:",
                    font=ctk.CTkFont(size=11),
                    text_color=ParagonTheme.TEXT_MUTED).pack(pady=(10, 5))
    
    def _load_existing_artwork_previews(self):
        """Load existing artwork files as previews"""
        def load_local_image(path: str, label, max_size: tuple, photo_attr: str, art_type: str):
            if not path or not os.path.exists(path):
                return
            def load():
                try:
                    if HAS_PIL:
                        img = Image.open(path)
                        img.thumbnail(max_size, Image.Resampling.LANCZOS)
                        photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                        setattr(self, photo_attr, photo)
                        self.after(0, lambda: label.configure(image=photo, text=""))
                except Exception as e:
                    print(f"Error loading {art_type}: {e}")
            threading.Thread(target=load, daemon=True).start()
        
        if self.existing_artwork.get('poster'):
            load_local_image(self.existing_artwork['poster'], self.poster_label, (120, 170), '_poster_photo', 'poster')
        if self.existing_artwork.get('fanart'):
            load_local_image(self.existing_artwork['fanart'], self.fanart_label, (260, 110), '_fanart_photo', 'fanart')
        if self.existing_artwork.get('logo'):
            load_local_image(self.existing_artwork['logo'], self.logo_label, (260, 60), '_logo_photo', 'logo')
        if self.existing_artwork.get('landscape'):
            load_local_image(self.existing_artwork['landscape'], self.landscape_label, (260, 90), '_landscape_photo', 'landscape')
    
    def _probe_stream_info(self, path):
        """Run ffprobe on `path` and return a stream-info dict.

        Returns the empty skeleton (all fields blank) if `path` is missing or
        ffprobe is unavailable/fails, so callers always get a usable dict."""
        info = {
            'video': {'codec': '', 'resolution': '', 'aspect': '', 'scantype': '', 'duration': ''},
            'audio': [],
            'subtitles': []
        }
        if not path:
            return info

        try:
            import subprocess
            cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-show_format', path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                data = json.loads(result.stdout)

                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        info['video'] = {
                            'codec': stream.get('codec_name', '').upper(),
                            'resolution': f"{stream.get('width', '')} x {stream.get('height', '')}",
                            'aspect': str(round(stream.get('width', 0) / stream.get('height', 1), 3)) if stream.get('height') else '',
                            'scantype': 'Progressive' if stream.get('field_order', 'progressive') == 'progressive' else 'Interlaced',
                            'duration': ''
                        }
                    elif stream.get('codec_type') == 'audio':
                        lang = stream.get('tags', {}).get('language', 'und')
                        codec = stream.get('codec_name', '').upper()
                        channels = stream.get('channels', 2)
                        info['audio'].append({'language': lang, 'codec': codec, 'channels': channels})
                    elif stream.get('codec_type') == 'subtitle':
                        lang = stream.get('tags', {}).get('language', 'und')
                        info['subtitles'].append({'language': lang})

                duration_secs = float(data.get('format', {}).get('duration', 0))
                hours = int(duration_secs // 3600)
                mins = int((duration_secs % 3600) // 60)
                secs = int(duration_secs % 60)
                info['video']['duration'] = f"{hours:02d}:{mins:02d}:{secs:02d}"
        except:
            pass

        return info

    def _extract_stream_info(self):
        """Extract stream info from the current video file using ffprobe"""
        if not self.current_file:
            return
        self.stream_info = self._probe_stream_info(self.current_file)
    
    def _update_stream_display(self):
        if not self.stream_info or not hasattr(self, 'video_info_labels'):
            return
        
        video = self.stream_info.get('video', {})
        if 'codec' in self.video_info_labels:
            self.video_info_labels['codec'].configure(text=video.get('codec', '--'))
        if 'resolution' in self.video_info_labels:
            self.video_info_labels['resolution'].configure(text=video.get('resolution', '--'))
        if 'aspect_ratio' in self.video_info_labels:
            self.video_info_labels['aspect_ratio'].configure(text=video.get('aspect', '--'))
        if 'scantype' in self.video_info_labels:
            self.video_info_labels['scantype'].configure(text=video.get('scantype', '--'))
        if 'duration' in self.video_info_labels:
            self.video_info_labels['duration'].configure(text=video.get('duration', '--'))
    
    def _create_artwork_panel(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=5, pady=10)
        
        # Poster
        ctk.CTkLabel(scroll, text="Poster (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.poster_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=180, corner_radius=4, cursor="hand2")
        self.poster_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.poster_frame.pack_propagate(False)
        self.poster_label = ctk.CTkLabel(self.poster_frame, text="No Poster\n(Click to choose)", 
                                         text_color=ParagonTheme.TEXT_SECONDARY, cursor="hand2")
        self.poster_label.pack(expand=True)
        self.poster_frame.bind("<Button-1>", lambda e: self._choose_artwork('poster'))
        self.poster_label.bind("<Button-1>", lambda e: self._choose_artwork('poster'))
        
        # Logo
        ctk.CTkLabel(scroll, text="Logo (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.logo_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=70, corner_radius=4, cursor="hand2")
        self.logo_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.logo_frame.pack_propagate(False)
        self.logo_label = ctk.CTkLabel(self.logo_frame, text="No Logo", text_color=ParagonTheme.TEXT_SECONDARY, cursor="hand2")
        self.logo_label.pack(expand=True)
        self.logo_frame.bind("<Button-1>", lambda e: self._choose_artwork('logo'))
        self.logo_label.bind("<Button-1>", lambda e: self._choose_artwork('logo'))
        
        # Fanart
        ctk.CTkLabel(scroll, text="Fanart (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.fanart_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=120, corner_radius=4, cursor="hand2")
        self.fanart_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.fanart_frame.pack_propagate(False)
        self.fanart_label = ctk.CTkLabel(self.fanart_frame, text="No Fanart", text_color=ParagonTheme.TEXT_SECONDARY, cursor="hand2")
        self.fanart_label.pack(expand=True)
        self.fanart_frame.bind("<Button-1>", lambda e: self._choose_artwork('fanart'))
        self.fanart_label.bind("<Button-1>", lambda e: self._choose_artwork('fanart'))
        
        # Landscape
        ctk.CTkLabel(scroll, text="Landscape (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.landscape_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=100, corner_radius=4, cursor="hand2")
        self.landscape_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.landscape_frame.pack_propagate(False)
        self.landscape_label = ctk.CTkLabel(self.landscape_frame, text="No Landscape", text_color=ParagonTheme.TEXT_SECONDARY, cursor="hand2")
        self.landscape_label.pack(expand=True)
        self.landscape_frame.bind("<Button-1>", lambda e: self._choose_artwork('landscape'))
        self.landscape_label.bind("<Button-1>", lambda e: self._choose_artwork('landscape'))
        
        ParagonLabel(scroll, text="DOWNLOAD", style="header").pack(anchor="w", padx=8, pady=(10, 0))
    
    def _choose_artwork(self, art_type: str):
        """Open image chooser for TV show artwork"""
        if not self.show_details or not self.show_details.get('id'):
            messagebox.showinfo("Search First", "Please search and select a TV show first")
            return
        
        show_id = self.show_details['id']
        show_title = self.show_details.get('title', '')
        tvdb_id = self.show_details.get('tvdb_id')  # Get TVDB ID for Fanart.tv
        
        # Map art types to API image types
        type_mapping = {
            'poster': ('posters', 'Choose Poster'),
            'fanart': ('backdrops', 'Choose Fanart'),
            'logo': ('logos', 'Choose Logo'),
            'landscape': ('thumbs', 'Choose Landscape'),
        }
        
        image_type, title = type_mapping.get(art_type, ('posters', 'Choose Image'))
        
        dialog = ImageChooserDialog(
            self,
            movie_id=show_id,
            image_type=image_type,
            movie_title=show_title,
            display_type=art_type,
            media_type='tv',
            tvdb_id=tvdb_id  # Pass TVDB ID for Fanart.tv
        )
        
        self.wait_window(dialog)
        
        selected_path = dialog.get_selected_path()
        selected_source = getattr(dialog, 'selected_source', 'tmdb')
        
        if selected_path:
            self.show_details[f'{art_type}_path'] = selected_path
            self.show_details[f'{art_type}_source'] = selected_source
            self._update_artwork_preview(art_type, selected_path, selected_source)
    
    def _update_artwork_preview(self, art_type: str, path: str, source: str = 'tmdb'):
        """Update artwork preview after selection"""
        label_map = {
            'poster': (self.poster_label, (120, 170), '_poster_photo'),
            'fanart': (self.fanart_label, (260, 110), '_fanart_photo'),
            'logo': (self.logo_label, (260, 60), '_logo_photo'),
            'landscape': (self.landscape_label, (260, 90), '_landscape_photo'),
        }
        
        if art_type not in label_map:
            return
        
        label, max_size, photo_attr = label_map[art_type]
        
        def load():
            try:
                if source == 'fanart':
                    data = FanartTVAPI.download_image(path)
                else:
                    data = TMDBAPI.download_image(path, 'w500')
                
                if data and HAS_PIL:
                    img = Image.open(io.BytesIO(data))
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                    setattr(self, photo_attr, photo)
                    self.after(0, lambda: label.configure(image=photo, text=""))
            except Exception as e:
                print(f"Error loading {art_type} preview: {e}")
        
        threading.Thread(target=load, daemon=True).start()
    
    def _search(self):
        """Search for TV shows"""
        query = self.search_entry.get().strip()
        year = self.year_entry.get().strip()
        
        if not query:
            messagebox.showinfo("Search", "Please enter a TV show name")
            return
        
        for widget in self.results_list.winfo_children():
            widget.destroy()
        ParagonLabel(self.results_list, text="Searching...", style="muted").pack(pady=20)
        self.update()
        
        def do_search():
            results = TMDBAPI.search_tv(query, year if year else None)
            self.after(0, lambda: self._display_results(results))
        
        threading.Thread(target=do_search, daemon=True).start()
    
    def _display_results(self, results: List[Dict]):
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        self.search_results = results
        
        if not results:
            ParagonLabel(self.results_list, text="No shows found", style="muted").pack(pady=20)
            return
        
        for i, show in enumerate(results[:15]):
            frame = ctk.CTkFrame(self.results_list,
                                fg_color=ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY,
                                corner_radius=4)
            frame.pack(fill="x", pady=2)
            frame.bind("<Button-1>", lambda e, idx=i: self._select_result(idx))
            
            title_text = show.get('title', 'Unknown')
            if show.get('year'):
                title_text += f" ({show['year']})"
            
            lbl = ctk.CTkLabel(frame, text=title_text, font=ctk.CTkFont(size=14),
                              text_color=ParagonTheme.TEXT_PRIMARY, anchor="w")
            lbl.pack(fill="x", padx=10, pady=8)
            lbl.bind("<Button-1>", lambda e, idx=i: self._select_result(idx))
    
    def _select_result(self, index: int):
        if index >= len(self.search_results):
            return
        
        self.selected_show = self.search_results[index]
        
        for i, widget in enumerate(self.results_list.winfo_children()):
            if isinstance(widget, ctk.CTkFrame):
                widget.configure(fg_color=ParagonTheme.RED_DARK if i == index else 
                               (ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY))
        
        show_id = self.selected_show.get('id')
        
        def fetch_details():
            details = TMDBAPI.get_tv_details(show_id)
            if details:
                self.after(0, lambda: self._update_details(details))
        
        threading.Thread(target=fetch_details, daemon=True).start()
    
    def _update_details(self, details: Dict):
        self.show_details = details
        
        if 'title' in self.field_vars:
            self.field_vars['title'].set(details.get('title', ''))
        if 'original_title' in self.field_vars:
            self.field_vars['original_title'].set(details.get('original_title', ''))
        if 'sort_title' in self.field_vars:
            self.field_vars['sort_title'].set(details.get('title', ''))
        if 'tagline' in self.field_vars:
            self.field_vars['tagline'].set(details.get('tagline', ''))
        if 'premiered' in self.field_vars:
            self.field_vars['premiered'].set(details.get('first_air_date', ''))
        if 'status' in self.field_vars:
            self.field_vars['status'].set(details.get('status', ''))
        if 'tmdb_id' in self.field_vars:
            self.field_vars['tmdb_id'].set(str(details.get('id', '')))
        if 'tvdb_id' in self.field_vars:
            tvdb_id = details.get('tvdb_id', '')
            self.field_vars['tvdb_id'].set(str(tvdb_id) if tvdb_id else '')
        
        rating = details.get('vote_average', 0)
        votes = details.get('vote_count', 0)
        self.rating_label.configure(text=f"TMDB: {rating:.1f} | Votes: {votes}")
        
        self.plot_text.delete("1.0", "end")
        self.plot_text.insert("1.0", details.get('overview', ''))
        
        self.selected_genres = set(details.get('genres', []))
        self._create_genre_chips()
        
        networks = details.get('networks', [])
        if networks:
            self.studios_label.configure(text=", ".join(networks[:3]))
            self.selected_studios = set(networks)
        
        # Load poster
        if details.get('poster_path') and HAS_PIL:
            def load_poster():
                data = TMDBAPI.download_image(details['poster_path'], 'w342')
                if data:
                    try:
                        img = Image.open(io.BytesIO(data))
                        img.thumbnail((120, 170), Image.Resampling.LANCZOS)
                        self._poster_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                        self.after(0, lambda: self.poster_label.configure(image=self._poster_photo, text=""))
                    except:
                        pass
            threading.Thread(target=load_poster, daemon=True).start()
    
    def _commit_current_episode_fields(self):
        """Flush the episode currently shown in the editor back into
        self.episodes_data so on-screen edits are included in any save."""
        if not self.current_episode:
            return

        ep_data = self.episodes_data.get(self.current_episode, {})
        ep_data['season'] = int(self.episode_field_vars.get('ep_season', ctk.StringVar()).get() or 1)
        ep_data['episode'] = int(self.episode_field_vars.get('ep_episode', ctk.StringVar()).get() or 1)
        ep_data['title'] = self.episode_field_vars.get('ep_title', ctk.StringVar()).get()
        ep_data['aired'] = self.episode_field_vars.get('ep_aired', ctk.StringVar()).get()
        ep_data['plot'] = self.ep_plot_text.get("1.0", "end-1c")

        try:
            ep_data['rating'] = float(self.episode_field_vars.get('ep_rating', ctk.StringVar()).get() or 0)
        except:
            ep_data['rating'] = 0

        # New extended fields
        try:
            ep_data['runtime'] = int(self.episode_field_vars.get('ep_runtime', ctk.StringVar()).get() or 0)
        except:
            ep_data['runtime'] = 0

        try:
            ep_data['userrating'] = float(self.episode_field_vars.get('ep_userrating', ctk.StringVar()).get() or 0)
        except:
            ep_data['userrating'] = 0

        # Parse directors, writers, guests from comma-separated strings
        directors_str = self.episode_field_vars.get('ep_directors', ctk.StringVar()).get()
        ep_data['directors'] = [d.strip() for d in directors_str.split(',') if d.strip()] if directors_str else []

        writers_str = self.episode_field_vars.get('ep_writers', ctk.StringVar()).get()
        ep_data['writers'] = [w.strip() for w in writers_str.split(',') if w.strip()] if writers_str else []

        guests_str = self.episode_field_vars.get('ep_guests', ctk.StringVar()).get()
        ep_data['guest_stars'] = [g.strip() for g in guests_str.split(',') if g.strip()] if guests_str else []

        self.episodes_data[self.current_episode] = ep_data

    def _write_episode_nfo(self, file, ep_data, stream_info=None):
        """Build and write a single episode's NFO next to its video file.

        Returns the full path of the written .nfo (raises on write failure)."""
        show_title = self.field_vars.get('title', ctk.StringVar()).get()
        if not show_title and self.show_details:
            show_title = self.show_details.get('title', 'Unknown Show')
        show_title = show_title or 'Unknown Show'

        episode_nfo_data = {
            'name': ep_data.get('title', ''),
            'season_number': ep_data.get('season', 1),
            'episode_number': ep_data.get('episode', 1),
            'overview': ep_data.get('plot', ''),
            'air_date': ep_data.get('aired', ''),
            'vote_average': ep_data.get('rating', 0),
            'runtime': ep_data.get('runtime', 0),
            'userrating': ep_data.get('userrating', 0),
            'directors': ep_data.get('directors', []),
            'writers': ep_data.get('writers', []),
            'guest_stars': ep_data.get('guest_stars', []),
            'still_path': ep_data.get('still_path', ''),
        }

        # Add stream info if available
        if stream_info:
            episode_nfo_data['fileinfo'] = stream_info

        show_data = {
            'title': show_title,
            'id': self.show_details.get('id') if self.show_details else None
        }

        nfo_content = NFOGenerator.generate_episode_nfo(episode_nfo_data, show_data)

        folder = os.path.dirname(file)
        basename = os.path.splitext(os.path.basename(file))[0]
        nfo_path = os.path.join(folder, f"{basename}.nfo")

        with open(nfo_path, 'w', encoding='utf-8') as f:
            f.write(nfo_content)
        return nfo_path

    def _save_current_episode(self):
        """Save NFO for the currently selected episode"""
        if not self.current_episode:
            messagebox.showwarning("No Episode", "Please select an episode first")
            return

        # Pull the on-screen field values into episodes_data, then write.
        self._commit_current_episode_fields()
        ep_data = self.episodes_data.get(self.current_episode, {})

        try:
            nfo_path = self._write_episode_nfo(self.current_episode, ep_data, self.stream_info)
            messagebox.showinfo("Saved", f"Episode NFO saved:\n{nfo_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save episode NFO: {e}")
    
    def _save_all(self):
        """Save tvshow.nfo and download artwork"""
        if not self.show_details and not self.field_vars.get('title', ctk.StringVar()).get():
            messagebox.showwarning("No Data", "Please search and select a TV show first or enter data manually")
            return
        
        # Get TMDB ID and TVDB ID from fields (may have been manually entered or loaded from NFO)
        tmdb_id_str = self.field_vars.get('tmdb_id', ctk.StringVar()).get()
        tvdb_id_str = self.field_vars.get('tvdb_id', ctk.StringVar()).get()
        
        try:
            tmdb_id = int(tmdb_id_str) if tmdb_id_str and tmdb_id_str.isdigit() else None
        except:
            tmdb_id = None
        
        try:
            tvdb_id = int(tvdb_id_str) if tvdb_id_str and tvdb_id_str.isdigit() else None
        except:
            tvdb_id = None
        
        # Fall back to show_details if no ID in field
        if not tmdb_id and self.show_details:
            tmdb_id = self.show_details.get('id')
        if not tvdb_id and self.show_details:
            tvdb_id = self.show_details.get('tvdb_id')
        
        show_data = {
            'title': self.field_vars.get('title', ctk.StringVar()).get(),
            'original_title': self.field_vars.get('original_title', ctk.StringVar()).get(),
            'sort_title': self.field_vars.get('sort_title', ctk.StringVar()).get(),
            'tagline': self.field_vars.get('tagline', ctk.StringVar()).get(),
            'overview': self.plot_text.get("1.0", "end-1c"),
            'first_air_date': self.field_vars.get('premiered', ctk.StringVar()).get(),
            'status': self.field_vars.get('status', ctk.StringVar()).get(),
            'certification': self.field_vars.get('certification', ctk.StringVar()).get(),
            'genres': list(self.selected_genres),
            'networks': list(self.selected_studios),
            'id': tmdb_id,
            'tvdb_id': tvdb_id,
            'imdb_id': self.show_details.get('imdb_id') if self.show_details else None,
            'vote_average': self.show_details.get('vote_average', 0) if self.show_details else 0,
            'vote_count': self.show_details.get('vote_count', 0) if self.show_details else 0,
            'poster_path': self.show_details.get('poster_path') if self.show_details else None,
            'backdrop_path': self.show_details.get('backdrop_path') if self.show_details else None,
            'cast': self.show_details.get('cast', []) if self.show_details else [],
            'creators': self.show_details.get('creators', []) if self.show_details else [],
        }
        
        folder = os.path.dirname(self.current_file)
        
        # Save tvshow.nfo
        nfo_content = NFOGenerator.generate_tvshow_nfo(show_data)
        nfo_path = os.path.join(folder, "tvshow.nfo")
        
        try:
            with open(nfo_path, 'w', encoding='utf-8') as f:
                f.write(nfo_content)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save NFO: {e}")
            return
        
        saved_files = ["tvshow.nfo"]
        
        # Download poster
        poster_path = self.show_details.get('poster_path') if self.show_details else None
        poster_source = self.show_details.get('poster_source', 'tmdb') if self.show_details else 'tmdb'
        if poster_path:
            if poster_source == 'fanart':
                data = FanartTVAPI.download_image(poster_path)
            else:
                data = TMDBAPI.download_image(poster_path, 'original')
            if data:
                try:
                    with open(os.path.join(folder, "poster.jpg"), 'wb') as f:
                        f.write(data)
                    saved_files.append("poster.jpg")
                except:
                    pass
        
        # Download fanart
        fanart_path = (self.show_details.get('fanart_path') or self.show_details.get('backdrop_path')) if self.show_details else None
        fanart_source = self.show_details.get('fanart_source', 'tmdb') if self.show_details else 'tmdb'
        if fanart_path:
            if fanart_source == 'fanart':
                data = FanartTVAPI.download_image(fanart_path)
            else:
                data = TMDBAPI.download_image(fanart_path, 'original')
            if data:
                try:
                    with open(os.path.join(folder, "fanart.jpg"), 'wb') as f:
                        f.write(data)
                    saved_files.append("fanart.jpg")
                except:
                    pass
        
        # Download logo if available
        logo_path = self.show_details.get('logo_path') if self.show_details else None
        logo_source = self.show_details.get('logo_source', 'fanart') if self.show_details else 'fanart'
        if logo_path:
            if logo_source == 'fanart':
                data = FanartTVAPI.download_image(logo_path)
            else:
                data = TMDBAPI.download_image(logo_path, 'original')
            if data:
                try:
                    with open(os.path.join(folder, "clearlogo.png"), 'wb') as f:
                        f.write(data)
                    saved_files.append("clearlogo.png")
                except:
                    pass
        
        # Download landscape if available
        landscape_path = self.show_details.get('landscape_path') if self.show_details else None
        landscape_source = self.show_details.get('landscape_source', 'fanart') if self.show_details else 'fanart'
        if landscape_path:
            if landscape_source == 'fanart':
                data = FanartTVAPI.download_image(landscape_path)
            else:
                data = TMDBAPI.download_image(landscape_path, 'original')
            if data:
                try:
                    with open(os.path.join(folder, "landscape.jpg"), 'wb') as f:
                        f.write(data)
                    saved_files.append("landscape.jpg")
                except:
                    pass

        # Write an NFO next to every episode file using the scraped/edited
        # data. Flush the episode currently shown in the editor first so its
        # unsaved edits are included.
        self._commit_current_episode_fields()

        episode_nfo_count = 0
        episode_nfo_errors = []
        for ep_file, ep_data in self.episodes_data.items():
            try:
                # Probe each file individually so every episode NFO carries
                # its own stream details rather than the current file's.
                stream_info = self._probe_stream_info(ep_file)
                self._write_episode_nfo(ep_file, ep_data, stream_info)
                episode_nfo_count += 1
            except Exception as e:
                print(f"Failed to write episode NFO for {ep_file}: {e}")
                episode_nfo_errors.append(os.path.basename(ep_file))

        if episode_nfo_count:
            saved_files.append(f"{episode_nfo_count} episode NFO file(s)")

        summary = f"TV show data saved!\n\n• " + "\n• ".join(saved_files)
        if episode_nfo_errors:
            summary += "\n\nCould not write NFO for:\n• " + "\n• ".join(episode_nfo_errors)
        messagebox.showinfo("Success", summary)
        self.destroy()


# =============================================================================
# MAIN APPLICATION
# =============================================================================

# Create a DnD-enabled CTk class if tkinterdnd2 is available
if HAS_DND:
    
    def _create_ui(self):
        """Create the TV show editor UI"""
        main = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        main.pack(fill="both", expand=True, padx=4, pady=4)
        
        inner = ctk.CTkFrame(main, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        self._create_header(inner)
        
        content = ctk.CTkFrame(inner, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        
        # Left side - Search results
        self.left_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=250)
        self.left_panel.pack(side="left", fill="y", padx=(0, 10))
        self.left_panel.pack_propagate(False)
        
        ParagonLabel(self.left_panel, text="SEARCH RESULTS", style="header").pack(anchor="w", padx=10, pady=(10, 5))
        
        self.results_list = ctk.CTkScrollableFrame(self.left_panel, fg_color=ParagonTheme.BG_DARK)
        self.results_list.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        
        ParagonLabel(self.results_list, text="Search for a TV show", style="muted").pack(pady=20)
        
        # Middle - Tabs
        middle_frame = ctk.CTkFrame(content, fg_color="transparent")
        middle_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        self.tabs = ctk.CTkTabview(middle_frame, fg_color=ParagonTheme.BG_SECONDARY,
                                   segmented_button_fg_color=ParagonTheme.BG_TERTIARY,
                                   segmented_button_selected_color=ParagonTheme.RED_PRIMARY)
        self.tabs.pack(fill="both", expand=True)
        
        self.tabs.add("Information")
        self.tabs.add("Extended")
        self.tabs.add("Stream Details")
        
        self._create_info_tab(self.tabs.tab("Information"))
        self._create_extended_tab(self.tabs.tab("Extended"))
        self._create_stream_tab(self.tabs.tab("Stream Details"))
        
        # Right side - Artwork
        right_panel = ctk.CTkFrame(content, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=8, width=300)
        right_panel.pack(side="right", fill="y")
        right_panel.pack_propagate(False)
        
        self._create_artwork_panel(right_panel)
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(5, 12))
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self.destroy, width=100).pack(side="left")
        
        ParagonButton(btn_frame, text="SAVE ALL", command=self._save_all, width=130).pack(side="right")
    
    def _create_header(self, parent):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(10, 5))
        
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left")
        
        ctk.CTkLabel(
            title_frame, text="TV SHOW EDITOR",
            font=ctk.CTkFont(family="Bebas Neue", size=self.FONT_TITLE, weight="bold"),
            text_color=ParagonTheme.RED_LIGHT
        ).pack(side="left")
        
        # Maximize button
        ctk.CTkButton(
            header, text="□", width=35, height=35,
            fg_color="transparent", hover_color=ParagonTheme.BG_HOVER,
            command=self._toggle_maximize
        ).pack(side="right", padx=5)
        
        # Search bar
        search_container = ctk.CTkFrame(parent, fg_color="transparent")
        search_container.pack(fill="x", padx=15, pady=(5, 15))
        
        search_frame = ctk.CTkFrame(search_container, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=8)
        search_frame.pack(anchor="center")
        
        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="TV Show title...",
                                         fg_color="transparent", border_width=0, width=350,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL), height=45)
        self.search_entry.pack(side="left", padx=(15, 5), pady=10)
        self.search_entry.bind('<Return>', lambda e: self._search())
        
        self.year_entry = ctk.CTkEntry(search_frame, placeholder_text="Year",
                                       fg_color="transparent", border_width=0, width=100,
                                       font=ctk.CTkFont(size=self.FONT_NORMAL), height=45)
        self.year_entry.pack(side="left", padx=5, pady=10)
        
        ParagonButton(search_frame, text="SEARCH", command=self._search, width=120, height=45).pack(side="left", padx=(5, 15), pady=10)
    
    def _toggle_maximize(self):
        try:
            current_state = self.state()
            if current_state == 'zoomed' or current_state == 'maximized':
                self.state('normal')
            else:
                self.state('zoomed')
        except:
            self.attributes('-fullscreen', not self.attributes('-fullscreen'))
    
    def _create_info_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        self._add_field(scroll, "Files", "files", readonly=True)
        
        # IDs
        id_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        id_frame.pack(fill="x", pady=4)
        
        ctk.CTkLabel(id_frame, text="TMDB ID", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['tmdb_id'] = ctk.StringVar()
        ctk.CTkEntry(id_frame, textvariable=self.field_vars['tmdb_id'], width=150,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", padx=(0, 20))
        
        ctk.CTkLabel(id_frame, text="TVDB ID", width=100, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['tvdb_id'] = ctk.StringVar()
        ctk.CTkEntry(id_frame, textvariable=self.field_vars['tvdb_id'], width=120,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left")
        
        self._add_field(scroll, "Name", "title")
        self._add_field(scroll, "Original Name", "original_title")
        self._add_field(scroll, "Sort Title", "sort_title")
        self._add_field(scroll, "Tagline", "tagline")
        
        # Rating
        rating_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        rating_frame.pack(fill="x", pady=6)
        ctk.CTkLabel(rating_frame, text="Rating", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        rating_info = ctk.CTkFrame(rating_frame, fg_color=ParagonTheme.BG_DARK, corner_radius=4)
        rating_info.pack(side="left", fill="x", expand=True)
        self.rating_label = ctk.CTkLabel(rating_info, text="TMDB: --",
                                         text_color=ParagonTheme.TEXT_PRIMARY,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.rating_label.pack(padx=10, pady=8, anchor="w")
        
        # Premiere and Status
        premiere_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        premiere_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(premiere_frame, text="Premiered", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['premiered'] = ctk.StringVar()
        ctk.CTkEntry(premiere_frame, textvariable=self.field_vars['premiered'], width=130,
                    fg_color=ParagonTheme.BG_DARK, font=ctk.CTkFont(size=self.FONT_NORMAL),
                    height=36).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(premiere_frame, text="Status", width=80, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['status'] = ctk.StringVar()
        ctk.CTkOptionMenu(premiere_frame, variable=self.field_vars['status'],
                         values=["", "Continuing", "Ended", "Canceled", "In Production"],
                         fg_color=ParagonTheme.BG_DARK,
                         button_color=ParagonTheme.RED_PRIMARY,
                         font=ctk.CTkFont(size=self.FONT_NORMAL),
                         height=36).pack(side="left")
        
        # Certification
        cert_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        cert_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(cert_frame, text="Certification", width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars['certification'] = ctk.StringVar()
        ctk.CTkOptionMenu(cert_frame, variable=self.field_vars['certification'],
                         values=[""] + self.CERTIFICATIONS,
                         fg_color=ParagonTheme.BG_DARK,
                         button_color=ParagonTheme.RED_PRIMARY,
                         font=ctk.CTkFont(size=self.FONT_NORMAL),
                         height=36).pack(side="left")
        
        # Network/Studio
        self._add_field(scroll, "Network", "studio")
        
        # Plot
        plot_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        plot_frame.pack(fill="x", pady=6)
        ctk.CTkLabel(plot_frame, text="Plot", width=120, anchor="ne",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10), anchor="n")
        self.plot_text = ctk.CTkTextbox(plot_frame, height=120, fg_color=ParagonTheme.BG_DARK,
                                        font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.plot_text.pack(side="left", fill="x", expand=True)
    
    def _add_field(self, parent, label, key, readonly=False):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=4)
        ctk.CTkLabel(frame, text=label, width=120, anchor="e",
                    text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=(0, 10))
        self.field_vars[key] = ctk.StringVar()
        entry = ctk.CTkEntry(frame, textvariable=self.field_vars[key],
                            fg_color=ParagonTheme.BG_DARK,
                            font=ctk.CTkFont(size=self.FONT_NORMAL),
                            height=36,
                            state="disabled" if readonly else "normal")
        entry.pack(side="left", fill="x", expand=True)
    
    def _create_extended_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        ParagonLabel(scroll, text="Genres", style="header").pack(anchor="w", pady=(0, 8))
        self.genres_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.genres_frame.pack(fill="x", pady=(0, 20))
        self._create_genre_chips()
        
        ParagonLabel(scroll, text="Network/Studio", style="header").pack(anchor="w", pady=(0, 8))
        self.studios_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6, height=80)
        self.studios_frame.pack(fill="x", pady=(0, 15))
        self.studios_label = ctk.CTkLabel(self.studios_frame, text="No network/studio", 
                                          text_color=ParagonTheme.TEXT_SECONDARY,
                                          font=ctk.CTkFont(size=self.FONT_NORMAL))
        self.studios_label.pack(padx=15, pady=15, anchor="w")
    
    def _create_genre_chips(self):
        for widget in self.genres_frame.winfo_children():
            widget.destroy()
        
        row_frame = None
        for i, genre in enumerate(self.DEFAULT_GENRES):
            if i % 5 == 0:
                row_frame = ctk.CTkFrame(self.genres_frame, fg_color="transparent")
                row_frame.pack(fill="x", padx=8, pady=4)
            
            is_selected = genre in self.selected_genres
            btn = ctk.CTkButton(
                row_frame, text=genre, height=36,
                fg_color=ParagonTheme.RED_PRIMARY if is_selected else ParagonTheme.BG_TERTIARY,
                hover_color=ParagonTheme.RED_LIGHT if is_selected else ParagonTheme.BG_HOVER,
                text_color=ParagonTheme.TEXT_PRIMARY,
                corner_radius=18,
                font=ctk.CTkFont(size=self.FONT_SMALL),
                command=lambda g=genre: self._toggle_genre(g)
            )
            btn.pack(side="left", padx=3, pady=3)
    
    def _toggle_genre(self, genre):
        if genre in self.selected_genres:
            self.selected_genres.remove(genre)
        else:
            self.selected_genres.add(genre)
        self._create_genre_chips()
    
    def _create_stream_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        ParagonLabel(scroll, text="Video", style="header").pack(anchor="w", pady=(0, 8))
        video_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        video_frame.pack(fill="x", pady=(0, 20))
        
        self.video_info_labels = {}
        for field in ["Codec", "Resolution", "Aspect Ratio", "Scantype", "Duration"]:
            row = ctk.CTkFrame(video_frame, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(row, text=field, width=140, anchor="w",
                        text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
            lbl = ctk.CTkLabel(row, text="--", anchor="w", text_color=ParagonTheme.TEXT_PRIMARY,
                              font=ctk.CTkFont(size=self.FONT_NORMAL))
            lbl.pack(side="left", fill="x", expand=True)
            self.video_info_labels[field.lower().replace(" ", "_")] = lbl
        
        ParagonLabel(scroll, text="Audio", style="header").pack(anchor="w", pady=(15, 8))
        self.audio_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.audio_frame.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(self.audio_frame, text="No audio tracks", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=15)
        
        ParagonLabel(scroll, text="Subtitles", style="header").pack(anchor="w", pady=(0, 8))
        self.subs_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, corner_radius=6)
        self.subs_frame.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(self.subs_frame, text="No subtitles", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=15)
    
    def _update_stream_display(self):
        if not self.stream_info:
            return
        
        video = self.stream_info.get('video', {})
        if 'codec' in self.video_info_labels:
            self.video_info_labels['codec'].configure(text=video.get('codec', '--'))
        if 'resolution' in self.video_info_labels:
            self.video_info_labels['resolution'].configure(text=video.get('resolution', '--'))
        if 'aspect_ratio' in self.video_info_labels:
            self.video_info_labels['aspect_ratio'].configure(text=video.get('aspect', '--'))
        if 'scantype' in self.video_info_labels:
            self.video_info_labels['scantype'].configure(text=video.get('scantype', '--'))
        if 'duration' in self.video_info_labels:
            self.video_info_labels['duration'].configure(text=video.get('duration', '--'))
        
        for widget in self.audio_frame.winfo_children():
            widget.destroy()
        audio_tracks = self.stream_info.get('audio', [])
        if audio_tracks:
            for i, track in enumerate(audio_tracks):
                row = ctk.CTkFrame(self.audio_frame, fg_color="transparent")
                row.pack(fill="x", padx=15, pady=4)
                ctk.CTkLabel(row, text=f"Track {i+1}", width=80, text_color=ParagonTheme.TEXT_SECONDARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
                ctk.CTkLabel(row, text=track.get('language', 'und').upper(), text_color=ParagonTheme.TEXT_PRIMARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=15)
                ctk.CTkLabel(row, text=track.get('codec', ''), text_color=ParagonTheme.TEXT_PRIMARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=15)
                ctk.CTkLabel(row, text=f"{track.get('channels', '')}ch", text_color=ParagonTheme.TEXT_SECONDARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
        else:
            ctk.CTkLabel(self.audio_frame, text="No audio tracks", text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=10)
        
        for widget in self.subs_frame.winfo_children():
            widget.destroy()
        sub_tracks = self.stream_info.get('subtitles', [])
        if sub_tracks:
            for i, track in enumerate(sub_tracks):
                row = ctk.CTkFrame(self.subs_frame, fg_color="transparent")
                row.pack(fill="x", padx=15, pady=4)
                ctk.CTkLabel(row, text=f"Track {i+1}", width=80, text_color=ParagonTheme.TEXT_SECONDARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left")
                ctk.CTkLabel(row, text=track.get('language', 'und').upper(), text_color=ParagonTheme.TEXT_PRIMARY,
                            font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(side="left", padx=15)
        else:
            ctk.CTkLabel(self.subs_frame, text="No subtitles", text_color=ParagonTheme.TEXT_SECONDARY,
                        font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(padx=15, pady=10)
    
    def _create_artwork_panel(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=5, pady=10)
        
        # Poster
        ctk.CTkLabel(scroll, text="Poster (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.poster_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=180, corner_radius=4,
                                         cursor="hand2")
        self.poster_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.poster_frame.pack_propagate(False)
        self.poster_label = ctk.CTkLabel(self.poster_frame, text="No Poster\n(Click to choose)", 
                                         text_color=ParagonTheme.TEXT_SECONDARY,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL), cursor="hand2")
        self.poster_label.pack(expand=True)
        self.poster_frame.bind("<Button-1>", lambda e: self._choose_artwork('poster'))
        self.poster_label.bind("<Button-1>", lambda e: self._choose_artwork('poster'))
        
        # Logo
        ctk.CTkLabel(scroll, text="Logo (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.logo_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=70, corner_radius=4,
                                       cursor="hand2")
        self.logo_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.logo_frame.pack_propagate(False)
        self.logo_label = ctk.CTkLabel(self.logo_frame, text="No Logo\n(Click to choose)",
                                       text_color=ParagonTheme.TEXT_SECONDARY,
                                       font=ctk.CTkFont(size=self.FONT_NORMAL), cursor="hand2")
        self.logo_label.pack(expand=True)
        self.logo_frame.bind("<Button-1>", lambda e: self._choose_artwork('logo'))
        self.logo_label.bind("<Button-1>", lambda e: self._choose_artwork('logo'))
        
        # Fanart
        ctk.CTkLabel(scroll, text="Fanart (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.fanart_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=120, corner_radius=4,
                                         cursor="hand2")
        self.fanart_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.fanart_frame.pack_propagate(False)
        self.fanart_label = ctk.CTkLabel(self.fanart_frame, text="No Fanart\n(Click to choose)",
                                         text_color=ParagonTheme.TEXT_SECONDARY,
                                         font=ctk.CTkFont(size=self.FONT_NORMAL), cursor="hand2")
        self.fanart_label.pack(expand=True)
        self.fanart_frame.bind("<Button-1>", lambda e: self._choose_artwork('fanart'))
        self.fanart_label.bind("<Button-1>", lambda e: self._choose_artwork('fanart'))
        
        # Landscape
        ctk.CTkLabel(scroll, text="Landscape (click to choose)", text_color=ParagonTheme.TEXT_SECONDARY,
                    font=ctk.CTkFont(size=self.FONT_NORMAL)).pack(anchor="w", padx=8)
        self.landscape_frame = ctk.CTkFrame(scroll, fg_color=ParagonTheme.BG_DARK, height=100, corner_radius=4,
                                            cursor="hand2")
        self.landscape_frame.pack(fill="x", padx=8, pady=(0, 12))
        self.landscape_frame.pack_propagate(False)
        self.landscape_label = ctk.CTkLabel(self.landscape_frame, text="No Landscape\n(Click to choose)",
                                            text_color=ParagonTheme.TEXT_SECONDARY,
                                            font=ctk.CTkFont(size=self.FONT_NORMAL), cursor="hand2")
        self.landscape_label.pack(expand=True)
        self.landscape_frame.bind("<Button-1>", lambda e: self._choose_artwork('landscape'))
        self.landscape_label.bind("<Button-1>", lambda e: self._choose_artwork('landscape'))
        
        # Download button
        ParagonLabel(scroll, text="DOWNLOAD", style="header").pack(anchor="w", padx=8, pady=(10, 0))
    
    def _choose_artwork(self, art_type: str):
        """Open image chooser for artwork"""
        if not self.show_details or not self.show_details.get('id'):
            messagebox.showinfo("Search First", "Please search and select a TV show first")
            return
        
        # TODO: Implement TV show image chooser
        messagebox.showinfo("Coming Soon", f"TV show {art_type} chooser coming soon!")
    
    def _search(self):
        """Search for TV shows"""
        query = self.search_entry.get().strip()
        year = self.year_entry.get().strip()
        
        if not query:
            messagebox.showinfo("Search", "Please enter a TV show name")
            return
        
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        ParagonLabel(self.results_list, text="Searching...", style="muted").pack(pady=20)
        self.update()
        
        def do_search():
            results = TMDBAPI.search_tv(query, year if year else None)
            self.after(0, lambda: self._display_results(results))
        
        threading.Thread(target=do_search, daemon=True).start()
    
    def _display_results(self, results: List[Dict]):
        """Display search results"""
        for widget in self.results_list.winfo_children():
            widget.destroy()
        
        self.search_results = results
        
        if not results:
            ParagonLabel(self.results_list, text="No shows found", style="muted").pack(pady=20)
            return
        
        for i, show in enumerate(results[:15]):
            self._add_result_row(i, show)
    
    def _add_result_row(self, index: int, show: Dict):
        """Add a result row"""
        frame = ctk.CTkFrame(
            self.results_list,
            fg_color=ParagonTheme.BG_TERTIARY if index % 2 == 0 else ParagonTheme.BG_SECONDARY,
            corner_radius=4
        )
        frame.pack(fill="x", pady=2)
        frame.bind("<Button-1>", lambda e, idx=index: self._select_result(idx))
        
        title_text = show.get('title', 'Unknown')
        if show.get('year'):
            title_text += f" ({show['year']})"
        
        lbl = ctk.CTkLabel(frame, text=title_text, font=ctk.CTkFont(size=14),
                          text_color=ParagonTheme.TEXT_PRIMARY, anchor="w")
        lbl.pack(fill="x", padx=10, pady=8)
        lbl.bind("<Button-1>", lambda e, idx=index: self._select_result(idx))
    
    def _select_result(self, index: int):
        """Select a search result"""
        if index >= len(self.search_results):
            return
        
        self.selected_show = self.search_results[index]
        
        # Highlight selected
        for i, widget in enumerate(self.results_list.winfo_children()):
            if isinstance(widget, ctk.CTkFrame):
                widget.configure(fg_color=ParagonTheme.RED_DARK if i == index else 
                               (ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY))
        
        # Fetch details
        show_id = self.selected_show.get('id')
        
        def fetch_details():
            details = TMDBAPI.get_tv_details(show_id)
            if details:
                self.after(0, lambda: self._update_details(details))
        
        threading.Thread(target=fetch_details, daemon=True).start()
    
    def _update_details(self, details: Dict):
        """Update UI with show details"""
        self.show_details = details
        
        # Update fields
        if 'title' in self.field_vars:
            self.field_vars['title'].set(details.get('title', ''))
        if 'original_title' in self.field_vars:
            self.field_vars['original_title'].set(details.get('original_title', ''))
        if 'sort_title' in self.field_vars:
            self.field_vars['sort_title'].set(details.get('title', ''))
        if 'tagline' in self.field_vars:
            self.field_vars['tagline'].set(details.get('tagline', ''))
        if 'premiered' in self.field_vars:
            self.field_vars['premiered'].set(details.get('first_air_date', ''))
        if 'status' in self.field_vars:
            self.field_vars['status'].set(details.get('status', ''))
        if 'tmdb_id' in self.field_vars:
            self.field_vars['tmdb_id'].set(str(details.get('id', '')))
        if 'tvdb_id' in self.field_vars:
            tvdb_id = details.get('tvdb_id', '')
            self.field_vars['tvdb_id'].set(str(tvdb_id) if tvdb_id else '')
        
        # Update rating
        rating = details.get('vote_average', 0)
        votes = details.get('vote_count', 0)
        self.rating_label.configure(text=f"TMDB: {rating:.1f} | Votes: {votes}")
        
        # Update plot
        self.plot_text.delete("1.0", "end")
        self.plot_text.insert("1.0", details.get('overview', ''))
        
        # Update genres
        self.selected_genres = set(details.get('genres', []))
        self._create_genre_chips()
        
        # Update network/studio
        networks = details.get('networks', [])
        if networks:
            self.studios_label.configure(text=", ".join(networks[:3]))
            self.selected_studios = set(networks)
        
        # Load poster
        if details.get('poster_path') and HAS_PIL:
            def load_poster():
                data = TMDBAPI.download_image(details['poster_path'], 'w342')
                if data:
                    try:
                        img = Image.open(io.BytesIO(data))
                        img.thumbnail((120, 170), Image.Resampling.LANCZOS)
                        self._poster_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                        self.after(0, lambda: self.poster_label.configure(image=self._poster_photo, text=""))
                    except:
                        pass
            threading.Thread(target=load_poster, daemon=True).start()
    
    def _save_all(self):
        """Save NFO and download artwork"""
        if not self.show_details and not self.field_vars.get('title', ctk.StringVar()).get():
            messagebox.showwarning("No Data", "Please search and select a TV show first or enter data manually")
            return
        
        # Get TMDB ID and TVDB ID from fields
        tmdb_id_str = self.field_vars.get('tmdb_id', ctk.StringVar()).get()
        tvdb_id_str = self.field_vars.get('tvdb_id', ctk.StringVar()).get()
        
        try:
            tmdb_id = int(tmdb_id_str) if tmdb_id_str and tmdb_id_str.isdigit() else None
        except:
            tmdb_id = None
        
        try:
            tvdb_id = int(tvdb_id_str) if tvdb_id_str and tvdb_id_str.isdigit() else None
        except:
            tvdb_id = None
        
        # Fall back to show_details if no ID in field
        if not tmdb_id and self.show_details:
            tmdb_id = self.show_details.get('id')
        if not tvdb_id and self.show_details:
            tvdb_id = self.show_details.get('tvdb_id')
        
        # Build show data from fields
        show_data = {
            'title': self.field_vars.get('title', ctk.StringVar()).get(),
            'original_title': self.field_vars.get('original_title', ctk.StringVar()).get(),
            'sort_title': self.field_vars.get('sort_title', ctk.StringVar()).get(),
            'tagline': self.field_vars.get('tagline', ctk.StringVar()).get(),
            'overview': self.plot_text.get("1.0", "end-1c"),
            'first_air_date': self.field_vars.get('premiered', ctk.StringVar()).get(),
            'status': self.field_vars.get('status', ctk.StringVar()).get(),
            'certification': self.field_vars.get('certification', ctk.StringVar()).get(),
            'genres': list(self.selected_genres),
            'networks': list(self.selected_studios),
            'id': tmdb_id,
            'tvdb_id': tvdb_id,
            'imdb_id': self.show_details.get('imdb_id') if self.show_details else None,
            'vote_average': self.show_details.get('vote_average', 0) if self.show_details else 0,
            'vote_count': self.show_details.get('vote_count', 0) if self.show_details else 0,
            'poster_path': self.show_details.get('poster_path') if self.show_details else None,
            'backdrop_path': self.show_details.get('backdrop_path') if self.show_details else None,
            'cast': self.show_details.get('cast', []) if self.show_details else [],
            'creators': self.show_details.get('creators', []) if self.show_details else [],
        }
        
        # Get folder
        folder = os.path.dirname(self.current_file)
        
        # Generate and save tvshow.nfo
        nfo_content = NFOGenerator.generate_tvshow_nfo(show_data)
        nfo_path = os.path.join(folder, "tvshow.nfo")
        
        try:
            with open(nfo_path, 'w', encoding='utf-8') as f:
                f.write(nfo_content)
            print(f"Saved: {nfo_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save NFO: {e}")
            return
        
        # Download poster
        if show_data.get('poster_path'):
            poster_data = TMDBAPI.download_image(show_data['poster_path'], 'original')
            if poster_data:
                poster_path = os.path.join(folder, "poster.jpg")
                try:
                    with open(poster_path, 'wb') as f:
                        f.write(poster_data)
                    print(f"Saved: {poster_path}")
                except Exception as e:
                    print(f"Error saving poster: {e}")
        
        # Download fanart
        if show_data.get('backdrop_path'):
            fanart_data = TMDBAPI.download_image(show_data['backdrop_path'], 'original')
            if fanart_data:
                fanart_path = os.path.join(folder, "fanart.jpg")
                try:
                    with open(fanart_path, 'wb') as f:
                        f.write(fanart_data)
                    print(f"Saved: {fanart_path}")
                except Exception as e:
                    print(f"Error saving fanart: {e}")
        
        messagebox.showinfo("Success", f"TV show data saved!\n\n• tvshow.nfo\n• poster.jpg\n• fanart.jpg")
        self.destroy()


# =============================================================================
# MAIN APPLICATION
# =============================================================================

# Create a DnD-enabled CTk class if tkinterdnd2 is available
if HAS_DND:
    class DnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
        """CustomTkinter with Drag & Drop support"""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    DnDCTk = ctk.CTk


def open_child_window(child, launcher):
    """Single-window navigation helper.

    Hides ``launcher`` (the window that opened ``child``) while ``child`` is
    displayed, and restores it once ``child`` is closed.  This keeps only one
    window visible at a time instead of letting library/editor windows stack
    on top of each other.

    Restoration is idempotent and fires whether the child is dismissed via the
    window-manager close button or by destroying itself (e.g. a Close/Save
    button).  Returns ``child`` so callers can keep chaining.
    """
    if child is None or launcher is None:
        return child

    try:
        launcher.withdraw()
    except Exception:
        pass

    state = {'restored': False}

    def restore():
        if state['restored']:
            return
        state['restored'] = True
        try:
            if launcher.winfo_exists():
                launcher.deiconify()
                launcher.lift()
                launcher.focus_force()
        except Exception:
            pass

    def on_wm_close():
        restore()
        try:
            child.destroy()
        except Exception:
            pass

    try:
        child.protocol("WM_DELETE_WINDOW", on_wm_close)
    except Exception:
        pass

    def on_destroy(event):
        # <Destroy> bubbles up from descendants too; only react to the window.
        if event.widget is child:
            restore()

    try:
        child.bind("<Destroy>", on_destroy, add="+")
    except Exception:
        pass

    return child


class PyRenamerApp(DnDCTk):
    """Main application - Paragon Edition"""
    
    # Class-level cache for directory listings (shared across instances)
    _dir_cache: Dict[str, any] = {}
    _cache_timestamps: Dict[str, float] = {}
    _cache_ttl = 600  # Cache TTL in seconds (10 minutes for NFS)
    
    @classmethod
    def preload_nfs_mounts(cls):
        """Preload NFS mount points in background thread - LIGHT version"""
        def _preload():
            import time
            mnt_path = "/mnt"

            # /mnt only exists on POSIX systems (Linux/macOS). On Windows
            # network shares are mapped to drive letters, so there is nothing
            # to preload here - skip quietly instead of printing an error.
            if not os.path.isdir(mnt_path):
                return

            try:
                # Only preload /mnt itself - keep it light!
                dirs = []
                files = []
                
                with os.scandir(mnt_path) as scanner:
                    for entry in scanner:
                        if entry.name.startswith('.'):
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=True):
                                dirs.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=True):
                                files.append(Path(entry.path))
                        except OSError:
                            dirs.append(Path(entry.path))
                
                dirs.sort(key=lambda x: x.name.lower())
                files.sort(key=lambda x: x.name.lower())
                
                cache_key = f"{mnt_path}_classified"
                cls._dir_cache[cache_key] = (dirs, files)
                cls._cache_timestamps[cache_key] = time.time()
                
                print(f"✓ Preloaded /mnt: {len(dirs)} dirs")
                
            except Exception as e:
                print(f"✗ Could not preload /mnt: {e}")
        
        # Run in background thread with low priority
        thread = threading.Thread(target=_preload, daemon=True)
        thread.start()
    
    @classmethod
    def get_cached_listing(cls, path: str) -> Optional[any]:
        """Get cached directory listing if available and not expired"""
        import time
        if path in cls._dir_cache:
            age = time.time() - cls._cache_timestamps.get(path, 0)
            if age < cls._cache_ttl:
                return cls._dir_cache[path]
        return None
    
    @classmethod
    def cache_listing(cls, path: str, entries: List[str]):
        """Cache a directory listing"""
        import time
        cls._dir_cache[path] = entries
        cls._cache_timestamps[path] = time.time()
    
    def __init__(self):
        # Enable mouse wheel scrolling globally BEFORE creating any widgets
        enable_mousewheel_scrolling(None)
        
        super().__init__()
        
        # Configure window
        self.title("PYRENAMER — Bulk File Renamer")
        self.geometry("1300x850")
        self.minsize(1000, 700)
        self.after(10, lambda: self.state('zoomed'))  # Maximize window
        
        # Set appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        
        # Configure colors
        self.configure(fg_color=ParagonTheme.BG_DARK)
        
        # State
        self.files: List[FileItem] = []
        self.undo_manager = UndoManager()
        self.include_extension = ctk.BooleanVar(value=False)
        self.include_folders = ctk.BooleanVar(value=False)
        self.recursive_scan = ctk.BooleanVar(value=False)
        self.filter_text = ctk.StringVar(value="")
        self.rename_history: List[dict] = []  # Track rename operations for log export
        self.sort_key: str = "name"  # Current sort key
        self.sort_reverse: bool = False  # Sort direction
        
        # Rule variables
        self._init_rule_variables()
        
        # Debounce timer for preview updates
        self._preview_timer = None
        self._debounce_delay = 300  # milliseconds
        
        # Build UI
        self._create_ui()
        
        # Preload NFS mounts in background
        PyRenamerApp.preload_nfs_mounts()
    
    def _init_rule_variables(self):
        """Initialize all rule-related variables"""
        # Replace
        self.replace_find = ctk.StringVar()
        self.replace_with = ctk.StringVar()
        self.replace_regex = ctk.BooleanVar(value=False)
        self.replace_case = ctk.BooleanVar(value=True)
        
        # Remove
        self.remove_start = ctk.StringVar(value="0")
        self.remove_count = ctk.StringVar(value="0")
        self.remove_from_end = ctk.BooleanVar(value=False)
        self.remove_digits = ctk.BooleanVar(value=False)
        self.remove_spaces = ctk.BooleanVar(value=False)
        self.remove_illegal = ctk.BooleanVar(value=False)
        self.remove_brackets = ctk.BooleanVar(value=False)
        self.remove_punctuation = ctk.BooleanVar(value=False)
        self.remove_all_special = ctk.BooleanVar(value=False)
        
        # Insert
        self.insert_text = ctk.StringVar()
        self.insert_pos = ctk.StringVar(value="0")
        self.insert_from_end = ctk.BooleanVar(value=False)
        
        # Case
        self.case_type = ctk.StringVar(value="none")
        
        # Number
        self.number_enabled = ctk.BooleanVar(value=False)
        self.number_start = ctk.StringVar(value="1")
        self.number_step = ctk.StringVar(value="1")
        self.number_padding = ctk.StringVar(value="2")
        self.number_position = ctk.StringVar(value="suffix")
        self.number_separator = ctk.StringVar(value="_")
        
        # TV Show
        self.tv_enabled = ctk.BooleanVar(value=False)
        self.tv_season = ctk.StringVar(value="1")
        self.tv_episode_start = ctk.StringVar(value="1")
        self.tv_episode_step = ctk.StringVar(value="1")
        self.tv_max_episodes = ctk.StringVar(value="0")  # 0 = unlimited
        self.tv_format = ctk.StringVar(value="S00E00")
        self.tv_separator = ctk.StringVar(value=" - ")
        self.tv_position = ctk.StringVar(value="prefix")
        self.tv_include_show = ctk.BooleanVar(value=False)
        self.tv_show_name = ctk.StringVar(value="")
        
        # DateTime
        self.datetime_enabled = ctk.BooleanVar(value=False)
        self.datetime_format = ctk.StringVar(value="%Y-%m-%d")
        self.datetime_source = ctk.StringVar(value="File modified date")
        self.datetime_position = ctk.StringVar(value="prefix")
        self.datetime_separator = ctk.StringVar(value="_")
        
        # Metadata
        self.metadata_enabled = ctk.BooleanVar(value=False)
        self.metadata_template = ctk.StringVar(value="{artist} - {title}")
        
        # Swap segments
        self.swap_enabled = ctk.BooleanVar(value=False)
        self.swap_delimiter = ctk.StringVar(value=" - ")
        
        # Bind trace callbacks for live preview WITH DEBOUNCING
        for var in [self.replace_find, self.replace_with, self.remove_start, 
                    self.remove_count, self.insert_text, self.insert_pos,
                    self.number_start, self.number_step, self.number_padding,
                    self.number_separator, self.datetime_format, self.datetime_separator,
                    self.metadata_template, self.tv_season, self.tv_episode_start,
                    self.tv_episode_step, self.tv_max_episodes, self.tv_separator, self.tv_show_name,
                    self.filter_text, self.swap_delimiter]:
            var.trace_add("write", lambda *args: self._schedule_preview_update())
        
        for var in [self.replace_regex, self.replace_case, self.remove_from_end,
                    self.remove_digits, self.remove_spaces,
                    self.remove_illegal, self.remove_brackets, self.remove_punctuation, self.remove_all_special,
                    self.insert_from_end, self.number_enabled, self.datetime_enabled,
                    self.metadata_enabled, self.include_extension, self.include_folders,
                    self.tv_enabled, self.tv_include_show,
                    self.swap_enabled]:
            var.trace_add("write", lambda *args: self._schedule_preview_update())
    
    def _schedule_preview_update(self):
        """Schedule a preview update with debouncing"""
        # Cancel any pending update
        if self._preview_timer is not None:
            self.after_cancel(self._preview_timer)
        
        # Schedule new update after delay
        self._preview_timer = self.after(self._debounce_delay, self._do_preview_update)
    
    def _do_preview_update(self):
        """Actually perform the preview update"""
        self._preview_timer = None
        self._update_preview()
    
    def _create_ui(self):
        """Create the main UI"""
        # Main container with gold border effect
        self.main_container = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=12)
        self.main_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        inner_container = ctk.CTkFrame(self.main_container, fg_color=ParagonTheme.BG_DARK, corner_radius=10)
        inner_container.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Header
        self._create_header(inner_container)
        
        # Decorative lines (Paragon style)
        self._create_decorative_lines(inner_container)
        
        # Toolbar
        self._create_toolbar(inner_container)
        
        # Main content area
        content = ctk.CTkFrame(inner_container, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=15, pady=(10, 15))
        
        # Left panel - Rules
        left_panel = ParagonFrame(content)
        left_panel.pack(side="left", fill="both", expand=False, padx=(0, 10))
        left_panel.configure(width=420)
        self._create_rules_panel(left_panel)
        
        # Right panel - Files
        right_panel = ParagonFrame(content)
        right_panel.pack(side="right", fill="both", expand=True)
        self._create_file_panel(right_panel)
        
        # Bottom decorative lines
        self._create_decorative_lines(inner_container, bottom=True)
        
        # Status bar
        self._create_status_bar(inner_container)
    
    def _create_header(self, parent):
        """Create Paragon-style header"""
        header = ctk.CTkFrame(parent, fg_color="transparent", height=180)
        header.pack(fill="x", padx=20, pady=(5, 5))
        header.pack_propagate(False)
        
        # Logo/Title area
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left", anchor="n")
        
        # Try to load PNG logo, fall back to text
        logo_loaded = False
        logo_path = Path(__file__).parent / "paragon_logo.png"
        
        if logo_path.exists() and HAS_PIL:
            try:
                logo_image = Image.open(logo_path)
                # Resize to fit header (height ~220px, maintain aspect ratio)
                target_height = 220
                aspect = logo_image.width / logo_image.height
                target_width = int(target_height * aspect)
                logo_image = logo_image.resize((target_width, target_height), Image.Resampling.LANCZOS)
                
                self._logo_ctk = ctk.CTkImage(light_image=logo_image, dark_image=logo_image, 
                                               size=(target_width, target_height))
                logo_label = ctk.CTkLabel(title_frame, image=self._logo_ctk, text="")
                logo_label.pack(side="left", anchor="nw", pady=(20, 0))
                logo_loaded = True
            except Exception as e:
                print(f"Could not load logo: {e}")
        
        if not logo_loaded:
            # Fallback: Text title - PARAGON style
            title = ctk.CTkLabel(
                title_frame,
                text="PYRENAMER",
                font=ctk.CTkFont(family="Segoe UI Black", size=32, weight="bold"),
                text_color=ParagonTheme.RED_LIGHT
            )
            title.pack(side="left", anchor="w")
        
        # Subtitle (only show if no logo, since logo has its own branding)
        if not logo_loaded:
            subtitle = ctk.CTkLabel(
                title_frame,
                text="  Bulk File Renamer",
                font=ctk.CTkFont(family="Segoe UI", size=14, slant="italic"),
                text_color=ParagonTheme.GOLD
            )
            subtitle.pack(side="left", anchor="s", pady=(0, 8))
    
    def _create_decorative_lines(self, parent, bottom=False):
        """Create Paragon-style decorative lines"""
        container = ctk.CTkFrame(parent, fg_color="transparent", height=8)
        container.pack(fill="x", padx=15, pady=(0 if bottom else 5, 5 if bottom else 0))
        container.pack_propagate(False)
        
        # Red line
        red_line = ctk.CTkFrame(container, fg_color=ParagonTheme.RED_DARK, height=3, corner_radius=1)
        red_line.pack(fill="x", pady=(0, 2))
        
        # Gold/orange line
        gold_line = ctk.CTkFrame(container, fg_color=ParagonTheme.GOLD, height=2, corner_radius=1)
        gold_line.pack(fill="x")
    
    def _create_toolbar(self, parent):
        """Create toolbar with Paragon-style buttons"""
        toolbar = ctk.CTkFrame(parent, fg_color="transparent", height=50)
        toolbar.pack(fill="x", padx=20, pady=(5, 10))
        toolbar.pack_propagate(False)
        
        # Left buttons
        left_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        left_frame.pack(side="left", fill="y")
        
        ParagonButton(left_frame, text="📁  ADD FILES", command=self._add_files, width=130).pack(side="left", padx=(0, 8))
        ParagonButton(left_frame, text="📂  ADD FOLDER", command=self._add_folder, width=140).pack(side="left", padx=(0, 8))
        ParagonSecondaryButton(left_frame, text="🗑️  CLEAR", command=self._clear_files, width=100).pack(side="left", padx=(0, 8))
        ParagonSecondaryButton(left_frame, text="📄  EXPORT LOG", command=self._export_log, width=120).pack(side="left")
        
        # Right buttons
        right_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        right_frame.pack(side="right", fill="y")
        
        ParagonSecondaryButton(right_frame, text="↩️  UNDO", command=self._undo, width=90).pack(side="left", padx=(0, 10))
        ParagonGoldButton(right_frame, text="✨  RENAME ALL", command=self._execute_rename, width=160).pack(side="left")
    
    def _create_rules_panel(self, parent):
        """Create the rules configuration panel"""
        # Header with preset buttons
        header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))
        
        ParagonLabel(header_frame, text="⚙️  RENAME RULES", style="title").pack(side="left")
        
        # Preset buttons on the right
        preset_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        preset_frame.pack(side="right")
        
        ParagonSecondaryButton(preset_frame, text="💾", command=self._save_preset, width=35, height=28).pack(side="left", padx=2)
        ParagonSecondaryButton(preset_frame, text="📂", command=self._load_preset, width=35, height=28).pack(side="left", padx=2)
        ParagonSecondaryButton(preset_frame, text="📋", command=self._manage_presets, width=35, height=28).pack(side="left", padx=2)
        
        # Tabview for rules
        self.rules_tabs = ParagonTabview(parent, height=460)
        self.rules_tabs.pack(fill="x", padx=10, pady=(0, 5))
        
        # Create tabs
        self.rules_tabs.add("Replace")
        self.rules_tabs.add("Remove")
        self.rules_tabs.add("Insert")
        self.rules_tabs.add("Case")
        self.rules_tabs.add("Number")
        self.rules_tabs.add("TV")
        self.rules_tabs.add("Date")
        self.rules_tabs.add("Tags")
        self.rules_tabs.add("Media")
        
        # Populate tabs
        self._create_replace_tab(self.rules_tabs.tab("Replace"))
        self._create_remove_tab(self.rules_tabs.tab("Remove"))
        self._create_insert_tab(self.rules_tabs.tab("Insert"))
        self._create_case_tab(self.rules_tabs.tab("Case"))
        self._create_number_tab(self.rules_tabs.tab("Number"))
        self._create_tv_tab(self.rules_tabs.tab("TV"))
        self._create_datetime_tab(self.rules_tabs.tab("Date"))
        self._create_tags_tab(self.rules_tabs.tab("Tags"))
        self._create_media_tab(self.rules_tabs.tab("Media"))
        
        # Set Media tab as default
        self.rules_tabs.set("Media")
        
        # Options section
        options_frame = ParagonFrame(parent)
        options_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        ParagonLabel(options_frame, text="OPTIONS", style="header").pack(anchor="w", padx=15, pady=(10, 5))
        
        ParagonCheckbox(options_frame, text="Include extension in rename", 
                       variable=self.include_extension).pack(anchor="w", padx=15, pady=3)
        ParagonCheckbox(options_frame, text="Include folders",
                       variable=self.include_folders).pack(anchor="w", padx=15, pady=3)
        ParagonCheckbox(options_frame, text="Scan subfolders (recursive)",
                       variable=self.recursive_scan).pack(anchor="w", padx=15, pady=(3, 10))
    
    def _create_replace_tab(self, parent):
        """Replace rule tab"""
        ParagonLabel(parent, text="Find:", style="muted").pack(anchor="w", padx=10, pady=(15, 5))
        ParagonEntry(parent, textvariable=self.replace_find, placeholder_text="Text to find...", width=350).pack(padx=10)
        
        ParagonLabel(parent, text="Replace with:", style="muted").pack(anchor="w", padx=10, pady=(15, 5))
        ParagonEntry(parent, textvariable=self.replace_with, placeholder_text="Replacement text...", width=350).pack(padx=10)
        
        ParagonCheckbox(parent, text="Use Regular Expressions", variable=self.replace_regex).pack(anchor="w", padx=10, pady=(15, 5))
        ParagonCheckbox(parent, text="Case Sensitive", variable=self.replace_case).pack(anchor="w", padx=10, pady=5)
    
    def _create_remove_tab(self, parent):
        """Remove rule tab"""
        # Position removal
        pos_frame = ctk.CTkFrame(parent, fg_color="transparent")
        pos_frame.pack(fill="x", padx=10, pady=(15, 10))
        
        ParagonLabel(pos_frame, text="Start position:", style="muted").pack(side="left")
        ParagonEntry(pos_frame, textvariable=self.remove_start, width=80).pack(side="left", padx=(10, 20))
        
        ParagonLabel(pos_frame, text="Count:", style="muted").pack(side="left")
        ParagonEntry(pos_frame, textvariable=self.remove_count, width=80).pack(side="left", padx=10)
        
        ParagonCheckbox(parent, text="Count from end", variable=self.remove_from_end).pack(anchor="w", padx=10, pady=5)
        
        # Separator
        ctk.CTkFrame(parent, fg_color=ParagonTheme.BORDER_DARK, height=1).pack(fill="x", padx=10, pady=15)
        
        ParagonLabel(parent, text="Remove character types:", style="muted").pack(anchor="w", padx=10, pady=(0, 10))
        ParagonCheckbox(parent, text="Digits (0-9)", variable=self.remove_digits).pack(anchor="w", padx=20, pady=3)
        ParagonCheckbox(parent, text="Spaces", variable=self.remove_spaces).pack(anchor="w", padx=20, pady=3)
        
        # Separator
        ctk.CTkFrame(parent, fg_color=ParagonTheme.BORDER_DARK, height=1).pack(fill="x", padx=10, pady=15)
        
        # Illegal/special characters section
        ParagonLabel(parent, text="Remove illegal/special characters:", style="muted").pack(anchor="w", padx=10, pady=(0, 10))
        
        ParagonCheckbox(parent, text='Illegal file chars:  \\ / : * ? " < > |', 
                       variable=self.remove_illegal).pack(anchor="w", padx=20, pady=3)
        ParagonCheckbox(parent, text="Brackets:  ( ) [ ] { }", 
                       variable=self.remove_brackets).pack(anchor="w", padx=20, pady=3)
        ParagonCheckbox(parent, text="Punctuation:  ! @ # $ % ^ & ~ ` ; ' ,", 
                       variable=self.remove_punctuation).pack(anchor="w", padx=20, pady=3)
        ParagonCheckbox(parent, text="All non-alphanumeric (keep spaces)", 
                       variable=self.remove_all_special).pack(anchor="w", padx=20, pady=3)
    
    def _create_insert_tab(self, parent):
        """Insert rule tab"""
        ParagonLabel(parent, text="Text to insert:", style="muted").pack(anchor="w", padx=10, pady=(15, 5))
        ParagonEntry(parent, textvariable=self.insert_text, placeholder_text="Text to insert...", width=350).pack(padx=10)
        
        pos_frame = ctk.CTkFrame(parent, fg_color="transparent")
        pos_frame.pack(fill="x", padx=10, pady=(15, 5))
        
        ParagonLabel(pos_frame, text="At position:", style="muted").pack(side="left")
        ParagonEntry(pos_frame, textvariable=self.insert_pos, width=80).pack(side="left", padx=10)
        
        ParagonCheckbox(parent, text="Count from end", variable=self.insert_from_end).pack(anchor="w", padx=10, pady=10)
    
    def _create_case_tab(self, parent):
        """Case change tab"""
        ParagonLabel(parent, text="Convert filename to:", style="muted").pack(anchor="w", padx=10, pady=(15, 10))
        
        cases = [
            ("No change", "none"),
            ("lowercase", "lower"),
            ("UPPERCASE", "upper"),
            ("Title Case", "title"),
            ("Sentence case", "sentence"),
            ("sWAP cASE", "swap"),
        ]
        
        for text, value in cases:
            ParagonRadioButton(parent, text=text, variable=self.case_type, value=value,
                              command=self._update_preview).pack(anchor="w", padx=20, pady=5)
        
        # Separator
        ctk.CTkFrame(parent, fg_color=ParagonTheme.BORDER_DARK, height=1).pack(fill="x", padx=10, pady=15)
        
        # Swap segments option
        ParagonLabel(parent, text="Swap Segments:", style="muted").pack(anchor="w", padx=10, pady=(0, 5))
        
        swap_frame = ctk.CTkFrame(parent, fg_color="transparent")
        swap_frame.pack(fill="x", padx=10, pady=5)
        
        ParagonCheckbox(swap_frame, text="Swap around delimiter:", 
                       variable=self.swap_enabled).pack(side="left")
        ParagonEntry(swap_frame, textvariable=self.swap_delimiter, width=80).pack(side="left", padx=10)
        
        # Help text
        help_frame = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        help_frame.pack(fill="x", padx=10, pady=(10, 5))
        ParagonLabel(help_frame, text="Example: 'Artist - Song' → 'Song - Artist'\n⚠️ Only applies to selected files (Ctrl+click to select)", 
                    style="muted").pack(padx=10, pady=8, anchor="w")
    
    def _create_number_tab(self, parent):
        """Number rule tab"""
        ParagonCheckbox(parent, text="Add sequential numbers", variable=self.number_enabled).pack(anchor="w", padx=10, pady=(15, 10))
        
        # Settings grid
        settings = ctk.CTkFrame(parent, fg_color="transparent")
        settings.pack(fill="x", padx=10, pady=5)
        
        row1 = ctk.CTkFrame(settings, fg_color="transparent")
        row1.pack(fill="x", pady=5)
        ParagonLabel(row1, text="Start:", style="muted").pack(side="left")
        ParagonEntry(row1, textvariable=self.number_start, width=70).pack(side="left", padx=(10, 20))
        ParagonLabel(row1, text="Step:", style="muted").pack(side="left")
        ParagonEntry(row1, textvariable=self.number_step, width=70).pack(side="left", padx=10)
        
        row2 = ctk.CTkFrame(settings, fg_color="transparent")
        row2.pack(fill="x", pady=5)
        ParagonLabel(row2, text="Padding:", style="muted").pack(side="left")
        ParagonEntry(row2, textvariable=self.number_padding, width=70).pack(side="left", padx=(10, 20))
        ParagonLabel(row2, text="Separator:", style="muted").pack(side="left")
        ParagonEntry(row2, textvariable=self.number_separator, width=70).pack(side="left", padx=10)
        
        ParagonLabel(parent, text="Position:", style="muted").pack(anchor="w", padx=10, pady=(15, 5))
        ParagonOptionMenu(parent, variable=self.number_position, values=["prefix", "suffix", "replace"],
                         command=lambda v: self._update_preview(), width=200).pack(anchor="w", padx=10)
    
    def _create_tv_tab(self, parent):
        """TV Show season/episode rule tab"""
        ParagonCheckbox(parent, text="Enable TV Show numbering", variable=self.tv_enabled).pack(anchor="w", padx=10, pady=(15, 10))
        
        # Season and Episode row
        se_frame = ctk.CTkFrame(parent, fg_color="transparent")
        se_frame.pack(fill="x", padx=10, pady=5)
        
        ParagonLabel(se_frame, text="Season:", style="muted").pack(side="left")
        ParagonEntry(se_frame, textvariable=self.tv_season, width=60).pack(side="left", padx=(10, 20))
        
        ParagonLabel(se_frame, text="Episode start:", style="muted").pack(side="left")
        ParagonEntry(se_frame, textvariable=self.tv_episode_start, width=60).pack(side="left", padx=(10, 20))
        
        ParagonLabel(se_frame, text="Step:", style="muted").pack(side="left")
        ParagonEntry(se_frame, textvariable=self.tv_episode_step, width=60).pack(side="left", padx=10)
        
        # Max episodes per season (auto-increment)
        max_frame = ctk.CTkFrame(parent, fg_color="transparent")
        max_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        ParagonLabel(max_frame, text="Episodes per season:", style="muted").pack(side="left")
        ParagonEntry(max_frame, textvariable=self.tv_max_episodes, width=60).pack(side="left", padx=10)
        ParagonLabel(max_frame, text="(0 = no limit)", style="muted").pack(side="left")
        
        # Format selection
        ParagonLabel(parent, text="Format:", style="muted").pack(anchor="w", padx=10, pady=(15, 5))
        ParagonOptionMenu(parent, variable=self.tv_format,
                         values=["S00E00", "00x00", "0x00", "s0e0", "Season 0 Episode 0"],
                         command=lambda v: self._schedule_preview_update(), width=200).pack(anchor="w", padx=10)
        
        # Separator
        sep_frame = ctk.CTkFrame(parent, fg_color="transparent")
        sep_frame.pack(fill="x", padx=10, pady=(10, 5))
        ParagonLabel(sep_frame, text="Separator:", style="muted").pack(side="left")
        ParagonEntry(sep_frame, textvariable=self.tv_separator, width=80).pack(side="left", padx=10)
        
        # Position
        ParagonLabel(parent, text="Position:", style="muted").pack(anchor="w", padx=10, pady=(10, 5))
        ParagonOptionMenu(parent, variable=self.tv_position,
                         values=["prefix", "suffix", "replace"],
                         command=lambda v: self._schedule_preview_update(), width=200).pack(anchor="w", padx=10)
        
        # Show name option
        ctk.CTkFrame(parent, fg_color=ParagonTheme.BORDER_DARK, height=1).pack(fill="x", padx=10, pady=10)
        
        ParagonCheckbox(parent, text="Include show name", variable=self.tv_include_show).pack(anchor="w", padx=10, pady=3)
        ParagonEntry(parent, textvariable=self.tv_show_name, placeholder_text="Show Name", width=250).pack(anchor="w", padx=10, pady=3)
        
        # Help text
        help_frame = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        help_frame.pack(fill="x", padx=10, pady=(10, 5))
        ParagonLabel(help_frame, text="💡 Set 'Episodes per season' to auto-increment seasons\n    e.g., 10 eps → S01E10 then S02E01", style="muted").pack(padx=10, pady=8, anchor="w")
    
    def _create_datetime_tab(self, parent):
        """Date/time rule tab"""
        ParagonCheckbox(parent, text="Add date/time", variable=self.datetime_enabled).pack(anchor="w", padx=10, pady=(15, 10))
        
        ParagonLabel(parent, text="Format:", style="muted").pack(anchor="w", padx=10, pady=(10, 5))
        ParagonOptionMenu(parent, variable=self.datetime_format,
                         values=["%Y-%m-%d", "%Y%m%d", "%Y-%m-%d_%H-%M-%S", "%d-%m-%Y", "%H-%M-%S"],
                         command=lambda v: self._update_preview(), width=250).pack(anchor="w", padx=10)
        
        ParagonLabel(parent, text="Source:", style="muted").pack(anchor="w", padx=10, pady=(15, 5))
        ParagonOptionMenu(parent, variable=self.datetime_source,
                         values=["File modified date", "Current date"],
                         command=lambda v: self._update_preview(), width=250).pack(anchor="w", padx=10)
        
        ParagonLabel(parent, text="Position:", style="muted").pack(anchor="w", padx=10, pady=(15, 5))
        ParagonOptionMenu(parent, variable=self.datetime_position,
                         values=["prefix", "suffix"],
                         command=lambda v: self._update_preview(), width=250).pack(anchor="w", padx=10)
    
    def _create_metadata_tab(self, parent):
        """Metadata rule tab"""
        ParagonCheckbox(parent, text="Rename by metadata", variable=self.metadata_enabled).pack(anchor="w", padx=10, pady=(15, 10))
        
        ParagonLabel(parent, text="Template:", style="muted").pack(anchor="w", padx=10, pady=(10, 5))
        ParagonEntry(parent, textvariable=self.metadata_template, placeholder_text="{artist} - {title}", width=350).pack(padx=10)
        
        # Help
        help_frame = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        help_frame.pack(fill="x", padx=10, pady=15)
        
        help_text = """Available placeholders:
Audio: {artist}, {title}, {album}, {genre}, {date}
Photos: {datetimeoriginal}, {make}, {model}
General: {original}"""
        
        ParagonLabel(help_frame, text=help_text, style="muted").pack(padx=10, pady=10, anchor="w")
        
        # Status
        status_parts = []
        status_parts.append(f"{'✓' if HAS_PIL else '✗'} EXIF support")
        status_parts.append(f"{'✓' if HAS_MUTAGEN else '✗'} Audio tags")
        
        ParagonLabel(parent, text="  |  ".join(status_parts), style="muted").pack(anchor="w", padx=10, pady=5)
    
    def _create_tags_tab(self, parent):
        """Tags tab - MP3tag style features"""
        # Info label
        ParagonLabel(parent, text="🎵 MP3TAG-STYLE FEATURES", style="accent").pack(anchor="w", padx=10, pady=(15, 10))
        
        info_text = "Edit audio file tags, convert between tags and filenames, manage cover art."
        ParagonLabel(parent, text=info_text, style="muted").pack(anchor="w", padx=10, pady=(0, 15))
        
        # Main buttons frame
        main_btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        main_btn_frame.pack(fill="x", padx=10, pady=10)
        
        # Button to open full tag editor
        ParagonButton(
            main_btn_frame, 
            text="🎵 OPEN TAG EDITOR",
            command=self._open_tag_editor,
            width=200
        ).pack(side="left", padx=(0, 10))
        
        # MusicBrainz Album Lookup button
        ParagonButton(
            main_btn_frame,
            text="🔍 MUSICBRAINZ ALBUM LOOKUP",
            command=self._open_album_lookup,
            width=250,
            fg_color=ParagonTheme.ORANGE,
            hover_color=ParagonTheme.GOLD_LIGHT
        ).pack(side="left")
        
        # Quick actions
        quick_frame = ctk.CTkFrame(parent, fg_color="transparent")
        quick_frame.pack(fill="x", padx=10, pady=(20, 10))
        
        ParagonLabel(quick_frame, text="Quick Actions:", style="muted").pack(anchor="w", pady=(0, 10))
        
        ParagonSecondaryButton(
            quick_frame,
            text="TAG → FILENAME",
            command=self._quick_tag_to_filename,
            width=180
        ).pack(side="left", padx=(0, 10))
        
        ParagonSecondaryButton(
            quick_frame,
            text="FILENAME → TAG",
            command=self._quick_filename_to_tag,
            width=180
        ).pack(side="left")
        
        # Help
        help_frame = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        help_frame.pack(fill="x", padx=10, pady=15)
        
        help_text = """Supported formats: MP3, FLAC, M4A, OGG, OPUS
        
Tag Editor features:
• Edit Title, Artist, Album, Year, Track, Genre
• Add/remove/extract cover art
• Batch edit multiple files
• Tag ↔ Filename conversion

MusicBrainz Album Lookup:
• Search albums by artist/name
• Match tracks to your files
• Auto-tag entire albums with cover art"""
        
        ParagonLabel(help_frame, text=help_text, style="muted").pack(padx=10, pady=10, anchor="w")
        
        # Mutagen status
        status = "✓ Mutagen installed" if HAS_MUTAGEN else "✗ Mutagen not installed (pip install mutagen)"
        ParagonLabel(parent, text=status, style="muted").pack(anchor="w", padx=10, pady=5)
    
    def _create_media_tab(self, parent):
        """Media tab - MediaElch-style movie/TV scraping"""
        print("DEBUG: _create_media_tab START")
        
        ParagonLabel(parent, text="🎬 MEDIA MANAGER", style="accent").pack(anchor="w", padx=10, pady=(15, 10))
        
        info_text = "Scrape metadata for movies & TV shows from TMDB. Generate NFO files for Kodi/Plex/Jellyfin."
        ParagonLabel(parent, text=info_text, style="muted").pack(anchor="w", padx=10, pady=(0, 15))
        
        # API Key section
        api_frame = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        api_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        api_inner = ctk.CTkFrame(api_frame, fg_color="transparent")
        api_inner.pack(fill="x", padx=10, pady=8)
        
        ParagonLabel(api_inner, text="TMDB API Key:", style="muted").pack(side="left")
        
        self.tmdb_api_entry = ctk.CTkEntry(
            api_inner, width=280, show="•",
            fg_color=ParagonTheme.BG_DARK, border_color=ParagonTheme.BORDER_DARK
        )
        self.tmdb_api_entry.pack(side="left", padx=(10, 5))
        
        print("DEBUG: About to load TMDB API key")
        # Load saved API key if exists
        self._load_tmdb_api_key()
        print("DEBUG: TMDB API key loaded")
        
        ParagonSecondaryButton(
            api_inner, text="SAVE", width=60,
            command=self._save_tmdb_api_key
        ).pack(side="left")
        
        # Fanart.tv API key row
        fanart_inner = ctk.CTkFrame(api_frame, fg_color="transparent")
        fanart_inner.pack(fill="x", padx=10, pady=(0, 8))
        
        ParagonLabel(fanart_inner, text="Fanart.tv API Key:", style="muted").pack(side="left")
        
        self.fanart_api_entry = ctk.CTkEntry(
            fanart_inner, width=256, show="•",
            fg_color=ParagonTheme.BG_DARK, border_color=ParagonTheme.BORDER_DARK
        )
        self.fanart_api_entry.pack(side="left", padx=(10, 5))
        
        # Load saved Fanart.tv API key if exists
        self._load_fanart_api_key()
        
        ParagonSecondaryButton(
            fanart_inner, text="SAVE", width=60,
            command=self._save_fanart_api_key
        ).pack(side="left")
        
        # TV Library folder row
        library_inner = ctk.CTkFrame(api_frame, fg_color="transparent")
        library_inner.pack(fill="x", padx=10, pady=(0, 8))
        
        ParagonLabel(library_inner, text="TV Library Folder:", style="muted").pack(side="left")
        
        self.tv_library_label = ctk.CTkLabel(
            library_inner, text="Not set",
            text_color=ParagonTheme.TEXT_MUTED,
            font=ctk.CTkFont(size=14),
            width=256, anchor="w"
        )
        self.tv_library_label.pack(side="left", padx=(10, 5))
        
        # Load saved TV library path
        self._load_tv_library_path()
        
        ParagonSecondaryButton(
            library_inner, text="CHANGE", width=80,
            command=self._change_tv_library_path
        ).pack(side="left")
        
        # Movie Library folder row
        movie_library_inner = ctk.CTkFrame(api_frame, fg_color="transparent")
        movie_library_inner.pack(fill="x", padx=10, pady=(0, 8))
        
        ParagonLabel(movie_library_inner, text="Movie Library Folder:", style="muted").pack(side="left")
        
        self.movie_library_label = ctk.CTkLabel(
            movie_library_inner, text="Not set",
            text_color=ParagonTheme.TEXT_MUTED,
            font=ctk.CTkFont(size=14),
            width=256, anchor="w"
        )
        self.movie_library_label.pack(side="left", padx=(10, 5))
        
        # Load saved Movie library path
        self._load_movie_library_path()
        
        ParagonSecondaryButton(
            movie_library_inner, text="CHANGE", width=80,
            command=self._change_movie_library_path
        ).pack(side="left")
        
        # Music Library folder row
        music_library_inner = ctk.CTkFrame(api_frame, fg_color="transparent")
        music_library_inner.pack(fill="x", padx=10, pady=(0, 8))
        
        ParagonLabel(music_library_inner, text="Music Library Folder:", style="muted").pack(side="left")
        
        self.music_library_label = ctk.CTkLabel(
            music_library_inner, text="Not set",
            text_color=ParagonTheme.TEXT_MUTED,
            font=ctk.CTkFont(size=14),
            width=256, anchor="w"
        )
        self.music_library_label.pack(side="left", padx=(10, 5))
        
        # Load saved Music library path
        self._load_music_library_path()
        
        ParagonSecondaryButton(
            music_library_inner, text="CHANGE", width=80,
            command=self._change_music_library_path
        ).pack(side="left")
        
        # Main buttons - Library browsers
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        ParagonButton(
            btn_frame,
            text="🎬 MOVIE LIBRARY",
            command=self._open_movie_library,
            width=170
        ).pack(side="left", padx=(0, 10))
        
        ParagonButton(
            btn_frame,
            text="📚 TV LIBRARY",
            command=self._open_tv_library,
            width=150
        ).pack(side="left", padx=(0, 10))
        
        ParagonButton(
            btn_frame,
            text="🎵 MUSIC LIBRARY",
            command=self._open_music_library,
            width=170
        ).pack(side="left", padx=(0, 10))
        
        ParagonButton(
            btn_frame,
            text="📁 FILE LIBRARY",
            command=self._open_file_library,
            width=150
        ).pack(side="left")
        
        print("DEBUG: _create_media_tab END")
    
    def _load_tmdb_api_key(self):
        """Load saved TMDB API key"""
        print("DEBUG: _load_tmdb_api_key START")
        config_path = Path.home() / ".pyrenamer_config.json"
        try:
            if config_path.exists():
                print(f"DEBUG: Config file exists at {config_path}")
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    api_key = config.get('tmdb_api_key', '')
                    if api_key:
                        print("DEBUG: Found API key, inserting into entry")
                        self.tmdb_api_entry.insert(0, api_key)
                        TMDBAPI.set_api_key(api_key)
            else:
                print("DEBUG: No config file found")
        except Exception as e:
            print(f"DEBUG: Could not load config: {e}")
        print("DEBUG: _load_tmdb_api_key END")
    
    def _save_tmdb_api_key(self):
        """Save TMDB API key"""
        api_key = self.tmdb_api_entry.get().strip()
        if not api_key:
            messagebox.showwarning("API Key", "Please enter a TMDB API key")
            return
        
        TMDBAPI.set_api_key(api_key)
        
        config_path = Path.home() / ".pyrenamer_config.json"
        try:
            config = {}
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
            
            config['tmdb_api_key'] = api_key
            
            with open(config_path, 'w') as f:
                json.dump(config, f)
            
            messagebox.showinfo("Saved", "API key saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save config: {e}")
    
    def _load_fanart_api_key(self):
        """Load saved Fanart.tv API key"""
        config_path = Path.home() / ".pyrenamer_config.json"
        try:
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    api_key = config.get('fanart_api_key', '')
                    if api_key:
                        self.fanart_api_entry.insert(0, api_key)
                        FanartTVAPI.set_api_key(api_key)
        except Exception as e:
            print(f"Could not load Fanart.tv config: {e}")
    
    def _save_fanart_api_key(self):
        """Save Fanart.tv API key"""
        api_key = self.fanart_api_entry.get().strip()
        if not api_key:
            messagebox.showwarning("API Key", "Please enter a Fanart.tv API key")
            return
        
        FanartTVAPI.set_api_key(api_key)
        
        config_path = Path.home() / ".pyrenamer_config.json"
        try:
            config = {}
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
            
            config['fanart_api_key'] = api_key
            
            with open(config_path, 'w') as f:
                json.dump(config, f)
            
            messagebox.showinfo("Saved", "Fanart.tv API key saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save config: {e}")
    
    def _load_tv_library_path(self):
        """Load saved TV library path"""
        config_path = Path.home() / ".pyrenamer_config.json"
        try:
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    library_path = config.get('tv_library_path', '')
                    if library_path and os.path.isdir(library_path):
                        self.tv_library_path = library_path
                        # Truncate display if too long
                        display_path = library_path
                        if len(display_path) > 35:
                            display_path = "..." + display_path[-32:]
                        self.tv_library_label.configure(text=display_path, text_color=ParagonTheme.TEXT_PRIMARY)
                    else:
                        self.tv_library_path = ""
        except Exception as e:
            print(f"Could not load TV library path: {e}")
            self.tv_library_path = ""
    
    def _change_tv_library_path(self):
        """Change the TV library folder"""
        initial_dir = getattr(self, 'tv_library_path', '') or str(Path.home())
        folder = filedialog.askdirectory(title="Select TV Library Folder", initialdir=initial_dir)
        if folder:
            self.tv_library_path = folder
            # Truncate display if too long
            display_path = folder
            if len(display_path) > 35:
                display_path = "..." + display_path[-32:]
            self.tv_library_label.configure(text=display_path, text_color=ParagonTheme.TEXT_PRIMARY)
            
            # Save to config
            config_path = Path.home() / ".pyrenamer_config.json"
            try:
                config = {}
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                
                config['tv_library_path'] = folder
                
                with open(config_path, 'w') as f:
                    json.dump(config, f)
            except Exception as e:
                print(f"Could not save TV library path: {e}")
    
    def _load_movie_library_path(self):
        """Load saved Movie library path"""
        config_path = Path.home() / ".pyrenamer_config.json"
        try:
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    library_path = config.get('movie_library_path', '')
                    if library_path and os.path.isdir(library_path):
                        self.movie_library_path = library_path
                        # Truncate display if too long
                        display_path = library_path
                        if len(display_path) > 35:
                            display_path = "..." + display_path[-32:]
                        self.movie_library_label.configure(text=display_path, text_color=ParagonTheme.TEXT_PRIMARY)
                    else:
                        self.movie_library_path = ""
        except Exception as e:
            print(f"Could not load Movie library path: {e}")
            self.movie_library_path = ""
    
    def _change_movie_library_path(self):
        """Change the Movie library folder"""
        initial_dir = getattr(self, 'movie_library_path', '') or str(Path.home())
        folder = filedialog.askdirectory(title="Select Movie Library Folder", initialdir=initial_dir)
        if folder:
            self.movie_library_path = folder
            # Truncate display if too long
            display_path = folder
            if len(display_path) > 35:
                display_path = "..." + display_path[-32:]
            self.movie_library_label.configure(text=display_path, text_color=ParagonTheme.TEXT_PRIMARY)
            
            # Save to config
            config_path = Path.home() / ".pyrenamer_config.json"
            try:
                config = {}
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                
                config['movie_library_path'] = folder
                
                with open(config_path, 'w') as f:
                    json.dump(config, f)
            except Exception as e:
                print(f"Could not save Movie library path: {e}")
    
    def _open_movie_library(self):
        """Open Movie Library browser to manage multiple movies"""
        api_key = self.tmdb_api_entry.get().strip()
        if not api_key:
            messagebox.showwarning("API Key Required", "Please enter your TMDB API key first")
            return
        
        TMDBAPI.set_api_key(api_key)
        
        # Also set Fanart.tv API key if available
        fanart_key = self.fanart_api_entry.get().strip() if hasattr(self, 'fanart_api_entry') else ''
        if fanart_key:
            FanartTVAPI.set_api_key(fanart_key)
        
        # Use saved path if available, otherwise prompt
        folder = getattr(self, 'movie_library_path', '') if hasattr(self, 'movie_library_path') else ''
        
        if not folder or not os.path.isdir(folder):
            # Ask user to select a folder containing movies
            folder = filedialog.askdirectory(title="Select Movie Library Folder (contains movie folders)")
            if not folder:
                return
            
            # Save the selected folder
            self.movie_library_path = folder
            display_path = folder
            if len(display_path) > 35:
                display_path = "..." + display_path[-32:]
            if hasattr(self, 'movie_library_label'):
                self.movie_library_label.configure(text=display_path, text_color=ParagonTheme.TEXT_PRIMARY)
            
            # Save to config
            config_path = Path.home() / ".pyrenamer_config.json"
            try:
                config = {}
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                config['movie_library_path'] = folder
                with open(config_path, 'w') as f:
                    json.dump(config, f)
            except:
                pass
        
        dialog = open_child_window(MovieLibraryDialog(self, folder), self)
    
    def _load_music_library_path(self):
        """Load saved Music library path"""
        config_path = Path.home() / ".pyrenamer_config.json"
        try:
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    library_path = config.get('music_library_path', '')
                    if library_path and os.path.isdir(library_path):
                        self.music_library_path = library_path
                        # Truncate display if too long
                        display_path = library_path
                        if len(display_path) > 35:
                            display_path = "..." + display_path[-32:]
                        self.music_library_label.configure(text=display_path, text_color=ParagonTheme.TEXT_PRIMARY)
                    else:
                        self.music_library_path = ""
        except Exception as e:
            print(f"Could not load Music library path: {e}")
            self.music_library_path = ""
    
    def _change_music_library_path(self):
        """Change the Music library folder"""
        initial_dir = getattr(self, 'music_library_path', '') or str(Path.home())
        folder = filedialog.askdirectory(title="Select Music Library Folder", initialdir=initial_dir)
        if folder:
            self.music_library_path = folder
            # Truncate display if too long
            display_path = folder
            if len(display_path) > 35:
                display_path = "..." + display_path[-32:]
            self.music_library_label.configure(text=display_path, text_color=ParagonTheme.TEXT_PRIMARY)
            
            # Save to config
            config_path = Path.home() / ".pyrenamer_config.json"
            try:
                config = {}
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                
                config['music_library_path'] = folder
                
                with open(config_path, 'w') as f:
                    json.dump(config, f)
            except Exception as e:
                print(f"Could not save Music library path: {e}")
    
    def _open_music_library(self):
        """Open Music Library browser to manage music collection"""
        # Use saved path if available, otherwise prompt
        folder = getattr(self, 'music_library_path', '') if hasattr(self, 'music_library_path') else ''
        
        if not folder or not os.path.isdir(folder):
            # Ask user to select a folder containing music
            folder = filedialog.askdirectory(title="Select Music Library Folder (contains artist/album folders)")
            if not folder:
                return
            
            # Save the selected folder
            self.music_library_path = folder
            display_path = folder
            if len(display_path) > 35:
                display_path = "..." + display_path[-32:]
            if hasattr(self, 'music_library_label'):
                self.music_library_label.configure(text=display_path, text_color=ParagonTheme.TEXT_PRIMARY)
            
            # Save to config
            config_path = Path.home() / ".pyrenamer_config.json"
            try:
                config = {}
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                config['music_library_path'] = folder
                with open(config_path, 'w') as f:
                    json.dump(config, f)
            except:
                pass
        
        dialog = open_child_window(MusicLibraryDialog(self, folder), self)
    
    def _open_file_library(self):
        """Open File Library browser for general file management and renaming"""
        # Ask user to select a folder
        folder = filedialog.askdirectory(title="Select Folder to Browse")
        if not folder:
            return
        
        dialog = open_child_window(FileLibraryDialog(self, folder), self)
    
    def _open_movie_scraper(self):
        """Open movie scraper dialog"""
        print("DEBUG: _open_movie_scraper CALLED!")
        import sys
        sys.stdout.flush()
        
        print("DEBUG: Getting API key from entry")
        sys.stdout.flush()
        
        api_key = self.tmdb_api_entry.get().strip()
        print(f"DEBUG: API key length: {len(api_key)}")
        sys.stdout.flush()
        
        if not api_key:
            messagebox.showwarning("API Key Required", "Please enter your TMDB API key first")
            return
        
        TMDBAPI.set_api_key(api_key)
        
        # Get selected video files
        print("DEBUG: Getting selected files")
        sys.stdout.flush()
        
        selected_indices = self.file_list.get_selected_indices()
        
        if selected_indices:
            print(f"DEBUG: Selected indices: {selected_indices}")
            sys.stdout.flush()
            files = [self.files[i].path for i in selected_indices if MediaFileParser.is_video_file(self.files[i].path)]
        else:
            print("DEBUG: No selection, using all video files")
            sys.stdout.flush()
            files = [f.path for f in self.files if MediaFileParser.is_video_file(f.path)]
        
        print(f"DEBUG: Found {len(files)} video files")
        sys.stdout.flush()
        
        if not files:
            messagebox.showinfo("No Video Files", "No video files selected or loaded.\n\nSupported: MKV, MP4, AVI, MOV, WMV, M4V")
            return
        
        print("DEBUG: Creating MovieEditorDialog")
        sys.stdout.flush()
        
        dialog = open_child_window(MovieEditorDialog(self, files), self)
        print("DEBUG: _open_movie_scraper END")
        sys.stdout.flush()
    
    def _open_tv_scraper(self):
        """Open TV show editor dialog"""
        api_key = self.tmdb_api_entry.get().strip()
        if not api_key:
            messagebox.showwarning("API Key Required", "Please enter your TMDB API key first")
            return
        
        TMDBAPI.set_api_key(api_key)
        
        # Also set Fanart.tv API key if available
        fanart_key = self.fanart_api_entry.get().strip() if hasattr(self, 'fanart_api_entry') else ''
        if fanart_key:
            FanartTVAPI.set_api_key(fanart_key)
        
        # Get selected video files
        selected_indices = self.file_list.get_selected_indices()
        
        if selected_indices:
            files = [self.files[i].path for i in selected_indices if MediaFileParser.is_video_file(self.files[i].path)]
        else:
            files = [f.path for f in self.files if MediaFileParser.is_video_file(f.path)]
        
        if not files:
            messagebox.showinfo("No Video Files", "No video files selected or loaded.\n\nSupported: MKV, MP4, AVI, MOV, WMV, M4V")
            return
        
        dialog = open_child_window(TVEditorDialog(self, files), self)
    
    def _open_tv_library(self):
        """Open TV Library browser to manage multiple TV shows"""
        api_key = self.tmdb_api_entry.get().strip()
        if not api_key:
            messagebox.showwarning("API Key Required", "Please enter your TMDB API key first")
            return
        
        TMDBAPI.set_api_key(api_key)
        
        # Also set Fanart.tv API key if available
        fanart_key = self.fanart_api_entry.get().strip() if hasattr(self, 'fanart_api_entry') else ''
        if fanart_key:
            FanartTVAPI.set_api_key(fanart_key)
        
        # Use saved path if available, otherwise prompt
        folder = getattr(self, 'tv_library_path', '') if hasattr(self, 'tv_library_path') else ''
        
        if not folder or not os.path.isdir(folder):
            # Ask user to select a folder containing TV shows
            folder = filedialog.askdirectory(title="Select TV Library Folder (contains TV show folders)")
            if not folder:
                return
            
            # Save the selected folder
            self.tv_library_path = folder
            display_path = folder
            if len(display_path) > 35:
                display_path = "..." + display_path[-32:]
            if hasattr(self, 'tv_library_label'):
                self.tv_library_label.configure(text=display_path, text_color=ParagonTheme.TEXT_PRIMARY)
            
            # Save to config
            config_path = Path.home() / ".pyrenamer_config.json"
            try:
                config = {}
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                config['tv_library_path'] = folder
                with open(config_path, 'w') as f:
                    json.dump(config, f)
            except:
                pass
        
        dialog = open_child_window(TVLibraryDialog(self, folder), self)
    
    def _open_tag_editor(self):
        """Open the full tag editor window"""
        # Get selected audio files
        selected_indices = self.file_list.get_selected_indices()
        
        if selected_indices:
            files = [self.files[i].path for i in selected_indices if TagManager.is_audio_file(self.files[i].path)]
        else:
            # Use all audio files
            files = [f.path for f in self.files if TagManager.is_audio_file(f.path)]
        
        if not files:
            messagebox.showinfo("No Audio Files", "No audio files selected or loaded.\n\nSupported formats: MP3, FLAC, M4A, OGG, OPUS")
            return
        
        # Open tag editor dialog
        dialog = open_child_window(TagEditorDialog(self, files), self)
    
    def _open_album_lookup(self):
        """Open MusicBrainz album lookup dialog"""
        # Get selected audio files
        selected_indices = self.file_list.get_selected_indices()
        
        if selected_indices:
            files = [self.files[i].path for i in selected_indices if TagManager.is_audio_file(self.files[i].path)]
        else:
            # Use all audio files
            files = [f.path for f in self.files if TagManager.is_audio_file(f.path)]
        
        if not files:
            messagebox.showinfo("No Audio Files", "No audio files selected or loaded.\n\nSupported formats: MP3, FLAC, M4A, OGG, OPUS")
            return
        
        # Open album lookup dialog
        dialog = MusicBrainzAlbumLookup(self, files, on_complete=self._update_preview)
    
    def _quick_tag_to_filename(self):
        """Quick tag to filename conversion"""
        files = [f.path for f in self.files if TagManager.is_audio_file(f.path)]
        if not files:
            messagebox.showinfo("No Audio Files", "No audio files loaded.")
            return
        
        dialog = TagFilenameDialog(self, mode="tag_to_filename", files=files)
    
    def _quick_filename_to_tag(self):
        """Quick filename to tag conversion"""
        files = [f.path for f in self.files if TagManager.is_audio_file(f.path)]
        if not files:
            messagebox.showinfo("No Audio Files", "No audio files loaded.")
            return
        
        dialog = TagFilenameDialog(self, mode="filename_to_tag", files=files)
    
    def _create_file_panel(self, parent):
        """Create the file list panel"""
        # Header
        header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 5))
        
        ParagonLabel(header_frame, text="📄  FILES", style="title").pack(side="left")
        self.file_count_label = ParagonLabel(header_frame, text="0 files", style="muted")
        self.file_count_label.pack(side="right")
        
        # DnD indicator
        if HAS_DND:
            dnd_label = ParagonLabel(header_frame, text="📥 Drop files here", style="muted")
            dnd_label.pack(side="right", padx=(0, 15))
        
        # Filter bar
        filter_frame = ctk.CTkFrame(parent, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=6, height=40)
        filter_frame.pack(fill="x", padx=15, pady=(5, 10))
        filter_frame.pack_propagate(False)
        
        ParagonLabel(filter_frame, text="🔍", style="muted").pack(side="left", padx=(10, 5))
        
        self.filter_entry = ParagonEntry(
            filter_frame, 
            textvariable=self.filter_text,
            placeholder_text="Filter by extension (e.g., .mkv, .mp3) or name...",
            width=300
        )
        self.filter_entry.pack(side="left", padx=5, pady=5)
        
        # Quick filter buttons
        quick_filters = [("All", ""), ("Video", ".mkv,.mp4,.avi,.mov"), 
                        ("Audio", ".mp3,.flac,.wav,.m4a"), ("Images", ".jpg,.png,.gif,.webp")]
        
        for label, extensions in quick_filters:
            btn = ctk.CTkButton(
                filter_frame,
                text=label,
                width=60,
                height=28,
                fg_color=ParagonTheme.BG_TERTIARY,
                hover_color=ParagonTheme.BG_HOVER,
                text_color=ParagonTheme.TEXT_SECONDARY,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                corner_radius=4,
                command=lambda e=extensions: self._set_filter(e)
            )
            btn.pack(side="left", padx=2, pady=5)
        
        # Clear filter button
        clear_btn = ctk.CTkButton(
            filter_frame,
            text="✕",
            width=28,
            height=28,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.RED_DARK,
            text_color=ParagonTheme.TEXT_SECONDARY,
            corner_radius=4,
            command=lambda: self._set_filter("")
        )
        clear_btn.pack(side="right", padx=10, pady=5)
        
        # Filtered count
        self.filter_count_label = ParagonLabel(filter_frame, text="", style="muted")
        self.filter_count_label.pack(side="right", padx=5)
        
        # Sort bar
        sort_frame = ctk.CTkFrame(parent, fg_color="transparent", height=32)
        sort_frame.pack(fill="x", padx=15, pady=(0, 5))
        sort_frame.pack_propagate(False)
        
        ParagonLabel(sort_frame, text="Sort:", style="muted").pack(side="left", padx=(0, 8))
        
        # Sort buttons
        sort_options = [
            ("Name ↕", "name"),
            ("Date ↕", "date"),
            ("Size ↕", "size"),
            ("Ext ↕", "extension")
        ]
        
        self.sort_buttons = {}
        for label, sort_key in sort_options:
            btn = ctk.CTkButton(
                sort_frame,
                text=label,
                width=65,
                height=26,
                fg_color=ParagonTheme.BG_TERTIARY,
                hover_color=ParagonTheme.BG_HOVER,
                text_color=ParagonTheme.TEXT_SECONDARY,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                corner_radius=4,
                command=lambda k=sort_key: self._sort_files(k)
            )
            btn.pack(side="left", padx=2)
            self.sort_buttons[sort_key] = btn
        
        # Reverse checkbox
        self.sort_reverse_btn = ctk.CTkButton(
            sort_frame,
            text="🔄",
            width=30,
            height=26,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_SECONDARY,
            corner_radius=4,
            command=self._toggle_sort_reverse
        )
        self.sort_reverse_btn.pack(side="left", padx=(8, 0))
        
        # Sort info label
        self.sort_info_label = ParagonLabel(sort_frame, text="", style="muted")
        self.sort_info_label.pack(side="right", padx=5)
        
        # File list container (for DnD highlighting)
        self.file_list_container = ctk.CTkFrame(parent, fg_color="transparent")
        self.file_list_container.pack(fill="both", expand=True, padx=10, pady=(0, 5))
        
        # File list with selection callback for swap feature
        self.file_list = FileListWidget(
            self.file_list_container, 
            height=500,
            on_selection_change=self._on_file_selection_change
        )
        self.file_list.pack(fill="both", expand=True)
        
        # Tag Panel (collapsible)
        self._create_tag_panel(parent)
        
        # Setup drag and drop if available
        if HAS_DND:
            self._setup_drag_and_drop()
    
    def _create_tag_panel(self, parent):
        """Create the MP3tag-style tag editing panel"""
        # Tag panel container
        self.tag_panel_frame = ParagonFrame(parent)
        self.tag_panel_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        # Header with toggle
        header_frame = ctk.CTkFrame(self.tag_panel_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        self.tag_panel_expanded = ctk.BooleanVar(value=False)
        
        self.tag_toggle_btn = ctk.CTkButton(
            header_frame,
            text="▶",
            width=30,
            height=30,
            fg_color=ParagonTheme.BG_TERTIARY,
            hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.GOLD,
            corner_radius=4,
            command=self._toggle_tag_panel
        )
        self.tag_toggle_btn.pack(side="left", padx=(0, 10))
        
        ParagonLabel(header_frame, text="🎵  TAG EDITOR", style="title").pack(side="left")
        
        # Tag action buttons
        tag_btn_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        tag_btn_frame.pack(side="right")
        
        ParagonSecondaryButton(tag_btn_frame, text="💾 SAVE TAGS", command=self._save_tags, width=120, height=32).pack(side="left", padx=2)
        ParagonSecondaryButton(tag_btn_frame, text="🔄 RELOAD", command=self._reload_tags, width=100, height=32).pack(side="left", padx=2)
        
        # Tag content area (collapsible) - hidden by default
        self.tag_content = ctk.CTkFrame(self.tag_panel_frame, fg_color="transparent")
        # Don't pack yet - starts collapsed
        
        # Main tag layout: left side for text tags, right side for cover art
        tag_main = ctk.CTkFrame(self.tag_content, fg_color="transparent")
        tag_main.pack(fill="x")
        
        # Left side: Tag fields
        tag_fields_frame = ctk.CTkFrame(tag_main, fg_color="transparent")
        tag_fields_frame.pack(side="left", fill="both", expand=True, padx=(0, 15))
        
        # Create tag entry fields
        self.tag_vars = {}
        tag_fields = [
            ("Title", "title"),
            ("Artist", "artist"),
            ("Album", "album"),
            ("Album Artist", "albumartist"),
            ("Year", "date"),
            ("Track", "tracknumber"),
            ("Genre", "genre"),
            ("Comment", "comment"),
        ]
        
        # Two-column layout for tags
        for i, (label, key) in enumerate(tag_fields):
            row = i // 2
            col = i % 2
            
            if col == 0:
                row_frame = ctk.CTkFrame(tag_fields_frame, fg_color="transparent")
                row_frame.pack(fill="x", pady=3)
            
            field_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            field_frame.pack(side="left", fill="x", expand=True, padx=(0, 10) if col == 0 else (10, 0))
            
            ParagonLabel(field_frame, text=f"{label}:", style="muted").pack(anchor="w")
            
            self.tag_vars[key] = ctk.StringVar()
            entry = ParagonEntry(field_frame, textvariable=self.tag_vars[key], width=250, height=36)
            entry.pack(fill="x", pady=(2, 0))
        
        # Right side: Cover art
        cover_frame = ctk.CTkFrame(tag_main, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=8, width=180, height=180)
        cover_frame.pack(side="right", padx=(0, 10))
        cover_frame.pack_propagate(False)
        
        self.cover_art_label = ctk.CTkLabel(
            cover_frame,
            text="🎵\nNo Cover Art",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=ParagonTheme.TEXT_SECONDARY
        )
        self.cover_art_label.pack(expand=True)
        self._cover_art_image = None  # Store reference to prevent garbage collection
        
        # Cover art buttons
        cover_btn_frame = ctk.CTkFrame(self.tag_content, fg_color="transparent")
        cover_btn_frame.pack(fill="x", pady=(10, 0))
        
        # Spacer to align buttons with cover art
        ctk.CTkFrame(cover_btn_frame, fg_color="transparent", width=500).pack(side="left")
        
        cover_actions = ctk.CTkFrame(cover_btn_frame, fg_color="transparent")
        cover_actions.pack(side="right")
        
        ctk.CTkButton(
            cover_actions, text="Add", width=55, height=28,
            fg_color=ParagonTheme.BG_TERTIARY, hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_SECONDARY, corner_radius=4,
            command=self._add_cover_art
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            cover_actions, text="Remove", width=65, height=28,
            fg_color=ParagonTheme.BG_TERTIARY, hover_color=ParagonTheme.RED_DARK,
            text_color=ParagonTheme.TEXT_SECONDARY, corner_radius=4,
            command=self._remove_cover_art
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            cover_actions, text="Extract", width=65, height=28,
            fg_color=ParagonTheme.BG_TERTIARY, hover_color=ParagonTheme.BG_HOVER,
            text_color=ParagonTheme.TEXT_SECONDARY, corner_radius=4,
            command=self._extract_cover_art
        ).pack(side="left", padx=2)
        
        # Separator
        ctk.CTkFrame(self.tag_content, fg_color=ParagonTheme.BORDER_DARK, height=1).pack(fill="x", pady=15)
        
        # Tag <-> Filename conversion section
        convert_frame = ctk.CTkFrame(self.tag_content, fg_color="transparent")
        convert_frame.pack(fill="x")
        
        # Tag to Filename
        t2f_frame = ctk.CTkFrame(convert_frame, fg_color="transparent")
        t2f_frame.pack(side="left", fill="x", expand=True)
        
        ParagonLabel(t2f_frame, text="Tag → Filename:", style="muted").pack(anchor="w")
        
        t2f_row = ctk.CTkFrame(t2f_frame, fg_color="transparent")
        t2f_row.pack(fill="x", pady=(5, 0))
        
        self.tag_to_filename_pattern = ctk.StringVar(value="%artist% - %title%")
        ParagonEntry(t2f_row, textvariable=self.tag_to_filename_pattern, 
                    placeholder_text="%artist% - %title%", width=280, height=36).pack(side="left")
        ParagonButton(t2f_row, text="APPLY", command=self._apply_tag_to_filename, 
                     width=80, height=36).pack(side="left", padx=(10, 0))
        
        # Filename to Tag
        f2t_frame = ctk.CTkFrame(convert_frame, fg_color="transparent")
        f2t_frame.pack(side="right", fill="x", expand=True, padx=(20, 0))
        
        ParagonLabel(f2t_frame, text="Filename → Tag:", style="muted").pack(anchor="w")
        
        f2t_row = ctk.CTkFrame(f2t_frame, fg_color="transparent")
        f2t_row.pack(fill="x", pady=(5, 0))
        
        self.filename_to_tag_pattern = ctk.StringVar(value="%artist% - %title%")
        ParagonEntry(f2t_row, textvariable=self.filename_to_tag_pattern,
                    placeholder_text="%artist% - %title%", width=280, height=36).pack(side="left")
        ParagonButton(f2t_row, text="APPLY", command=self._apply_filename_to_tag,
                     width=80, height=36).pack(side="left", padx=(10, 0))
        
        # Help text for patterns
        help_frame = ctk.CTkFrame(self.tag_content, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=6)
        help_frame.pack(fill="x", pady=(15, 0))
        ParagonLabel(
            help_frame,
            text="Patterns: %artist%, %title%, %album%, %albumartist%, %track%, %year%, %genre%, %comment%, %_filename%",
            style="muted"
        ).pack(padx=10, pady=8)
    
    def _toggle_tag_panel(self):
        """Toggle tag panel visibility"""
        if self.tag_panel_expanded.get():
            self.tag_content.pack_forget()
            self.tag_toggle_btn.configure(text="▶")
            self.tag_panel_expanded.set(False)
        else:
            self.tag_content.pack(fill="x", padx=10, pady=(5, 10))
            self.tag_toggle_btn.configure(text="▼")
            self.tag_panel_expanded.set(True)
    
    def _get_selected_audio_files(self) -> List:
        """Get selected files that are audio files"""
        audio_extensions = {'.mp3', '.flac', '.m4a', '.ogg', '.wav', '.wma', '.aac', '.opus'}
        selected_indices = self.file_list.get_selected_indices()
        
        if not selected_indices:
            # If nothing selected, return all audio files
            return [f for f in self.files if f.extension.lower() in audio_extensions]
        
        filtered_files = self._get_filtered_files()
        return [filtered_files[i] for i in selected_indices 
                if i < len(filtered_files) and filtered_files[i].extension.lower() in audio_extensions]
    
    def _load_tags_for_file(self, file_item):
        """Load tags from a single audio file"""
        if not HAS_MUTAGEN:
            return {}
        
        try:
            audio = MutagenFile(file_item.path, easy=True)
            if audio is None:
                return {}
            
            tags = {}
            for key in ['title', 'artist', 'album', 'albumartist', 'date', 'tracknumber', 'genre', 'comment']:
                value = audio.get(key, [''])[0] if audio.get(key) else ''
                tags[key] = value
            
            return tags
        except Exception as e:
            print(f"Error loading tags from {file_item.path}: {e}")
            return {}
    
    def _load_cover_art(self, file_item):
        """Load cover art from audio file"""
        if not HAS_MUTAGEN or not HAS_PIL:
            return None
        
        try:
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3
            from mutagen.flac import FLAC
            from mutagen.mp4 import MP4
            
            ext = file_item.extension.lower()
            
            if ext == '.mp3':
                audio = MP3(file_item.path, ID3=ID3)
                for tag in audio.tags.values():
                    if tag.FrameID == 'APIC':
                        return Image.open(io.BytesIO(tag.data))
            elif ext == '.flac':
                audio = FLAC(file_item.path)
                if audio.pictures:
                    return Image.open(io.BytesIO(audio.pictures[0].data))
            elif ext in ['.m4a', '.mp4']:
                audio = MP4(file_item.path)
                if 'covr' in audio.tags:
                    return Image.open(io.BytesIO(audio.tags['covr'][0]))
            
            return None
        except Exception as e:
            print(f"Error loading cover art: {e}")
            return None
    
    def _reload_tags(self):
        """Reload tags from selected file"""
        audio_files = self._get_selected_audio_files()
        
        if not audio_files:
            messagebox.showinfo("Info", "No audio files selected")
            return
        
        # Load tags from first selected file
        file_item = audio_files[0]
        tags = self._load_tags_for_file(file_item)
        
        # Update UI
        for key, var in self.tag_vars.items():
            var.set(tags.get(key, ''))
        
        # Load cover art
        cover = self._load_cover_art(file_item)
        self._display_cover_art(cover)
        
        self.status_label.configure(text=f"🎵 Loaded tags from: {file_item.original_name}")
    
    def _display_cover_art(self, image):
        """Display cover art in the panel"""
        if image is None:
            # Clear the image - we need to destroy and recreate the label to fully clear
            self._cover_art_image = None
            try:
                # Just update the text and don't touch the image parameter
                # This avoids the CTkImage warning
                for widget in self.cover_art_label.master.winfo_children():
                    widget.destroy()
                
                self.cover_art_label = ctk.CTkLabel(
                    self.cover_art_label.master,
                    text="🎵\nNo Cover Art",
                    font=ctk.CTkFont(family="Segoe UI", size=14),
                    text_color=ParagonTheme.TEXT_SECONDARY
                )
                self.cover_art_label.pack(expand=True)
            except Exception as e:
                print(f"Error clearing cover art: {e}")
            return
        
        try:
            # Resize to fit
            image.thumbnail((170, 170), Image.Resampling.LANCZOS)
            
            self._cover_art_image = ctk.CTkImage(light_image=image, dark_image=image,
                                                  size=(image.width, image.height))
            self.cover_art_label.configure(image=self._cover_art_image, text="")
        except Exception as e:
            print(f"Error displaying cover art: {e}")
            self._cover_art_image = None
            try:
                for widget in self.cover_art_label.master.winfo_children():
                    widget.destroy()
                
                self.cover_art_label = ctk.CTkLabel(
                    self.cover_art_label.master,
                    text="🎵\nError Loading",
                    font=ctk.CTkFont(family="Segoe UI", size=14),
                    text_color=ParagonTheme.TEXT_SECONDARY
                )
                self.cover_art_label.pack(expand=True)
            except:
                pass
    
    def _save_tags(self):
        """Save tags to selected audio files"""
        if not HAS_MUTAGEN:
            messagebox.showerror("Error", "Mutagen library not installed.\nInstall with: pip install mutagen")
            return
        
        audio_files = self._get_selected_audio_files()
        
        if not audio_files:
            messagebox.showinfo("Info", "No audio files selected")
            return
        
        # Confirm if multiple files
        if len(audio_files) > 1:
            if not messagebox.askyesno("Confirm", f"Save tags to {len(audio_files)} files?"):
                return
        
        saved = 0
        errors = []
        
        # Formats that support easy tagging
        supported_formats = {'.mp3', '.flac', '.ogg', '.opus', '.m4a', '.mp4', '.wma', '.asf'}
        
        for file_item in audio_files:
            try:
                ext = file_item.extension.lower()
                
                # Check if format supports tagging
                if ext not in supported_formats:
                    errors.append(f"{file_item.original_name}: {ext} format doesn't support metadata tags")
                    continue
                
                # For MP3 files, we may need to add ID3 tags first
                if ext == '.mp3':
                    try:
                        audio = MutagenFile(file_item.path, easy=True)
                        if audio is None:
                            # Try to add ID3 tags
                            from mutagen.mp3 import MP3
                            from mutagen.id3 import ID3NoHeaderError
                            try:
                                audio = MP3(file_item.path)
                            except ID3NoHeaderError:
                                audio = MP3(file_item.path)
                                audio.add_tags()
                                audio.save()
                            # Now try easy mode again
                            audio = MutagenFile(file_item.path, easy=True)
                    except:
                        audio = MutagenFile(file_item.path, easy=True)
                else:
                    audio = MutagenFile(file_item.path, easy=True)
                
                if audio is None:
                    errors.append(f"{file_item.original_name}: Unsupported format")
                    continue
                
                # Update tags
                for key, var in self.tag_vars.items():
                    value = var.get().strip()
                    try:
                        if value:
                            audio[key] = value
                        elif key in audio:
                            del audio[key]
                    except Exception as tag_err:
                        # Some tags may not be supported by all formats
                        pass
                
                audio.save()
                saved += 1
            except Exception as e:
                errors.append(f"{file_item.original_name}: {str(e)}")
        
        if errors:
            messagebox.showwarning("Save Tags", f"Saved: {saved}\nErrors: {len(errors)}\n\n" + "\n".join(errors[:5]))
        else:
            self.status_label.configure(text=f"💾 Saved tags to {saved} file(s)")
            messagebox.showinfo("Success", f"Tags saved to {saved} file(s)")
    
    def _add_cover_art(self):
        """Add cover art to selected files"""
        if not HAS_MUTAGEN or not HAS_PIL:
            messagebox.showerror("Error", "Requires Mutagen and Pillow libraries")
            return
        
        audio_files = self._get_selected_audio_files()
        if not audio_files:
            messagebox.showinfo("Info", "No audio files selected")
            return
        
        # Open file dialog for image
        image_path = filedialog.askopenfilename(
            title="Select Cover Art",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.gif *.bmp"), ("All files", "*.*")]
        )
        
        if not image_path:
            return
        
        try:
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3, APIC
            from mutagen.flac import FLAC, Picture
            from mutagen.mp4 import MP4, MP4Cover
            
            # Read image data
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Determine MIME type
            mime = 'image/jpeg'
            if image_path.lower().endswith('.png'):
                mime = 'image/png'
            
            added = 0
            for file_item in audio_files:
                try:
                    ext = file_item.extension.lower()
                    
                    if ext == '.mp3':
                        audio = MP3(file_item.path, ID3=ID3)
                        audio.tags.delall('APIC')
                        audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover', data=image_data))
                        audio.save()
                    elif ext == '.flac':
                        audio = FLAC(file_item.path)
                        audio.clear_pictures()
                        pic = Picture()
                        pic.type = 3
                        pic.mime = mime
                        pic.data = image_data
                        audio.add_picture(pic)
                        audio.save()
                    elif ext in ['.m4a', '.mp4']:
                        audio = MP4(file_item.path)
                        audio.tags['covr'] = [MP4Cover(image_data, imageformat=MP4Cover.FORMAT_JPEG if 'jpeg' in mime else MP4Cover.FORMAT_PNG)]
                        audio.save()
                    
                    added += 1
                except Exception as e:
                    print(f"Error adding cover to {file_item.path}: {e}")
            
            # Reload display
            self._reload_tags()
            messagebox.showinfo("Success", f"Cover art added to {added} file(s)")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add cover art: {e}")
    
    def _remove_cover_art(self):
        """Remove cover art from selected files"""
        if not HAS_MUTAGEN:
            return
        
        audio_files = self._get_selected_audio_files()
        if not audio_files:
            messagebox.showinfo("Info", "No audio files selected")
            return
        
        if not messagebox.askyesno("Confirm", f"Remove cover art from {len(audio_files)} file(s)?"):
            return
        
        try:
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3
            from mutagen.flac import FLAC
            from mutagen.mp4 import MP4
            
            removed = 0
            for file_item in audio_files:
                try:
                    ext = file_item.extension.lower()
                    
                    if ext == '.mp3':
                        audio = MP3(file_item.path, ID3=ID3)
                        audio.tags.delall('APIC')
                        audio.save()
                    elif ext == '.flac':
                        audio = FLAC(file_item.path)
                        audio.clear_pictures()
                        audio.save()
                    elif ext in ['.m4a', '.mp4']:
                        audio = MP4(file_item.path)
                        if 'covr' in audio.tags:
                            del audio.tags['covr']
                            audio.save()
                    
                    removed += 1
                except Exception as e:
                    print(f"Error removing cover from {file_item.path}: {e}")
            
            self._reload_tags()
            messagebox.showinfo("Success", f"Cover art removed from {removed} file(s)")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to remove cover art: {e}")
    
    def _extract_cover_art(self):
        """Extract cover art from selected file"""
        audio_files = self._get_selected_audio_files()
        if not audio_files:
            messagebox.showinfo("Info", "No audio files selected")
            return
        
        cover = self._load_cover_art(audio_files[0])
        if cover is None:
            messagebox.showinfo("Info", "No cover art found in file")
            return
        
        # Ask where to save
        save_path = filedialog.asksaveasfilename(
            title="Save Cover Art",
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")],
            initialfile=f"{audio_files[0].original_name.rsplit('.', 1)[0]}_cover"
        )
        
        if save_path:
            try:
                cover.save(save_path)
                messagebox.showinfo("Success", f"Cover art saved to:\n{save_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save cover art: {e}")
    
    def _apply_tag_to_filename(self):
        """Rename files based on their tags using the pattern"""
        if not HAS_MUTAGEN:
            messagebox.showerror("Error", "Mutagen library not installed")
            return
        
        audio_files = self._get_selected_audio_files()
        if not audio_files:
            messagebox.showinfo("Info", "No audio files selected")
            return
        
        pattern = self.tag_to_filename_pattern.get()
        if not pattern:
            messagebox.showinfo("Info", "Enter a pattern first (e.g., %artist% - %title%)")
            return
        
        # Preview the changes
        changes = []
        for file_item in audio_files:
            tags = self._load_tags_for_file(file_item)
            new_name = self._apply_tag_pattern(pattern, tags, file_item)
            if new_name and new_name != file_item.original_name.rsplit('.', 1)[0]:
                changes.append((file_item, new_name + file_item.extension))
        
        if not changes:
            messagebox.showinfo("Info", "No changes to make")
            return
        
        # Show preview and confirm
        preview = "\n".join([f"{f.original_name} → {n}" for f, n in changes[:10]])
        if len(changes) > 10:
            preview += f"\n... and {len(changes) - 10} more"
        
        if messagebox.askyesno("Tag → Filename", f"Rename {len(changes)} file(s)?\n\n{preview}"):
            renamed = 0
            for file_item, new_name in changes:
                try:
                    old_path = Path(file_item.path)
                    new_path = old_path.parent / new_name
                    old_path.rename(new_path)
                    file_item.path = str(new_path)
                    file_item.original_name = new_name
                    renamed += 1
                except Exception as e:
                    print(f"Error renaming {file_item.path}: {e}")
            
            self._update_preview()
            messagebox.showinfo("Success", f"Renamed {renamed} file(s)")
    
    def _apply_tag_pattern(self, pattern: str, tags: dict, file_item) -> str:
        """Apply tag pattern to create filename"""
        result = pattern
        
        # Map pattern placeholders to tag keys
        mappings = {
            '%artist%': tags.get('artist', ''),
            '%title%': tags.get('title', ''),
            '%album%': tags.get('album', ''),
            '%albumartist%': tags.get('albumartist', ''),
            '%year%': tags.get('date', ''),
            '%track%': tags.get('tracknumber', '').split('/')[0].zfill(2),
            '%genre%': tags.get('genre', ''),
            '%comment%': tags.get('comment', ''),
            '%_filename%': file_item.original_name.rsplit('.', 1)[0],
        }
        
        for placeholder, value in mappings.items():
            result = result.replace(placeholder, value)
        
        # Clean up illegal characters
        result = re.sub(r'[\\/:*?"<>|]', '', result)
        result = result.strip()
        
        return result if result else None
    
    def _apply_filename_to_tag(self):
        """Parse filenames into tags using the pattern"""
        if not HAS_MUTAGEN:
            messagebox.showerror("Error", "Mutagen library not installed")
            return
        
        audio_files = self._get_selected_audio_files()
        if not audio_files:
            messagebox.showinfo("Info", "No audio files selected")
            return
        
        pattern = self.filename_to_tag_pattern.get()
        if not pattern:
            messagebox.showinfo("Info", "Enter a pattern first (e.g., %artist% - %title%)")
            return
        
        # Convert pattern to regex
        regex_pattern = self._pattern_to_regex(pattern)
        if not regex_pattern:
            messagebox.showerror("Error", "Invalid pattern")
            return
        
        parsed = 0
        for file_item in audio_files:
            filename = file_item.original_name.rsplit('.', 1)[0]
            tags = self._parse_filename_to_tags(filename, regex_pattern)
            
            if tags:
                try:
                    audio = MutagenFile(file_item.path, easy=True)
                    if audio:
                        for key, value in tags.items():
                            if value:
                                audio[key] = value
                        audio.save()
                        parsed += 1
                except Exception as e:
                    print(f"Error saving tags to {file_item.path}: {e}")
        
        self._reload_tags()
        messagebox.showinfo("Success", f"Tags written to {parsed} file(s)")
    
    def _pattern_to_regex(self, pattern: str) -> Optional[re.Pattern]:
        """Convert MP3tag pattern to regex"""
        # Map placeholders to named groups
        mappings = {
            '%artist%': '(?P<artist>.+?)',
            '%title%': '(?P<title>.+?)',
            '%album%': '(?P<album>.+?)',
            '%albumartist%': '(?P<albumartist>.+?)',
            '%year%': '(?P<date>\\d{4})',
            '%track%': '(?P<tracknumber>\\d+)',
            '%genre%': '(?P<genre>.+?)',
            '%comment%': '(?P<comment>.+?)',
            '%_filename%': '(?P<_filename>.+?)',
        }
        
        regex_str = re.escape(pattern)
        for placeholder, regex_group in mappings.items():
            regex_str = regex_str.replace(re.escape(placeholder), regex_group)
        
        try:
            return re.compile(f'^{regex_str}$')
        except:
            return None
    
    def _parse_filename_to_tags(self, filename: str, regex: re.Pattern) -> dict:
        """Parse filename using regex and return tags"""
        match = regex.match(filename)
        if match:
            return {k: v for k, v in match.groupdict().items() if not k.startswith('_')}
        return {}
    
    def _on_file_selection_change(self):
        """Handle file selection change (for swap feature and tag panel)"""
        # Update preview if swap is enabled
        if self.swap_enabled.get():
            self._update_preview()
        
        # Auto-load tags for selected audio file
        audio_files = self._get_selected_audio_files()
        if audio_files and len(audio_files) == 1:
            self._reload_tags()
    
    def _set_filter(self, filter_text: str):
        """Set filter and update preview"""
        self.filter_text.set(filter_text)
    
    def _get_filtered_files(self) -> List:
        """Get files matching the current filter"""
        filter_str = self.filter_text.get().strip().lower()
        
        if not filter_str:
            return self.files
        
        filtered = []
        # Parse filter - can be comma-separated extensions or text search
        filter_parts = [f.strip() for f in filter_str.split(',')]
        
        for file_item in self.files:
            filename_lower = file_item.original_name.lower()
            ext_lower = file_item.extension.lower()
            
            for part in filter_parts:
                if part.startswith('.'):
                    # Extension filter
                    if ext_lower == part:
                        filtered.append(file_item)
                        break
                else:
                    # Text search in filename
                    if part in filename_lower:
                        filtered.append(file_item)
                        break
        
        return filtered
    
    def _sort_files(self, sort_key: str):
        """Sort files by the given key"""
        # If clicking same key, toggle reverse
        if sort_key == self.sort_key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key = sort_key
            self.sort_reverse = False
        
        self._apply_sort()
        self._update_sort_ui()
    
    def _toggle_sort_reverse(self):
        """Toggle sort direction"""
        self.sort_reverse = not self.sort_reverse
        self._apply_sort()
        self._update_sort_ui()
    
    def _apply_sort(self):
        """Apply current sort to files list"""
        if not self.files:
            return
        
        if self.sort_key == "name":
            self.files.sort(key=lambda f: f.original_name.lower(), reverse=self.sort_reverse)
        elif self.sort_key == "date":
            self.files.sort(key=lambda f: f.modified_date or datetime.min, reverse=self.sort_reverse)
        elif self.sort_key == "size":
            self.files.sort(key=lambda f: f.size, reverse=self.sort_reverse)
        elif self.sort_key == "extension":
            self.files.sort(key=lambda f: (f.extension.lower(), f.original_name.lower()), reverse=self.sort_reverse)
        
        self._update_preview()
    
    def _update_sort_ui(self):
        """Update sort button states and info label"""
        # Reset all buttons
        for key, btn in self.sort_buttons.items():
            if key == self.sort_key:
                btn.configure(fg_color=ParagonTheme.RED_DARK, text_color=ParagonTheme.TEXT_PRIMARY)
            else:
                btn.configure(fg_color=ParagonTheme.BG_TERTIARY, text_color=ParagonTheme.TEXT_SECONDARY)
        
        # Update reverse button
        if self.sort_reverse:
            self.sort_reverse_btn.configure(fg_color=ParagonTheme.RED_DARK)
        else:
            self.sort_reverse_btn.configure(fg_color=ParagonTheme.BG_TERTIARY)
        
        # Update info label
        direction = "↓ Z-A" if self.sort_reverse else "↑ A-Z"
        if self.sort_key == "date":
            direction = "↓ Newest" if self.sort_reverse else "↑ Oldest"
        elif self.sort_key == "size":
            direction = "↓ Largest" if self.sort_reverse else "↑ Smallest"
        
        self.sort_info_label.configure(text=f"{self.sort_key.title()} {direction}")
    
    def _setup_drag_and_drop(self):
        """Setup drag and drop bindings"""
        # Register the file list area for drops
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self._on_drop)
        self.dnd_bind('<<DragEnter>>', self._on_drag_enter)
        self.dnd_bind('<<DragLeave>>', self._on_drag_leave)
    
    def _on_drag_enter(self, event):
        """Visual feedback when dragging over"""
        self.file_list_container.configure(fg_color=ParagonTheme.RED_DARK)
        return event.action
    
    def _on_drag_leave(self, event):
        """Reset visual feedback"""
        self.file_list_container.configure(fg_color="transparent")
        return event.action
    
    def _on_drop(self, event):
        """Handle dropped files"""
        self.file_list_container.configure(fg_color="transparent")
        
        # Parse the dropped data - tkdnd returns space-separated paths
        # Paths with spaces are enclosed in braces {}
        dropped = event.data
        
        # Parse paths (handles both simple and braced paths)
        paths = []
        if '{' in dropped:
            # Complex parsing for paths with spaces
            import re
            # Find all braced paths and unbraced paths
            pattern = r'\{([^}]+)\}|(\S+)'
            matches = re.findall(pattern, dropped)
            for braced, unbraced in matches:
                path = braced if braced else unbraced
                if path:
                    paths.append(path)
        else:
            # Simple space-separated paths
            paths = dropped.split()
        
        # Process dropped paths
        files_to_add = []
        for path in paths:
            path = Path(path)
            if path.exists():
                if path.is_file():
                    files_to_add.append(str(path))
                elif path.is_dir():
                    # Use _scan_folder for recursive support
                    files_to_add.extend(self._scan_folder(path))
        
        if files_to_add:
            self._load_files(files_to_add)
            self.status_label.configure(text=f"📥 Dropped {len(files_to_add)} file(s)")
        
        return event.action
    
    def _create_status_bar(self, parent):
        """Create status bar"""
        status_frame = ctk.CTkFrame(parent, fg_color="transparent", height=30)
        status_frame.pack(fill="x", padx=20, pady=(0, 10))
        status_frame.pack_propagate(False)
        
        self.status_label = ParagonLabel(status_frame, text="Ready", style="muted")
        self.status_label.pack(side="left")
        
        self.progress_bar = ParagonProgressBar(status_frame, width=250)
        self.progress_bar.pack(side="right")
        self.progress_bar.set(0)
        self.progress_bar.pack_forget()
    
    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================
    
    def _add_files(self):
        """Add files via custom Paragon file browser"""
        browser = ParagonFileBrowser(
            self,
            mode="files",
            title="Select Files to Rename",
            initial_dir=Path.home() / "Downloads",
            multiple=True
        )
        
        selected = browser.get_result()
        if selected:
            self._load_files([str(p) for p in selected])
    
    def _add_folder(self):
        """Add all files from a folder via custom Paragon file browser"""
        browser = ParagonFileBrowser(
            self,
            mode="folder",
            title="Select Folder",
            initial_dir=Path.home(),
            multiple=False
        )
        
        selected = browser.get_result()
        if selected:
            folder = selected[0]
            files = self._scan_folder(folder)
            
            if files:
                self._load_files(files)
                if self.recursive_scan.get():
                    self.status_label.configure(text=f"📂 Loaded {len(files)} file(s) recursively")
    
    def _scan_folder(self, folder: Path, depth: int = 0) -> List[str]:
        """Scan a folder for files, optionally recursive"""
        files = []
        max_depth = 10  # Safety limit for recursion
        
        try:
            for item in folder.iterdir():
                if item.is_file():
                    files.append(str(item))
                elif item.is_dir():
                    if self.include_folders.get():
                        files.append(str(item))
                    # Recurse into subdirectories if enabled
                    if self.recursive_scan.get() and depth < max_depth:
                        files.extend(self._scan_folder(item, depth + 1))
        except PermissionError:
            if depth == 0:
                messagebox.showerror("Error", f"Permission denied: {folder}")
            # Silently skip permission errors in subfolders
        
        return files
    
    def _load_files(self, paths: List[str]):
        """Load files into the list"""
        for path in paths:
            if any(f.path == path for f in self.files):
                continue
            self.files.append(FileItem(path))
        
        self._update_preview()
        self._update_file_count()
    
    def _clear_files(self):
        """Clear all files"""
        self.files.clear()
        self.file_list.clear()
        self._update_file_count()
        self.status_label.configure(text="Ready")
    
    def _update_file_count(self):
        """Update file count label"""
        total_count = len(self.files)
        filtered_files = self._get_filtered_files()
        filtered_count = len(filtered_files)
        changed = self.file_list.get_changed_count()
        
        # Check for duplicates in preview
        files_to_check = [(f, f.new_name) for f in filtered_files if f.new_name != f.original_name]
        duplicates = self._find_duplicate_names(files_to_check) if files_to_check else {}
        dup_count = sum(len(sources) for sources in duplicates.values())
        
        # Build status text
        if filtered_count < total_count:
            status_text = f"{filtered_count}/{total_count} files • {changed} to rename"
            self.filter_count_label.configure(text=f"Showing {filtered_count} of {total_count}")
        else:
            status_text = f"{total_count} files • {changed} to rename"
            self.filter_count_label.configure(text="")
        
        # Add duplicate warning
        if dup_count > 0:
            status_text += f" • ⚠️ {dup_count} conflicts"
            self.file_count_label.configure(text=status_text, text_color=ParagonTheme.WARNING)
        else:
            self.file_count_label.configure(text=status_text, text_color=ParagonTheme.TEXT_SECONDARY)
    
    # =========================================================================
    # RULE BUILDING & PREVIEW
    # =========================================================================
    
    def _build_rules(self) -> List[RenameRule]:
        """Build list of active rules from UI state"""
        rules = []
        
        # Replace
        if self.replace_find.get():
            rules.append(ReplaceRule(
                enabled=True,
                find=self.replace_find.get(),
                replace=self.replace_with.get(),
                use_regex=self.replace_regex.get(),
                case_sensitive=self.replace_case.get()
            ))
        
        # Remove
        try:
            remove_count = int(self.remove_count.get())
        except ValueError:
            remove_count = 0
        
        has_remove = (remove_count > 0 or self.remove_digits.get() or self.remove_spaces.get() or
                      self.remove_illegal.get() or self.remove_brackets.get() or 
                      self.remove_punctuation.get() or self.remove_all_special.get())
        
        if has_remove:
            try:
                start_pos = int(self.remove_start.get())
            except ValueError:
                start_pos = 0
            
            rules.append(RemoveRule(
                enabled=True,
                start_pos=start_pos,
                count=remove_count,
                from_end=self.remove_from_end.get(),
                remove_digits=self.remove_digits.get(),
                remove_spaces=self.remove_spaces.get(),
                remove_illegal=self.remove_illegal.get(),
                remove_brackets=self.remove_brackets.get(),
                remove_punctuation=self.remove_punctuation.get(),
                remove_all_special=self.remove_all_special.get()
            ))
        
        # Insert
        if self.insert_text.get():
            try:
                insert_pos = int(self.insert_pos.get())
            except ValueError:
                insert_pos = 0
            
            rules.append(InsertRule(
                enabled=True,
                text=self.insert_text.get(),
                position=insert_pos,
                from_end=self.insert_from_end.get()
            ))
        
        # Case
        if self.case_type.get() != "none":
            rules.append(CaseRule(enabled=True, case_type=self.case_type.get()))
        
        # Note: Swap is handled separately in _update_preview for selected files only
        
        # Number
        if self.number_enabled.get():
            try:
                start = int(self.number_start.get())
                step = int(self.number_step.get())
                padding = int(self.number_padding.get())
            except ValueError:
                start, step, padding = 1, 1, 2
            
            rules.append(NumberRule(
                enabled=True,
                start=start,
                step=step,
                padding=padding,
                position=self.number_position.get(),
                separator=self.number_separator.get()
            ))
        
        # TV Show
        if self.tv_enabled.get():
            try:
                season = int(self.tv_season.get())
                ep_start = int(self.tv_episode_start.get())
                ep_step = int(self.tv_episode_step.get())
            except ValueError:
                season, ep_start, ep_step = 1, 1, 1
            
            try:
                max_eps = int(self.tv_max_episodes.get())
            except ValueError:
                max_eps = 0
            
            rules.append(TVShowRule(
                enabled=True,
                season=season,
                episode_start=ep_start,
                episode_step=ep_step,
                max_episodes=max_eps,
                format_style=self.tv_format.get(),
                separator=self.tv_separator.get(),
                position=self.tv_position.get(),
                include_show_name=self.tv_include_show.get(),
                show_name=self.tv_show_name.get()
            ))
        
        # DateTime
        if self.datetime_enabled.get():
            rules.append(DateTimeRule(
                enabled=True,
                format=self.datetime_format.get(),
                use_file_date=self.datetime_source.get() == "File modified date",
                position=self.datetime_position.get(),
                separator=self.datetime_separator.get()
            ))
        
        # Metadata
        if self.metadata_enabled.get():
            rules.append(MetadataRule(
                enabled=True,
                template=self.metadata_template.get()
            ))
        
        return rules
    
    def _apply_rules(self, file_item: FileItem, index: int, rules: List[RenameRule]) -> str:
        """Apply all rules to a filename"""
        if self.include_extension.get():
            name = file_item.original_name
        else:
            name = file_item.name_without_ext
        
        for rule in rules:
            name = rule.apply(name, index, file_item.metadata)
        
        if not self.include_extension.get():
            name = name + file_item.extension
        
        return name
    
    def _apply_swap(self, filename: str) -> str:
        """Apply swap segments rule"""
        delimiter = self.swap_delimiter.get()
        if not delimiter or delimiter not in filename:
            return filename
        
        parts = filename.split(delimiter)
        return delimiter.join(reversed(parts))
    
    def _update_preview(self):
        """Update the preview in the file list (optimized)"""
        if not self.files:
            self.file_list.clear()
            self._update_file_count()
            return
        
        # Get filtered files
        filtered_files = self._get_filtered_files()
        
        # Get selected indices for swap feature
        selected_indices = set(self.file_list.get_selected_indices()) if self.swap_enabled.get() else set()
        
        rules = self._build_rules()
        
        # Build all items as tuples first
        items = []
        for i, file_item in enumerate(filtered_files):
            # Use index in filtered list for numbering
            new_name = self._apply_rules(file_item, i, rules)
            
            # Apply swap only to selected files
            if self.swap_enabled.get() and i in selected_indices:
                # Apply swap to the name part only (without extension if not including it)
                if not self.include_extension.get() and file_item.extension:
                    name_part = new_name[:-len(file_item.extension)] if new_name.endswith(file_item.extension) else new_name
                    ext_part = file_item.extension
                    new_name = self._apply_swap(name_part) + ext_part
                else:
                    new_name = self._apply_swap(new_name)
            
            file_item.new_name = new_name
            changed = new_name != file_item.original_name
            items.append((file_item.original_name, new_name, changed))
        
        # Update all at once (uses in-place update if count unchanged)
        self.file_list.set_items(items)
        self._update_file_count()
    
    # =========================================================================
    # RENAME EXECUTION
    # =========================================================================
    
    def _execute_rename(self):
        """Execute the rename operation"""
        if not self.files:
            messagebox.showinfo("Info", "No files to rename")
            return
        
        # Only rename filtered files that have changes
        filtered_files = self._get_filtered_files()
        files_to_rename = [(f, f.new_name) for f in filtered_files if f.new_name != f.original_name]
        
        if not files_to_rename:
            messagebox.showinfo("Info", "No changes to apply")
            return
        
        # Check for duplicates
        duplicates = self._find_duplicate_names(files_to_rename)
        if duplicates:
            if not self._show_duplicate_warning(duplicates):
                return
        
        filter_note = ""
        if len(filtered_files) < len(self.files):
            filter_note = f"\n\n(Only filtered files will be renamed)"
        
        result = messagebox.askyesno(
            "Confirm Rename",
            f"Rename {len(files_to_rename)} file(s)?{filter_note}\n\nThis operation can be undone."
        )
        
        if not result:
            return
        
        # Show progress
        self.progress_bar.pack(side="right")
        self.progress_bar.set(0)
        
        successful_renames = []
        errors = []
        
        for i, (file_item, new_name) in enumerate(files_to_rename):
            old_path = file_item.path
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            
            try:
                if os.path.exists(new_path) and old_path != new_path:
                    errors.append(f"{file_item.original_name}: Destination exists")
                    continue
                
                os.rename(old_path, new_path)
                successful_renames.append((old_path, new_path))
                
                file_item.path = new_path
                file_item.original_name = new_name
                file_item.name_without_ext = os.path.splitext(new_name)[0]
                file_item.extension = os.path.splitext(new_name)[1]
                
            except OSError as e:
                errors.append(f"{file_item.original_name}: {str(e)}")
            
            self.progress_bar.set((i + 1) / len(files_to_rename))
            self.update()
        
        if successful_renames:
            self.undo_manager.save_state(successful_renames)
            # Log the rename operation
            self.rename_history.append({
                'timestamp': datetime.now().isoformat(),
                'renames': [(old, new) for old, new in successful_renames],
                'errors': errors.copy()
            })
        
        self.progress_bar.pack_forget()
        self._update_preview()
        
        if errors:
            error_msg = "\n".join(errors[:10])
            if len(errors) > 10:
                error_msg += f"\n... and {len(errors) - 10} more errors"
            messagebox.showwarning("Rename Complete", f"Renamed {len(successful_renames)} file(s).\n\nErrors:\n{error_msg}")
        else:
            self.status_label.configure(text=f"✓ Successfully renamed {len(successful_renames)} file(s)")
            messagebox.showinfo("Success", f"Renamed {len(successful_renames)} file(s)")
    
    def _find_duplicate_names(self, files_to_rename: List[tuple]) -> Dict[str, List[str]]:
        """Find files that would have duplicate names after renaming"""
        # Group by target directory + new name
        name_map: Dict[str, List[str]] = {}
        
        for file_item, new_name in files_to_rename:
            target_dir = os.path.dirname(file_item.path)
            key = os.path.join(target_dir, new_name.lower())  # Case-insensitive on Windows
            
            if key not in name_map:
                name_map[key] = []
            name_map[key].append(file_item.original_name)
        
        # Filter to only duplicates
        duplicates = {name: sources for name, sources in name_map.items() if len(sources) > 1}
        
        return duplicates
    
    def _show_duplicate_warning(self, duplicates: Dict[str, List[str]]) -> bool:
        """Show warning dialog for duplicate filenames, return True to proceed"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("⚠️ Duplicate Filenames Detected")
        dialog.geometry("500x400")
        dialog.configure(fg_color=ParagonTheme.BG_DARK)
        dialog.transient(self)
        
        # Center on parent
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 500) // 2
        y = self.winfo_y() + (self.winfo_height() - 400) // 2
        dialog.geometry(f"+{x}+{y}")
        
        result = [False]
        
        # Warning header
        header_frame = ctk.CTkFrame(dialog, fg_color=ParagonTheme.RED_DARK, corner_radius=0)
        header_frame.pack(fill="x", pady=(0, 10))
        
        ParagonLabel(
            header_frame, 
            text=f"⚠️  {len(duplicates)} filename conflict(s) detected!",
            style="title"
        ).pack(padx=15, pady=10)
        
        # Explanation
        ParagonLabel(
            dialog,
            text="The following files would have the same name after renaming.\nOnly the first file in each group will be renamed successfully.",
            style="muted"
        ).pack(padx=15, pady=(0, 10))
        
        # Scrollable list of duplicates
        scroll_frame = ctk.CTkScrollableFrame(
            dialog,
            fg_color=ParagonTheme.BG_SECONDARY,
            corner_radius=6
        )
        scroll_frame.pack(fill="both", expand=True, padx=15, pady=5)
        
        for target_path, source_files in duplicates.items():
            target_name = os.path.basename(target_path)
            
            # Target name
            target_frame = ctk.CTkFrame(scroll_frame, fg_color=ParagonTheme.BG_TERTIARY, corner_radius=4)
            target_frame.pack(fill="x", pady=5, padx=5)
            
            ParagonLabel(
                target_frame,
                text=f"→ {target_name}",
                style="muted"
            ).pack(anchor="w", padx=10, pady=(8, 2))
            
            # Source files
            for source in source_files:
                ctk.CTkLabel(
                    target_frame,
                    text=f"   • {source}",
                    text_color=ParagonTheme.WARNING,
                    font=ctk.CTkFont(family="Segoe UI", size=11)
                ).pack(anchor="w", padx=10, pady=1)
            
            ctk.CTkFrame(target_frame, height=5, fg_color="transparent").pack()
        
        # Buttons
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=15)
        
        def on_cancel():
            result[0] = False
            dialog.destroy()
        
        def on_proceed():
            result[0] = True
            dialog.destroy()
        
        ParagonSecondaryButton(
            btn_frame, 
            text="Cancel", 
            command=on_cancel,
            width=120
        ).pack(side="left", padx=5)
        
        ParagonButton(
            btn_frame, 
            text="Proceed Anyway", 
            command=on_proceed,
            width=140
        ).pack(side="right", padx=5)
        
        # Deferred grab_set to avoid "window not viewable" error
        dialog.after(50, lambda: dialog.grab_set() if dialog.winfo_exists() else None)
        
        dialog.wait_window()
        return result[0]
    
    def _undo(self):
        """Undo last rename operation"""
        if not self.undo_manager.can_undo():
            messagebox.showinfo("Info", "Nothing to undo")
            return
        
        renames = self.undo_manager.undo()
        if not renames:
            return
        
        errors = []
        successful = 0
        
        for current_path, original_path in renames:
            try:
                if os.path.exists(current_path):
                    os.rename(current_path, original_path)
                    successful += 1
                    
                    for file_item in self.files:
                        if file_item.path == current_path:
                            file_item.path = original_path
                            file_item.original_name = os.path.basename(original_path)
                            file_item.name_without_ext = os.path.splitext(file_item.original_name)[0]
                            file_item.extension = os.path.splitext(file_item.original_name)[1]
                            break
            except OSError as e:
                errors.append(str(e))
        
        self._update_preview()
        
        if errors:
            messagebox.showwarning("Undo", f"Restored {successful} file(s).\nErrors: {len(errors)}")
        else:
            self.status_label.configure(text=f"↩️ Restored {successful} file(s)")
            messagebox.showinfo("Undo", f"Restored {successful} file(s)")
    
    def _export_log(self):
        """Export rename log to file"""
        # Check if we have anything to export
        if not self.rename_history and not self.files:
            messagebox.showinfo("Export Log", "No rename history or files to export.")
            return
        
        # Ask for export format
        export_type = self._show_export_dialog()
        if not export_type:
            return
        
        # Get save location
        if export_type == "txt":
            filetypes = [("Text files", "*.txt"), ("All files", "*.*")]
            default_ext = ".txt"
        elif export_type == "csv":
            filetypes = [("CSV files", "*.csv"), ("All files", "*.*")]
            default_ext = ".csv"
        else:  # json
            filetypes = [("JSON files", "*.json"), ("All files", "*.*")]
            default_ext = ".json"
        
        filename = filedialog.asksaveasfilename(
            title="Export Rename Log",
            defaultextension=default_ext,
            filetypes=filetypes,
            initialfile=f"pyrenamer_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        
        if not filename:
            return
        
        try:
            if export_type == "txt":
                self._export_log_txt(filename)
            elif export_type == "csv":
                self._export_log_csv(filename)
            else:
                self._export_log_json(filename)
            
            self.status_label.configure(text=f"📄 Log exported to {os.path.basename(filename)}")
            messagebox.showinfo("Export Complete", f"Log exported to:\n{filename}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export log:\n{str(e)}")
    
    def _show_export_dialog(self) -> Optional[str]:
        """Show dialog to choose export format"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Export Format")
        dialog.geometry("300x200")
        dialog.configure(fg_color=ParagonTheme.BG_DARK)
        dialog.transient(self)
        
        # Center on parent
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 300) // 2
        y = self.winfo_y() + (self.winfo_height() - 200) // 2
        dialog.geometry(f"+{x}+{y}")
        
        result = [None]
        
        ParagonLabel(dialog, text="Select export format:", style="muted").pack(pady=(20, 15))
        
        format_var = ctk.StringVar(value="txt")
        
        formats = [
            ("Text file (.txt) - Human readable", "txt"),
            ("CSV file (.csv) - Spreadsheet compatible", "csv"),
            ("JSON file (.json) - Machine readable", "json")
        ]
        
        for label, value in formats:
            ctk.CTkRadioButton(
                dialog,
                text=label,
                variable=format_var,
                value=value,
                fg_color=ParagonTheme.RED_PRIMARY,
                hover_color=ParagonTheme.RED_LIGHT,
                text_color=ParagonTheme.TEXT_PRIMARY
            ).pack(anchor="w", padx=30, pady=5)
        
        def on_export():
            result[0] = format_var.get()
            dialog.destroy()
        
        def on_cancel():
            dialog.destroy()
        
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        ParagonSecondaryButton(btn_frame, text="Cancel", command=on_cancel, width=80).pack(side="left", padx=5)
        ParagonButton(btn_frame, text="Export", command=on_export, width=80).pack(side="left", padx=5)
        
        # Deferred grab_set to avoid "window not viewable" error
        dialog.after(50, lambda: dialog.grab_set() if dialog.winfo_exists() else None)
        
        dialog.wait_window()
        return result[0]
    
    def _export_log_txt(self, filename: str):
        """Export log as text file"""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("PYRENAMER - Rename Log\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")
            
            # Current pending changes
            filtered_files = self._get_filtered_files()
            pending = [(fi, fi.new_name) for fi in filtered_files if fi.new_name != fi.original_name]
            
            if pending:
                f.write("PENDING CHANGES:\n")
                f.write("-" * 50 + "\n")
                for file_item, new_name in pending:
                    f.write(f"  {file_item.original_name}\n")
                    f.write(f"    → {new_name}\n")
                f.write(f"\nTotal pending: {len(pending)} file(s)\n\n")
            
            # History
            if self.rename_history:
                f.write("RENAME HISTORY:\n")
                f.write("-" * 50 + "\n")
                for i, entry in enumerate(self.rename_history, 1):
                    f.write(f"\n[Operation {i}] {entry['timestamp']}\n")
                    for old_path, new_path in entry['renames']:
                        old_name = os.path.basename(old_path)
                        new_name = os.path.basename(new_path)
                        f.write(f"  {old_name} → {new_name}\n")
                    if entry['errors']:
                        f.write(f"  Errors: {len(entry['errors'])}\n")
                        for err in entry['errors'][:5]:
                            f.write(f"    - {err}\n")
                
                total_renames = sum(len(e['renames']) for e in self.rename_history)
                f.write(f"\nTotal renamed: {total_renames} file(s) in {len(self.rename_history)} operation(s)\n")
    
    def _export_log_csv(self, filename: str):
        """Export log as CSV file"""
        import csv
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Type', 'Timestamp', 'Original Name', 'New Name', 'Original Path', 'New Path', 'Status'])
            
            # Pending changes
            filtered_files = self._get_filtered_files()
            for file_item in filtered_files:
                if file_item.new_name != file_item.original_name:
                    new_path = os.path.join(os.path.dirname(file_item.path), file_item.new_name)
                    writer.writerow([
                        'Pending',
                        '',
                        file_item.original_name,
                        file_item.new_name,
                        file_item.path,
                        new_path,
                        'Pending'
                    ])
            
            # History
            for entry in self.rename_history:
                for old_path, new_path in entry['renames']:
                    writer.writerow([
                        'Completed',
                        entry['timestamp'],
                        os.path.basename(old_path),
                        os.path.basename(new_path),
                        old_path,
                        new_path,
                        'Success'
                    ])
    
    def _export_log_json(self, filename: str):
        """Export log as JSON file"""
        filtered_files = self._get_filtered_files()
        pending = []
        for file_item in filtered_files:
            if file_item.new_name != file_item.original_name:
                pending.append({
                    'original_name': file_item.original_name,
                    'new_name': file_item.new_name,
                    'original_path': file_item.path,
                    'new_path': os.path.join(os.path.dirname(file_item.path), file_item.new_name)
                })
        
        data = {
            'generated': datetime.now().isoformat(),
            'pending_changes': pending,
            'history': self.rename_history
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    # =========================================================================
    # PRESET MANAGEMENT
    # =========================================================================
    
    def _get_presets_dir(self) -> Path:
        """Get the presets directory, creating it if needed"""
        presets_dir = Path.home() / ".pyrenamer" / "presets"
        presets_dir.mkdir(parents=True, exist_ok=True)
        return presets_dir
    
    def _get_current_rules_state(self) -> dict:
        """Get current rules configuration as a dictionary"""
        return {
            'replace': {
                'find': self.replace_find.get(),
                'replace': self.replace_with.get(),
                'regex': self.replace_regex.get(),
                'case_sensitive': self.replace_case.get(),
            },
            'remove': {
                'start': self.remove_start.get(),
                'count': self.remove_count.get(),
                'from_end': self.remove_from_end.get(),
                'digits': self.remove_digits.get(),
                'spaces': self.remove_spaces.get(),
                'illegal': self.remove_illegal.get(),
                'brackets': self.remove_brackets.get(),
                'punctuation': self.remove_punctuation.get(),
                'all_special': self.remove_all_special.get(),
            },
            'insert': {
                'text': self.insert_text.get(),
                'position': self.insert_pos.get(),
                'from_end': self.insert_from_end.get(),
            },
            'case': {
                'type': self.case_type.get(),
            },
            'number': {
                'enabled': self.number_enabled.get(),
                'start': self.number_start.get(),
                'step': self.number_step.get(),
                'padding': self.number_padding.get(),
                'position': self.number_position.get(),
                'separator': self.number_separator.get(),
            },
            'tv': {
                'enabled': self.tv_enabled.get(),
                'season': self.tv_season.get(),
                'episode_start': self.tv_episode_start.get(),
                'episode_step': self.tv_episode_step.get(),
                'max_episodes': self.tv_max_episodes.get(),
                'format': self.tv_format.get(),
                'separator': self.tv_separator.get(),
                'position': self.tv_position.get(),
                'include_show': self.tv_include_show.get(),
                'show_name': self.tv_show_name.get(),
            },
            'datetime': {
                'enabled': self.datetime_enabled.get(),
                'format': self.datetime_format.get(),
                'source': self.datetime_source.get(),
                'position': self.datetime_position.get(),
                'separator': self.datetime_separator.get(),
            },
            'metadata': {
                'enabled': self.metadata_enabled.get(),
                'template': self.metadata_template.get(),
            },
            'swap': {
                'enabled': self.swap_enabled.get(),
                'delimiter': self.swap_delimiter.get(),
            },
            'options': {
                'include_extension': self.include_extension.get(),
                'include_folders': self.include_folders.get(),
            }
        }
    
    def _apply_rules_state(self, state: dict):
        """Apply a saved rules configuration"""
        # Replace
        if 'replace' in state:
            self.replace_find.set(state['replace'].get('find', ''))
            self.replace_with.set(state['replace'].get('replace', ''))
            self.replace_regex.set(state['replace'].get('regex', False))
            self.replace_case.set(state['replace'].get('case_sensitive', True))
        
        # Remove
        if 'remove' in state:
            self.remove_start.set(state['remove'].get('start', '0'))
            self.remove_count.set(state['remove'].get('count', '0'))
            self.remove_from_end.set(state['remove'].get('from_end', False))
            self.remove_digits.set(state['remove'].get('digits', False))
            self.remove_spaces.set(state['remove'].get('spaces', False))
            self.remove_illegal.set(state['remove'].get('illegal', False))
            self.remove_brackets.set(state['remove'].get('brackets', False))
            self.remove_punctuation.set(state['remove'].get('punctuation', False))
            self.remove_all_special.set(state['remove'].get('all_special', False))
        
        # Insert
        if 'insert' in state:
            self.insert_text.set(state['insert'].get('text', ''))
            self.insert_pos.set(state['insert'].get('position', '0'))
            self.insert_from_end.set(state['insert'].get('from_end', False))
        
        # Case
        if 'case' in state:
            self.case_type.set(state['case'].get('type', 'none'))
        
        # Number
        if 'number' in state:
            self.number_enabled.set(state['number'].get('enabled', False))
            self.number_start.set(state['number'].get('start', '1'))
            self.number_step.set(state['number'].get('step', '1'))
            self.number_padding.set(state['number'].get('padding', '2'))
            self.number_position.set(state['number'].get('position', 'suffix'))
            self.number_separator.set(state['number'].get('separator', '_'))
        
        # TV Show
        if 'tv' in state:
            self.tv_enabled.set(state['tv'].get('enabled', False))
            self.tv_season.set(state['tv'].get('season', '1'))
            self.tv_episode_start.set(state['tv'].get('episode_start', '1'))
            self.tv_episode_step.set(state['tv'].get('episode_step', '1'))
            self.tv_max_episodes.set(state['tv'].get('max_episodes', '0'))
            self.tv_format.set(state['tv'].get('format', 'S00E00'))
            self.tv_separator.set(state['tv'].get('separator', ' - '))
            self.tv_position.set(state['tv'].get('position', 'prefix'))
            self.tv_include_show.set(state['tv'].get('include_show', False))
            self.tv_show_name.set(state['tv'].get('show_name', ''))
        
        # DateTime
        if 'datetime' in state:
            self.datetime_enabled.set(state['datetime'].get('enabled', False))
            self.datetime_format.set(state['datetime'].get('format', '%Y-%m-%d'))
            self.datetime_source.set(state['datetime'].get('source', 'File modified date'))
            self.datetime_position.set(state['datetime'].get('position', 'prefix'))
            self.datetime_separator.set(state['datetime'].get('separator', '_'))
        
        # Metadata
        if 'metadata' in state:
            self.metadata_enabled.set(state['metadata'].get('enabled', False))
            self.metadata_template.set(state['metadata'].get('template', '{artist} - {title}'))
        
        # Swap
        if 'swap' in state:
            self.swap_enabled.set(state['swap'].get('enabled', False))
            self.swap_delimiter.set(state['swap'].get('delimiter', ' - '))
        
        # Options
        if 'options' in state:
            self.include_extension.set(state['options'].get('include_extension', False))
            self.include_folders.set(state['options'].get('include_folders', False))
    
    def _save_preset(self):
        """Save current rules as a preset"""
        dialog = PresetSaveDialog(self)
        name = dialog.get_result()
        
        if name:
            preset_file = self._get_presets_dir() / f"{name}.json"
            state = self._get_current_rules_state()
            state['name'] = name
            state['created'] = datetime.now().isoformat()
            
            try:
                with open(preset_file, 'w') as f:
                    json.dump(state, f, indent=2)
                self.status_label.configure(text=f"💾 Preset '{name}' saved")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save preset: {e}")
    
    def _load_preset(self):
        """Load a preset"""
        presets = self._get_available_presets()
        
        if not presets:
            messagebox.showinfo("Info", "No presets saved yet.\n\nUse 💾 to save your current rules as a preset.")
            return
        
        dialog = PresetLoadDialog(self, presets)
        selected = dialog.get_result()
        
        if selected:
            preset_file = self._get_presets_dir() / f"{selected}.json"
            try:
                with open(preset_file, 'r') as f:
                    state = json.load(f)
                self._apply_rules_state(state)
                self.status_label.configure(text=f"📂 Preset '{selected}' loaded")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load preset: {e}")
    
    def _manage_presets(self):
        """Open preset manager dialog"""
        presets = self._get_available_presets()
        dialog = PresetManagerDialog(self, presets, self._get_presets_dir())
        
        # Refresh status after managing
        if dialog.deleted_any:
            self.status_label.configure(text="🗑️ Presets updated")
    
    def _get_available_presets(self) -> List[dict]:
        """Get list of available presets with metadata"""
        presets = []
        presets_dir = self._get_presets_dir()
        
        for preset_file in presets_dir.glob("*.json"):
            try:
                with open(preset_file, 'r') as f:
                    data = json.load(f)
                    presets.append({
                        'name': data.get('name', preset_file.stem),
                        'file': preset_file,
                        'created': data.get('created', 'Unknown')
                    })
            except:
                pass
        
        return sorted(presets, key=lambda x: x['name'].lower())


# =============================================================================
# PRESET DIALOGS
# =============================================================================

class PresetSaveDialog(ctk.CTkToplevel):
    """Dialog for saving a preset"""
    
    def __init__(self, master):
        super().__init__(master)
        
        self.result = None
        
        self.title("Save Preset")
        self.geometry("400x180")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        self._create_ui()
        
        self.update()
        self.after(50, self._on_ready)
        
        self.wait_window()
    
    def _on_ready(self):
        try:
            self.grab_set()
        except:
            pass
        self.name_entry.focus()
    
    def _create_ui(self):
        # Gold border frame
        outer = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=10)
        outer.pack(fill="both", expand=True, padx=3, pady=3)
        
        inner = ctk.CTkFrame(outer, fg_color=ParagonTheme.BG_DARK, corner_radius=8)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Title
        ParagonLabel(inner, text="💾  SAVE PRESET", style="title").pack(pady=(20, 15))
        
        # Name entry
        entry_frame = ctk.CTkFrame(inner, fg_color="transparent")
        entry_frame.pack(fill="x", padx=30)
        
        ParagonLabel(entry_frame, text="Preset name:", style="muted").pack(anchor="w")
        self.name_entry = ParagonEntry(entry_frame, placeholder_text="My Preset", width=300)
        self.name_entry.pack(fill="x", pady=(5, 0))
        self.name_entry.bind("<Return>", lambda e: self._on_save())
        
        # Buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self._on_cancel, width=100).pack(side="left", padx=5)
        ParagonGoldButton(btn_frame, text="SAVE", command=self._on_save, width=100).pack(side="left", padx=5)
    
    def _on_save(self):
        name = self.name_entry.get().strip()
        if name:
            # Sanitize filename
            name = re.sub(r'[<>:"/\\|?*]', '_', name)
            self.result = name
            self.destroy()
    
    def _on_cancel(self):
        self.destroy()
    
    def get_result(self):
        return self.result


class PresetLoadDialog(ctk.CTkToplevel):
    """Dialog for loading a preset"""
    
    def __init__(self, master, presets: List[dict]):
        super().__init__(master)
        
        self.presets = presets
        self.result = None
        
        self.title("Load Preset")
        self.geometry("450x400")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        self._create_ui()
        
        self.update()
        self.after(50, self._on_ready)
        
        self.wait_window()
    
    def _on_ready(self):
        try:
            self.grab_set()
        except:
            pass
    
    def _create_ui(self):
        # Gold border frame
        outer = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=10)
        outer.pack(fill="both", expand=True, padx=3, pady=3)
        
        inner = ctk.CTkFrame(outer, fg_color=ParagonTheme.BG_DARK, corner_radius=8)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Title
        ParagonLabel(inner, text="📂  LOAD PRESET", style="title").pack(pady=(20, 15))
        
        # Preset list
        list_frame = ctk.CTkScrollableFrame(inner, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=6)
        list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        
        self.selected_var = ctk.StringVar()
        
        for i, preset in enumerate(self.presets):
            bg = ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY
            
            item_frame = ctk.CTkFrame(list_frame, fg_color=bg, corner_radius=4)
            item_frame.pack(fill="x", padx=5, pady=2)
            
            rb = ParagonRadioButton(
                item_frame, 
                text=preset['name'],
                variable=self.selected_var,
                value=preset['name'],
                command=lambda: None
            )
            rb.pack(side="left", padx=10, pady=8)
            
            # Show date if available
            if preset['created'] != 'Unknown':
                try:
                    dt = datetime.fromisoformat(preset['created'])
                    date_str = dt.strftime("%Y-%m-%d")
                except:
                    date_str = ""
                if date_str:
                    ParagonLabel(item_frame, text=date_str, style="muted").pack(side="right", padx=10)
        
        # Buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(pady=(0, 20))
        
        ParagonSecondaryButton(btn_frame, text="CANCEL", command=self._on_cancel, width=100).pack(side="left", padx=5)
        ParagonGoldButton(btn_frame, text="LOAD", command=self._on_load, width=100).pack(side="left", padx=5)
    
    def _on_load(self):
        selected = self.selected_var.get()
        if selected:
            self.result = selected
            self.destroy()
    
    def _on_cancel(self):
        self.destroy()
    
    def get_result(self):
        return self.result


class PresetManagerDialog(ctk.CTkToplevel):
    """Dialog for managing (viewing/deleting) presets"""
    
    def __init__(self, master, presets: List[dict], presets_dir: Path):
        super().__init__(master)
        
        self.presets = presets
        self.presets_dir = presets_dir
        self.deleted_any = False
        
        self.title("Manage Presets")
        self.geometry("500x450")
        self.configure(fg_color=ParagonTheme.BG_DARK)
        # self.transient(master)  # Disabled - causes window issues on Windows
        
        self._create_ui()
        
        self.update()
        self.after(50, self._on_ready)
        
        self.wait_window()
    
    def _on_ready(self):
        try:
            self.grab_set()
        except:
            pass
    
    def _create_ui(self):
        # Gold border frame
        outer = ctk.CTkFrame(self, fg_color=ParagonTheme.BORDER_GOLD, corner_radius=10)
        outer.pack(fill="both", expand=True, padx=3, pady=3)
        
        inner = ctk.CTkFrame(outer, fg_color=ParagonTheme.BG_DARK, corner_radius=8)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Title
        ParagonLabel(inner, text="📋  MANAGE PRESETS", style="title").pack(pady=(20, 15))
        
        # Preset list with delete buttons
        self.list_frame = ctk.CTkScrollableFrame(inner, fg_color=ParagonTheme.BG_SECONDARY, corner_radius=6)
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        
        self._populate_list()
        
        # Close button
        ParagonGoldButton(inner, text="CLOSE", command=self.destroy, width=120).pack(pady=(0, 20))
    
    def _populate_list(self):
        # Clear existing
        for widget in self.list_frame.winfo_children():
            widget.destroy()
        
        if not self.presets:
            ParagonLabel(self.list_frame, text="No presets saved", style="muted").pack(pady=30)
            return
        
        for i, preset in enumerate(self.presets):
            bg = ParagonTheme.BG_TERTIARY if i % 2 == 0 else ParagonTheme.BG_SECONDARY
            
            item_frame = ctk.CTkFrame(self.list_frame, fg_color=bg, corner_radius=4)
            item_frame.pack(fill="x", padx=5, pady=2)
            
            ParagonLabel(item_frame, text=f"  📄 {preset['name']}").pack(side="left", padx=10, pady=8)
            
            # Delete button
            del_btn = ctk.CTkButton(
                item_frame,
                text="🗑️",
                width=35,
                height=28,
                fg_color=ParagonTheme.RED_DARK,
                hover_color=ParagonTheme.RED_PRIMARY,
                command=lambda p=preset: self._delete_preset(p)
            )
            del_btn.pack(side="right", padx=10, pady=5)
            
            # Date
            if preset['created'] != 'Unknown':
                try:
                    dt = datetime.fromisoformat(preset['created'])
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    date_str = ""
                if date_str:
                    ParagonLabel(item_frame, text=date_str, style="muted").pack(side="right", padx=10)
    
    def _delete_preset(self, preset: dict):
        result = messagebox.askyesno("Delete Preset", f"Delete preset '{preset['name']}'?")
        if result:
            try:
                preset['file'].unlink()
                self.presets.remove(preset)
                self.deleted_any = True
                self._populate_list()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    app = PyRenamerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
