from pathlib import Path
from enum import Enum, auto, unique
from re import compile, search
from plotly.graph_objs._figure import Figure  # type: ignore
from plotly.graph_objs._scatter import Scatter  # type: ignore
from .Meas import Meas, MeasType, MeasUnit
from numpy import float64, dtype, fromfile
from numpy.typing import NDArray


@unique
class _Direction(Enum):
    """Graph cursor direction"""
    Horizontal = auto()
    Vertical = auto()


class _Cursor:
    """
    Graph cursor

    Attributes:
        direction: Cursor direction
        value: Cursor value
    """

    def __init__(self, direction: _Direction, value: float):
        """
        Inits Cursor

        Args:
            direction: Cursor direction
            value: Cursor value
        """
        self.direction = direction
        self.value = value


def _load_signal(
    file_path: Path
) -> tuple[NDArray[float64], NDArray[float64], list[_Cursor]]:
    """
    Loads advanced measurements signal from file

    Args:
        file_path: File to load

    Returns:
        Tuple made of:
        - Horizontal coordinates array
        - Vertical coordinates array
        - List of cursors
    """
    cursors: list[_Cursor] = []
    with file_path.open('rb') as f:
        line = ''
        pattern = compile(r'#(\D)\d=(.*)')
        try:
            while not line.startswith('##B1#'):
                line = f.readline().decode('ascii')
                match = search(pattern, line)
                if match:
                    if match.group(1) == 'Y':
                        cursors.append(
                            _Cursor(_Direction.Horizontal,
                                    float(match.group(2))))
                    elif match.group(1) == 'X':
                        cursors.append(
                            _Cursor(_Direction.Vertical,
                                    float(match.group(2))))
        except Exception as e:
            raise Exception('Unsupported advanced measurements file format '
                            f'({e})')
        meas_offset = f.tell()

    dt = dtype([('x', float64), ('y', float64)])
    data = fromfile(file_path, dt, offset=meas_offset)
    return (data['x'], data['y'], cursors)


class AdvancedMeas(Meas):
    """
    Advanced measurements

    Attributes:
        file: File path
        y_unit: Vertical axis unit
        x_unit: Horizontal axis unit
        type: Measurement type
        x: Horizontal coordinates array
        y: Vertical coordinates array
        cursors: List of cursors
    """

    def __init__(self, file_path: Path):
        """
        Inits AdvancedMeas

        Args:
            file_path: Advanced measurements file path
        """
        super().__init__(file_path)
        self.y_unit = MeasUnit.Volt
        self.type = MeasType.Demodulated
        (self.x, self.y, self.cursors) = _load_signal(file_path)

    def convert(self, html_file: Path) -> None:
        """
        Converts advanced measurements data to HTML

        Args:
            html_file: HTML output file
        """
        fig = Figure()
        fig.add_trace(Scatter(x=self.x, y=self.y, mode='lines'))
        fig.data[0].hovertemplate = (
            f'date=%{{x}}{self.x_unit.get_label()}<br>'
            f'value=%{{y}}{self.y_unit.get_label()}<extra></extra>')
        for cursor in self.cursors:
            if cursor.direction == _Direction.Horizontal:
                fig.add_hline(
                    y=cursor.value,
                    line_dash='dash',
                    annotation_text=f'{cursor.value}{self.y_unit.get_label()}')
            else:
                fig.add_vline(
                    x=cursor.value,
                    line_dash='dash',
                    annotation_text=f'{cursor.value}{self.x_unit.get_label()}')
        fig.add_hline(0)
        self._plot(fig, html_file)

    def fft(self, _: Path) -> None:
        """
        Performs FFT on advanced measurements and converts it to HTML

        Args:
            html_file: HTML output file
        """
        raise Exception('FFT cannot be performed on demodulated signal')
