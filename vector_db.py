import chromadb
from chromadb.config import Settings
import os

# We will store the vector database in a folder called 'chroma_data'
CHROMA_DATA_PATH = "./chroma_data"
COLLECTION_NAME = "fotosai_collection"

class VectorDB:
    def __init__(self):
        os.makedirs(CHROMA_DATA_PATH, exist_ok=True)
        # Initialize chroma client with persistent storage
        self.client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)
        
        # Get or create the collection
        # We specify cosine similarity as the space, common for CLIP embeddings
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

    def add_image_embedding(self, image_id: str, embedding: list[float], metadata: dict = None):
        """
        Adds an image embedding to the vector database.
        """
        metadatas = [metadata] if metadata else None
        
        self.collection.add(
            ids=[image_id],
            embeddings=[embedding],
            metadatas=metadatas
        )

    def search_by_embedding(self, query_embedding: list[float], n_results: int = 50):
        """
        Searches the database for the closest image embeddings.
        """
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        return results

    def check_exists(self, image_id: str) -> bool:
        """
        Checks if an image ID is already in the vector database.
        """
        try:
            res = self.collection.get(ids=[image_id])
            return len(res['ids']) > 0
        except Exception:
            return False

    def delete_embeddings(self, ids: list[str]):
        """ Deletes embeddings by their IDs """
        if ids:
            self.collection.delete(ids=ids)

vector_db = VectorDB()
