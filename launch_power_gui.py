"""Base power GUI, with original Res1.1 parameters and optional read-only LSCI log files."""
import tkinter as tk
from resonator_lab.gui import ResonatorApp


def main():
    root = tk.Tk()
    app = ResonatorApp(root, power_only=True)
    settings = {'temperature_source': 'Label only', 'regulate': 'No (read temperatures only)',
                'temperature_mode': 'Power sweep at one temperature', 'single_temperature_mk': '',
                'points': '10001', 'power_start': '-45', 'power_stop': '20', 'power_count': '14'}
    for name, value in settings.items():
        app.vars[name].set(value)
    app.set_batch([app.editor_resonator()])
    root.mainloop()


if __name__ == '__main__':
    main()
