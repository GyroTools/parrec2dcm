import pytest

from parrec2dcm.diffusion import diffusion_tags

TRANSVERSAL = 1
SAGITTAL = 2
CORONAL = 3


def _image(diffusion_ap_fh_rl, orientation=TRANSVERSAL, b_factor=1000.0):
    return {
        "DiffusionBFactor": b_factor,
        "Diffusion": list(diffusion_ap_fh_rl),
        "SliceOrientation": orientation,
    }


@pytest.mark.parametrize(
    "diffusion_ap_fh_rl,orientation,expected",
    [
        ((0.0, 1.0, 0.0), TRANSVERSAL, "S"),  # slice-select axis only
        ((1.0, 0.0, 0.0), TRANSVERSAL, "M"),
        ((0.0, 0.0, 1.0), TRANSVERSAL, "P"),
        ((0.0, 0.0, 0.0), TRANSVERSAL, "I"),
        ((1.0, 1.0, 0.0), TRANSVERSAL, "O"),
        ((0.0, 1.0, 0.0), SAGITTAL, "M"),
        ((0.0, 0.0, 1.0), CORONAL, "P"),
    ],
)
def test_direction_letter(diffusion_ap_fh_rl, orientation, expected):
    tags = diffusion_tags(_image(diffusion_ap_fh_rl, orientation), diffusion_enabled=True)
    assert tags["private:MRImageDiffusionDirection"] == expected


def test_diffusion_disabled_gives_zero_values():
    tags = diffusion_tags(_image((1.0, 0.0, 0.0)), diffusion_enabled=False)
    assert tags["DiffusionBValue"] == 0.0
    assert tags["DiffusionGradientOrientation"] == [0.0, 0.0, 0.0]
    assert tags["private:MRImageDiffusionDirection"] == ""
