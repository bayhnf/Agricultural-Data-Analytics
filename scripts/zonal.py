"""Small raster zonal reducers shared by assignments 2, 5, and 7."""

from __future__ import annotations

import numpy as np


def categorical_summary(values: np.ndarray, valid_mask: np.ndarray,
                        minimum_coverage: float = 0.70) -> dict:
    """Majority class and pixel coverage over a masked raster region."""
    values = np.asarray(values)
    valid = np.asarray(valid_mask, dtype=bool)
    total_pixels = int(values.size)
    valid_pixels = int(np.count_nonzero(valid))
    coverage_fraction = valid_pixels / total_pixels if total_pixels else 0.0
    result = {
        "value": None,
        "majority_fraction": None,
        "valid_pixels": valid_pixels,
        "total_pixels": total_pixels,
        "coverage_fraction": float(coverage_fraction),
    }
    if valid_pixels and coverage_fraction >= minimum_coverage:
        codes, counts = np.unique(values[valid], return_counts=True)
        index = int(counts.argmax())
        result["value"] = int(codes[index])
        result["majority_fraction"] = float(counts[index] / valid_pixels)
    return result


def continuous_summary(values: np.ndarray, valid_mask: np.ndarray) -> dict:
    """Mean/median of finite valid pixels; reused by assignments 5 and 7."""
    values = np.asarray(values, dtype=float)
    valid = np.asarray(valid_mask, dtype=bool) & np.isfinite(values)
    total_pixels = int(values.size)
    valid_pixels = int(np.count_nonzero(valid))
    coverage_fraction = valid_pixels / total_pixels if total_pixels else 0.0
    if not valid_pixels:
        return {
            "mean": None,
            "median": None,
            "valid_pixels": 0,
            "total_pixels": total_pixels,
            "coverage_fraction": float(coverage_fraction),
        }
    selected = values[valid]
    return {
        "mean": float(np.mean(selected)),
        "median": float(np.median(selected)),
        "valid_pixels": valid_pixels,
        "total_pixels": total_pixels,
        "coverage_fraction": float(coverage_fraction),
    }
