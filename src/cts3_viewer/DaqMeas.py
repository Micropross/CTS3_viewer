from pathlib import Path
from ctypes import (c_uint8, c_char, c_double, c_float, c_int16, c_int32,
                    c_uint16, c_uint32, c_uint64, Structure, sizeof)
from plotly.graph_objs._figure import Figure  # type: ignore
from plotly.graph_objs._scatter import Scatter  # type: ignore
from .Meas import BaseUnit, Meas, MeasType, MeasUnit
from datetime import datetime
from typing import cast
from math import sqrt
from numpy import (absolute, float64, int16, isnan, log10, uint32, dtype,
                   vectorize, concatenate, empty, frombuffer, full, linspace)
from numpy.fft import rfft, rfftfreq
from numpy.typing import NDArray


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
                ('demod_noise', c_double)]  # yapf: disable


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
                ('rfu2', c_uint8 * 52)]  # yapf: disable


class _Footer(Structure):
    """Acquisition file footer"""
    _pack_ = 1
    _fields_ = [('id', c_uint32),
                ('version', c_uint16),
                ('footer_size', c_uint16),
                ('metadata_size', c_uint16)]  # yapf: disable


def _load_signals(
    file_path: Path, verbose: bool
) -> tuple[NDArray[float64], list[NDArray[float64]], MeasUnit, MeasType, float,
           list[float]]:
    """
    Loads DAQ signals from file

    Args:
        file_path: File to load
        verbose: Verbose mode

    Returns:
        Tuple made of:
        - Horizontal coordinates array
        - List of vertical coordinates arrays
        - Vertical axis unit
        - Measurement type
        - Sampling rate
        - List of vertical lines
    """
    NAN_POINT = full(1, float('nan'), float64)
    with file_path.open('rb') as f:
        x = empty(0, float64)
        y1 = empty(0, float64)
        y2 = empty(0, float64)
        unit = MeasUnit.Volt
        type = MeasType.Modulated
        separators: list[float] = []
        sampling = 0.0
        start_date = 0.0

        while True:
            buffer = f.read(sizeof(_Header))
            if len(buffer) != sizeof(_Header):
                if len(buffer) > 0:
                    print('Unexpected end of file')
                break
            header = _Header.from_buffer_copy(buffer)
            if verbose:
                print(f'Acquisition file version: {header.version}')
            if header.version < 2:
                raise Exception(
                    f'Unsupported acquisition file version ({header.version})')
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
            if data_length == 0:
                break
            sampling = float(cast(int, header.sampling))
            if header.version > 2:
                if sampling == 0.0:
                    start_date += cast(int, header.delay)
                else:
                    start_date += cast(int, header.delay) / 1e9
            if len(y1) > 0:
                separators.append(start_date)
                y1 = concatenate((y1, NAN_POINT))
                if len(y2) > 0:
                    y2 = concatenate((y1, NAN_POINT))

            if sampling == 0.0:
                x = concatenate((x,
                                 linspace(1,
                                          data_length + 1,
                                          data_length + 1,
                                          endpoint=True,
                                          dtype=float64)))
                start_date += data_length + 2
                if header.version > 2:
                    start_date -= cast(int, header.delay)
            else:
                x = concatenate(
                    (x,
                     linspace(start_date,
                              start_date + (data_length + 1) / sampling,
                              data_length + 1,
                              endpoint=True,
                              dtype=float64)))
                start_date += (data_length + 2) / sampling
                if header.version > 2:
                    start_date -= cast(int, header.delay) / 1e9

            if data_width == sizeof(c_int16):
                SOURCE_TXRX = 1
                SOURCE_ANALOG_IN = 2
                SOURCE_DAQ_CH1 = 3
                SOURCE_DAQ_CH2 = 4
                SOURCE_VDC = 5
                SOURCE_PHASE = 6
                channels = cast(int, header.channels)
                if channels == 1:
                    buffer = f.read(data_length * sizeof(c_int16))
                    if len(buffer) != data_length * sizeof(c_int16):
                        print('Unexpected end of file')
                        break
                    y_raw = frombuffer(buffer, int16, data_length)
                    if header.source == SOURCE_PHASE:
                        # Phase
                        if verbose:
                            print('Phase measurement')
                        calib = vectorize(lambda raw: float('nan') if raw >
                                          8192 else 180.0 * raw / 8192.0)
                        y1 = concatenate((y1, calib(y_raw)))
                        unit = MeasUnit.Degree
                        type = MeasType.Phase
                    elif header.source == SOURCE_VDC:
                        # Vdc
                        if verbose:
                            print('Vdc measurement')
                        offset = cast(float, header.ch1.offset)
                        slope = cast(float, header.ch1.slope)
                        quadratic = cast(float, header.ch1.rms_noise)
                        cubic = cast(float, header.ch1.demod_noise)
                        calib = vectorize(lambda raw: (offset + (slope * raw) +
                                                       (quadratic * raw**2) +
                                                       (cubic * raw**3)) / 1e3)
                        y1 = concatenate((y1, calib(y_raw)))
                        unit = MeasUnit.Volt
                        type = MeasType.Vdc
                    else:
                        # Modulated signal
                        if header.ch1.config & 1:
                            offset = cast(float, header.ch1.offset)
                            slope = cast(float, header.ch1.slope)
                            probe = cast(str,
                                         header.probe_id_ch1.decode('ascii'))
                        else:
                            offset = cast(float, header.ch2.offset)
                            slope = cast(float, header.ch2.slope)
                            probe = cast(str,
                                         header.probe_id_ch2.decode('ascii'))
                        if header.source == SOURCE_TXRX:
                            if verbose:
                                print('RF signal measurement '
                                      'on TX/RX (uncalibrated)')
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
                                        print('RF signal measurement '
                                              'on DAQ CH1')
                                    else:
                                        print('RF signal measurement '
                                              'on DAQ CH2')
                                if len(probe):
                                    print(f'Active probe: {probe}')
                            y_unit = MeasUnit.Volt
                            slope /= 1e3
                        calib = vectorize(lambda raw: slope * (raw + offset))
                        y1 = concatenate((y1, calib(y_raw)))
                        unit = y_unit
                        type = MeasType.Modulated

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
                    buffer = f.read(data_length * sizeof(c_int16) * 2)
                    if len(buffer) != data_length * sizeof(c_int16) * 2:
                        print('Unexpected end of file')
                        break
                    # Data interleaved
                    dt = dtype([('ch1', int16), ('ch2', int16)])
                    data = frombuffer(buffer, dt, data_length)
                    offset = cast(float, header.ch1.offset)
                    slope = cast(float, header.ch1.slope) / 1e3
                    calib = vectorize(lambda raw: slope * (raw + offset))
                    y1 = concatenate((y1, calib(data['ch1'])))
                    offset = cast(float, header.ch2.offset)
                    slope = cast(float, header.ch2.slope) / 1e3
                    calib = vectorize(lambda raw: slope * (raw + offset))
                    y2 = concatenate((y2, calib(data['ch2'])))
                    unit = MeasUnit.Volt
                    type = MeasType.Modulated

            elif data_width == sizeof(c_uint32):
                buffer = f.read(data_length * sizeof(c_uint32))
                if len(buffer) != data_length * sizeof(c_uint32):
                    print('Unexpected end of file')
                    break
                y_raw = frombuffer(buffer, uint32, data_length)

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
                calib = vectorize(lambda raw: slope * sqrt(raw - noise)
                                  if raw > noise else 0.0)
                y1 = concatenate((y1, calib(y_raw)))
                unit = MeasUnit.Volt
                type = MeasType.Demodulated

            else:
                raise Exception('Invalid acquisition file format')

            # Read footer
            buffer = f.read(sizeof(_Footer))
            if len(buffer) != sizeof(_Footer):
                print('Unexpected end of file')
                break
            footer = _Footer.from_buffer_copy(buffer)
            metadata_len = int(footer.metadata_size)
            if metadata_len:
                f.read(metadata_len)

        if y2.size > 0:
            return (x, [y1, y2], unit, type, sampling, separators)
        else:
            return (x, [y1], unit, type, sampling, separators)


class DaqMeas(Meas):
    """
    DAQ measurements

    Attributes:
        file: File path
        y_unit: Vertical axis unit
        x_unit: Horizontal axis unit
        type: Measurement type
        x: Horizontal coordinates array
        y: List of vertical coordinates arrays
        sampling: Sampling rate
        separators: List of vertical lines
    """

    def __init__(self, file_path: Path, verbose: bool):
        """
        Inits DaqMeas

        Args:
            file_path: DAQ file path
            verbose: Verbose mode
        """
        super().__init__(file_path)
        (self.x, self.y, self.y_unit, self.type, self.sampling,
         self.separators) = _load_signals(file_path, verbose)
        if self.sampling == 0:
            self.x_unit = BaseUnit.Dimensionless

    def convert(self, html_file: Path) -> None:
        """
        Converts DAQ data to HTML

        Args:
            html_file: HTML output file
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
            fig.data[count].hovertemplate = (
                f'{hover_header}'
                f'date=%{{x}}{self.x_unit.get_label()}<br>'
                f'value=%{{y}}{self.y_unit.get_label()}<extra></extra>')
            count += 1
        fig.add_hline(0)
        for sep in self.separators:
            fig.add_vline(x=sep, line_dash='longdash')
        self._plot(fig, html_file)

    def fft(self, html_file: Path) -> None:
        """
        Performs FFT on DAQ data and converts it to HTML

        Args:
            html_file: HTML output file
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
            if isnan(line).any():
                raise Exception('FFT cannot be performed on multi-signals')
            signal = absolute(rfft(line))
            normalized_fft = 20 * log10(signal / signal.max())
            freq = rfftfreq(self.x.size, 1 / self.sampling)
            fig.add_trace(Scatter(x=freq, y=normalized_fft, mode='lines'))
            if multichannel:
                fig.data[count].name = f'CH{count+1}'
                hover_header = f'CH{count+1}<br>'
            else:
                hover_header = ''
            fig.data[count].hovertemplate = (
                f'{hover_header}'
                f'frequency=%{{x}}{self.x_unit.get_label()}<br>'
                f'value=%{{y}}{self.y_unit.get_label()}<extra></extra>')
            count += 1
            x_max = freq[signal.argmax()]
            fig.add_vline(x=x_max,
                          line_dash='dash',
                          annotation_text=f'{x_max}{self.x_unit.get_label()}')
        self._plot(fig, html_file)
