"""Starting cutoffs from the system design. Tune these against fixtures."""

HIGH_CONFIDENCE = 0.85
LOW_CONFIDENCE = 0.60
NEAR_MISS_MAX_DISTANCE = 2
NEAR_MISS_MIN_SIMILARITY = 0.90
# Percentage points. 45 and 45.0 match; 45 and 40 do not.
ABV_TOLERANCE_POINTS = 0.05
VOLUME_TOLERANCE_RATIO = 0.005
ML_PER_FL_OZ = 29.5735
# A second line at least this fraction of the tallest leftover line is another possible brand.
BRAND_HEIGHT_RATIO = 0.85
