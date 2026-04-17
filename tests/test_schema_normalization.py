import pandas as pd

from mfethuls.schema_normalization import apply_dataframe_schema


def test_apply_dataframe_schema_renames_and_casts_dsc_mettler_columns():
    df = pd.DataFrame(
        {
            "Tr [\u00b0C]": ["25.0", "26.5"],
            "Value [mW]": ["0.12", "0.15"],
            "name": ["run_1", "run_1"],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="dsc",
        instrument_model="mettler_toledo",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.1"
    assert "temperature_C" in normalized.columns
    assert "heat_flow_mW" in normalized.columns
    assert "Tr [\u00b0C]" not in normalized.columns
    assert "Value [mW]" not in normalized.columns
    assert str(normalized["temperature_C"].dtype) == "float64"
    assert str(normalized["heat_flow_mW"].dtype) == "float64"


def test_apply_dataframe_schema_renames_and_casts_tga_columns():
    df = pd.DataFrame(
        {
            "Temperature [°C]": [25.0, 30.0],
            "Mass [%]": [100.0, 99.5],
            "Time [s]": [0.0, 10.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="tga",
        instrument_model="tgaX",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["missing_required_columns"] == []
    assert "temperature_C" in normalized.columns
    assert "mass_pct" in normalized.columns
    assert "time_s" in normalized.columns
    assert "Temperature [°C]" not in normalized.columns
    assert "Mass [%]" not in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_ftir_columns():
    df = pd.DataFrame(
        {
            "Wavenumber [cm-1]": [4000.0, 3999.0],
            "Transmittance [%]": [95.0, 94.5],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="ftir",
        instrument_model="bruker",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["missing_required_columns"] == []
    assert "wavenumber_cm_inv" in normalized.columns
    assert "transmittance_pct" in normalized.columns
    assert "Wavenumber [cm-1]" not in normalized.columns
    assert "Transmittance [%]" not in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_ftir_absorbance_columns():
    df = pd.DataFrame(
        {
            "Wavenumber [cm-1]": [4000.0, 3999.0],
            "Absorbance": [0.10, 0.11],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="ftir",
        instrument_model="bruker",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["missing_required_columns"] == []
    assert "wavenumber_cm_inv" in normalized.columns
    assert "absorbance_a_u" in normalized.columns
    assert "Wavenumber [cm-1]" not in normalized.columns
    assert "Absorbance" not in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_saxs_columns():
    df = pd.DataFrame(
        {
            "q": [0.10, 0.20],
            "I": [1000.0, 900.0],
            "dI": [10.0, 9.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="saxs",
        instrument_model="anton_paar",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["missing_required_columns"] == []
    assert "q_inv_nm" in normalized.columns
    assert "intensity_a_u" in normalized.columns
    assert "intensity_error_a_u" in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_ms_columns():
    df = pd.DataFrame(
        {
            "m/z": [100.0, 101.0],
            "intensity": [5000.0, 5200.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="ms",
        instrument_model="bruker",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["missing_required_columns"] == []
    assert "mz" in normalized.columns
    assert "intensity_a_u" in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_sec_columns():
    df = pd.DataFrame(
        {
            "time (min)": [5.0, 5.1],
            "value": [0.2, 0.25],
            "Detector": ["ri", "ri"],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="sec",
        instrument_model="agilent",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["missing_required_columns"] == []
    assert "retention_time_min" in normalized.columns
    assert "detector_response_a_u" in normalized.columns
    assert "detector_name" in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_nmr_columns():
    df = pd.DataFrame(
        {
            "ppm": [1.0, 0.9],
            "intensity": [100.0, 120.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="nmr",
        instrument_model="bruker_nmr",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["missing_required_columns"] == []
    assert "chemical_shift_ppm" in normalized.columns
    assert "intensity_a_u" in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_uv_vis_flame_columns():
    df = pd.DataFrame(
        {
            "wavelength (nm)": [400.0, 450.0],
            "transmission": [0.8, 0.75],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="uv_vis",
        instrument_model="flame",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["missing_required_columns"] == []
    assert "wavelength_nm" in normalized.columns
    assert "transmittance_pct" in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_uv_vis_shimadzu_columns():
    df = pd.DataFrame(
        {
            "Wavelength (nm)": [400.0, 450.0],
            "Absorbance": [0.10, 0.12],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="uv_vis",
        instrument_model="Shimadzu",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["missing_required_columns"] == []
    assert "wavelength_nm" in normalized.columns
    assert "absorbance_a_u" in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_dma_temperature_sweep_columns():
    df = pd.DataFrame(
        {
            "Temperature [°C]": [25.0, 30.0],
            "Storage Modulus [Pa]": [1000.0, 1100.0],
            "Loss Modulus [Pa]": [200.0, 220.0],
            "tan delta": [0.20, 0.21],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="dma",
        instrument_model="ta_q800",
        measurement_profile="oscillatory_temperature_sweep",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["measurement_profile"] == "oscillatory_temperature_sweep"
    assert report["layers_applied"]["profile"] is True
    assert report["missing_required_columns"] == []
    assert "temperature_C" in normalized.columns
    assert "storage_modulus_pa" in normalized.columns
    assert "loss_modulus_pa" in normalized.columns
    assert "tan_delta" in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_dma_frequency_sweep_columns():
    df = pd.DataFrame(
        {
            "Frequency [Hz]": [1.0, 10.0],
            "Storage Modulus [Pa]": [1000.0, 1100.0],
            "Loss Modulus [Pa]": [200.0, 220.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="dma",
        instrument_model="ta_q800",
        measurement_profile="oscillatory_frequency_sweep",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["measurement_profile"] == "oscillatory_frequency_sweep"
    assert report["layers_applied"]["profile"] is True
    assert report["missing_required_columns"] == []
    assert "frequency_hz" in normalized.columns
    assert "storage_modulus_pa" in normalized.columns
    assert "loss_modulus_pa" in normalized.columns


def test_apply_dataframe_schema_renames_and_casts_dma_strain_sweep_columns():
    df = pd.DataFrame(
        {
            "Strain [%]": [0.1, 0.2],
            "Storage Modulus [Pa]": [1000.0, 1100.0],
            "Loss Modulus [Pa]": [200.0, 220.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="dma",
        instrument_model="ta_q800",
        measurement_profile="oscillatory_strain_sweep",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["measurement_profile"] == "oscillatory_strain_sweep"
    assert report["layers_applied"]["profile"] is True
    assert report["missing_required_columns"] == []
    assert "strain_pct" in normalized.columns
    assert "storage_modulus_pa" in normalized.columns
    assert "loss_modulus_pa" in normalized.columns


def test_apply_dataframe_schema_returns_report_when_schema_missing():
    df = pd.DataFrame({"a": [1, 2]})

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="unknown_type",
        instrument_model="unknown_model",
    )

    assert normalized.equals(df)
    assert report["schema_applied"] is False
    assert report["schema_version"] is None
    assert report["missing_required_columns"] == []
    assert report["warnings"]


def test_apply_dataframe_schema_layered_rheometer_profile_required_columns():
    df = pd.DataFrame(
        {
            "w [rad/s]": [1.0, 2.0],
            "gamma [%]": [0.1, 0.2],
            "t [s]": [0.0, 1.0],
            "T [\u00b0C]": [25.0, 25.0],
            "G' [Pa]": [1000.0, 1100.0],
            "G'' [Pa]": [200.0, 220.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="rheometer",
        instrument_model="anton_paar",
        measurement_profile="oscillatory_frequency_sweep",
    )

    assert report["schema_applied"] is True
    assert report["schema_version"] == "1.0"
    assert report["measurement_profile"] == "oscillatory_frequency_sweep"
    assert report["layers_applied"]["profile"] is True
    assert report["missing_required_columns"] == []
    assert "angular_frequency_rad_s" in normalized.columns
    assert "storage_modulus_pa" in normalized.columns
    assert "loss_modulus_pa" in normalized.columns


def test_apply_dataframe_schema_layered_rheometer_oscillatory_strain_sweep_profile_required_columns():
    df = pd.DataFrame(
        {
            "gamma [%]": [0.1, 0.2],
            "w [rad/s]": [1.0, 1.0],
            "G' [Pa]": [1000.0, 1100.0],
            "G'' [Pa]": [200.0, 220.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="rheometer",
        instrument_model="anton_paar",
        measurement_profile="oscillatory_strain_sweep",
    )

    assert report["schema_applied"] is True
    assert report["measurement_profile"] == "oscillatory_strain_sweep"
    assert report["layers_applied"]["profile"] is True
    assert report["missing_required_columns"] == []
    assert "strain_pct" in normalized.columns
    assert "storage_modulus_pa" in normalized.columns
    assert "loss_modulus_pa" in normalized.columns


def test_apply_dataframe_schema_layered_rheometer_oscillatory_time_sweep_profile_required_columns():
    df = pd.DataFrame(
        {
            "t [s]": [0.0, 1.0],
            "T [\u00b0C]": [25.0, 25.0],
            "G' [Pa]": [1000.0, 1100.0],
            "G'' [Pa]": [200.0, 220.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="rheometer",
        instrument_model="anton_paar",
        measurement_profile="oscillatory_time_sweep",
    )

    assert report["schema_applied"] is True
    assert report["measurement_profile"] == "oscillatory_time_sweep"
    assert report["layers_applied"]["profile"] is True
    assert report["missing_required_columns"] == []
    assert "time_s" in normalized.columns
    assert "temperature_C" in normalized.columns
    assert "storage_modulus_pa" in normalized.columns
    assert "loss_modulus_pa" in normalized.columns


def test_apply_dataframe_schema_layered_rheometer_unknown_profile_warns():
    df = pd.DataFrame(
        {
            "t [s]": [0.0, 1.0],
            "T [\u00b0C]": [25.0, 25.0],
        }
    )

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="rheometer",
        instrument_model="anton_paar",
        measurement_profile="unknown_profile",
    )

    assert "time_s" in normalized.columns
    assert "temperature_C" in normalized.columns
    assert any("Unknown measurement_profile" in warning for warning in report["warnings"])
