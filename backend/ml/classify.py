"""
AI photo hint - inference helper for the Waste Segregation collector app.

Loads the MobileNetV2 model trained by train_model.py once, and classifies
an uploaded photo as WET (organic) or DRY (recyclable). This is used ONLY
as an optional hint shown to the collector - it never overrides or replaces
the collector's own Good/Average/Poor rating.
"""
import json
import os

import numpy as np
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "waste_classifier.keras")
CLASS_MAP_PATH = os.path.join(BASE_DIR, "class_map.json")
IMG_SIZE = (224, 224)

_model = None
_class_map = None


class ModelNotAvailable(Exception):
    """Raised when the trained model file hasn't been produced yet."""
    pass


def _load_model():
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise ModelNotAvailable(
                f"No trained model found at {MODEL_PATH}. Run "
                "backend/ml/train_model.py first to generate it."
            )
        # Imported lazily so the whole Flask app doesn't pay TensorFlow's
        # import cost on startup if this feature is never used.
        import tensorflow as tf
        _model = tf.keras.models.load_model(MODEL_PATH)
    return _model


def _load_class_map():
    global _class_map
    if _class_map is None:
        with open(CLASS_MAP_PATH) as f:
            _class_map = json.load(f)
    return _class_map


def classify_image(file_stream):
    """
    file_stream: a file-like object opened in binary mode (e.g. Flask's
    request.files['photo'].stream), containing a JPEG/PNG image.

    Returns: {"predicted_class": "WET"|"DRY", "confidence": float 0-1}
    Raises: ModelNotAvailable, ValueError (bad/corrupt image)
    """
    model = _load_model()
    class_map = _load_class_map()

    try:
        image = Image.open(file_stream).convert("RGB").resize(IMG_SIZE)
    except Exception as e:
        raise ValueError(f"Could not read image: {e}")

    arr = np.asarray(image, dtype=np.float32)
    arr = np.expand_dims(arr, axis=0)  # batch of 1; model applies its own preprocessing internally

    score = float(model.predict(arr, verbose=0)[0][0])  # P(class index 1), per training's sigmoid output
    predicted_index = 1 if score >= 0.5 else 0
    confidence = score if predicted_index == 1 else 1 - score
    label = class_map.get(str(predicted_index), "UNKNOWN")

    return {"predicted_class": label, "confidence": round(confidence, 4)}