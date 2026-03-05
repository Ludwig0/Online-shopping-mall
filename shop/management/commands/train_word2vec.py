from django.core.management.base import BaseCommand
from shop.models import Product
from gensim.models import Word2Vec
import numpy as np
import joblib
import os

class Command(BaseCommand):
    help = 'Train Word2Vec model for product recommendations'
    
    def add_arguments(self, parser):
        parser.add_argument('--vector-size', type=int, default=100, help='Word vector dimension')
        parser.add_argument('--window', type=int, default=5, help='Context window size')
        parser.add_argument('--epochs', type=int, default=10, help='Training epochs')
    
    def handle(self, *args, **options):
        self.stdout.write('Starting Word2Vec training...')
        
        products = Product.objects.filter(is_active=True)
        self.stdout.write(f'Found {products.count()} active products')
        
        sentences = []
        for product in products:
            text = f"{product.title} {product.description} {product.authors} {product.category} {product.publisher}"
            words = text.lower().split()
            if len(words) > 3:
                sentences.append(words)
        
        self.stdout.write(f'Prepared {len(sentences)} sentences for training')
        
        self.stdout.write('Training Word2Vec model...')
        model = Word2Vec(
            sentences=sentences,
            vector_size=options['vector_size'],
            window=options['window'],
            min_count=2,
            workers=4,
            epochs=options['epochs']
        )
        
        product_vectors = []
        product_ids = []
        
        for product in products:
            text = f"{product.title} {product.description} {product.authors} {product.category} {product.publisher}"
            words = text.lower().split()
            
            word_vectors = []
            for word in words:
                if word in model.wv:
                    word_vectors.append(model.wv[word])
            
            if word_vectors:
                product_vector = np.mean(word_vectors, axis=0)
            else:
                product_vector = np.zeros(options['vector_size'])
            
            product_vectors.append(product_vector)
            product_ids.append(product.id)
        
        product_vectors = np.array(product_vectors)
        
        self.stdout.write('Computing similarity matrix...')
        norms = np.linalg.norm(product_vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        normalized_vectors = product_vectors / norms
        
        similarity_matrix = np.dot(normalized_vectors, normalized_vectors.T)
        
        os.makedirs('shop/ml_models', exist_ok=True)
        
        model_data = {
            'word2vec_model': model,
            'product_vectors': product_vectors,
            'product_ids': product_ids,
            'similarity_matrix': similarity_matrix,
            'vector_size': options['vector_size']
        }
        
        model_path = 'shop/ml_models/word2vec_recommendation.pkl'
        joblib.dump(model_data, model_path)
        
        self.stdout.write(self.style.SUCCESS(
            f'\nTraining completed!\n'
            f'- Products: {len(product_ids)}\n'
            f'- Vector size: {options["vector_size"]}\n'
            f'- Vocabulary size: {len(model.wv.key_to_index)}\n'
            f'- Model saved: {model_path}'
        ))