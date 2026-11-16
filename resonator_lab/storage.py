"""Versioned raw complex data, atomic files, and a run manifest.

No pickle or Python objects in NPZ. CSV and NPZ contain the same samples.
"""
import csv
import json
import os
import re
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from .model import Trace

SCHEMA_VERSION = '1.2'
SUPPORTED_SCHEMAS = ('1.0', '1.1', '1.2')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write('\n')
    os.replace(str(temp), str(path))


class RunStore:
    def __init__(self, root, config, instrument):
        slug = re.sub(r'[^A-Za-z0-9_.-]+', '_', config.run_name).strip('._') or 'resonator'
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ') + '_' + slug + '_' + uuid.uuid4().hex[:8]
        self.path = Path(root).expanduser().resolve() / name
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / 'traces').mkdir()
        self._thermal_lock = threading.Lock()
        self.thermal_fields = ['read_ended_utc', 'snapshot_ended_utc', 'phase', 'channel', 'kelvin',
                               'resistance_ohm', 'excitation_power_w', 'quadrature_ohm',
                               'temperature_target_k', 'simulated', 'source_timestamp_utc', 'age_s', 'log_file', 'source_line']
        with (self.path / 'temperature_log.csv').open('w', newline='', encoding='utf-8') as stream:
            csv.DictWriter(stream, fieldnames=self.thermal_fields).writeheader()
        self.manifest = {
            'schema_version': SCHEMA_VERSION,
            'run_id': name,
            'created_utc': utc_now(),
            'status': 'running',
            'config': config.to_dict(),
            'instrument': {'identity': instrument.identity, 'address': instrument.address},
            'data_definition': {
                'frequency_hz': 'Frequency in Hz; strictly increasing.',
                's_real': 'Real part of dimensionless complex S-parameter.',
                's_imag': 'Imaginary part of dimensionless complex S-parameter.',
                'npz': 'frequency_hz (float64), s_complex (complex128); allow_pickle=False.',
                'processing': 'No magnitude offsets, normalization, phase subtraction, or fitting applied.',
                'calibration': 'Loaded VNA calibration is not changed. Siglent adapter reads SENS1:DATA:RAWD?; correction semantics must be verified on your firmware.',
            },
            'traces': [],
            'measurement_order': ['temperature', 'resonator', 'power'],
            'configuration_history': [],
            'temperature_log_csv': 'temperature_log.csv',
        }
        atomic_json(self.path / 'manifest.json', self.manifest)
        atomic_json(self.path / 'config.json', config.to_dict())

    def set_effective_settings(self, settings):
        self.manifest['effective_settings'] = settings
        self.flush()

    def record_configuration(self, temperature_index, resonator_index, resonator, settings):
        self.manifest['configuration_history'].append({
            'temperature_index': temperature_index, 'resonator_index': resonator_index,
            'resonator': resonator.name, 'requested_settings': resonator.to_dict()['sweep'],
            'effective_settings': dict(settings), 'configured_utc': utc_now()})
        # Retain this legacy field as the first configuration, not the last one.
        self.manifest.setdefault('effective_settings', dict(settings))
        self.flush()

    def flush(self):
        atomic_json(self.path / 'manifest.json', self.manifest)

    def save(self, trace):
        trace.validate()
        index = len(self.manifest['traces'])
        stem = 'trace_{:05d}'.format(index)
        base = self.path / 'traces' / stem
        npz_path = base.with_suffix('.npz')
        temp = npz_path.with_suffix('.npz.tmp')
        with temp.open('wb') as stream:
            np.savez_compressed(stream, frequency_hz=np.asarray(trace.frequency_hz, dtype=np.float64),
                                s_complex=np.asarray(trace.s_complex, dtype=np.complex128))
        os.replace(str(temp), str(npz_path))
        csv_path = base.with_suffix('.csv')
        temp = csv_path.with_suffix('.csv.tmp')
        with temp.open('w', newline='', encoding='utf-8') as stream:
            stream.write('frequency_hz,s_real,s_imag\n')
            np.savetxt(stream, np.column_stack((trace.frequency_hz, trace.s_complex.real, trace.s_complex.imag)),
                       delimiter=',', fmt='%.17g')
        os.replace(str(temp), str(csv_path))
        metadata = dict(trace.metadata, schema_version=SCHEMA_VERSION, run_id=self.manifest['run_id'], trace_index=index,
                        npz='traces/' + stem + '.npz', csv='traces/' + stem + '.csv')
        atomic_json(base.with_suffix('.json'), metadata)
        self.manifest['traces'].append(dict(metadata, metadata='traces/' + stem + '.json'))
        self.flush()
        return npz_path

    def log_temperature(self, snapshot, phase='monitor'):
        channels = snapshot.get('channels') or {snapshot.get('primary_channel', 'primary'): {
            'kelvin': snapshot['primary_kelvin'], 'read_ended_utc': snapshot.get('read_ended_utc', utc_now())}}
        rows = []
        for channel, reading in channels.items():
            row = {name: reading.get(name) for name in self.thermal_fields}
            row.update(snapshot_ended_utc=snapshot.get('ended_utc'), phase=phase, channel=channel,
                       temperature_target_k=snapshot.get('pid', {}).get('target_k'),
                       simulated=snapshot.get('simulated', False))
            rows.append(row)
        with self._thermal_lock:
            with (self.path / 'temperature_log.csv').open('a', newline='', encoding='utf-8') as stream:
                csv.DictWriter(stream, fieldnames=self.thermal_fields).writerows(rows)

    def finish(self, status, error=None, cleanup_errors=None):
        self.manifest.update(status=status, ended_utc=utc_now(), error=error,
                             cleanup_errors=cleanup_errors or [])
        self.flush()


def load_trace(path):
    """Load a stored NPZ with matching metadata, suitable for fitting complex Sij."""
    path = Path(path)
    with np.load(str(path), allow_pickle=False) as data:
        f = data['frequency_hz'].copy()
        z = data['s_complex'].copy()
    with path.with_suffix('.json').open(encoding='utf-8') as stream:
        meta = json.load(stream)
    if meta.get('schema_version') not in SUPPORTED_SCHEMAS:
        raise ValueError('Unsupported trace schema version.')
    trace = Trace(f, z, meta)
    trace.validate()
    return trace


def iter_run(path):
    """Yield completed traces in acquisition order, including interrupted runs."""
    path = Path(path)
    with (path / 'manifest.json').open(encoding='utf-8') as stream:
        manifest = json.load(stream)
    if manifest.get('schema_version') not in SUPPORTED_SCHEMAS:
        raise ValueError('Unsupported run schema version.')
    for record in manifest['traces']:
        yield load_trace(path / record['npz'])
