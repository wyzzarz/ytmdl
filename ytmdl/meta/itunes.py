"""
Handle extracting metadata from iTunes
"""

from ytmdl.stringutils import (
    get_similar_match
)

import itunespy

from typing import Dict
from ytmdl import defaults
from simber import Logger

logger = Logger('itunes')

class ItunesSong:
    """
    Class to store data about the songs fetched from
    iTunes.
    """

    def __init__(self, song) -> None:
        self.provider = "itunes"
        self.track_name = song.track_name
        self.release_date = song.release_date
        self.artist_name = song.artist_name
        self.collection_name = song.collection_name
        self.primary_genre_name = song.primary_genre_name
        self.track_number = song.track_number
        self.track_count = song.track_count
        self.disc_number = song.disc_number
        self.disc_count = song.disc_count
        self.artwork_url_100 = song.artwork_url_100
        self.track_time = song.track_time_millis
 

def search_track(song_name: str):
    """
    Lookup the metadata by using the ID on iTunes
    """
    country = defaults.DEFAULT.ITUNES_COUNTRY
    SONG_INFO = itunespy.search_track(song_name, country=country)
    return [ItunesSong(SONG_INFO)]


def lookup_track(ID: str):
    """
    Lookup the track using the ID on iTunes.
    """
    country = defaults.DEFAULT.ITUNES_COUNTRY
    SONG_INFO = itunespy.lookup_track(int(ID), country=country)

    # Only keep track results
    SONG_INFO = [ItunesSong(i) for i in SONG_INFO if i.type == 'track']
    return SONG_INFO

def lookup_tracks_for_album(ID, args):
    """
    Lookup tracks using the album on iTunes.
    """
    country = defaults.DEFAULT.ITUNES_COUNTRY

    # Load album info
    if hasattr(args, 'album_info') and hasattr(args, 'track_names'):
        ALBUM_INFO = args.album_info
        TRACK_NAMES = args.track_names
    else:
        # Get album and track info from itunes
        ALBUM_INFO = itunespy.lookup(int(ID), None, None, country, 'music', itunespy.entities['song'], None, 100)

        # Only keep track results
        ALBUM_INFO = [i for i in ALBUM_INFO if i.type == 'track']

        # Cache album info for future lookup
        args.album_info = ALBUM_INFO

        # Cache track names for future lookup
        TRACK_NAMES = [track.track_name for track in ALBUM_INFO]
        args.track_names = TRACK_NAMES
    
    return ALBUM_INFO, TRACK_NAMES


def lookup_from_itunes_album(ID, SONG_NAME, args):
    """
    Lookup the track using the album on iTunes.
    """
    country = defaults.DEFAULT.ITUNES_COUNTRY

    # Load album info
    ALBUM_INFO, TRACK_NAMES = lookup_tracks_for_album(ID, args)

    # Find best matching track
    _, matches_index = get_similar_match(TRACK_NAMES, SONG_NAME)
    if matches_index is not None:
        SONG_INFO = ItunesSong(ALBUM_INFO[matches_index])
        return [SONG_INFO]
    else:
        return None
