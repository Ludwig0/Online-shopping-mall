from decimal import Decimal
from email.mime import text
from django.db import transaction
from django.utils import timezone
from numpy.ma import product
from .models import Cart, CartItem, CustomerProfile, PurchaseOrder, PurchaseOrderItem, OrderStatusLog
import numpy as np

def get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(customer=user)
    return cart


def generate_po_number():
    now = timezone.now()
    return f"PO{now.strftime('%Y%m%d%H%M%S%f')[-18:]}"


def get_or_create_customer_profile(user):
    profile, _ = CustomerProfile.objects.get_or_create(
        user=user,
        defaults={
            'full_name': (user.get_full_name() or user.username).strip(),
            'shipping_address': 'Address not provided',
        }
    )
    return profile


@transaction.atomic
def checkout_cart(user):
    cart = get_or_create_cart(user)
    items = list(cart.items.select_related('variant__product', 'variant').all())
    if not items:
        raise ValueError("Cart is empty.")

    for item in items:
        if not item.variant.is_in_stock:
            raise ValueError(f"{item.variant.product.title} ({item.variant.config_summary}) is out of stock.")

    profile = get_or_create_customer_profile(user)

    order = PurchaseOrder.objects.create(
        po_number=generate_po_number(),
        customer=user,
        customer_name_snapshot=profile.full_name,
        shipping_address_snapshot=profile.shipping_address,
        status=PurchaseOrder.STATUS_PENDING,
        purchase_date=timezone.now(),
        total_amount=Decimal('0.00')
    )

    total = Decimal('0.00')
    for item in items:
        unit_price = item.variant.effective_price
        subtotal = unit_price * item.quantity
        PurchaseOrderItem.objects.create(
            order=order,
            product=item.variant.product,
            variant=item.variant,
            product_title_snapshot=item.variant.product.title,
            variant_summary_snapshot=item.variant.config_summary,
            sku_snapshot=item.variant.sku,
            unit_price_snapshot=unit_price,
            quantity=item.quantity,
            subtotal_snapshot=subtotal,
        )
        total += subtotal

    order.total_amount = total
    order.save(update_fields=['total_amount'])

    OrderStatusLog.objects.create(order=order, from_status='', to_status=PurchaseOrder.STATUS_PENDING, note='Order created')

    cart.items.all().delete()
    return order


def transition_order_status(order, new_status, actor='vendor'):
    old_status = order.status
    allowed = {
        PurchaseOrder.STATUS_PENDING: [PurchaseOrder.STATUS_HOLD, PurchaseOrder.STATUS_SHIPPED, PurchaseOrder.STATUS_CANCELLED],
        PurchaseOrder.STATUS_HOLD: [PurchaseOrder.STATUS_SHIPPED, PurchaseOrder.STATUS_CANCELLED],
        PurchaseOrder.STATUS_SHIPPED: [],
        PurchaseOrder.STATUS_CANCELLED: [],
    }

    if new_status not in allowed.get(old_status, []):
        raise ValueError(f"Invalid status transition: {old_status} -> {new_status}")

    order.status = new_status
    now = timezone.now()

    if new_status == PurchaseOrder.STATUS_HOLD:
        order.hold_at = now
    elif new_status == PurchaseOrder.STATUS_SHIPPED:
        order.shipped_at = now
    elif new_status == PurchaseOrder.STATUS_CANCELLED:
        order.cancelled_at = now

    order.save()
    OrderStatusLog.objects.create(order=order, from_status=old_status, to_status=new_status, note=f'By {actor}')
    return order

# ==================== Word2Vec Recommendation Service ====================

import numpy as np
import joblib
import os
from django.db.models import Q, Avg, Count
from .models import Product, BookReview, CartItem, PurchaseOrderItem

class Word2VecRecommendationService:
    """Word2Vec-based recommendation system"""
    
    def __init__(self):
        self.model = None
        self.product_ids = []
        self.similarity_matrix = None
        self.product_vectors = None
        self.model_path = 'shop/ml_models/word2vec_recommendation.pkl'
        self._load_model()
    
    def _load_model(self):
        """Load trained model from disk"""
        if os.path.exists(self.model_path):
            try:
                data = joblib.load(self.model_path)
                self.model = data.get('word2vec_model')
                self.product_ids = data.get('product_ids', [])
                self.similarity_matrix = data.get('similarity_matrix')
                self.product_vectors = data.get('product_vectors')
                self.vector_size = data.get('vector_size', 100)
            except Exception as e:
                print(f"Error loading model: {e}")
                self.model = None
    
    def get_similar_products(self, product, top_k=5):
        """Get similar products based on Word2Vec semantic similarity"""
        if not self.model or not self.product_ids:
            return self._get_fallback_recommendations(top_k, exclude_product_id=product.id)
        
        try:
            # Find product index in the matrix
            if product.id not in self.product_ids:
                return self._get_category_recommendations(product, top_k)
            
            idx = self.product_ids.index(product.id)
            
            # Get similarity scores for this product
            sim_scores = list(enumerate(self.similarity_matrix[idx]))
            
            # Sort by similarity score (descending)
            sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)
            
            # Skip the product itself, take top_k
            sim_scores = sim_scores[1:top_k+1]
            
            # Get recommended products
            similar_products = []
            for i, score in sim_scores:
                try:
                    p = Product.objects.get(id=self.product_ids[i], is_active=True)
                    p.similarity_score = score  # Store score for display
                    similar_products.append(p)
                except Product.DoesNotExist:
                    continue
            
            return similar_products
            
        except Exception as e:
            print(f"Error getting similar products: {e}")
            return self._get_category_recommendations(product, top_k)
    
    def get_bestsellers(self, top_k=10):
        """Get best-selling products based on average review score and review count"""
        from django.db.models import Avg, Count
    
        bestseller_products = []
        product_stats = BookReview.objects.values('product').annotate(
            avg_rating=Avg('score'),
            review_count=Count('id')
        ).order_by('-avg_rating', '-review_count')[:top_k]
    
        product_ids = [item['product'] for item in product_stats]
        if product_ids:
            products = Product.objects.filter(id__in=product_ids, is_active=True)
            product_dict = {p.id: p for p in products}
            bestseller_products = [product_dict[pid] for pid in product_ids if pid in product_dict]
    
        return bestseller_products
    
    def get_new_arrivals(self, top_k=10):
        """Get newly added products"""
        return list(Product.objects.filter(
            is_active=True
        ).order_by('-created_at')[:top_k])
    
    def get_cart_recommendations(self, cart, top_k=5):
        """Get recommendations based on items in user's cart"""
        if not cart or not cart.items.exists():
            return self.get_bestsellers(top_k)
        
        # Get categories from cart items
        categories = cart.items.values_list(
            'variant__product__category', flat=True
        ).distinct()
        
        # Get product IDs already in cart
        cart_product_ids = cart.items.values_list(
            'variant__product_id', flat=True
        )
        
        # Recommend products from same categories
        recommendations = Product.objects.filter(
            category__in=categories,
            is_active=True
        ).exclude(
            id__in=cart_product_ids
        ).order_by('?')[:top_k]
        
        return list(recommendations)
 
    def _get_category_recommendations(self, product, top_k=5):
        """Fallback: category-based recommendations when model fails"""
        return list(Product.objects.filter(
            category=product.category,
            is_active=True
        ).exclude(id=product.id)[:top_k])
    
    def _get_fallback_recommendations(self, top_k=5, exclude_product_id=None):
        """Fallback: random products when no model available"""
        products = list(Product.objects.filter(is_active=True))
        if exclude_product_id is not None:
            products = [product for product in products if product.id != exclude_product_id]
        import random
        random.shuffle(products)
        return products[:top_k]
    
    def add_new_product(self, product):
        """Add a new product to the recommendation model without full retraining"""
        text = f"{product.title} {product.description} {product.authors} {product.category} {product.publisher}"
        words = text.lower().split()

        word_vectors = []
        for word in words:
            if word in self.model.wv:
                word_vectors.append(self.model.wv[word])

        if word_vectors:
            new_vector = np.mean(word_vectors, axis=0)
        else:
            new_vector = np.zeros(self.vector_size)

        self.product_vectors = np.vstack([self.product_vectors, new_vector])
        self.product_ids.append(product.id)

        new_normalized = new_vector / np.linalg.norm(new_vector)
        old_normalized = self.product_vectors[:-1] / np.linalg.norm(self.product_vectors[:-1], axis=1, keepdims=True)
        new_similarities = np.dot(old_normalized, new_normalized)

        new_row = np.append(new_similarities, 1.0)  
        self.similarity_matrix = np.vstack([self.similarity_matrix, new_row[:-1]])  # 加行
        self.similarity_matrix = np.column_stack([self.similarity_matrix, new_row])  # 加列

        self._save_model()

        return True


    def _save_model(self):
        """Save the current model to disk"""
        import joblib
        import os

        os.makedirs('shop/ml_models', exist_ok=True)

        model_data = {
            'word2vec_model': self.model,
            'product_vectors': self.product_vectors,
            'product_ids': self.product_ids,
            'similarity_matrix': self.similarity_matrix,
            'vector_size': self.vector_size
    }

        joblib.dump(model_data, self.model_path)
        print(f"Model saved to {self.model_path}")
