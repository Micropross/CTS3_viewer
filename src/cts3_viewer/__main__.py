#!/usr/bin/python3
from sys import modules, path
from pathlib import Path

name = modules[__name__].__file__
if name:
    path.insert(0, str(Path(name).parent.joinpath('..')))

from cts3_viewer import main

main()
