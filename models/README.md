# Local face models

The application downloads these unquantized model files automatically on first face-index operation into this directory:

- YuNet face detector: OpenCV Zoo, MIT license.
- SFace face recognizer: OpenCV Zoo, Apache 2.0 license.

The application deliberately uses the unquantized SFace model, not the quantized ONNX variant that triggered the OpenCV DequantizeLinear importer error in the previous implementation.

Models are downloaded from the official OpenCV Zoo repository. They are not committed to Git because they are external model weights.

The first face-index operation needs Internet access to download the model files. Later use is local/offline while the models remain cached.
