# -*- coding: utf-8 -*-
from pathlib import Path
import os
import sys


def getLog(APP_NAME: str, name: str) -> Path:
    logdir = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state') / Path(APP_NAME))
    os.makedirs(logdir, exist_ok=True)
    return logdir / Path(name)


def resource_path(path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, path)
    return os.path.join(os.path.abspath('.'), path)
