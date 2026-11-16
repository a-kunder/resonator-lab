"""Run from the project root: python -m examples.read_for_fitting PATH_TO_RUN"""
import sys
from resonator_lab import iter_run

for trace in iter_run(sys.argv[1]):
    frequency_hz = trace.frequency_hz
    s_complex = trace.s_complex
    metadata = trace.metadata
    print(metadata['vna_power_readback_dbm'],
          metadata.get('temperature_before_k'), metadata.get('temperature_after_k'),
          metadata.get('temperature_within_tolerance'), frequency_hz.shape)
    # Pass frequency_hz and s_complex to your existing fitting function.
    # Raw complex values preserve the IQ circle and phase information needed
    # for Qi/Qc fitting. No fitting model is assumed by this acquisition package.
