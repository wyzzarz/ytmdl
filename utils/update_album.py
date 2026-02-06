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

from ytmdl.meta.itunes import ItunesSong, lookup_tracks_for_album
from ytmdl.stringutils import get_similar_match
from ytmdl.song import set_MP3_data, set_M4A_data

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


def fetch_album_data(album_id: str, args) -> List[ItunesSong]:
    """Fetch album data from iTunes API."""
    try:
        params = {
            'id': album_id,
            'entity': 'song'
        }
        
        logger.info(f"Fetching album data for ID: {album_id}")
        tracks, track_names = lookup_tracks_for_album(album_id, args)
        
        if len(tracks) == 0:
            logger.error(f"Album ID {album_id} not found on iTunes")
            return None, None
        
        return tracks, track_names
    except Exception as e:
        logger.error(f"Unexpected error fetching album data: {e}")
        return None, None


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
        List of tuples: (track_number, track_name, filename, full_path)
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
            match = re.match(r'^(\d+)\s*-\s*(.+)', filename)
            if not match:
                logger.warning(f"Skipping file without track number prefix: {filename}")
                continue
            
            track_number = int(match.group(1))
            track_name = match.group(2)
            files.append((track_number, track_name, filename, file_path))
    
    except Exception as e:
        logger.error(f"Error scanning directory: {e}")
        return []
    
    return sorted(files, key=lambda x: x[0])


def match_metadata_with_audio_files(tracks, track_names, audio_files) -> List[Tuple[int, str, str, ItunesSong]]:
    """Match track names with audio files."""
    new_audio_files = []

    for track_number, track_name, filename, file_path in audio_files:
        _, matches_index = get_similar_match(track_names, track_name)
        track = tracks[matches_index] if matches_index is not None else None
        new_audio_files.append((track_number, track_name, file_path, track))

    return new_audio_files


def update_file_metadata(file_path: str, track: ItunesSong) -> bool:
    """Update audio file metadata based on file type."""
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    
    if ext == '.mp3':
        set_MP3_data(track, file_path)
        return True
    elif ext == '.m4a':
        set_M4A_data(track, file_path)
        return True
    else:
        return False


def process_album(directory: str, album_id: str, args) -> bool:
    """Process all audio files in directory and update with album metadata."""
    # Extract album ID from URL or direct ID
    album_id = extract_album_id(album_id)
    if not album_id:
        logger.error("Invalid album ID or URL provided")
        return False
    
    # Fetch album data
    tracks, track_names = fetch_album_data(album_id, args)
    if not tracks:
        logger.error("Failed to fetch album data")
        return False
    
    track0 = tracks[0]
    logger.info(f"Found album: {track0.collection_name}")
    logger.info(f"Artist: {track0.artist_name}")
    logger.info(f"Total tracks: {len(tracks)}")

    # Find audio files in directory
    audio_files = find_audio_files(directory)
    if not audio_files:
        logger.error(f"No audio files found in {directory}")
        return False
    
    logger.info(f"Found {len(audio_files)} audio files to process")
    
    # Match metadata to audio files
    audio_files = match_metadata_with_audio_files(tracks, track_names, audio_files)

    # Update each audio file
    updated_count = 0
    for track_number, filename, file_path, track in audio_files:
        if update_file_metadata(file_path, track):
            updated_count += 1
        else:
            logger.warning(f"Failed to update: {filename}")
    
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
    
    if args.verbose:
        logger.update_level('DEBUG')

    # Validate directory
    if not os.path.isdir(args.directory):
        logger.error(f"Directory not found: {args.directory}")
        sys.exit(1)
    
    # Process album
    success = process_album(args.directory, args.album_id, args)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
