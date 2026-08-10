import unittest

import numpy as np
import xarray as xr

from meteostation.reanalysis import FIELDS, _field_values


class ReanalysisFieldTests(unittest.TestCase):
    def test_temperature_is_converted_from_kelvin(self) -> None:
        dataset = xr.Dataset(
            {"t": (("latitude", "longitude"), np.array([[273.15, 274.15]]))},
            coords={"latitude": [31.0], "longitude": [121.0, 122.0]},
        )

        values = _field_values(dataset, FIELDS["temperature"], "temperature")

        np.testing.assert_allclose(values, [[0.0, 1.0]], atol=1e-6)

    def test_geopotential_is_converted_to_geopotential_metres(self) -> None:
        dataset = xr.Dataset(
            {"z": (("latitude", "longitude"), np.array([[98066.5]]))},
            coords={"latitude": [31.0], "longitude": [121.0]},
        )

        values = _field_values(
            dataset,
            FIELDS["geopotential_height"],
            "geopotential_height",
        )

        np.testing.assert_allclose(values, [[10000.0]], atol=1e-6)

    def test_wind_speed_uses_both_components(self) -> None:
        dataset = xr.Dataset(
            {
                "u": (("latitude", "longitude"), np.array([[3.0]])),
                "v": (("latitude", "longitude"), np.array([[4.0]])),
            },
            coords={"latitude": [31.0], "longitude": [121.0]},
        )

        values = _field_values(dataset, FIELDS["wind_speed"], "wind_speed")

        np.testing.assert_allclose(values, [[5.0]], atol=1e-6)


if __name__ == "__main__":
    unittest.main()
