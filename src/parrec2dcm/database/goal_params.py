"""Goal-parameter-derived DICOM tag enrichment -- REL5/REL53 old-format DB only.

Ports the legacy exporter's REL53-native goal-parameter block,
``dicom_get_static_values53`` (``DICOMExporter.m:847-1208``). The
byte-for-byte identical logic also exists as the REL5-catchall
``dicom_get_static_values`` (lines 354-715), differing only by a
``UGN1_``/``UGN0_``/``UGN5_`` parameter-name prefix instead of
``VAL01_``/``VAL00_``/``VAL05_`` -- REL53's own copy is ported here
directly since its names are confirmed present in real goal-parameter
exports (``goal_r11.json``/``goal_r5.json``), with no name-guessing
needed; the legacy ``UGN_``-prefixed naming stays out of scope entirely,
per the project plan.

Confirmed REL5/REL53-only, never REL11: the real REL11 function,
``dicom_get_static_values11`` (line 720), does nothing beyond the plain
DB-value pass -- MATLAB's own top-level dispatch (``Export()``, lines
116-123) routes REL53 to ``dicom_get_static_values53``, REL11 to
``dicom_get_static_values11``, everything else (REL5) to
``dicom_get_static_values``. So this module is wired into ``pipeline.py``
for ``DatabaseTier.OLD`` only, matching that real behavior -- new-format
(REL11) datasets never get this enrichment, in this package or the
original. Internally gated the same way MATLAB gates it,
``EX_ACQ_imaging_sequence`` presence (mirrors
``format_detect.goal_parameters_available``).

``GetValue(name, [], 1)`` / ``GetValue(name, 1)`` -- extracts element 1
(1-based) of a goal parameter's value, which may be a genuine array (e.g.
``PS_volume_ap_angulations``, one slot per stack) or, harmlessly, a
scalar (indexing a scalar at position 1 is a no-op). ``_first`` below
mirrors this.

Deliberately NOT ported: a handful of source lines assign an
Enum-*typed* goal parameter's value directly as a DICOM string (not as a
numeric comparison) -- e.g. ``upper(GetValue('PS_volume_geom_types', 1))``
or the ``strrep(GetValue('RC_receive_coil_types', 1), 'ARGRC_COIL_TYPE_',
'')`` fallback branch. Those calls (no ``[]`` numeric-force argument)
rely on MATLAB's own internal enum-index -> human-readable-string
decoding (via ``Properties.EnumDescription``, an opaque ID with no
lookup table included in a flat parameter JSON export) -- confirmed by
inspecting real fixtures: the raw ``Value`` for these fields is always
the bare numeric index (e.g. ``2``), never a string. Writing that raw
index straight into a DICOM CS field would silently produce a
meaningless value (e.g. ``AcquisitionContrast = "3"``, not a real
enumerated CS value like ``"T1"``), which is worse than omitting the tag
entirely -- so ``AcquisitionContrast`` (``EX_FFE_ceffe``),
``PS_volume_geom_types`` (2005,105D), and ``PS_slab_orientations``
(2005,105E) are skipped, and ``ReceiveCoilType`` only ever resolves to
``MULTICOIL``/``UNKNOWN`` (the two numerically-compared cases), never
the string-decoded fallback. Every OTHER Enum-typed parameter used here
is fine: it's only ever compared numerically against a literal case
number (exactly what MATLAB's own ``switch``/``if`` statements already
decode), never assigned directly as a string.

Also simplified without changing behavior: the source computes
``water_suppress``/``fat_suppress`` via two textually-identical blocks
back to back (lines 922-934 and 940-952 of the REL53 source) -- an
idempotent no-op duplication, collapsed here to run once.
"""

from __future__ import annotations

from typing import Any

from pydicom.datadict import tag_for_keyword

from parrec2dcm.database.format_detect import goal_parameters_available
from parrec2dcm.database.new_format import ResolvedTag, coerce_value, resolve_vr
from parrec2dcm.database.records import ParameterPool

_STEADY_STATE_PULSE_SEQ = {0: "NONE", 1: "LONGITUDINAL", 2: "TIME_REVERSE", 3: "FREE_PRECESSION"}
_TAG_DIMENSION = {0: "LINE", 1: "GRID", 2: "GRID"}
_MTC = {0: "NONE", 1: "ON_RESONANCE", 2: "OFF_RESONANCE", 3: "OFF_RESONANCE"}
_K_SPACE_TRAJ = {0: "RECTILINEAR", 1: "RADIAL", 2: "SPIRAL", 3: "PROPELLER"}
_PROFILE_ORDER = {
    2: "LINEAR",
    3: "REVERSE_LINEAR",
    4: "SEGMENTED",
    8: "SEGMENTED",
    9: "SEGMENTED",
    5: "CENTRIC",
    7: "CENTRIC",
    1: "CENTRIC",
    6: "REVERSE_CENTRIC",
    0: "REVERSE_CENTRIC",
}
_CARDIAC_SIGNAL_SOURCE = {0: "ECG", 2: "ECG", 3: "ECG", 1: "PP"}


def _first(pool: ParameterPool, name: str) -> Any:
    """Element 1 (1-based) of a goal parameter's value -- see module docstring."""
    value = pool.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _has_nonzero(pool: ParameterPool, name: str) -> bool:
    value = _first(pool, name)
    return value is not None and value != 0


def _tag(target: str | tuple[int, int], value: Any) -> ResolvedTag | None:
    """Build a ResolvedTag for a public keyword or explicit (group, element)."""
    if isinstance(target, tuple):
        group, element = target
    else:
        raw_tag = tag_for_keyword(target)
        assert raw_tag is not None, f"unknown DICOM keyword: {target}"
        group, element = raw_tag >> 16, raw_tag & 0xFFFF
    vr = resolve_vr(group, element, {})
    if vr is None:
        return None
    coerced = coerce_value(vr, value)
    if coerced is None:
        return None
    return ResolvedTag(group, element, vr, coerced)


def _tagging(pool: ParameterPool) -> str:
    if not _has_nonzero(pool, "VAL01_TAG_ctagging"):
        return "NONE"
    dimension = _first(pool, "VAL01_TAG_dimension")
    return _TAG_DIMENSION.get(dimension, "NONE") if dimension is not None else "NONE"


def _spectrally_selected_excitation(pool: ParameterPool) -> str:
    if _first(pool, "VAL01_SPIR_mode") == 3:  # MPUSPIR_MODE_PROSET
        return "NONE"
    return "WATER" if _first(pool, "VAL01_SPIR_suppr_tissue") == 0 else "FAT"


def _spectrally_selected_suppression(pool: ParameterPool) -> str:
    water_suppress = _first(pool, "VAL01_MTC_sos") == 1
    fat_suppress = _first(pool, "VAL01_MTC_sos") == 1

    if _first(pool, "VAL01_SPIR_enable") == 1:
        water_suppress = True

    if _has_nonzero(pool, "VAL01_WATSUP_method"):
        water_suppress = True

    in_base = _first(pool, "VAL01_WATSUP_in_base")
    if in_base == 2:  # MPUWATSUP_INBASE_WATER
        water_suppress = True
    elif in_base == 1:  # MPUWATSUP_INBASE_FAT
        fat_suppress = True
    elif in_base == 3:  # MPUWATSUP_INBASE_WATER_FAT
        water_suppress = True
        fat_suppress = True

    if water_suppress and fat_suppress:
        return "FAT_AND_WATER"
    if water_suppress:
        return "WATER"
    if fat_suppress:
        return "FAT"
    return "NONE"


def _rectilinear_phase_encode_reordering(pool: ParameterPool) -> str:
    if _first(pool, "VAL01_ACQ_imaging_sequence") == 3:  # MGUACQ_SEQ_FFE
        outer_order = _first(pool, "VAL01_FFE_outer_profile_orders")
    else:
        outer_order = _first(pool, "VAL01_RFE_outer_profile_orders")
    return _PROFILE_ORDER.get(outer_order, "UNKNOWN") if outer_order is not None else "UNKNOWN"


def _parallel_acquisition_technique(pool: ParameterPool) -> str:
    technique = ""
    if _first(pool, "VAL01_GEO_sense_enable") == 1:
        technique = "SENSE"
    kt_factor = _first(pool, "VAL01_ACQ_kt_factor")
    if kt_factor is not None and kt_factor > 1:
        technique = "KT"
    if pool.has("VAL01_ACQ_MB") and _first(pool, "VAL01_ACQ_MB") == 1:
        technique = "MULTIBAND"
    if pool.has("VAL01_ACQ_caipi") and _first(pool, "VAL01_ACQ_caipi") == 1:
        technique = "MULTIBAND"
    return technique


def _cardiac_signal_source(pool: ParameterPool) -> str:
    if not _has_nonzero(pool, "VAL01_CARD_synchronisation"):
        return ""
    device = _first(pool, "EX_CARD_device")
    return _CARDIAC_SIGNAL_SOURCE.get(device, "") if device is not None else ""


def _coverage_of_k_space(pool: ParameterPool) -> str:
    if _first(pool, "VAL01_ACQ_scan_mode") != 1:
        return ""
    if _first(pool, "VAL00_DEF_elliptical_k_space_shutter") != 1:
        return "FULL"
    return "ELLIPSOIDAL" if _first(pool, "VAL01_ACQ_scan_type") == 1 else "ELLIPTICAL"


def _nr_grad_oris(pool: ParameterPool) -> Any:
    if pool.has("VAL01_DIFF_nr_directions"):
        return _first(pool, "VAL01_DIFF_nr_directions")
    if pool.has("VAL05_DIFF_measured_nr_oris"):
        return _first(pool, "VAL05_DIFF_measured_nr_oris")
    return 1


def _patient_position(pool: ParameterPool) -> str:
    position = "HF" if _first(pool, "EX_GEO_patient_position") == 0 else "FF"
    orientation = _first(pool, "EX_GEO_patient_orientation")
    suffix = {0: "S", 1: "P", 2: "L"}.get(orientation, "R")
    return position + suffix


def _receive_coil_type(pool: ParameterPool) -> str | None:
    coil_type = _first(pool, "RC_receive_coil_types")
    if coil_type == 3:
        return "MULTICOIL"
    if coil_type == 4:
        return "UNKNOWN"
    return None  # string-decoded fallback not portable -- see module docstring


def goal_derived_tags(pool: ParameterPool) -> list[ResolvedTag]:
    """Resolve every goal-parameter-derived tag, if goal parameters are available.

    No-ops (returns ``[]``) when ``EX_ACQ_imaging_sequence`` is absent --
    matches ``dicom_get_static_values53``'s own gate.
    """
    if not goal_parameters_available(pool):
        return []

    pairs: list[tuple[str | tuple[int, int], Any]] = [
        (
            "SteadyStatePulseSequence",
            _STEADY_STATE_PULSE_SEQ.get(_first(pool, "VAL01_FFE_contrast_enh"), "NONE"),
        ),
        ("Tagging", _tagging(pool)),
        ("MagnetizationTransfer", _MTC.get(_first(pool, "VAL01_MTC_enable"), "NONE")),
        ("SpectrallySelectedExcitation", _spectrally_selected_excitation(pool)),
        ("SpectrallySelectedSuppression", _spectrally_selected_suppression(pool)),
        (
            "GeometryOfKSpaceTraversal",
            _K_SPACE_TRAJ.get(_first(pool, "RC_k_space_traj_type"), "RECTILINEAR"),
        ),
        ("RectilinearPhaseEncodeReordering", _rectilinear_phase_encode_reordering(pool)),
        ("ParallelAcquisitionTechnique", _parallel_acquisition_technique(pool)),
        ("CardiacSignalSource", _cardiac_signal_source(pool)),
        ("CoverageOfKSpace", _coverage_of_k_space(pool)),
        ("PatientPosition", _patient_position(pool)),
        ("MRAcquisitionType", "3D" if _first(pool, "VAL01_ACQ_scan_mode") == 1 else "2D"),
        ("QuadratureReceiveCoil", "YES" if _has_nonzero(pool, "RC_quad_receive_coils") else "NO"),
        ("MultipleSpinEcho", "YES" if _first(pool, "VAL01_ACQ_fast_imaging_mode") == 1 else "NO"),
        (
            "MultiPlanarExcitation",
            "YES" if pool.has("VAL01_ACQ_MB") and _first(pool, "VAL01_ACQ_MB") == 1 else "NO",
        ),
        ("PhaseContrast", "YES" if _first(pool, "EX_PC_angio_mode") == 2 else "NO"),
        ("TimeOfFlightContrast", "YES" if _first(pool, "EX_PC_angio_mode") == 1 else "NO"),
        (
            "Spoiling",
            "RF"
            if _first(pool, "MPF_RFE_rf_spoil_mode") == 1
            and _first(pool, "VAL01_FFE_contrast_enh") == 1
            else "NONE",
        ),
        (
            "EchoPlanarPulseSequence",
            "YES" if _first(pool, "VAL01_ACQ_fast_imaging_mode") in (3, 4, 5) else "NO",
        ),
        ("T2Preparation", "YES" if _first(pool, "VAL01_T2PREP_enable") == 1 else "NO"),
        ("BloodSignalNulling", "YES" if _first(pool, "VAL01_TFEPP_type") == 3 else "NO"),
        (
            "SaturationRecovery",
            "YES"
            if _first(pool, "VAL01_ACQ_tfe_excitations") == 1
            and _first(pool, "VAL01_TFEPP_type") == 2
            else "NO",
        ),
        ("Decoupling", "YES" if _has_nonzero(pool, "VAL01_SPY_decouple") else "NO"),
        ((0x2001, 0x1009), pool.get("VW_prepulse_delay")),
        ((0x2005, 0x1415), _nr_grad_oris(pool)),
        ((0x2005, 0x1054), _first(pool, "PS_volume_ap_angulations")),
        ((0x2005, 0x1055), _first(pool, "PS_volume_fh_angulations")),
        ((0x2005, 0x1056), _first(pool, "PS_volume_rl_angulations")),
        ((0x2005, 0x1057), _first(pool, "PS_volume_ap_fovs")),
        ((0x2005, 0x1058), _first(pool, "PS_volume_fh_fovs")),
        ((0x2005, 0x1059), _first(pool, "PS_volume_rl_fovs")),
        ((0x2005, 0x105A), _first(pool, "PS_volume_ap_offcentres")),
        ((0x2005, 0x105B), _first(pool, "PS_volume_fh_offcentres")),
        ((0x2005, 0x105C), _first(pool, "PS_volume_rl_offcentres")),
        ((0x2001, 0x1001), _first(pool, "RC_chemical_shifts")),
    ]

    if pool.has("HW_main_magnetic_field_mT"):
        field_strength_mt = pool.get("HW_main_magnetic_field_mT")
        pairs.append(("MagneticFieldStrength", field_strength_mt / 1000))
    pairs.append(("PercentPhaseFieldOfView", pool.get("EX_GEO_rect_fov_perc")))
    pairs.append(("AcquisitionDuration", pool.get("AC_total_scan_time")))

    receive_coil_type = _receive_coil_type(pool)
    if receive_coil_type is not None:
        pairs.append(("ReceiveCoilType", receive_coil_type))

    resolved = []
    for target, value in pairs:
        tag = _tag(target, value)
        if tag is not None:
            resolved.append(tag)
    return resolved
