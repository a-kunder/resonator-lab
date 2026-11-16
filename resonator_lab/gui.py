"""Tk desktop UI. All VISA work runs on one worker thread; Tk stays on main thread."""
import json
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from .model import ExperimentConfig, SweepSettings, ResonatorConfig, sequence, stepped_sequence
from .instruments import DEFAULT_ADDRESS, SiglentVNA, SimulatedVNA
from .experiment import ResonatorPowerSweep
from .thermometry import ThermometrySettings, PIDSettings
from .devices import create_temperature_devices
import time
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal


class ResonatorApp:
    def __init__(self, root, power_only=False):
        self.root = root
        self.power_only = power_only
        self.root.title('Resonator Lab · Base power sweep' if power_only else 'Resonator Lab · Power sweeps')
        screen_w = self.root.winfo_screenwidth() or 1360
        screen_h = self.root.winfo_screenheight() or 950
        self.root.geometry('{}x{}'.format(min(1280, max(1040, screen_w - 80)), min(850, max(640, screen_h - 100))))
        self.root.minsize(1040, 640)
        self.queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.closing = False
        self.run_path = None
        self.profile_widgets = []
        self.vars = {}
        self.batch = []
        self.selected_batch_index = None
        self.trace_cache = {}
        style = ttk.Style(root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure('TFrame', background='#f4f6fa')
        style.configure('TLabel', background='#f4f6fa')
        style.configure('TLabelframe', background='#f4f6fa')
        style.configure('TLabelframe.Label', background='#f4f6fa', font=('Helvetica', 11, 'bold'))
        style.configure('Title.TLabel', font=('Helvetica', 21, 'bold'), foreground='#17263e')
        style.configure('Hint.TLabel', foreground='#51627b')
        style.configure('TButton', padding=(10, 6))
        outer = ttk.Frame(root, padding=18)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Resonator Lab', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Resonator batch • Shared powers • LSCI Reader stays unchanged' if power_only else 'Resonator batches • Shared powers • Temperature plans', style='Hint.TLabel').pack(anchor='w', pady=(3, 14))
        body = ttk.Frame(outer)
        body.pack(fill='both', expand=True)
        left = ttk.Frame(body, width=375)
        left.pack(side='left', fill='y', padx=(0, 16))
        canvas = tk.Canvas(left, width=375, background='#f4f6fa', highlightthickness=0)
        scrollbar = ttk.Scrollbar(left, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        form = ttk.Frame(canvas, padding=(0, 0, 10, 10))
        window = canvas.create_window((0, 0), window=form, anchor='nw')
        form.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        conn = self.section(form, '1  Instrument')
        self.field(conn, 'Instrument', 'backend', 'Simulator', ['Simulator', 'Siglent SNA5000A'])
        self.field(conn, 'VISA address', 'address', DEFAULT_ADDRESS)
        scan = ttk.Button(conn, text='Find VISA instruments', command=self.scan_resources)
        scan.pack(fill='x', pady=(5, 2)); self.profile_widgets.append(scan)
        ttk.Label(conn, text='Simulator is selected by default.', style='Hint.TLabel').pack(anchor='w')
        res = self.section(form, '2  Resonator editor')
        self.field(res, 'Batch name', 'batch_name', 'Resonator batch')
        self.field(res, 'Resonator name', 'resonator', 'Res1.1')
        self.field(res, 'S-parameter', 's_parameter', 'S43', ['S{}{}'.format(i, j) for i in range(1, 5) for j in range(1, 5)])
        self.field(res, 'Start frequency (GHz)', 'start_ghz', '5.9297')
        self.field(res, 'Stop frequency (GHz)', 'stop_ghz', '5.9547')
        self.field(res, 'Frequency points', 'points', '1001')
        self.field(res, 'IF bandwidth (Hz)', 'if_bandwidth_hz', '1000')
        self.field(res, 'Averages per trace', 'averages', '7')
        self.field(res, 'Acquisition timeout (s)', 'timeout_s', '1800')
        self.field(res, 'Power settling time (s)', 'settle_s', '0.2')
        editor_buttons = ttk.Frame(res)
        editor_buttons.pack(fill='x', pady=4)
        for label, action in [('Add to batch', self.add_resonator), ('Update selected', self.update_resonator)]:
            button = ttk.Button(editor_buttons, text=label, command=action)
            button.pack(side='left', expand=True, fill='x', padx=2)
            self.profile_widgets.append(button)
        self.queue_info = tk.StringVar()
        ttk.Label(res, textvariable=self.queue_info, style='Hint.TLabel', wraplength=325).pack(anchor='w')
        power = self.section(form, '3  Shared VNA output powers')
        self.field(power, 'Start power (dBm)', 'power_start', '-45')
        self.field(power, 'Stop power (dBm)', 'power_stop', '-15')
        self.field(power, 'Number of powers', 'power_count', '7')
        self.field(power, 'Or explicit list (dBm)', 'power_list', '')
        ttk.Label(power, text='Comma-separated list overrides start/stop/count.\nOrder is preserved, including descending sweeps.', style='Hint.TLabel', wraplength=325).pack(anchor='w')
        self.field(power, 'Input path loss (dB, optional)', 'input_loss_db', '')
        temp = self.section(form, '4  Temperature and experiment mode')
        self.field(temp, 'Experiment mode', 'temperature_mode', 'Power sweep at one temperature',
                   ['Power sweep at one temperature', 'Temperature × power sweep'])
        self.field(temp, 'Thermometry', 'temperature_source', 'Label only',
                   ['Simulator', 'Lake Shore 372', 'Label only'])
        self.field(temp, 'Regulate temperature with PID', 'regulate', 'No (read temperatures only)', ['Yes', 'No (read temperatures only)'])
        self.field(temp, 'Optional temperature label (mK; blank = unknown)', 'single_temperature_mk', '')
        self.field(temp, 'Sweep list (mK)', 'temperatures_mk', '20, 30, 50, 75, 100, 150, 200, 300, 400, 500, 600, 700, 800')
        generation_mode = self.field(temp, 'Generate by', 'temp_generation', 'Number of temperatures', ['Number of temperatures', 'Step size (mK)'])
        generation_mode.bind('<<ComboboxSelected>>', self.update_temperature_generator)
        self.field(temp, 'From (mK)', 'temp_start_mk', '20')
        self.field(temp, 'To (mK)', 'temp_stop_mk', '800')
        count_widget = self.field(temp, 'Number of temperatures', 'temp_count', '14')
        step_widget = self.field(temp, 'Step size (mK)', 'temp_step_mk', '20')
        spacing_widget = self.field(temp, 'Spacing for count mode', 'temp_spacing', 'Linear', ['Linear', 'Logarithmic'])
        self.temp_count_widgets, self.temp_step_widgets, self.temp_spacing_widgets = [count_widget], [step_widget], [spacing_widget]
        self.generation_status = tk.StringVar(value='Step mode includes the stop only when aligned to the grid.')
        generate = ttk.Button(temp, text='Generate temperature list', command=self.generate_temperatures)
        generate.pack(fill='x', pady=4); self.profile_widgets.append(generate)
        ttk.Label(temp, textvariable=self.generation_status, style='Hint.TLabel', wraplength=325).pack(anchor='w')
        self.field(temp, 'Base temperature (mK)', 'base_temperature_mk', '20')
        self.field(temp, 'Maximum setpoint (mK)', 'max_temperature_mk', '800')
        self.field(temp, 'Stability band ± (mK)', 'temperature_tolerance_mk', '2')
        self.field(temp, 'Continuous stable dwell (min)', 'dwell_min', '10')
        self.field(temp, 'Read / log interval (s)', 'poll_s', '5')
        self.field(temp, 'Stabilization timeout (min)', 'temperature_timeout_min', '60')
        self.field(temp, 'Passive cooldown timeout (min)', 'cooldown_timeout_min', '120')
        ttk.Label(temp, text='After regulation: sample heater + PID OFF, then log passive cooldown. Simulator thermal waits run at 3600× speed.',
                  style='Hint.TLabel', wraplength=325).pack(anchor='w', pady=4)
        hardware = self.section(form, 'Lake Shore connection · fill in at Falkor')
        self.field(hardware, 'Connection', 'thermal_connection', 'Serial / USB', ['Serial / USB', 'TCP / LAN'])
        self.field(hardware, 'COM port (serial)', 'thermal_com_port', '')
        self.field(hardware, 'Baud rate', 'thermal_baud', '57600')
        self.field(hardware, 'Instrument IP (TCP)', 'thermal_ip', '')
        self.field(hardware, 'TCP port', 'thermal_tcp_port', '7777')
        self.field(hardware, 'I/O timeout (s)', 'thermal_timeout_s', '2')
        self.field(hardware, 'Primary thermometer channel', 'primary_channel', '')
        self.field(hardware, 'Channels to log (comma-separated)', 'thermal_channels', '')
        ttk.Label(hardware, text='Channels: 1–16 or A. No Snoopy channel or heater wiring is assumed. Use read-only mode to log without heater changes.',
                  style='Hint.TLabel', wraplength=325).pack(anchor='w', pady=4)
        heater = self.section(form, 'Sample-heater PID · confirmed hardware values')
        self.field(heater, 'Confirmed heater output (0 only)', 'heater_output', '')
        self.field(heater, 'Current range code (1–8)', 'heater_range', '')
        self.field(heater, 'Heater resistance (Ω)', 'heater_resistance_ohm', '')
        self.field(heater, 'Maximum allowed heater power (µW)', 'max_heater_power_uw', '')
        self.field(heater, 'P (blank = existing tuning)', 'pid_gain', '')
        self.field(heater, 'I (instrument units)', 'pid_integral', '')
        self.field(heater, 'D (instrument units)', 'pid_derivative', '')
        ttk.Label(heater, text='All P/I/D blank uses existing controller tuning. Feedback input must already match the primary thermometer. Other heater outputs are not changed.',
                  style='Hint.TLabel', wraplength=325).pack(anchor='w', pady=4)
        if power_only:
            temp.pack_forget()
            hardware.pack_forget()
            heater.pack_forget()
        logs = self.section(form, 'Read temperatures from LSCI logs')
        self.field(logs, 'Record CH temperature logs', 'log_enabled', 'No', ['No', 'Yes'])
        self.field(logs, 'CoolDownData folder or daily T file', 'log_path', str(Path.home() / 'Documents' / 'CoolDownData'))
        self.field(logs, 'Temperature channel', 'log_channel', '6')
        self.field(logs, 'Maximum reading age (s)', 'log_max_age_s', '180')
        for label, command in [('Choose log folder…', self.choose_log_folder), ('Choose daily T file…', self.choose_log_file), ('Check latest temperature', self.check_log_temperature)]:
            button = ttk.Button(logs, text=label, command=command)
            button.pack(fill='x', pady=3)
            self.profile_widgets.append(button)
        ttk.Label(logs, text='Reads CH6 T files only. Folder mode follows daily rollover. Dates are day-month-year; times use this PC’s local timezone. LSCI keeps control. Old or invalid readings stop acquisition.', style='Hint.TLabel', wraplength=325).pack(anchor='w')
        save = self.section(form, '4  Timing and files' if power_only else '5  Timing and files')
        self.field(save, 'Output folder', 'output_root', str(Path.cwd() / 'data'))
        browse = ttk.Button(save, text='Choose output folder…', command=self.choose_folder)
        browse.pack(fill='x'); self.profile_widgets.append(browse)
        self.field(save, 'Notes', 'notes', '')
        ttk.Label(save, text='Saves complex NPZ + CSV + JSON per trace.\nNo phase correction or normalization is applied.', style='Hint.TLabel', wraplength=325).pack(anchor='w', pady=5)
        right = ttk.Frame(body)
        right.pack(side='left', fill='both', expand=True)
        actions = ttk.Frame(right)
        actions.pack(fill='x', pady=(0, 10))
        self.start = ttk.Button(actions, text='▶  Start batch', command=self.start_run)
        self.start.pack(side='left')
        self.stop = ttk.Button(actions, text='■  Stop after acquisition', command=self.stop_run, state='disabled')
        self.stop.pack(side='left', padx=7)
        self.load_button = ttk.Button(actions, text='Load settings', command=self.load_settings)
        self.load_button.pack(side='right')
        self.save_button = ttk.Button(actions, text='Save settings', command=self.save_settings)
        self.save_button.pack(side='right', padx=6)
        self.profile_widgets.extend([self.load_button, self.save_button])
        self.summary = tk.StringVar(value='Ready · Simulator selected · No instruments connected')
        ttk.Label(right, textvariable=self.summary, wraplength=730, style='Hint.TLabel').pack(anchor='w', pady=(0, 8))
        self.progress = ttk.Progressbar(right, mode='determinate')
        self.progress.pack(fill='x', pady=(0, 8))
        self.temperature_status = tk.StringVar(value='Measured temperature: —')
        ttk.Label(right, textvariable=self.temperature_status, style='Hint.TLabel', wraplength=730).pack(anchor='w', pady=(0, 5))
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill='both', expand=True)
        self.batch_page = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.batch_page, text='Resonator batch')
        trace_page, temperature_page = ttk.Frame(self.notebook), ttk.Frame(self.notebook)
        self.trace_page = trace_page
        self.build_batch_page()
        self.notebook.add(trace_page, text='VNA traces')
        self.notebook.add(temperature_page, text='Temperature history')
        self.build_temperature_planner()
        plot_controls = ttk.Frame(trace_page)
        plot_controls.pack(fill='x', pady=4)
        ttk.Label(plot_controls, text='Plot resonator:').pack(side='left', padx=5)
        self.plot_resonator = tk.StringVar(value='')
        self.plot_selector = ttk.Combobox(plot_controls, textvariable=self.plot_resonator, state='readonly', width=20)
        self.plot_selector.pack(side='left')
        self.plot_selector.bind('<<ComboboxSelected>>', self.select_plot)
        self.follow_active = tk.BooleanVar(value=True)
        ttk.Checkbutton(plot_controls, text='Follow active resonator', variable=self.follow_active).pack(side='left', padx=8)
        self.figure = Figure(figsize=(7, 5.3), dpi=100, facecolor='#ffffff')
        self.ax_mag, self.ax_phase = self.figure.subplots(2, 1, sharex=True)
        self.reset_plot()
        self.plot = FigureCanvasTkAgg(self.figure, master=trace_page)
        self.plot.get_tk_widget().pack(fill='both', expand=True)
        NavigationToolbar2Tk(self.plot, trace_page).update()
        self.thermal_figure = Figure(figsize=(7, 5), dpi=100, facecolor='white')
        self.thermal_ax = self.thermal_figure.subplots()
        self.thermal_ax.set_xlabel('Elapsed wall time (min)')
        self.thermal_ax.set_ylabel('Temperature (mK)')
        self.thermal_ax.grid(True, alpha=0.2)
        self.thermal_line, = self.thermal_ax.plot([], [], label='Primary thermometer', linewidth=1)
        self.thermal_target_line, = self.thermal_ax.plot([], [], label='Setpoint', linestyle='--', linewidth=1)
        self.thermal_ax.legend(loc='best')
        self.thermal_figure.tight_layout()
        self.thermal_plot = FigureCanvasTkAgg(self.thermal_figure, master=temperature_page)
        self.thermal_plot.get_tk_widget().pack(fill='both', expand=True)
        NavigationToolbar2Tk(self.thermal_plot, temperature_page).update()
        self.thermal_history = deque(maxlen=20000)
        self.thermal_start_utc = datetime.now(timezone.utc).timestamp()
        ttk.Label(right, text='Run log', style='Hint.TLabel').pack(anchor='w', pady=(7, 2))
        self.log = tk.Text(right, height=5, font=('Courier', 10), background='#17263e', foreground='#e0e8f5', wrap='word', state='disabled')
        self.log.pack(fill='x')
        self.location = tk.StringVar(value='Completed traces are saved immediately; Stop keeps saved data.')
        ttk.Label(outer, textvariable=self.location, style='Hint.TLabel', wraplength=1180).pack(anchor='w', pady=(10, 0))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.poll)
        self.set_batch([self.editor_resonator()])
        for key in ('resonator', 's_parameter', 'start_ghz', 'stop_ghz', 'points', 'if_bandwidth_hz', 'averages', 'timeout_s', 'settle_s'):
            self.vars[key].trace_add('write', self.mark_editor_state)
        self.update_temperature_generator()

    def build_batch_page(self):
        ttk.Label(self.batch_page, text='At each temperature: every power for row 1, then every power for row 2, and so on.',
                  style='Hint.TLabel', wraplength=730).pack(anchor='w', pady=(0, 8))
        holder = ttk.Frame(self.batch_page)
        holder.pack(fill='both', expand=True)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        columns = ('order', 'name', 'start', 'stop', 'ifbw', 'averages', 'points', 'parameter')
        self.batch_tree = ttk.Treeview(holder, columns=columns, show='headings', selectmode='browse', height=10)
        for key, title, width in [('order', '#', 35), ('name', 'Resonator', 105), ('start', 'Start (GHz)', 105),
                                  ('stop', 'Stop (GHz)', 105), ('ifbw', 'IFBW (Hz)', 85),
                                  ('averages', 'Avgs', 50), ('points', 'Points', 75), ('parameter', 'Sij', 55)]:
            self.batch_tree.heading(key, text=title)
            self.batch_tree.column(key, width=width, minwidth=width, stretch=key == 'name')
        self.batch_tree.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(holder, orient='vertical', command=self.batch_tree.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        self.batch_tree.configure(yscrollcommand=vertical.set)
        horizontal = ttk.Scrollbar(holder, orient='horizontal', command=self.batch_tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.batch_tree.configure(xscrollcommand=horizontal.set)
        self.batch_tree.bind('<<TreeviewSelect>>', self.select_batch_row)
        buttons = ttk.Frame(self.batch_page)
        buttons.pack(fill='x', pady=8)
        for label, command in [('Remove', self.remove_resonator), ('Move up', lambda: self.move_resonator(-1)),
                               ('Move down', lambda: self.move_resonator(1)),
                               ('Load original 9', self.load_original_batch),
                               ('Export experiment JSON', self.export_experiment)]:
            button = ttk.Button(buttons, text=label, command=command)
            button.pack(side='left', padx=2)
            self.profile_widgets.append(button)
        ttk.Label(self.batch_page, text='Select a row to edit its settings on the left. Click Update selected to apply edits, or give it a new name and Add to batch. Shared powers are below the editor. Trace timeout and settling time are also per resonator.',
                  style='Hint.TLabel', wraplength=730).pack(anchor='w', pady=5)
        ttk.Label(self.batch_page, textvariable=self.queue_info, wraplength=730).pack(anchor='w')

    def build_temperature_planner(self):
        page = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(page, text='Temperature plan')
        self.temperature_plan_page = page
        ttk.Label(page, text='Generate the temperature list for the same resonator batch.',
                  style='Title.TLabel', wraplength=720).pack(anchor='w', pady=(0, 8))
        ttk.Label(page, text='Planning only in the base-power launcher: the current batch runs once at base and LSCI Reader stays in control. Export a future plan to rehearse temperature × resonator × power order with --simulate. Physical temperature integration is deferred.',
                  style='Hint.TLabel', wraplength=720).pack(anchor='w', pady=(0, 10))
        row = ttk.Frame(page)
        row.pack(fill='x')
        left, right = ttk.Frame(row), ttk.Frame(row)
        left.pack(side='left', fill='x', expand=True, padx=(0, 12))
        right.pack(side='left', fill='x', expand=True)
        self.linked_field(left, 'Start (mK)', 'temp_start_mk')
        self.linked_field(right, 'Stop (mK)', 'temp_stop_mk')
        mode = self.linked_field(left, 'Generate by', 'temp_generation', ['Number of temperatures', 'Step size (mK)'])
        mode.bind('<<ComboboxSelected>>', self.update_temperature_generator)
        self.temp_spacing_widgets.append(self.linked_field(right, 'Spacing in count mode', 'temp_spacing', ['Linear', 'Logarithmic']))
        self.temp_count_widgets.append(self.linked_field(left, 'Number of temperatures', 'temp_count'))
        self.temp_step_widgets.append(self.linked_field(right, 'Step size (mK; positive magnitude)', 'temp_step_mk'))
        self.linked_field(left, 'Base / lower setpoint (mK)', 'base_temperature_mk')
        self.linked_field(right, 'Maximum setpoint (mK)', 'max_temperature_mk')
        actions = ttk.Frame(page)
        actions.pack(fill='x', pady=10)
        for label, command in [('Generate list', self.generate_temperatures),
                               ('Export future batch JSON', lambda: self.export_experiment(future=True))]:
            button = ttk.Button(actions, text=label, command=command)
            button.pack(side='left', padx=3)
            self.profile_widgets.append(button)
        self.linked_field(page, 'Explicit temperature list (mK; editable, acquisition order)', 'temperatures_mk')
        ttk.Label(page, textvariable=self.generation_status, wraplength=720).pack(anchor='w', pady=6)
        ttk.Label(page, text='Step mode is linear. Stop is included only when it lies on the step grid; no shorter final step is silently appended. For descending sweeps, keep a positive step size and reverse start/stop. The explicit list is saved in the plan.',
                  style='Hint.TLabel', wraplength=720).pack(anchor='w', pady=6)

    def editor_resonator(self):
        v = lambda key: self.vars[key].get().strip()
        entry = ResonatorConfig(v('resonator'), SweepSettings(
            start_hz=float(Decimal(v('start_ghz')) * Decimal('1e9')), stop_hz=float(Decimal(v('stop_ghz')) * Decimal('1e9')),
            points=int(v('points')), if_bandwidth_hz=float(v('if_bandwidth_hz')),
            averages=int(v('averages')), s_parameter=v('s_parameter'),
            timeout_s=float(v('timeout_s')), settle_s=float(v('settle_s'))))
        entry.validate()
        return entry

    def set_editor(self, entry):
        s = entry.sweep
        fields = dict(resonator=entry.name, start_ghz=str((Decimal(str(s.start_hz)) / Decimal('1e9')).normalize()),
                      stop_ghz=str((Decimal(str(s.stop_hz)) / Decimal('1e9')).normalize()), points=str(s.points),
                      if_bandwidth_hz=str(s.if_bandwidth_hz), averages=str(s.averages),
                      s_parameter=s.s_parameter, timeout_s=str(s.timeout_s), settle_s=str(s.settle_s))
        for key, value in fields.items():
            self.vars[key].set(value)
        self.mark_editor_state()

    def set_batch(self, entries, name=None):
        entries = [ResonatorConfig.from_dict(entry.to_dict()) for entry in entries]
        if not entries:
            raise ValueError('A loaded batch must contain at least one resonator.')
        names = [entry.name.strip().casefold() for entry in entries]
        if len(set(names)) != len(names):
            raise ValueError('Resonator names must be unique.')
        self.batch = entries
        self.selected_batch_index = 0
        if name is not None:
            self.vars['batch_name'].set(name)
        self.refresh_batch()

    def refresh_batch(self):
        self.batch_tree.delete(*self.batch_tree.get_children())
        for i, entry in enumerate(self.batch):
            s = entry.sweep
            self.batch_tree.insert('', 'end', iid=str(i), values=(i + 1, entry.name,
                '{:.9g}'.format(s.start_hz / 1e9), '{:.9g}'.format(s.stop_hz / 1e9),
                s.if_bandwidth_hz, s.averages, s.points, s.s_parameter))
        if self.batch:
            self.selected_batch_index = min(self.selected_batch_index or 0, len(self.batch) - 1)
            self.batch_tree.selection_set(str(self.selected_batch_index))
            self.batch_tree.see(str(self.selected_batch_index))
            self.set_editor(self.batch[self.selected_batch_index])
        else:
            self.selected_batch_index = None
        self.mark_editor_state()

    def select_batch_row(self, event=None):
        selected = self.batch_tree.selection()
        if selected:
            self.selected_batch_index = int(selected[0])
            self.set_editor(self.batch[self.selected_batch_index])

    def mark_editor_state(self, *unused):
        if not hasattr(self, 'queue_info'):
            return
        if not self.batch:
            self.queue_info.set('No queued rows: Start uses the editor as a single resonator.')
            return
        dirty = False
        try:
            dirty = self.editor_resonator().to_dict() != self.batch[self.selected_batch_index or 0].to_dict()
        except (ValueError, TypeError):
            dirty = True
        self.queue_info.set('{} resonator(s) queued{}'.format(len(self.batch),
            ' · editor changes need Update selected or Add to batch' if dirty else ' · editor matches selected row'))

    def ensure_editor_applied(self):
        if self.batch and self.editor_resonator().to_dict() != self.batch[self.selected_batch_index or 0].to_dict():
            raise ValueError('The resonator editor has unapplied changes. Click Update selected or Add to batch before starting or saving.')

    def add_resonator(self):
        try:
            entry = self.editor_resonator()
            if entry.name.strip().casefold() in [r.name.strip().casefold() for r in self.batch]:
                raise ValueError('That resonator name is already queued. Use Update selected, or choose a new name.')
            self.batch.append(entry)
            self.selected_batch_index = len(self.batch) - 1
            self.refresh_batch()
        except Exception as exc:
            messagebox.showerror('Resonator batch', str(exc))

    def update_resonator(self):
        if not self.batch:
            self.add_resonator()
            return
        try:
            entry = self.editor_resonator()
            index = self.selected_batch_index or 0
            if entry.name.strip().casefold() in [r.name.strip().casefold() for i, r in enumerate(self.batch) if i != index]:
                raise ValueError('Another queued resonator already has that name.')
            self.batch[index] = entry
            self.refresh_batch()
        except Exception as exc:
            messagebox.showerror('Resonator batch', str(exc))

    def remove_resonator(self):
        if self.batch:
            self.batch.pop(self.selected_batch_index or 0)
            self.refresh_batch()

    def move_resonator(self, direction):
        if not self.batch:
            return
        try:
            self.ensure_editor_applied()
            index = self.selected_batch_index or 0
            other = index + direction
            if 0 <= other < len(self.batch):
                self.batch[index], self.batch[other] = self.batch[other], self.batch[index]
                self.selected_batch_index = other
                self.refresh_batch()
        except Exception as exc:
            messagebox.showerror('Resonator batch', str(exc))

    def load_original_batch(self):
        try:
            path = Path(__file__).resolve().parents[1] / 'examples' / 'base_batch_original.json'
            with path.open(encoding='utf-8') as stream:
                config = ExperimentConfig.from_dict(json.load(stream))
            self.apply_experiment_config(config)
            self.notebook.select(self.batch_page)
        except Exception as exc:
            messagebox.showerror('Load resonators', str(exc))

    def apply_experiment_config(self, config):
        self.vars['power_list'].set(', '.join('{:.12g}'.format(p) for p in config.powers_dbm))
        self.vars['power_start'].set(str(config.powers_dbm[0]))
        self.vars['power_stop'].set(str(config.powers_dbm[-1]))
        self.vars['power_count'].set(str(len(config.powers_dbm)))
        self.vars['input_loss_db'].set('' if config.input_loss_db is None else str(config.input_loss_db))
        self.vars['notes'].set(config.notes)
        self.vars['temperature_mode'].set('Temperature × power sweep' if len(config.temperatures_k) > 1 else 'Power sweep at one temperature')
        self.vars['regulate'].set('Yes' if config.temperature_mode == 'controlled' else 'No (read temperatures only)')
        self.vars['temperature_source'].set('Simulator' if config.temperature_mode == 'controlled' else 'Label only')
        self.vars['log_enabled'].set('Yes' if config.thermometry.backend == 'lsci_log' else 'No')
        for key in ('log_path', 'log_channel', 'log_max_age_s'):
            self.vars[key].set(str(getattr(config.thermometry, key)))
        known = [t for t in config.temperatures_k if t is not None]
        self.vars['single_temperature_mk'].set(str(known[0] * 1000) if known else '')
        if known:
            self.vars['temp_start_mk'].set(str(known[0] * 1000))
            self.vars['temp_stop_mk'].set(str(known[-1] * 1000))
            self.vars['temp_count'].set(str(len(known)))
            self.vars['temperatures_mk'].set(', '.join('{:.12g}'.format(t * 1000) for t in known))
        for key, value in dict(base_temperature_mk=config.pid.base_temperature_k * 1000,
                               max_temperature_mk=config.pid.max_temperature_k * 1000,
                               temperature_tolerance_mk=config.temperature_tolerance_k * 1000,
                               dwell_min=config.pid.dwell_s / 60, poll_s=config.pid.poll_s,
                               temperature_timeout_min=config.temperature_timeout_s / 60,
                               cooldown_timeout_min=config.pid.cooldown_timeout_s / 60).items():
            self.vars[key].set(str(value))
        self.set_batch(config.resonator_plan, config.run_name)

    def future_temperature_config(self):
        """Plan only; hardware needs an owner-mediated temperature adapter later."""
        config = self.config()
        config.temperatures_k = [x / 1000 for x in self.parse_list(self.vars['temperatures_mk'].get())]
        config.temperature_mode = 'controlled'
        config.thermometry = ThermometrySettings(backend='none')
        config.pid = PIDSettings(base_temperature_k=float(self.vars['base_temperature_mk'].get()) / 1000,
            max_temperature_k=float(self.vars['max_temperature_mk'].get()) / 1000,
            dwell_s=float(self.vars['dwell_min'].get()) * 60,
            poll_s=float(self.vars['poll_s'].get()),
            cooldown_timeout_s=float(self.vars['cooldown_timeout_min'].get()) * 60)
        config.temperature_tolerance_k = float(self.vars['temperature_tolerance_mk'].get()) / 1000
        config.temperature_timeout_s = float(self.vars['temperature_timeout_min'].get()) * 60
        config.validate()
        return config

    def export_experiment(self, future=False):
        try:
            config = self.future_temperature_config() if future else self.config()
            path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('Experiment JSON', '*.json')])
            if path:
                with open(path, 'w', encoding='utf-8') as stream:
                    json.dump(config.to_dict(), stream, indent=2, allow_nan=False)
        except Exception as exc:
            messagebox.showerror('Export experiment', str(exc))

    def linked_field(self, parent, label, key, options=None):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text=label).pack(anchor='w')
        widget = ttk.Combobox(row, textvariable=self.vars[key], values=options, state='readonly') if options else ttk.Entry(row, textvariable=self.vars[key])
        widget.pack(fill='x', pady=(2, 0))
        self.profile_widgets.append(widget)
        return widget

    def update_temperature_generator(self, event=None):
        step_mode = self.vars['temp_generation'].get() == 'Step size (mK)'
        if step_mode:
            self.vars['temp_spacing'].set('Linear')
        for widget in self.temp_count_widgets:
            widget.configure(state='disabled' if step_mode else 'normal')
        for widget in self.temp_step_widgets:
            widget.configure(state='normal' if step_mode else 'disabled')
        for widget in self.temp_spacing_widgets:
            widget.configure(state='disabled' if step_mode else 'readonly')

    def select_plot(self, event=None):
        self.follow_active.set(False)
        self.draw_resonator_plot()

    def draw_resonator_plot(self):
        self.reset_plot()
        name = self.plot_resonator.get()
        traces = self.trace_cache.get(name, [])
        for trace in traces:
            m = trace.metadata
            temp = m.get('temperature_before_k')
            if temp is None:
                temp = m.get('temperature_target_k') if m['temperature_mode'] == 'controlled' else m.get('temperature_label_k')
            temperature_text = 'base' if temp is None else '{:.4g} mK'.format(temp * 1000)
            label = '{:g} dBm · {}'.format(m['vna_power_readback_dbm'], temperature_text)
            line, = self.ax_mag.plot(trace.frequency_hz / 1e9, trace.magnitude_db, label=label, linewidth=1)
            self.ax_phase.plot(trace.frequency_hz / 1e9, trace.phase_rad, color=line.get_color(), linewidth=1)
        simulated = traces[-1].metadata['simulated'] if traces else self.vars['backend'].get() == 'Simulator'
        parameter = traces[-1].metadata['s_parameter'] if traces else ''
        self.ax_mag.set_title(('SIMULATED · ' if simulated else '') + name + ' · ' + parameter, loc='left', fontsize=12)
        handles, labels = self.ax_mag.get_legend_handles_labels()
        if handles:
            self.ax_mag.legend(handles[-8:], labels[-8:], fontsize=8, loc='best')
        self.figure.tight_layout()
        self.plot.draw_idle()

    def section(self, parent, title):
        box = ttk.LabelFrame(parent, text=title, padding=10)
        box.pack(fill='x', pady=(0, 10))
        return box

    def field(self, parent, label, key, value, options=None):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text=label).pack(anchor='w')
        var = tk.StringVar(value=value)
        self.vars[key] = var
        widget = ttk.Combobox(row, textvariable=var, values=options, state='readonly') if options else ttk.Entry(row, textvariable=var)
        widget.pack(fill='x', pady=(2, 0))
        self.profile_widgets.append(widget)
        return widget

    def config(self):
        v = lambda key: self.vars[key].get().strip()
        optional_float = lambda key: float(v(key)) if v(key) else None
        optional_int = lambda key: int(v(key)) if v(key) else None
        powers = self.parse_list(v('power_list')) if v('power_list') else sequence(float(v('power_start')), float(v('power_stop')), int(v('power_count')))
        multi = not self.power_only and v('temperature_mode') == 'Temperature × power sweep'
        temperatures = [None] if self.power_only else ([x / 1000 for x in self.parse_list(v('temperatures_mk'))] if multi else [float(v('single_temperature_mk')) / 1000 if v('single_temperature_mk') else None])
        source = 'none' if self.power_only else {'Simulator': 'simulator', 'Lake Shore 372': 'lakeshore372', 'Label only': 'none'}.get(v('temperature_source'))
        if source is None:
            raise ValueError('Select a thermometry source.')
        use_log = 'log_enabled' in self.vars and v('log_enabled') == 'Yes'
        if use_log:
            source = 'lsci_log'
        controlled = not self.power_only and v('regulate') == 'Yes'
        if controlled and source == 'lsci_log':
            raise ValueError('Log reading does not control temperature. Turn regulation off for a single-temperature batch.')
        if controlled and any(t is None for t in temperatures):
            raise ValueError('Enter a temperature for a regulated simulation. Leave regulation off for base power sweeps.')
        if source == 'lakeshore372':
            raise ValueError('LSCI Reader retains ownership. Direct Lake Shore integration is disabled; choose Label only and regulation No.')
        if multi and not controlled:
            raise ValueError('Temperature × power mode requires temperature regulation.')
        if controlled and source == 'none':
            raise ValueError('Select thermometry for regulation, or turn regulation off for a label-only run.')
        if source == 'simulator' and v('backend') != 'Simulator':
            raise ValueError('Simulated thermometry requires a simulated VNA.')
        if source == 'lakeshore372' and v('backend') == 'Simulator':
            raise ValueError('Select the hardware VNA for a real Lake Shore run.')
        thermal = self.log_settings() if use_log else ThermometrySettings(backend=source)
        if source == 'lakeshore372':
            thermal = ThermometrySettings(backend=source,
                connection='serial' if v('thermal_connection') == 'Serial / USB' else 'tcp',
                com_port=v('thermal_com_port'), ip_address=v('thermal_ip'),
                tcp_port=int(v('thermal_tcp_port')), baud_rate=int(v('thermal_baud')),
                io_timeout_s=float(v('thermal_timeout_s')), primary_channel=v('primary_channel'),
                channels=[item.strip() for item in v('thermal_channels').split(',')])
        pid = PIDSettings() if self.power_only else PIDSettings(base_temperature_k=float(v('base_temperature_mk')) / 1000,
            max_temperature_k=float(v('max_temperature_mk')) / 1000,
            dwell_s=float(v('dwell_min')) * 60, poll_s=float(v('poll_s')),
            cooldown_timeout_s=float(v('cooldown_timeout_min')) * 60)
        if controlled and source == 'lakeshore372':
            pid.heater_output = optional_int('heater_output')
            pid.heater_range = optional_int('heater_range')
            pid.heater_resistance_ohm = optional_float('heater_resistance_ohm')
            power_uw = optional_float('max_heater_power_uw')
            pid.max_heater_power_w = power_uw * 1e-6 if power_uw is not None else None
            pid.gain, pid.integral, pid.derivative = (optional_float(key) for key in ('pid_gain', 'pid_integral', 'pid_derivative'))
        c = ExperimentConfig(resonator=v('resonator'),
            sweep=SweepSettings(start_hz=float(Decimal(v('start_ghz')) * Decimal('1e9')), stop_hz=float(Decimal(v('stop_ghz')) * Decimal('1e9')),
                points=int(v('points')), if_bandwidth_hz=float(v('if_bandwidth_hz')),
                averages=int(v('averages')), s_parameter=v('s_parameter'), timeout_s=float(v('timeout_s')),
                settle_s=float(v('settle_s'))), powers_dbm=powers, temperatures_k=temperatures,
            temperature_mode='controlled' if controlled else 'fixed',
            temperature_tolerance_k=.002 if self.power_only else float(v('temperature_tolerance_mk')) / 1000,
            temperature_timeout_s=3600 if self.power_only else float(v('temperature_timeout_min')) * 60,
            thermometry=thermal, pid=pid,
            input_loss_db=optional_float('input_loss_db'), notes=v('notes'))
        if getattr(self, 'batch', []):
            self.ensure_editor_applied()
            c.batch_name = v('batch_name')
            c.resonators = [ResonatorConfig.from_dict(r.to_dict()) for r in self.batch]
            c.resonator, c.sweep = c.resonators[0].name, c.resonators[0].sweep
        c.validate()
        if not v('output_root'):
            raise ValueError('Choose an output folder.')
        if v('backend') != 'Simulator' and not v('address'):
            raise ValueError('Enter the VISA address.')
        return c

    def generate_temperatures(self):
        try:
            start = float(self.vars['temp_start_mk'].get())
            stop = float(self.vars['temp_stop_mk'].get())
            base = float(self.vars['base_temperature_mk'].get())
            ceiling = float(self.vars['max_temperature_mk'].get())
            if not all(base <= x <= ceiling for x in (start, stop)):
                raise ValueError('Temperature endpoints must be within the configured base and maximum.')
            if self.vars['temp_generation'].get() == 'Step size (mK)':
                values = stepped_sequence(start, stop, float(self.vars['temp_step_mk'].get()))
            else:
                count = int(self.vars['temp_count'].get())
                if count > 100000:
                    raise ValueError('Temperature list exceeds 100000 entries.')
                values = sequence(start, stop, count)
                if self.vars['temp_spacing'].get() == 'Logarithmic':
                    if min(start, stop) <= 0:
                        raise ValueError('Logarithmic spacing requires positive temperatures.')
                    import numpy as np
                    values = np.geomspace(start, stop, count).tolist()
            self.vars['temperatures_mk'].set(', '.join('{:.12g}'.format(x) for x in values))
            self.generation_status.set('{} temperatures · {} to {} mK{}'.format(len(values), values[0], values[-1],
                ' · requested stop is off-grid' if values[-1] != stop else ''))
        except Exception as exc:
            messagebox.showerror('Temperature list', str(exc))

    @staticmethod
    def parse_list(text):
        parts = text.split(',')
        if not text or any(not part.strip() for part in parts):
            raise ValueError('Enter a comma-separated list without empty values.')
        return [float(part.strip()) for part in parts]

    def log_settings(self):
        return ThermometrySettings(backend='lsci_log', log_path=self.vars['log_path'].get().strip(),
            log_channel=self.vars['log_channel'].get().strip(), log_max_age_s=float(self.vars['log_max_age_s'].get()))

    def choose_log_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.vars['log_path'].set(path)

    def choose_log_file(self):
        path = filedialog.askopenfilename(filetypes=[('Text logs', '*.txt'), ('All files', '*')])
        if path:
            self.vars['log_path'].set(path)

    def check_log_temperature(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            settings = self.log_settings()
            settings.validate()
        except Exception as exc:
            messagebox.showerror('Temperature log', str(exc))
            return
        self.busy(True)
        def work():
            try:
                from .log_thermometry import LSCILogReader
                snapshot = LSCILogReader(settings).read_snapshot()
                self.queue.put(('temperature', snapshot))
                self.queue.put(('status', 'Log OK: {:.5g} mK · age {:.0f} s · {}'.format(snapshot['primary_kelvin'] * 1000, snapshot['age_s'], snapshot['log_file'])))
            except Exception as exc:
                self.queue.put(('error', str(exc)))
            finally:
                self.queue.put(('worker_done', None))
        self.worker = threading.Thread(target=work, name='Temperature log check', daemon=False)
        self.worker.start()

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.vars['output_root'].set(folder)

    def save_settings(self):
        try:
            self.config()
            filename = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('Settings', '*.json')])
            if filename:
                with open(filename, 'w', encoding='utf-8') as stream:
                    json.dump({'gui_schema_version': 3, 'fields': {k: v.get() for k, v in self.vars.items()}, 'resonators': [r.to_dict() for r in self.batch], 'selected_resonator': self.selected_batch_index}, stream, indent=2)
        except Exception as exc:
            messagebox.showerror('Settings', str(exc))

    def load_settings(self):
        filename = filedialog.askopenfilename(filetypes=[('Settings', '*.json')])
        if not filename:
            return
        try:
            with open(filename, encoding='utf-8') as stream:
                data = json.load(stream)
            if 'gui_schema_version' not in data:
                self.apply_experiment_config(ExperimentConfig.from_dict(data))
                return
            if data.get('gui_schema_version') not in (1, 2, 3):
                raise ValueError('Select a GUI settings profile saved with Save settings.')
            if data.get('gui_schema_version') == 1:
                fields = data['fields']
                legacy_control = fields.get('temperature_mode') == 'Simulated temperature sweep'
                fields['temperature_mode'] = 'Temperature × power sweep' if legacy_control else 'Power sweep at one temperature'
                fields['temperature_source'] = 'Simulator' if legacy_control else 'Label only'
                fields['regulate'] = 'Yes' if legacy_control else 'No (read temperatures only)'
                if 'temperatures' in fields:
                    values = self.parse_list(fields['temperatures'])
                    fields['single_temperature_mk'] = str(values[0] * 1000)
                    fields['temperatures_mk'] = ', '.join(str(x * 1000) for x in values)
                if 'temperature_tolerance_k' in fields:
                    fields['temperature_tolerance_mk'] = str(float(fields['temperature_tolerance_k']) * 1000)
                if 'temperature_timeout_s' in fields:
                    fields['temperature_timeout_min'] = str(float(fields['temperature_timeout_s']) / 60)
            old = {k: v.get() for k, v in self.vars.items()}
            old_batch = list(self.batch)
            old_selected = self.selected_batch_index
            try:
                for key, value in data['fields'].items():
                    if key in self.vars:
                        self.vars[key].set(str(value))
                if data.get('resonators'):
                    self.set_batch([ResonatorConfig.from_dict(r) for r in data['resonators']])
                    self.selected_batch_index = min(data.get('selected_resonator') or 0, len(self.batch) - 1)
                    self.refresh_batch()
                else:
                    self.set_batch([self.editor_resonator()])
                self.config()
                self.update_temperature_generator()
            except Exception:
                self.batch, self.selected_batch_index = old_batch, old_selected
                self.refresh_batch()
                for key, value in old.items():
                    self.vars[key].set(value)
                raise
        except Exception as exc:
            messagebox.showerror('Settings', str(exc))

    def busy(self, enabled):
        self.start.configure(state='disabled' if enabled else 'normal')
        self.stop.configure(state='normal' if enabled else 'disabled')
        for widget in self.profile_widgets:
            widget.configure(state='disabled' if enabled else ('readonly' if isinstance(widget, ttk.Combobox) else 'normal'))
        if not enabled:
            self.update_temperature_generator()

    def reset_plot(self):
        for ax in (self.ax_mag, self.ax_phase):
            ax.clear()
            ax.grid(True, alpha=0.2)
        self.ax_mag.set_ylabel('Magnitude (dB)')
        self.ax_phase.set_ylabel('Unwrapped phase (rad)')
        self.ax_phase.set_xlabel('Frequency (GHz)')
        self.ax_mag.set_title('Complex S-parameter traces', loc='left', fontsize=12)
        self.figure.tight_layout()

    def start_run(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            config = self.config()
        except Exception as exc:
            messagebox.showerror('Check sweep settings', str(exc))
            return
        backend = self.vars['backend'].get()
        address = self.vars['address'].get().strip()
        root = self.vars['output_root'].get().strip()
        self.cancel.clear()
        self.run_path = None
        self.trace_cache = {r.name: deque(maxlen=40) for r in config.resonator_plan}
        self.plot_selector.configure(values=[r.name for r in config.resonator_plan])
        self.plot_resonator.set(config.resonator_plan[0].name)
        self.notebook.select(self.trace_page)
        self.thermal_history.clear()
        self.thermal_start_utc = datetime.now(timezone.utc).timestamp()
        self.thermal_line.set_data([], [])
        self.thermal_target_line.set_data([], [])
        self.thermal_plot.draw_idle()
        self.temperature_status.set('Temperature not measured · no controller connection' if config.thermometry.backend == 'none' else 'Waiting for thermometer readings…')
        self.thermal_ax.set_title(('SIMULATED · ' if backend == 'Simulator' else '') + 'Temperature history', loc='left', fontsize=12)
        self.reset_plot()
        self.ax_mag.set_title(('SIMULATED · ' if backend == 'Simulator' else '') + config.resonator + ' · ' + config.sweep.s_parameter, loc='left', fontsize=12)
        self.plot.draw_idle()
        self.progress.configure(value=0, maximum=config.total_traces)
        self.busy(True)
        self.summary.set('Connecting…' if backend != 'Simulator' else 'Starting simulated run…')
        def work():
            runner = None
            vna = None
            try:
                vna = SimulatedVNA() if backend == 'Simulator' else SiglentVNA(address)
                controller, reader = create_temperature_devices(config, vna)
                runner = ResonatorPowerSweep(vna, controller, reader)
                runner.run(config, root, self.cancel, lambda kind, data: self.queue.put((kind, data)))
            except Exception as exc:
                # Runner already emits finished on failure; constructor failures need one here.
                if runner is None:
                    if vna is not None:
                        try:
                            vna.close()
                        except Exception as close_error:
                            self.queue.put(('error', 'VNA close: ' + str(close_error)))
                    self.queue.put(('finished', {'status': 'failed', 'error': str(exc), 'path': None, 'cleanup_errors': []}))
                self.queue.put(('error', str(exc)))
            finally:
                self.queue.put(('worker_done', None))
        self.worker = threading.Thread(target=work, name='VNA acquisition', daemon=False)
        self.worker.start()

    def stop_run(self):
        self.cancel.set()
        self.stop.configure(state='disabled')
        self.summary.set('Stop requested; VNA waits for its acquisition or timeout. LSCI Reader is unchanged.')

    def scan_resources(self):
        if self.worker and self.worker.is_alive():
            return
        self.busy(True)
        self.stop.configure(state='disabled')
        self.summary.set('Searching VISA resources…')
        def work():
            rm = None
            try:
                import pyvisa
                rm = pyvisa.ResourceManager()
                self.queue.put(('resources', [address for address in rm.list_resources() if not address.upper().startswith('ASRL')]))
            except Exception as exc:
                self.queue.put(('error', 'VISA discovery: ' + str(exc)))
            finally:
                try:
                    if rm is not None:
                        rm.close()
                except Exception as exc:
                    self.queue.put(('error', 'VISA discovery cleanup: ' + str(exc)))
                finally:
                    self.queue.put(('worker_done', None))
        self.worker = threading.Thread(target=work, name='VISA discovery', daemon=False)
        self.worker.start()

    def append_log(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', message + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def poll(self):
        thermal_dirty = False
        try:
            while True:
                kind, data = self.queue.get_nowait()
                if kind == 'status':
                    if not self.cancel.is_set():
                        self.summary.set(data)
                    self.append_log(data)
                elif kind == 'run_started':
                    self.run_path = Path(data)
                    self.location.set('Data: ' + data)
                    self.append_log('Run folder: ' + data)
                elif kind == 'temperature':
                    value = data['primary_kelvin']
                    target = data.get('pid', {}).get('target_k')
                    stamp = data.get('ended_utc') or data.get('read_ended_utc')
                    elapsed = ((datetime.fromisoformat(stamp).timestamp() if stamp else datetime.now(timezone.utc).timestamp()) - self.thermal_start_utc) / 60
                    self.thermal_history.append((elapsed, value * 1000, target * 1000 if target is not None else float('nan')))
                    self.temperature_status.set('Measured: {:.4g} mK · {}'.format(value * 1000, 'SIMULATED' if data.get('simulated') else ('LSCI log · age {:.0f} s'.format(data['age_s']) if data.get('source') == 'lsci_log' else 'Lake Shore')))
                    thermal_dirty = True
                elif kind == 'stability':
                    if data.get('error'):
                        self.summary.set('Temperature error: ' + data['error'])
                        self.append_log(data['error'])
                    elif not self.cancel.is_set():
                        self.summary.set('{} {:.4g} mK · measured {:.4g} mK · stable {:.1f} / {:.1f} min'.format(
                            'Cooling to base' if data['cooling'] else 'Stabilizing at', data['target_k'] * 1000,
                            data['kelvin'] * 1000, data['stable_s'] / 60, data['required_s'] / 60))
                elif kind == 'resonator':
                    if self.follow_active.get():
                        self.plot_resonator.set(data['name'])
                        self.draw_resonator_plot()
                elif kind == 'trace':
                    trace = data['trace']
                    name = trace.metadata['resonator']
                    self.trace_cache.setdefault(name, deque(maxlen=40)).append(trace)
                    if self.follow_active.get():
                        self.plot_resonator.set(name)
                    self.draw_resonator_plot()
                    self.progress.configure(value=data['completed'])
                    self.append_log('{} · saved {}'.format(name, Path(data['path']).name))
                elif kind == 'finished':
                    self.summary.set(data['status'].capitalize() + (' · ' + data['error'] if data.get('error') else ''))
                    self.append_log('Run ' + data['status'])
                    for error in data.get('cleanup_errors', []):
                        self.append_log('Cleanup error: ' + error)
                    if self.run_path and self.ax_mag.lines:
                        try:
                            selected_plot = self.plot_resonator.get()
                            for index, name in enumerate(self.trace_cache):
                                if self.trace_cache[name]:
                                    self.plot_resonator.set(name)
                                    self.draw_resonator_plot()
                                    self.figure.savefig(str(self.run_path / 'overview_resonator_{:03d}.png'.format(index)), dpi=150)
                            self.plot_resonator.set(selected_plot)
                            self.draw_resonator_plot()
                            self.figure.savefig(str(self.run_path / 'overview.png'), dpi=150)
                            if self.thermal_history:
                                self.update_thermal_plot()
                                self.thermal_figure.savefig(str(self.run_path / 'temperature_history.png'), dpi=150)
                        except Exception as exc:
                            self.append_log('Could not save overview: ' + str(exc))
                elif kind == 'error':
                    self.summary.set('Failed · ' + data)
                    self.append_log('ERROR: ' + data)
                    if not self.closing:
                        messagebox.showerror('Acquisition error', data)
                elif kind == 'resources':
                    self.summary.set('VISA resources: ' + (', '.join(data) if data else 'none found'))
                    self.append_log(self.summary.get())
                    if len(data) == 1:
                        self.vars['address'].set(data[0])
                    elif data:
                        messagebox.showinfo('VISA instruments', 'Copy the intended address into VISA address:\n\n' + '\n'.join(data))
                elif kind == 'worker_done':
                    self.busy(False)
        except queue.Empty:
            pass
        if thermal_dirty:
            self.update_thermal_plot()
        if self.closing and (not self.worker or not self.worker.is_alive()):
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def update_thermal_plot(self):
        if self.thermal_history:
            elapsed, values, targets = zip(*self.thermal_history)
            self.thermal_line.set_data(elapsed, values)
            self.thermal_target_line.set_data(elapsed, targets)
            self.thermal_ax.relim()
            self.thermal_ax.autoscale_view()
            self.thermal_plot.draw_idle()

    def close(self):
        if self.worker and self.worker.is_alive():
            self.closing = True
            self.stop_run()
            self.location.set('Waiting for instrument cleanup before closing…')
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    ResonatorApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
