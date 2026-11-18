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

print('Temperature recording: reads existing LSCI log files; no serial/Lake Shore driver required.')
print('LSCI Reader retains ownership; no thermometer port was opened.')
