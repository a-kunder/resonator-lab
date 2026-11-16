"""Reusable experiment orchestration, independent of GUI or instrument transport."""
import math
import threading
import time
from .instruments import Cancelled, check_cancel
from .storage import RunStore, utc_now


class ResonatorPowerSweep:
    """Run temperature -> resonator -> power, using one VNA session for the batch.

    Consumes and closes the supplied VNA and optional temperature controller.

    Events are (kind, payload). Callback errors propagate like acquisition errors.
    RF remains off while changing temperature and is disabled on every exit.
    """
    def __init__(self, vna, temperature_controller=None, temperature_reader=None):
        self.vna = vna
        self.temperature = temperature_controller
        self.reader = temperature_reader or (temperature_controller if hasattr(temperature_controller, 'read_snapshot') else None)
        self.last_run_path = None

    def run(self, config, output_root, cancel=None, on_event=None):
        cancel = cancel if cancel is not None else threading.Event()
        emit = on_event if on_event is not None else lambda kind, data: None
        store = None
        status, error = 'failed', None
        cleanup_errors = []
        try:
            config.validate()
            if config.temperature_mode == 'controlled' and self.temperature is None:
                raise ValueError('A TemperatureController is required for a controlled temperature sweep.')
            if config.thermometry.backend != 'none' and self.reader is None:
                raise ValueError('Configured thermometry requires a TemperatureReader.')
            store = RunStore(output_root, config, self.vna)
            self.last_run_path = store.path
            emit('run_started', str(store.path))
            check_cancel(cancel)
            emit('status', 'Connected: ' + self.vna.identity)
            def record_snapshot(snapshot, phase='monitor'):
                store.log_temperature(snapshot, phase)
                emit('temperature', snapshot)
            if self.reader is not None and hasattr(self.reader, 'start_monitor'):
                self.reader.cancel_event = cancel
                self.reader.start_monitor(record_snapshot, lambda progress: emit('stability', progress))
            total = config.total_traces
            completed = 0
            for ti, target in enumerate(config.temperatures_k):
                check_cancel(cancel)
                self.vna.set_output(False)
                if config.temperature_mode == 'controlled':
                    emit('status', 'Waiting for temperature {:.6g} K to stabilize…'.format(target))
                    self.temperature.set_target(target)
                    measured = self.temperature.wait_until_stable(config.temperature_tolerance_k,
                                                                   config.temperature_timeout_s, cancel)
                    self._check_temperature(measured, target, config.temperature_tolerance_k)
                for ri, resonator in enumerate(config.resonator_plan):
                    check_cancel(cancel)
                    self.vna.set_output(False)
                    emit('status', 'Configuring {} ({}/{})'.format(resonator.name, ri + 1, len(config.resonator_plan)))
                    effective = self.vna.configure(resonator.sweep)
                    store.record_configuration(ti, ri, resonator, effective)
                    emit('resonator', {'name': resonator.name, 'index': ri, 'temperature_index': ti,
                                      'effective_settings': dict(effective)})
                    for pi, requested in enumerate(config.powers_dbm):
                        check_cancel(cancel)
                        actual = self.vna.set_power(requested)
                        self.vna.set_output(True)
                        temperature_text = ('base (read-only temperature log)' if self.reader is not None else 'base (temperature not measured)') if target is None else '{:.6g} K'.format(target)
                        emit('status', '{} [{}/{}] · {:.6g} dBm at {} ({}/{})'.format(resonator.name, ri + 1, len(config.resonator_plan), actual, temperature_text, completed + 1, total))
                        if cancel.wait(resonator.sweep.settle_s):
                            raise Cancelled('Stop requested.')
                        if hasattr(self.temperature, 'ensure_stable_before_trace'):
                            self.temperature.ensure_stable_before_trace(config.temperature_tolerance_k, config.temperature_timeout_s, cancel)
                        before_snapshot = self._read_snapshot(config)
                        before = before_snapshot['primary_kelvin'] if before_snapshot else None
                        if before_snapshot:
                            record_snapshot(before_snapshot, 'before_trace')
                        if config.temperature_mode == 'controlled':
                            self._check_temperature(before, target, config.temperature_tolerance_k)
                        started = utc_now()
                        started_monotonic = time.monotonic()
                        trace = self.vna.acquire(cancel)
                        ended = utc_now()
                        ended_monotonic = time.monotonic()
                        after_error = None
                        try:
                            after_snapshot = self._read_snapshot(config)
                        except Exception as exc:
                            # Never discard acquired complex data because thermometry failed afterwards.
                            after_snapshot = None
                            after_error = '{}: {}'.format(type(exc).__name__, exc)
                        after = after_snapshot['primary_kelvin'] if after_snapshot else None
                        if after_snapshot:
                            record_snapshot(after_snapshot, 'after_trace')
                        # Save even a trace that drifted out of tolerance, flag it, then stop.
                        if after is not None and not math.isfinite(after):
                            after = None
                        within = (self._within(after, target, config.temperature_tolerance_k)
                                  if config.temperature_mode == 'controlled' else None)
                        summary = self.temperature.acquisition_summary(started_monotonic, ended_monotonic, target) if hasattr(self.temperature, 'acquisition_summary') else None
                        if summary and summary['samples_within_tolerance'] is False:
                            within = False
                        trace.metadata.update({
                            'resonator': resonator.name,
                            'resonator_index': ri,
                            'resonator_config': resonator.to_dict(),
                            'batch_name': config.run_name,
                            'notes': config.notes,
                            's_parameter': resonator.sweep.s_parameter,
                            'power_index': pi, 'temperature_index': ti,
                            'vna_power_requested_dbm': requested,
                            'vna_power_readback_dbm': actual,
                            'input_loss_db': config.input_loss_db,
                            'estimated_device_power_dbm': None if config.input_loss_db is None else actual - config.input_loss_db,
                            'temperature_mode': config.temperature_mode,
                            'temperature_target_k': target if config.temperature_mode == 'controlled' else None,
                            'temperature_label_k': target if config.temperature_mode == 'fixed' else None,
                            'temperature_stability_before': before_snapshot.get('stability') if before_snapshot else None,
                            'temperature_acquisition_summary': summary,
                            'temperature_snapshot_before': before_snapshot,
                            'temperature_snapshot_after': after_snapshot,
                            'temperature_read_error_after': after_error,
                            'temperature_logging_enabled': self.reader is not None or config.temperature_mode == 'controlled',
                            'temperature_before_k': before,
                            'temperature_after_k': after,
                            'temperature_within_tolerance': within,
                            'acquisition_started_utc': started, 'acquisition_ended_utc': ended,
                            'effective_settings': effective,
                            'instrument_identity': self.vna.identity,
                            'simulated': self.vna.address == 'simulation',
                        })
                        file = store.save(trace)
                        completed += 1
                        emit('trace', {'trace': trace, 'path': str(file), 'completed': completed, 'total': total})
                        check_cancel(cancel)
                        if summary and summary.get('monitor_error'):
                            raise RuntimeError('Temperature logger failed; acquired trace saved: ' + summary['monitor_error'])
                        if after_error:
                            raise RuntimeError('Temperature read failed after acquisition; trace saved with error: ' + after_error)
                        if within is False:
                            raise RuntimeError('Temperature drifted out of tolerance; last trace saved and flagged.')
            check_cancel(cancel)
            if hasattr(self.temperature, 'finish'):
                self.vna.set_output(False)
                emit('status', 'Sweep complete. Sample heater/PID OFF; monitoring passive return to base…')
                self.temperature.finish(cancel)
            status = 'completed'
        except Cancelled as exc:
            status, error = 'cancelled', str(exc)
        except BaseException as exc:
            error = '{}: {}'.format(type(exc).__name__, exc)
            raise
        finally:
            for label, operation in [('RF output off', lambda: self.vna.set_output(False)),
                                     ('VNA close', self.vna.close),
                                     ('Temperature controller close', self.temperature.close if self.temperature else lambda: None),
                                     ('Temperature reader close', self.reader.close if self.reader is not None and self.reader is not self.temperature else lambda: None)]:
                try:
                    operation()
                except Exception as exc:
                    cleanup_errors.append('{}: {}'.format(label, exc))
            if cleanup_errors and status == 'completed':
                status = 'failed'
                error = 'Cleanup failed: ' + '; '.join(cleanup_errors)
            if store is not None:
                if hasattr(self.temperature, 'shutdown_report'):
                    store.manifest['temperature_shutdown'] = self.temperature.shutdown_report
                store.finish(status, error, cleanup_errors)
            emit('finished', {'status': status, 'error': error, 'cleanup_errors': cleanup_errors,
                              'path': str(store.path) if store else None})
        return store.path if store else None

    def _read_snapshot(self, config):
        if self.reader is not None:
            snapshot = self.reader.read_snapshot()
            value = snapshot.get('primary_kelvin')
            if value is None or not math.isfinite(value) or value <= 0:
                raise ValueError('Temperature reader returned an invalid primary temperature.')
            return snapshot
        if config.temperature_mode == 'controlled':
            value = self.temperature.read_temperature()
            if value is None or not math.isfinite(value) or value <= 0:
                raise ValueError('Temperature controller returned an invalid measurement.')
            return {'source': type(self.temperature).__name__, 'primary_kelvin': value,
                    'read_ended_utc': utc_now(), 'channels': {},
                    'simulated': self.vna.address == 'simulation'}
        return None

    @staticmethod
    def _within(value, target, tolerance):
        return value is not None and math.isfinite(value) and abs(value - target) <= tolerance

    @classmethod
    def _check_temperature(cls, value, target, tolerance):
        if not cls._within(value, target, tolerance):
            raise RuntimeError('Measured temperature is outside the configured tolerance.')
