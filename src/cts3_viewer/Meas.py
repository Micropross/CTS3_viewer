from pathlib import Path
from enum import Enum, auto, unique
from abc import ABC, abstractmethod
from plotly.graph_objs._figure import Figure  # type: ignore


@unique
class MeasUnit(Enum):
    """Measurements unit"""
    Degree = auto()
    Volt = auto()
    Dimensionless = auto()
    dBc = auto()

    def get_axis_label(self) -> str:
        """Gets vertical axis label

        Returns
        -------
        str
            Axis label
        """
        if self == MeasUnit.Degree:
            return 'Phase (°)'
        if self == MeasUnit.Volt:
            return 'Voltage (V)'
        if self == MeasUnit.dBc:
            return 'Power (dBc)'
        return 'Voltage'

    def get_label(self) -> str:
        """Gets Unit label

        Returns
        -------
        str
            Unit label
        """
        if self == MeasUnit.Degree:
            return '°'
        if self == MeasUnit.Volt:
            return 'V'
        if self == MeasUnit.dBc:
            return 'dBc'
        return ''


@unique
class BaseUnit(Enum):
    """Base measurements unit"""
    Time = auto()
    Frequency = auto()
    Dimensionless = auto()

    def get_axis_label(self) -> str:
        """Gets horizontal axis label

        Returns
        -------
        str
            Axis label
        """
        if self == BaseUnit.Time:
            return 'Time (s)'
        if self == BaseUnit.Dimensionless:
            return 'Samples'
        return 'Frequency (Hz)'

    def get_label(self) -> str:
        """Gets Unit label

        Returns
        -------
        str
            Unit label
        """
        if self == BaseUnit.Time:
            return 's'
        if self == BaseUnit.Dimensionless:
            return ''
        return 'Hz'


@unique
class MeasType(Enum):
    """Measurements type"""
    Modulated = auto()
    Demodulated = auto()
    Phase = auto()
    Vdc = auto()
    Power = auto()


class Meas(ABC):
    """Measurement abstract class

    Attributes
    ----------
    file : str
        File path
    y_unit : MeasUnit
        Vertical axis unit
    x_unit : BaseUnit
        Horizontal axis unit
    type : MeasUnit
        Measurement type
    """

    def __init__(self, file_path: Path):
        """Inits Meas

        Parameters
        ----------
        file_path : Path
            File path
        """
        self.file = str(file_path)
        self.y_unit = MeasUnit.Dimensionless
        self.x_unit = BaseUnit.Time
        self.type = MeasType.Demodulated

    @abstractmethod
    def convert(self, html_file: Path) -> None:
        """Converts data to HTML

        Parameters
        ----------
        html_file : Path
            HTML output file
        """
        ...

    @abstractmethod
    def fft(self, html_file: Path) -> None:
        """Performs FFT and converts it to HTML

        Parameters
        ----------
        html_file : Path
            HTML output file
        """
        ...

    def _plot(self, fig: Figure,  # type: ignore[no-any-unimported]
              html_file: Path) -> None:
        """Configures and saves plot to HTML file

        Parameters
        ----------
        fig : Figure
            Plotly figure
        html_file : Path
            HTML output file
        """
        fig.update_layout(title=self.file)
        fig.update_xaxes(title_text=self.x_unit.get_axis_label())
        fig.update_yaxes(title_text=self.y_unit.get_axis_label())
        fig.update_layout(hovermode='x')
        configuration = {'modeBarButtonsToAdd': ['drawline',
                                                 'drawrect',
                                                 'drawopenpath'],
                         'displaylogo': False}
        fig.write_html(html_file,
                       config=configuration,
                       auto_play=False)
