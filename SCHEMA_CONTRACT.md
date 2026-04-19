# Schema Contract

This document defines the canonical data contract after parser normalization.

## Scope

1. The contract applies to normalized Dataset.data outputs.
2. Raw export column names are mapped to canonical names through schema aliases.
3. Canonical names and units are stable API for plotting, storage, and future database backends.

## Normalization Rules

1. Required columns are checked after alias mapping.
2. Dtype coercion is best-effort. Failed casts become warnings in schema reports.
3. Unknown measurement profiles are warned and do not crash normalization.
4. No synthetic signal conversion for UV/Vis and FTIR. Only observed source signals are published.
5. Profile-driven instruments can have empty global required columns and enforce requirements at profile level.

## Canonical Column Semantics

1. temperature_C: temperature in degrees Celsius.
2. time_s: time in seconds.
3. heat_flow_mW: heat flow in mW.
4. mass_pct: mass as percent of initial mass.
5. mass_mg: mass in mg.
6. d_mass_dt_pct_min: derivative mass change in percent per minute.
7. wavenumber_cm_inv: FTIR axis in cm^-1.
8. wavelength_nm: optical axis in nm.
9. absorbance_a_u: absorbance, unitless absorbance units.
10. transmittance_pct: transmittance in percent.
11. q_inv_nm: SAXS axis in 1/nm.
12. intensity_a_u: measured signal in arbitrary units when instrument semantics define intensity directly.
13. intensity_error_a_u: uncertainty of intensity in arbitrary units.
14. mz: mass-to-charge ratio.
15. retention_time_min: chromatographic retention time in minutes.
16. detector_response_a_u: SEC detector signal in arbitrary units.
17. detector_name: canonical SEC detector identity.
18. chemical_shift_ppm: NMR axis in ppm.
19. frequency_hz: oscillation frequency in Hz.
20. angular_frequency_rad_s: angular frequency in rad/s.
21. strain_pct: strain amplitude in percent.
22. storage_modulus_pa: storage modulus in Pa.
23. loss_modulus_pa: loss modulus in Pa.
24. tan_delta: tan(delta), unitless.
25. shear_rate_s_inv: shear rate in 1/s.
26. shear_stress_pa: shear stress in Pa.
27. viscosity_pa_s: viscosity in Pa*s.

## Instrument Contracts

1. DSC (schema 1.1): required columns temperature_C, heat_flow_mW.
2. TGA (schema 1.0): required columns temperature_C, mass_pct.
3. FTIR (schema 1.0): required column wavenumber_cm_inv. Signal can be absorbance_a_u or transmittance_pct.
4. UV/Vis (schema 1.0): required column wavelength_nm. Signal can be absorbance_a_u or transmittance_pct.
5. SAXS (schema 1.0): required columns q_inv_nm, intensity_a_u.
6. MS (schema 1.0): required columns mz, intensity_a_u.
7. SEC (schema 1.0): required columns retention_time_min, detector_response_a_u, detector_name.
8. NMR (schema 1.0): required columns chemical_shift_ppm, intensity_a_u.
9. Rheometer (schema 1.0): no global required columns. Requirements are profile-driven.
10. DMA (schema 1.0): no global required columns. Requirements are profile-driven.

## Profile-Driven Requirements

1. Rheometer oscillatory_frequency_sweep: angular_frequency_rad_s, storage_modulus_pa, loss_modulus_pa.
2. Rheometer oscillatory_strain_sweep: strain_pct, storage_modulus_pa, loss_modulus_pa.
3. Rheometer oscillatory_time_sweep: time_s, storage_modulus_pa, loss_modulus_pa.
4. Rheometer flow_curve: shear_rate_s_inv, shear_stress_pa, viscosity_pa_s.
5. DMA oscillatory_temperature_sweep: temperature_C, storage_modulus_pa, loss_modulus_pa.
6. DMA oscillatory_frequency_sweep: frequency_hz, storage_modulus_pa, loss_modulus_pa.
7. DMA oscillatory_strain_sweep: strain_pct, storage_modulus_pa, loss_modulus_pa.

## Database-Facing Guidance

1. Persist canonical columns unchanged.
2. Preserve parser metadata and schema normalization report for provenance.
3. Treat optional canonical signals as nullable.
4. Do not derive absorbance from transmittance or vice versa during ingestion.
5. Keep detector_name explicit for SEC rather than encoding detector identity in filenames.

## Change Management

1. Any schema JSON change that renames canonical columns is a breaking change.
2. Alias additions are backward-compatible.
3. New canonical columns must include semantic definition and unit in this document.
4. Profile requirement changes must be mirrored in tests.