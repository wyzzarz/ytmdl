"""All directory handling definitions."""

import os
import glob
import shutil
from html import unescape
from re import sub

from ytmdl import defaults
from simber import Logger
from pathlib import Path

logger = Logger("Dir")


def __replace_special_characters(passed_name: str) -> str:
    """
    In the passed name, replace the special characters like
    / with a `-` so that it does not raise any errors
    related to the OS while moving the file
    """
    passed_name = sub(r'^\.', '-', passed_name)
    return sub(r'[\\/|&?;:#~!"<>$%^*{}[\]+=`´]+', '-', passed_name)


def get_abs_path(path_passed: str) -> str:
    """
    Get the absolute path by removing special path directives
    that `ytmdl` supports.
    """
    if "$" not in path_passed:
        return path_passed

    return path_passed.split("$")[0]


def cleanup(song_index, TRACK_INFO, index, datatype, remove_cached=True, filename_passed=None):
    """Move the song from temp to the song dir."""
    try:
        SONG = glob.glob(os.path.join(
            defaults.DEFAULT.SONG_TEMP_DIR,
            '*{}'.format(datatype)
        ))
        SONG = SONG[0]

        SONG_NAME = os.path.basename(SONG)

        # If the filename is passed, use that instead of the song
        #
        # NOTE that is the path is set to be a dynamic value by using
        # special characters like `$` though the config then that will
        # overwrite the filename_passed.
        if filename_passed is not None:
            SONG_NAME = filename_passed + ".{}".format(datatype)

        DIR, name = make_custom_dir(TRACK_INFO[index], song_index)
        logger.debug("directory being used: ", DIR)

        if name is not None:
            os.rename(SONG, name +  ".{}".format(datatype))
            SONG_NAME = name + '.{}'.format(datatype)
            SONG = SONG_NAME

        dest_filename = os.path.join(
            DIR, __replace_special_characters(SONG_NAME))

        logger.debug("Final name: ", dest_filename)
        shutil.move(SONG, dest_filename)

        if remove_cached:
            _delete_cached_songs(datatype)

        logger.info('Moved to {}...'.format(DIR))
        return True
    except Exception as e:
        logger.critical("Failed while moving with error: {}".format(e))
        return False


def _delete_cached_songs(ext='mp3'):
    """Delete cached songs"""
    # We need to call this after song is moved
    # because otherwise if there is an error along the way
    # next time a wrong song may be copied.
    SONGS_PATH = os.path.join(
        defaults.DEFAULT.SONG_TEMP_DIR,
        '*{}'.format(ext)
    )
    deleted = False
    for song in glob.glob(SONGS_PATH):
        deleted = True
        os.remove(song)
        logger.debug('Removed "{}" from cache'.format(os.path.basename(song)))
    if deleted:
        logger.debug('{}'.format('Deleted cached songs'))


def ret_proper_names(ordered_names):
    """Return a list with the names changed to itunespy supported ones.

    For eg: Artist to artist_name
    """
    info_dict = {'Artist': 'artist_name',
                 'Title': 'track_name',
                 'Album': 'collection_name',
                 'Genre': 'primary_genre_name',
                 'TrackNumber': 'track_number',
                 'ReleaseDate': 'release_date'
                 }

    logger.debug(ordered_names)
    logger.debug(info_dict)

    new_names = []
    for name in ordered_names:
        new_names.append(info_dict.get(name))

    return new_names


def seperate_kw(uns_kw):
    """Separate the keywords and return a list."""
    sep_kw = []

    # Check if -> is present in the name
    if '->' not in uns_kw:
        sep_kw.append(uns_kw)
    else:
        while '->' in uns_kw:
            pos = uns_kw.find("->")
            sep_kw.append(uns_kw[:pos])
            uns_kw = uns_kw[pos + 2:]

        sep_kw.append(uns_kw)
    return sep_kw


def make_custom_dir(TRACK_INFO, song_index):
    """Update SONG_DIR by adding song metadata to it.
    
    The DIR is probably in the format of
    .../$keyword/$keyword/[$keyword]
    """
    DIR = defaults.DEFAULT.SONG_DIR
    logger.debug("Directory being used: {}".format(DIR))

    logger.debug(TRACK_INFO)

    # expand DIR to get rid of any ~ or . and then split into parts
    DIR = os.path.expanduser(DIR)
    DIR = os.path.expandvars(DIR)

    # Apply keywords to DIR
    kw = {'Artist': 'artist_name',
    'Title': 'track_name',
    'Album': 'collection_name',
    'Genre': 'primary_genre_name',
    'TrackNumber': 'track_number',
    'ReleaseDate': 'release_date',
    'TrackIndex': 'track_index'
    }
    for key, word in kw.items():
        value = str(getattr(TRACK_INFO, word, "Unknown"))
        logger.debug("Checking {} with {}".format(key, word))
        if key == 'TrackIndex':
            logger.debug("Substituting {} with {}".format(value, song_index + 1))
            value = str(song_index + 1)
        if value.isdigit():
            value = value.zfill(2)
        DIR = DIR.replace("${}".format(key), __replace_special_characters(value))

    # Get last element if it is in the format of [...]
    path = Path(DIR)
    parts = [part for part in path.parts if part]  # filter out empty parts
    last_element = None
    if parts[-1].startswith('[') and parts[-1].endswith(']'):
        last_element = parts[-1][1:-1]  # remove the brackets
        parts = parts[:-1]  # remove the last part from the list
    base_DIR = os.path.join(*parts)
    logger.debug("New directory being used: {}".format(base_DIR))

    # create base_DIR if it doesn't exist including missing parents
    os.makedirs(base_DIR, exist_ok=True)

    return (base_DIR, last_element)


def dry_cleanup(current_path, passed_name, filename_passed=None):
    """
    Move the song from the current path to the
    song dir and change the name to the passed_name.

    This is only for when the meta-skip option is passed,
    in which case the song needs to be moved from the cache
    to the user directory.
    """
    try:
        extension = os.path.basename(current_path).split(".")[-1]
        logger.debug("ext: {}".format(extension))

        # If the filename is passed from the CLI, we will use that
        # instead of the passed name.
        if filename_passed is not None:
            passed_name = filename_passed

        new_basename = "{}.{}".format(passed_name, extension)
        DEST = defaults.DEFAULT.SONG_DIR

        # NOTE: If the DEST is a dynamic directory, then we cannot
        # do a dry cleanup. So we'll have to use the base directory
        # instead.
        if "$" in DEST:
            logger.debug(DEST)

            # pylama:ignore=E501
            logger.warning(
                "Destination is a dynamic directory but this is a dry cleanup. Don't pass `--skip-meta` if you don't want this!")

            # Use the base directory
            DEST = DEST[:DEST.find("$")]

            logger.debug(f"Using {DEST} as destination instead")

        logger.debug("Moving to: {}".format(DEST))

        # Create the destination file name
        dest_filename = os.path.join(
            DEST, __replace_special_characters(new_basename))

        shutil.move(current_path, dest_filename)

        logger.info('Moved to {}...'.format(DEST))
        return True
    except Exception as e:
        logger.error("{}".format(e))
        return False
