"""Regression coverage for readable chart annotations."""
import unittest

import matplotlib.pyplot as plt

from meteostation.weather_map.render import (
    style_contour_labels,
    suppress_conflicting_contour_labels,
)


class WeatherLabelLayoutTests(unittest.TestCase):
    def test_only_intersecting_contour_labels_are_hidden_at_both_dpis(self):
        for dpi in (100, 180):
            with self.subTest(dpi=dpi):
                figure, axis = plt.subplots(figsize=(10, 8), dpi=dpi)
                try:
                    axis.set(xlim=(70, 145), ylim=(15, 60))
                    axis.set_aspect(1.25)
                    overlapping = axis.text(120, 30, "584", fontsize=17)
                    nearby = axis.text(120, 35, "588", fontsize=17)
                    style_contour_labels([overlapping, nearby])
                    axis.text(120, 30, "22W EXAMPLE\n985 hPa · 40 kt", fontsize=17)
                    centre_value = axis.text(110, 25, "586", fontsize=17)
                    suppress_conflicting_contour_labels(axis, markers=[])
                    self.assertFalse(overlapping.get_visible())
                    self.assertTrue(nearby.get_visible())
                    self.assertTrue(centre_value.get_visible())
                finally:
                    plt.close(figure)
