#!/usr/bin/python3
from sys import exit
from pathlib import Path
from enum import auto, Enum, unique
from typing import Optional, cast
from .Meas import Meas
from .DaqMeas import DaqMeas
from .AdvancedMeas import AdvancedMeas
from .SpyMeas import SpyMeas
from webbrowser import open
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser

__version__ = '24.1.0'
__author__ = 'FIME'
__copyright__ = f'Copyright 20{__version__[:2]}, FIME'
__license__ = 'MIT'


@unique
class FileType(Enum):
    """Analog file type"""
    Unknown = auto()
    DaqFile = auto()
    SpyFile = auto()
    AdvancedFile = auto()


def _find_file_type(file_path: Path, verbose: bool) -> FileType:
    """
    Gets input file type

    Args:
        file_path: Acquisition file
        verbose: Verbose mode

    Returns:
        File type
    """
    with file_path.open('rb') as f:
        id = f.read(4)
        if id == b'MPDQ':
            if verbose:
                print(f"'{file_path}' detected as acquisition file")
            return FileType.DaqFile
        if id == b'MPCS':
            if verbose:
                print(f"'{file_path}' detected as protocol analyze file")
            return FileType.SpyFile
        if id.startswith(b'#'):
            if verbose:
                print(f"'{file_path}' detected as advanced measurement file")
            return FileType.AdvancedFile
    if verbose:
        print(f'Unknown identifier (0x{id.hex()})')
    return FileType.Unknown


def viewer(source: Path,
           force: bool = False,
           fft: bool = False,
           output: Optional[str] = None,
           silent: bool = False,
           verbose: bool = False) -> int:
    """
    CTS3 Waveform viewer

    Args:
        source: Analog source file
        force: Overwrite output file if exists
        fft: Compute signal FFT
        output: Output HTML file
        silent: Convert to HTML file without plotting the graph
        verbose: Increase verbosity

    Returns:
        Error code
    """
    try:
        if output is None:
            if fft:
                stem = source.stem
                html = source.with_suffix('.html').with_stem(f'{stem}_fft')
            else:
                html = source.with_suffix('.html')
        else:
            html = Path(output)
        if html.exists():
            if not force:
                raise Exception(f"'{html}' already exists")

        type = _find_file_type(source, verbose)
        data: Meas
        if type == FileType.DaqFile:
            data = DaqMeas(source, verbose)
        elif type == FileType.SpyFile:
            data = SpyMeas(source, verbose)
        elif type == FileType.AdvancedFile:
            data = AdvancedMeas(source)
        else:
            raise Exception(f"Unable to detect '{source}' type")

        if fft:
            data.fft(html)
        else:
            data.convert(html)
        if verbose:
            print(f"'{source}' converted to '{html}'")
        if not silent:
            open(html.resolve().as_uri())
        return 0

    except Exception as e:
        print(e)
        return 1


def main() -> None:
    """Runs CTS3 Waveform viewer"""
    parser = ArgumentParser(description='Analog waveform viewer for CTS3',
                            formatter_class=ArgumentDefaultsHelpFormatter,
                            prog='cts3-viewer')
    parser.add_argument('src', type=str, help='analog file location')
    parser.add_argument('-f',
                        '--force',
                        action='store_true',
                        help='overwrite output file if exists')
    parser.add_argument('--fft',
                        action='store_true',
                        help='compute signal FFT')
    parser.add_argument('-o',
                        '--output',
                        type=str,
                        help='select output HTML file')
    parser.add_argument('-s',
                        '--silent',
                        action='store_true',
                        help='convert to HTML file without plotting the graph')
    parser.add_argument('-v',
                        '--verbose',
                        action='store_true',
                        help='increase verbosity')
    parser.add_argument('--version',
                        action='version',
                        version=f'%(prog)s {__version__}',
                        help='show version information and exit')
    args = parser.parse_args()
    config = vars(args)
    exit(
        viewer(Path(cast(str, config['src']).strip('"')), config['force'],
               config['fft'], config['output'], config['silent'],
               config['verbose']))


if __name__ == '__main__':
    main()
