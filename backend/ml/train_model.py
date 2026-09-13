"""
Waste Segregation - AI photo hint model trainer.

Trains a MobileNetV2-based binary classifier (Wet/Organic vs Dry/Recyclable)
on the Kaggle "Waste Classification data" dataset. This is a ONE-TIME,
OFFLINE script - run it manually with `python train_model.py`, not as part
of the Flask app.

The resulting model is used only as an optional hint for the collector -
the human always makes the final Good/Average/Poor rating.

Expects the dataset already downloaded and unzipped at:
    backend/ml_data/DATASET/TRAIN/{O,R}/...
    backend/ml_data/DATASET/TEST/{O,R}/...
(O = Organic/Wet, R = Recyclable/Dry - Kaggle's original folder names)
"""
import json
import os

import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "ml_data", "DATASET")
TRAIN_DIR = os.path.join(DATA_DIR, "TRAIN")
TEST_DIR = os.path.join(DATA_DIR, "TEST")

IMG_SIZE = (224, 224)
BATCH_SIZE = 32
EPOCHS = 10
MODEL_PATH = os.path.join(BASE_DIR, "waste_classifier.keras")
CLASS_MAP_PATH = os.path.join(BASE_DIR, "class_map.json")

print(f"Loading training data from: {TRAIN_DIR}")
train_ds = tf.keras.utils.image_dataset_from_directory(
    TRAIN_DIR, validation_split=0.1, subset="training", seed=42,
    image_size=IMG_SIZE, batch_size=BATCH_SIZE,
)
val_ds = tf.keras.utils.image_dataset_from_directory(
    TRAIN_DIR, validation_split=0.1, subset="validation", seed=42,
    image_size=IMG_SIZE, batch_size=BATCH_SIZE,
)
test_ds = tf.keras.utils.image_dataset_from_directory(
    TEST_DIR, image_size=IMG_SIZE, batch_size=BATCH_SIZE, shuffle=False,
)

class_names = train_ds.class_names  # e.g. ['O', 'R'], sorted alphabetically
print("Class order (0, 1):", class_names)

# Save which index means Wet vs Dry, so the inference script never has to guess.
label_map = {}
for idx, name in enumerate(class_names):
    label_map[str(idx)] = "WET" if name == "O" else "DRY"
with open(CLASS_MAP_PATH, "w") as f:
    json.dump(label_map, f, indent=2)
print("Saved class map:", label_map)

AUTOTUNE = tf.data.AUTOTUNE
train_ds = train_ds.cache().shuffle(1000).prefetch(buffer_size=AUTOTUNE)
val_ds = val_ds.cache().prefetch(buffer_size=AUTOTUNE)
test_ds = test_ds.cache().prefetch(buffer_size=AUTOTUNE)

data_augmentation = models.Sequential([
    layers.RandomFlip("horizontal"),
    layers.RandomRotation(0.08),
    layers.RandomZoom(0.1),
])

base_model = tf.keras.applications.MobileNetV2(
    input_shape=IMG_SIZE + (3,), include_top=False, weights="imagenet",
)
base_model.trainable = False  # feature extraction only - keeps CPU training time reasonable

inputs = tf.keras.Input(shape=IMG_SIZE + (3,))
x = data_augmentation(inputs)
x = preprocess_input(x)
x = base_model(x, training=False)
x = layers.GlobalAveragePooling2D()(x)
x = layers.Dropout(0.2)(x)
outputs = layers.Dense(1, activation="sigmoid")(x)
model = models.Model(inputs, outputs)

model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
    loss="binary_crossentropy",
    metrics=["accuracy"],
)
model.summary()

print(f"\nTraining for {EPOCHS} epochs - this will take a while on CPU. Please be patient.\n")
history = model.fit(train_ds, validation_data=val_ds, epochs=EPOCHS)

print("\nEvaluating on held-out TEST set...")
test_loss, test_acc = model.evaluate(test_ds)
print(f"Test accuracy: {test_acc:.4f}  (test loss: {test_loss:.4f})")

model.save(MODEL_PATH)
print(f"\nModel saved to: {MODEL_PATH}")
print("Training complete. This model is ready to be loaded by the Flask backend.")