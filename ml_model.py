import os
from sentence_transformers import SentenceTransformer
from PIL import Image

class CLIPModelWrapper:
    def __init__(self):
        print("Loading Dual CLIP Models...")
        # 1. Official CLIP for Vision Processing
        self.img_model = SentenceTransformer('clip-ViT-B-32')
        # 2. Multilingual alignment model for Text (Portuguese)
        self.text_model = SentenceTransformer('clip-ViT-B-32-multilingual-v1')
        print("Both Models Loaded Successfully!")

    def encode_image(self, image_path: str) -> list[float]:
        """Reads an image from disk and returns its embedding vector."""
        try:
            # We open the image and make sure it's RGB
            img = Image.open(image_path).convert('RGB')
            # Use original model for images
            embedding = self.img_model.encode(img)
            return embedding.tolist()
        except Exception as e:
            print(f"Error encoding image {image_path}: {e}")
            return None

    def encode_text(self, text: str) -> list[float]:
        """Returns the embedding vector for a given text query."""
        try:
            embedding = self.text_model.encode([text])[0]
            return embedding.tolist()
        except Exception as e:
            print(f"Error encoding text '{text}': {e}")
            return None

# Singleton instance
clip_engine = CLIPModelWrapper()
