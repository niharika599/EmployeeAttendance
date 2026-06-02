from io import BytesIO

import numpy as np
from PIL import Image


def decode_image(data: bytes) -> np.ndarray:
    return np.array(Image.open(BytesIO(data)).convert("RGB"))
