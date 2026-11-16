"""Read-only VISA diagnostics. Does not change instrument settings or enable RF."""
import platform
import sys

print('Python:', sys.version)
print('Platform:', platform.platform(), platform.architecture()[0])
try:
    import tkinter
    print('Tk:', tkinter.TkVersion)
except ImportError as exc:
    print('Tk unavailable:', exc)
try:
    import pyvisa
    rm = pyvisa.ResourceManager()
    try:
        print('VISA backend:', rm.visalib)
        print('VISA resources:', rm.list_resources())
    finally:
        rm.close()
except Exception as exc:
    print('VISA unavailable:', exc)
    print('Install NI-VISA or Keysight IO Libraries for hardware. Simulator does not require a VISA runtime.')

try:
    from importlib.metadata import version
    from serial.tools import list_ports
    print('Lake Shore driver:', version('lakeshore'))
    print('Serial ports (enumeration only; none opened):')
    for port in list_ports.comports():
        print(' ', port.device, '-', port.description)
except Exception as exc:
    print('Lake Shore/serial diagnostics unavailable:', exc)
    print('For thermometry, rerun setup or install the temperature extra. No Lake Shore connection was attempted.')
