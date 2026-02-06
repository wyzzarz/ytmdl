#!/usr/bin/env python3
"""Update album metadata for songs in a directory using iTunes API."""

import os
import sys
import re
import requests
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TCON, TRCK, TPOS, TYER, PictureType
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen import File
from mutagen.flac import Picture

try:
    from simber import Logger
    logger = Logger('update_album')
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('update_album')


def extract_album_id(album_id_or_url: str) -> Optional[str]:
    """Extract album ID from either a direct ID or iTunes URL."""
    if album_id_or_url.isdigit():
        return album_id_or_url
    
    # Handle URLs like https://music.apple.com/us/album/juliet-original-broadway-cast-recording/1643207110
    match = re.search(r'/(\d+)$', album_id_or_url)
    if match:
        return match.group(1)
    
    return None


def fetch_album_data(album_id: str) -> Optional[Dict]:
    """Fetch album data from iTunes API."""
    try:
        params = {
            'id': album_id,
            'entity': 'song'
        }
        
        logger.info(f"Fetching album data for ID: {album_id}")
        response = requests.get("https://itunes.apple.com/lookup", params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if data['resultCount'] == 0:
            logger.error(f"Album ID {album_id} not found on iTunes")
            return None
        
        return data
    except requests.RequestException as e:
        logger.error(f"Failed to fetch album data: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching album data: {e}")
        return None


def parse_album_data(data: Dict) -> Tuple[Optional[Dict], List[Dict]]:
    """Parse iTunes API response to extract album and track information."""
    if not data or data['resultCount'] == 0:
        return None, []
    
    results = data['results']
    
    # First result is the album
    album_info = results[0]
    
    # Remaining results are tracks
    tracks = sorted(results[1:], key=lambda x: x.get('trackNumber', 0))
    
    return album_info, tracks


def download_artwork(artwork_url: str, output_path: str) -> bool:
    """Download artwork from URL and save to file."""
    try:
        if not artwork_url:
            return False
        
        # Try to get larger artwork if available
        artwork_url = artwork_url.replace('100x100', '600x600')
        
        logger.info(f"Downloading artwork from: {artwork_url}")
        response = requests.get(artwork_url, timeout=10)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        return True
    except Exception as e:
        logger.warning(f"Failed to download artwork: {e}")
        return False


def find_audio_files(directory: str) -> List[Tuple[int, str, str]]:
    """Find audio files prefixed with track numbers in directory.
    
    Returns:
        List of tuples: (track_number, filename, full_path)
    """
    audio_extensions = {'.mp3', '.m4a' }
    files = []
    
    try:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            
            if not os.path.isfile(file_path):
                continue
            
            _, ext = os.path.splitext(filename)
            if ext.lower() not in audio_extensions:
                continue
            
            # Extract track number from filename (e.g., "01 - Song Name.mp3")
            match = re.match(r'^(\d+)\s*[-.\s]', filename)
            if not match:
                logger.warning(f"Skipping file without track number prefix: {filename}")
                continue
            
            track_number = int(match.group(1))
            files.append((track_number, filename, file_path))
    
    except Exception as e:
        logger.error(f"Error scanning directory: {e}")
        return []
    
    return sorted(files, key=lambda x: x[0])


def set_mp3_metadata(file_path: str, track_data: Dict, album_data: Dict, artwork_path: Optional[str] = None) -> bool:
    """Update MP3 file with metadata and artwork."""
    try:
        audio = MP3(file_path, ID3=ID3)
        
        # Initialize ID3 tags if they don't exist
        try:
            audio.add_tags()
        except Exception:
            pass
        
        data = ID3(file_path)
        
        # Add artwork if available
        if artwork_path and os.path.exists(artwork_path):
            try:
                with open(artwork_path, 'rb') as f:
                    imagedata = f.read()
                data.add(APIC(3, 'image/jpeg', 3, 'Front cover', imagedata))
                logger.info(f"Added artwork to {file_path}")
            except Exception as e:
                logger.warning(f"Failed to add artwork to {file_path}: {e}")
        
        # Add track metadata
        data.add(TIT2(encoding=3, text=track_data.get('trackName', 'Unknown')))
        data.add(TPE1(encoding=3, text=track_data.get('artistName', album_data.get('artistName', 'Unknown'))))
        data.add(TALB(encoding=3, text=album_data.get('collectionName', 'Unknown')))
        if album_data['primaryGenreName']:
            data.add(TCON(encoding=3, text=album_data['primaryGenreName']))
        if album_data['releaseDate']:
            data.add(TYER(encoding=3, text=album_data['releaseDate'][:4]))  # Extract year

        # Add track information
        track_str = track_data.get('trackNumber', '')
        if track_data['trackCount']:
            track_str = f"{track_str}/{track_data['trackCount']}"
        data.add(TRCK(encoding=3, text=track_str))
        
        # Add disk information
        data.add(TPOS(encoding=3, text=f"{track_data.get('discNumber', 1)}/{album_data.get('discCount', 1)}"))

        data.save()
        logger.info(f"Updated MP3 metadata: {file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to update MP3 {file_path}: {e}")
        return False


def set_m4a_metadata(file_path: str, track_data: Dict, album_data: Dict, artwork_path: Optional[str] = None) -> bool:
    """Update M4A file with metadata and artwork."""
    try:
        audio = MP4(file_path)
        
        # Initialize tags if they don't exist
        try:
            audio.add_tags()
        except Exception:
            pass
        
        # Add artwork if available
        if artwork_path and os.path.exists(artwork_path):
            try:
                with open(artwork_path, 'rb') as f:
                    imagedata = f.read()
                audio["covr"] = [MP4Cover(imagedata, imageformat=MP4Cover.FORMAT_JPEG)]
                logger.info(f"Added artwork to {file_path}")
            except Exception as e:
                logger.warning(f"Failed to add artwork to {file_path}: {e}")
        
        # Add track metadata
        audio["\xa9nam"] = track_data.get('trackName', 'Unknown')
        audio["\xa9ART"] = track_data.get('artistName', album_data.get('artistName', 'Unknown'))
        audio['\xa9alb'] = album_data.get('collectionName', 'Unknown')
        if album_data['primaryGenreName']:
            audio['\xa9gen'] = [album_data['primaryGenreName']]
        if album_data['releaseDate']:
            audio["\xa9day"] = [album_data['releaseDate'][:4]]  # Extract year
        audio["trkn"] = [(track_data.get('trackNumber', 0), track_data.get('trackCount', 0))]
        audio["disk"] = [(track_data.get('discNumber', 1), album_data.get('discCount', 1))]

        audio.save()
        logger.info(f"Updated M4A metadata: {file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to update M4A {file_path}: {e}")
        return False


def update_file_metadata(file_path: str, track_data: Dict, album_data: Dict, artwork_path: Optional[str] = None) -> bool:
    """Update audio file metadata based on file type."""
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    
    if ext == '.mp3':
        return set_mp3_metadata(file_path, track_data, album_data, artwork_path)
    elif ext == '.m4a':
        return set_m4a_metadata(file_path, track_data, album_data, artwork_path)
    else:
        return False


def process_album(directory: str, album_id: str) -> bool:
    """Process all audio files in directory and update with album metadata."""
    # Extract album ID from URL or direct ID
    album_id = extract_album_id(album_id)
    if not album_id:
        logger.error("Invalid album ID or URL provided")
        return False
    
    # Fetch album data
    data = fetch_album_data(album_id)
    if not data:
        logger.error("Failed to fetch album data")
        return False
    
    album_info, tracks = parse_album_data(data)
    if not album_info or not tracks:
        logger.error("No album or tracks found in iTunes data")
        return False
    
    logger.info(f"Found album: {album_info.get('collectionName', 'Unknown')}")
    logger.info(f"Artist: {album_info.get('artistName', 'Unknown')}")
    logger.info(f"Total tracks: {len(tracks)}")
    
    # Find audio files in directory
    audio_files = find_audio_files(directory)
    if not audio_files:
        logger.error(f"No audio files found in {directory}")
        return False
    
    logger.info(f"Found {len(audio_files)} audio files to process")
    
    # Total tracks should match number of audio files
    if len(tracks) != len(audio_files):
        logger.warning(f"Track count from iTunes ({len(tracks)}) does not match number of audio files ({len(audio_files)})")
        return False
    
    # Download artwork once for all songs
    artwork_path = None
    artwork_url = album_info.get('artworkUrl100') or album_info.get('artworkUrl60')
    if artwork_url:
        artwork_path = os.path.join(directory, '.album_artwork.jpg')
        if download_artwork(artwork_url, artwork_path):
            logger.info(f"Artwork saved to {artwork_path}")
        else:
            artwork_path = None
    
    # Create a mapping of track numbers to track data
    track_map = {track.get('trackNumber'): track for track in tracks}
    
    # Update each audio file
    updated_count = 0
    for track_number, filename, file_path in audio_files:
        if track_number not in track_map:
            logger.warning(f"No iTunes data found for track {track_number}: {filename}")
            continue
        
        track_data = track_map[track_number]
        
        if update_file_metadata(file_path, track_data, album_info, artwork_path):
            updated_count += 1
        else:
            logger.warning(f"Failed to update: {filename}")
    
    # Clean up temporary artwork file
    if artwork_path and os.path.exists(artwork_path):
        try:
            os.remove(artwork_path)
        except Exception as e:
            logger.warning(f"Failed to remove temporary artwork file: {e}")
    
    logger.info(f"Successfully updated {updated_count}/{len(audio_files)} files")
    return updated_count > 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Update audio file metadata with album information from iTunes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using album ID
  python update_album.py /path/to/songs 1643207110

  # Using iTunes URL
  python update_album.py /path/to/songs https://music.apple.com/us/album/juliet-original-broadway-cast-recording/1643207110
        """
    )
    
    parser.add_argument(
        'directory',
        help='Directory containing audio files to update'
    )
    
    parser.add_argument(
        'album_id',
        help='iTunes album ID or URL ending with the ID'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Validate directory
    if not os.path.isdir(args.directory):
        logger.error(f"Directory not found: {args.directory}")
        sys.exit(1)
    
    # Process album
    success = process_album(args.directory, args.album_id)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
