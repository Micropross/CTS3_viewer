from pathlib import Path
from ctypes import c_uint64, c_uint32, c_int32, c_uint16, c_int16
from ctypes import c_double, c_float, c_uint8, c_char
from ctypes import sizeof, Structure
from plotly.graph_objs._figure import Figure  # type: ignore
from plotly.graph_objs._scatter import Scatter  # type: ignore
from .Meas import Meas, BaseUnit, MeasUnit, MeasType
from datetime import datetime
from typing import cast
from math import sqrt
from numpy import linspace, fromfile, log10, absolute
from numpy import vectorize, dtype, int16, uint32, float64
from numpy.fft import rfft, rfftfreq
try:
    from numpy.typing import NDArray
except ImportError:
    NDArray = list  # type: ignore


class _ChannelConfig(Structure):
    """Channel configuration"""
    _pack_ = 1
    _fields_ = [('config', c_uint32),
                ('range', c_uint32),
                ('impedance', c_uint32),
                ('term', c_uint32),
                ('slope', c_double),
                ('offset', c_double),
                ('rms_noise', c_double),
                ('demod_noise', c_double)]


class _Header(Structure):
    """Acquisition file header"""
    _pack_ = 1
    _fields_ = [('id', c_uint32),
                ('version', c_uint16),
                ('header_size', c_uint16),
                ('measurements_count', c_uint32),
                ('timestamp', c_uint32),
                ('device_id', c_char * 32),
                ('device_version', c_char * 32),
                ('bits_per_sample', c_uint8),
                ('channels', c_uint8),
                ('source', c_uint8),
                ('channel_size', c_uint8),
                ('sampling', c_uint32),
                ('trig_date', c_uint64),
                ('ch1', _ChannelConfig),
                ('ch2', _ChannelConfig),
                ('rfu1', c_uint8 * 96),
                ('normalization', c_float),
                ('demod_delay', c_int32),
                ('probe_id_ch1', c_char * 16),
                ('probe_id_ch2', c_char * 16),
                ('delay', c_int32),
                ('rfu2', c_uint8 * 52)]


def _linear_calib(raw: NDArray[int16], offset: float,
                  slope: float) -> NDArray[float64]:
    """Performs linear calibration

    Parameters
    ----------
    raw : ndarray
        Values to calibrate
    offset : float
        Calibration offset
    slope : float
        Calibration slope

    Returns
    -------
    ndarray
        Calibrated values
    """
    return slope * (raw + offset)


def _load_signals(file_path: Path, verbose: bool) -> \
        tuple[NDArray[float64], list[NDArray[float64]],
              MeasUnit, MeasType, float]:
    """Loads DAQ signals from file

    Parameters
    ----------
    file_path : Path
        File to load
    verbose : bool
        Verbose mode

    Returns
    -------
    tuple(ndarray, list(ndarray), MeasUnit, MeasType, float)
        Horizontal coordinates array
        List of vertical coordinates arrays
        Vertical axis unit
        Measurement type
        Sampling rate
    """
    with file_path.open('rb') as f:
        header = _Header.from_buffer_copy(f.read(sizeof(_Header)))
        if verbose:
            print(f'Acquisition file version: {header.version}')
        if header.version < 2:
            raise Exception('Unsupported acquisition file version '
                            f'({header.version})')
        if verbose:
            print(f'Date: {datetime.fromtimestamp(header.timestamp)}')
            print(f'Device: {header.device_id.decode("ascii")}')
            fw = cast(str, header.device_version.decode('ascii')).split()
            if len(fw) > 2:
                print(f'Firmware: {fw[2]}')
                if fw[0].lower() == 'fb':
                    print(f'DAQ: {fw[1]}')
                else:
                    print(f'FPGA: {fw[1]}')
        data_width = int(header.bits_per_sample / 8)
        data_length = cast(int, header.measurements_count)
        start_date = 0.0
        if header.version > 2:
            start_date = cast(int, header.delay) / 1e9
        sampling = float(cast(int, header.sampling))
        channels = cast(int, header.channels)

    if sampling == 0:
        x = linspace(1, data_length,
                     data_length, endpoint=True, dtype=float)
    else:
        x = linspace(start_date, start_date + data_length / sampling,
                     data_length, endpoint=True, dtype=float)

    if data_width == sizeof(c_int16):
        SOURCE_TXRX = 1
        SOURCE_ANALOG_IN = 2
        SOURCE_DAQ_CH1 = 3
        SOURCE_DAQ_CH2 = 4
        SOURCE_VDC = 5
        SOURCE_PHASE = 6
        if channels == 1:
            y = fromfile(file_path, int16, data_length,
                         offset=sizeof(_Header))
            if header.source == SOURCE_PHASE:
                # Phase
                if verbose:
                    print('Phase measurement')
                calib = vectorize(lambda raw:
                                  float('nan') if raw > 8192
                                  else 180.0 * raw / 8192.0)
                return (x,
                        [calib(y)],
                        MeasUnit.Degree,
                        MeasType.Phase,
                        sampling)
            elif header.source == SOURCE_VDC:
                # Vdc
                if verbose:
                    print('Vdc measurement')
                offset = cast(float, header.ch1.offset)
                slope = cast(float, header.ch1.slope)
                quadratic = cast(float, header.ch1.rms_noise)
                cubic = cast(float, header.ch1.demod_noise)
                calib = vectorize(lambda raw:
                                  (offset + slope * raw +
                                   quadratic * raw ** 2 +
                                   cubic * raw ** 3) / 1e3)
                return (x,
                        [calib(y)],
                        MeasUnit.Volt,
                        MeasType.Vdc,
                        sampling)
            else:
                # Modulated signal
                if header.ch1.config & 1:
                    offset = cast(float, header.ch1.offset)
                    slope = cast(float, header.ch1.slope)
                    probe = cast(str, header.probe_id_ch1.decode('ascii'))
                else:
                    offset = cast(float, header.ch2.offset)
                    slope = cast(float, header.ch2.slope)
                    probe = cast(str, header.probe_id_ch2.decode('ascii'))
                if header.source == SOURCE_TXRX:
                    if verbose:
                        print('RF signal measurement on TX/RX (uncalibrated)')
                    y_unit = MeasUnit.Dimensionless
                else:
                    if verbose:
                        if header.source == SOURCE_ANALOG_IN:
                            print('RF signal measurement on ANALOG IN')
                        elif header.source == SOURCE_DAQ_CH1:
                            print('RF signal measurement on DAQ CH1')
                        elif header.source == SOURCE_DAQ_CH2:
                            print('RF signal measurement on DAQ CH2')
                        else:
                            if header.ch1.config & 1:
                                print('RF signal measurement on DAQ CH1')
                            else:
                                print('RF signal measurement on DAQ CH2')
                        if len(probe):
                            print(f'Active probe: {probe}')
                    y_unit = MeasUnit.Volt
                    slope /= 1e3
                return (x,
                        [_linear_calib(y, offset, slope)],
                        y_unit,
                        MeasType.Modulated,
                        sampling)

        else:
            # Dual channel
            if verbose:
                print('RF signal dual measurement on DAQ')
                probe = cast(str, header.probe_id_ch1.decode('ascii'))
                if len(probe):
                    print(f'Active probe on CH1: {probe}')
                probe = cast(str, header.probe_id_ch2.decode('ascii'))
                if len(probe):
                    print(f'Active probe on CH2: {probe}')
            dt = dtype([('ch1', int16), ('ch2', int16)])
            data = fromfile(file_path, dt, data_length,
                            offset=sizeof(_Header))
            offset_1 = cast(float, header.ch1.offset)
            slope_1 = cast(float, header.ch1.slope) / 1e3
            offset_2 = cast(float, header.ch2.offset)
            slope_2 = cast(float, header.ch2.slope) / 1e3
            return (x,
                    [_linear_calib(data['ch1'], offset_1, slope_1),
                     _linear_calib(data['ch2'], offset_2, slope_2)],
                    MeasUnit.Volt,
                    MeasType.Modulated,
                    sampling)

    elif data_width == sizeof(c_uint32):
        y = fromfile(file_path, uint32, data_length, offset=sizeof(_Header))

        # Demodulated signal
        if verbose:
            print('RF demodulated signal measurement')
        if header.ch1.config & 1:
            slope = cast(float, header.ch1.slope)
            noise = cast(float, header.ch1.demod_noise)
        else:
            slope = cast(float, header.ch2.slope)
            noise = cast(float, header.ch2.demod_noise)
        slope *= cast(float, header.normalization) / 1e3
        calib = vectorize(lambda raw:
                          slope * sqrt(raw - noise) if raw > noise
                          else 0.0)
        return (x,
                [calib(y)],
                MeasUnit.Volt,
                MeasType.Demodulated,
                sampling)

    else:
        raise Exception('Invalid acquisition file format')


class DaqMeas(Meas):
    """DAQ measurements

    Attributes
    ----------
    x : ndarray
        Horizontal coordinates array
    y : ndarray or list(ndarray)
        List of vertical coordinates arrays
    sampling : float
        Sampling rate
    """

    def __init__(self, file_path: Path, verbose: bool):
        """Inits DaqMeas

        Parameters
        ----------
        file_path : Path
            DAQ file path
        verbose : bool
            Verbose mode
        """
        super().__init__(file_path)
        (self.x, self.y, self.y_unit,
            self.type, self.sampling) = _load_signals(file_path, verbose)
        if self.sampling == 0:
            self.x_unit = BaseUnit.Dimensionless

    def convert(self, html_file: Path) -> None:
        """Converts DAQ data to HTML

        Parameters
        ----------
        html_file : Path
            HTML output file
        """
        fig = Figure()
        count = 0
        multichannel = len(self.y) > 1
        for line in self.y:
            fig.add_trace(Scatter(x=self.x, y=line, mode='lines'))
            if multichannel:
                fig.data[count].name = f'CH{count+1}'
                hover_header = f'CH{count+1}<br>'
            else:
                hover_header = ''
            fig.data[count].hovertemplate = \
                f'{hover_header}' \
                f'date=%{{x}}{self.x_unit.get_label()}<br>' \
                f'value=%{{y}}{self.y_unit.get_label()}<extra></extra>'
            count += 1
        fig.add_hline(y=0)
        self._plot(fig, html_file)

    def fft(self, html_file: Path) -> None:
        """Performs FFT on DAQ data and converts it to HTML

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
        if self.sampling == 0:
            raise Exception('FFT cannot be computed with external clock')
        self.file += ' (FFT)'
        self.type = MeasType.Power
        self.x_unit = BaseUnit.Frequency
        self.y_unit = MeasUnit.dBc
        fig = Figure()
        count = 0
        multichannel = len(self.y) > 1
        for line in self.y:
            signal = absolute(rfft(line))
            normalized_fft = 20 * log10(signal / signal.max())
            freq = rfftfreq(self.x.size, 1 / self.sampling)
            fig.add_trace(Scatter(x=freq, y=normalized_fft, mode='lines'))
            if multichannel:
                fig.data[count].name = f'CH{count+1}'
                hover_header = f'CH{count+1}<br>'
            else:
                hover_header = ''
            fig.data[count].hovertemplate = \
                f'{hover_header}' \
                f'frequency=%{{x}}{self.x_unit.get_label()}<br>' \
                f'value=%{{y}}{self.y_unit.get_label()}<extra></extra>'
            count += 1
            x_max = freq[signal.argmax()]
            fig.add_vline(x=x_max, line_dash='dash',
                          annotation_text=f'{x_max}{self.x_unit.get_label()}')
        self._plot(fig, html_file)
