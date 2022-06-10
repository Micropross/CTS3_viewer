from pathlib import Path
from os import SEEK_CUR
from plotly.graph_objs._figure import Figure  # type: ignore
from plotly.graph_objs._scatter import Scatter  # type: ignore
from .Meas import Meas, BaseUnit, MeasUnit, MeasType
from ctypes import c_uint64, c_uint32, c_int32, c_uint16
from ctypes import c_double, c_float, c_uint8, c_char
from ctypes import sizeof, Structure
from typing import cast, Union
from numpy import linspace, fromfile, log10, absolute
from numpy import dtype, int16, float64
from numpy.fft import rfft, rfftfreq
try:
    from numpy.typing import NDArray
except ImportError:
    NDArray = list  # type: ignore


class _EventHeader(Structure):
    """Spy file events header"""
    _pack_ = 1
    _fields_ = [('id', c_uint32),
                ('format', c_uint16),
                ('version', c_uint16),
                ('device_id', c_char * 32),
                ('device_version', c_char * 32),
                ('time_base', c_uint16),
                ('rfu1', c_uint8 * 4),
                ('type', c_uint8),
                ('rfu2', c_uint8),
                ('events_number', c_uint32),
                ('rfu3', c_uint8 * 2),
                ('mask', c_uint32),
                ('rfu4', c_uint8 * 38)]


class _BurstHeader(Structure):
    """Spy file analog measurements header"""
    _pack_ = 1
    _fields_ = [('id', c_uint32),
                ('format', c_uint16),
                ('version', c_uint16),
                ('device_id', c_char * 16),
                ('probe_id', c_char * 16),
                ('device_version', c_char * 32),
                ('time_base', c_uint16),
                ('normalization', c_float),
                ('type', c_uint8),
                ('source', c_uint8),
                ('events_number', c_uint32),
                ('rfu', c_uint8 * 6),
                ('range', c_uint16),
                ('sampling', c_uint32),
                ('delay', c_int32),
                ('date', c_uint64),
                ('impedance', c_uint32),
                ('offset', c_double),
                ('slope', c_double)]


def _load_signal(file_path: Path, verbose: bool) -> \
        tuple[NDArray[float64],
              Union[NDArray[float64], NDArray[int16]],
              MeasUnit, MeasType, float]:
    """Loads spy measurements signal from file

    Parameters
    ----------
    file_path : Path
        File to load
    verbose : bool
        Verbose mode

    Returns
    -------
    tuple(ndarray, ndarray, MeasUnit, MeasType, float)
        Horizontal coordinates array
        Vertical coordinates array
        Vertical axis unit
        Measurement type
        Sampling rate
    """
    with file_path.open('rb') as f:
        evt_header = _EventHeader.from_buffer_copy(
            f.read(sizeof(_EventHeader)))
        if verbose:
            print(f'Protocol analyzer file version: {evt_header.version}')
        if evt_header.version < 2:
            raise Exception('Unsupported protocol analyzer file version '
                            f'({evt_header.version})')
        evt_number = cast(int, evt_header.events_number)
        f.seek(evt_number * sizeof(c_uint64), SEEK_CUR)
        burst_header = _BurstHeader.from_buffer_copy(
            f.read(sizeof(_BurstHeader)))
        if burst_header.type != 5:
            raise Exception('No analog measurements found')
        if verbose:
            print(f'Protocol analyzer analog version: {burst_header.version}')
        if burst_header.version < 3:
            raise Exception('Unsupported protocol analyzer analog version '
                            f'({burst_header.version})')
        data_length = cast(int, burst_header.events_number)
        if not data_length:
            raise Exception('No analog measurements found')
        if verbose:
            print(f'Device: {burst_header.device_id.decode("ascii")}')
            fw = cast(str, burst_header.device_version.decode('ascii')).split()
            if len(fw) > 2:
                print(f'Firmware: {fw[2]}')
                if fw[0].lower() == 'fb':
                    print(f'DAQ: {fw[1]}')
                else:
                    print(f'FPGA: {fw[1]}')
            probe = cast(str, burst_header.probe_id.decode('ascii'))
            if len(probe):
                print(f'Active probe: {probe}')
        start_date = cast(int, burst_header.date) / 1e9
        sampling = cast(int, burst_header.sampling) * 1e3
        meas_offset = f.tell()

    x = linspace(start_date, start_date + data_length / sampling,
                 data_length, endpoint=True, dtype=float)
    data = fromfile(file_path, dtype('>i2'), data_length, offset=meas_offset)

    SOURCE_TXRX = 1
    SOURCE_ANALOG_IN = 2
    SOURCE_DAQ_CH1 = 3
    SOURCE_DAQ_CH2 = 4
    SOURCE_VDC = 5
    SOURCE_PHASE = 6
    demodulated = cast(float, burst_header.normalization) != 0
    if burst_header.source == SOURCE_TXRX:
        if verbose:
            print('RF signal measurement on TX/RX (uncalibrated)')
        return (x,
                data,
                MeasUnit.Dimensionless,
                MeasType.Demodulated if demodulated else MeasType.Modulated,
                sampling)
    if burst_header.source == SOURCE_PHASE:
        if verbose:
            print('Phase measurement')
        return (x,
                data / 10.0,
                MeasUnit.Degree,
                MeasType.Phase,
                sampling)
    if burst_header.source == SOURCE_VDC:
        if verbose:
            print('Vdc measurement')
        return (x,
                data / 1e3,
                MeasUnit.Volt,
                MeasType.Vdc,
                sampling)
    if verbose:
        if burst_header.source == SOURCE_ANALOG_IN:
            print('RF signal measurement on ANALOG IN')
        elif burst_header.source == SOURCE_DAQ_CH1:
            print('RF signal measurement on DAQ CH1')
        elif burst_header.source == SOURCE_DAQ_CH2:
            print('RF signal measurement on DAQ CH2')
        impedance = cast(int, burst_header.impedance)
        if impedance >= 1e6:
            print(f'Input impedance: {int(impedance / 1e6)} MΩ')
        else:
            print(f'Input impedance: {impedance} Ω')
    return (x,
            data / 1e3,
            MeasUnit.Volt,
            MeasType.Demodulated if demodulated else MeasType.Modulated,
            sampling)


class SpyMeas(Meas):
    """Spy measurements

    Attributes
    ----------
    x : ndarray
        Horizontal coordinates array
    y : ndarray
        Vertical coordinates array
    sampling : float
        Sampling rate
    """

    def __init__(self, file_path: Path, verbose: bool):
        """Inits SpyMeas

        Parameters
        ----------
        file_path : Path
            Spy measurements file path
        verbose : bool
            Verbose mode
        """
        super().__init__(file_path)
        (self.x, self.y, self.y_unit,
            self.type, self.sampling) = _load_signal(file_path, verbose)

    def convert(self, html_file: Path) -> None:
        """Converts spy measurements data to HTML

        Parameters
        ----------
        html_file : Path
            HTML output file
        """
        fig = Figure()
        fig.add_trace(Scatter(x=self.x, y=self.y, mode='lines'))
        fig.data[0].hovertemplate = \
            f'date=%{{x}}{self.x_unit.get_label()}<br>' \
            f'value=%{{y}}{self.y_unit.get_label()}<extra></extra>'
        fig.add_hline(y=0)
        self._plot(fig, html_file)

    def fft(self, html_file: Path) -> None:
        """Performs FFT on spy measurements and converts it to HTML

        Parameters
        ----------
        html_file : Path
            HTML output file
        """
        if self.type == MeasType.Phase:
            raise Exception('FFT cannot be performed on phase measurement')
        if self.type == MeasType.Vdc:
            raise Exception('FFT cannot be performed on Vdc measurement')
        if self.type == MeasType.Demodulated:
            raise Exception('FFT cannot be performed on demodulated signal')
        self.file += ' (FFT)'
        self.type = MeasType.Power
        self.x_unit = BaseUnit.Frequency
        self.y_unit = MeasUnit.dBc
        signal = absolute(rfft(self.y))
        normalized_fft = 20 * log10(signal / signal.max())
        freq = rfftfreq(self.x.size, 1 / self.sampling)
        fig = Figure()
        fig.add_trace(Scatter(x=freq, y=normalized_fft, mode='lines'))
        fig.data[0].hovertemplate = \
            f'frequency=%{{x}}{self.x_unit.get_label()}<br>' \
            f'value=%{{y}}{self.y_unit.get_label()}<extra></extra>'
        x_max = freq[signal.argmax()]
        fig.add_vline(x=x_max, line_dash='dash',
                      annotation_text=f'{x_max}{self.x_unit.get_label()}')
        self._plot(fig, html_file)
