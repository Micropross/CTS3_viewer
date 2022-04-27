#!/usr/bin/python3
import sys
from pathlib import Path

name = sys.modules[__name__].__file__
if name:
    path = str(Path(name).parent.joinpath('..'))
    sys.path.insert(0, path)

from cts3_viewer import main  # noqa: E402

main()
