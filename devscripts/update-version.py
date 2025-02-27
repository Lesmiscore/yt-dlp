#!/usr/bin/env python3

# Allow direct execution
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import contextlib
import subprocess
import sys
from datetime import datetime

from devscripts.utils import read_version, write_file


def get_new_version(revision):
    version = datetime.utcnow().strftime('%Y.%m.%d')

    if revision:
        assert revision.isdigit(), 'Revision must be a number'
    else:
        old_version = read_version().split('.')
        if version.split('.') == old_version[:3]:
            revision = str(int((old_version + [0])[3]) + 1)

    return f'{version}.{revision}' if revision else version


def get_git_head():
    with contextlib.suppress(Exception):
        sp = subprocess.Popen(['git', 'rev-parse', '--short', 'HEAD'], stdout=subprocess.PIPE)
        return sp.communicate()[0].decode().strip() or None


VERSION = get_new_version((sys.argv + [''])[1])
GIT_HEAD = get_git_head()

VERSION_FILE = f'''\
# Autogenerated by devscripts/update-version.py

__version__ = {VERSION!r}

RELEASE_GIT_HEAD = {GIT_HEAD!r}

VARIANT = None

UPDATE_HINT = None
'''

write_file('yt_dlp/version.py', VERSION_FILE)
write_file(os.getenv('GITHUB_OUTPUT'), f'ytdlp_version={VERSION}\n', 'a')
print(f'\nVersion = {VERSION}, Git HEAD = {GIT_HEAD}')
