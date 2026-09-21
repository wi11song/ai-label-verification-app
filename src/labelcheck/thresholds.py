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
MIN_SHORT_EDGE = 600
BLUR_RESIZE_WIDTH = 500
# Variance of the Laplacian on the resized grayscale. Below this, the photo is too soft to read.
BLUR_VARIANCE_MIN = 100
WHITE_LEVEL = 245
WHITE_FRACTION_MAX = 0.90
FLAT_STD_MAX = 12
GLARE_ROW_MEAN = 235
GLARE_BAND_FRACTION = 0.20
GLARE_CONTRAST = 40
MAX_IMAGE_BYTES = 10 * 1024 * 1024
# Long edge of the copy sent to OCR, so CPU time stays predictable.
OCR_LONG_EDGE = 1600
