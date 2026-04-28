# Sample Run: SciBench Atkins Task 1

This document shows the shape of a successful end-to-end run for the example used in the README.

## Problem

Given an ethane gas sample with:

- `n = 10.0 mol`
- `V = 4.860 dm^3`
- `T = 27°C`

predict the pressure in `atm`.

## Extracted Initial Facts

```text
temperature_c(27.0)
moles(10.0)
volume(4.860)
```

## Generated Streams

```text
temp_to_K
Converts temperature from Celsius to Kelvin.
Formula: T_K = T_C + 273.15
Requires temperature_c.
Produces temperature_K

pressure_from_nRT
Computes pressure using the ideal gas law.
Formula: P = n * 0.082057 * T_K / V
Requires moles, volume, temperature_K.
Produces pressure

final_answer
Produces the final numeric pressure value and marks completion.
Requires pressure.
Produces answer and (done)
```

## Evaluation Snapshot

See [sample_atkins_evaluation.json](sample_atkins_evaluation.json) for the corresponding evaluation output.
