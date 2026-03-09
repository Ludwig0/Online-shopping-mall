from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from .models import CustomerProfile, Product, Cart, PurchaseOrder, CustomerReview,ProductVariant, PurchaseOrderItem 
from .services import Word2VecRecommendationService

# ==================== Block A: Core Functions Tests ====================

class ProductPageTest(TestCase):
    """Test product listing and detail pages"""
    
    def setUp(self):
        """Create test data before each test"""
        self.client = Client()
        self.product = Product.objects.create(
            title='Test Book',
            slug='test-book',
            authors='John Doe',
            category='Fiction',
            base_price=19.99,
            description='A test book description',
            is_active=True
        )
    
    def test_product_list_page_loads(self):
        """Test that product list page returns 200 OK"""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Book')
        self.assertContains(response, 'Books')
    
    def test_product_detail_page_loads(self):
        """Test that product detail page returns 200 OK"""
        response = self.client.get(f'/product/{self.product.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Book')
        self.assertContains(response, 'John Doe')
        self.assertContains(response, '$19.99')
    
    def test_product_search(self):
        """Test product search functionality"""
        response = self.client.get('/', {'q': 'Test'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Book')


class CartTest(TestCase):
    """Test shopping cart functionality"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass123')
        
        self.product = Product.objects.create(
            title='Cart Test Book',
            slug='cart-test-book',
            base_price=15.99,
            is_active=True,
            is_configurable=False
        )
        
        ProductVariant.objects.create(
            product=self.product,
            sku=f"TEST-CART-{self.product.id}",
            price_delta=0,
            inventory_status='in_stock',
            is_default=True
        )

    
    def test_add_to_cart(self):
        """Test adding product to cart"""
        response = self.client.post(
            f'/cart/add/{self.product.id}/',
            {'quantity': 2}
        )
        self.assertEqual(response.status_code, 302)  # Redirect after add
        
        cart = Cart.objects.get(customer=self.user)
        self.assertEqual(cart.items.count(), 1)
        cart_item = cart.items.first()
        self.assertEqual(cart_item.quantity, 2)
    
    def test_cart_detail_page(self):
        """Test cart detail page loads"""
        # First add item to cart
        self.client.post(f'/cart/add/{self.product.id}/', {'quantity': 1})
        
        response = self.client.get('/cart/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cart Test Book')
        self.assertContains(response, '$15.99')


# ==================== Block B: Order Tests ====================

class OrderTest(TestCase):
    """Test order creation and processing"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='orderuser',
            password='orderpass123'
        )
        CustomerProfile.objects.create(
        user=self.user,
        full_name='Test User',
        shipping_address='123 Test St, Test City'
    )
        self.client.login(username='orderuser', password='orderpass123')
        
        self.product = Product.objects.create(
            title='Order Test Book',
            slug='order-test-book',
            base_price=25.50,
            is_active=True,
            is_configurable=False
        )
        ProductVariant.objects.create(
            product=self.product,
            sku=f"TEST-ORDER-{self.product.id}",
            price_delta=0,
            inventory_status='in_stock',
            is_default=True
        )
    def test_checkout(self):
        """Test checkout process"""
        # Add item to cart first
        self.client.post(f'/cart/add/{self.product.id}/', {'quantity': 1})
        
        # Checkout
        response = self.client.post('/checkout/')
        self.assertEqual(response.status_code, 302)  # Redirect to order detail
        
        # Verify order was created
        order = PurchaseOrder.objects.filter(customer=self.user).first()
        self.assertIsNotNone(order)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.total_amount, 25.50)
    
    def test_order_list_page(self):
        """Test order list page loads"""
        response = self.client.get('/orders/')
        self.assertEqual(response.status_code, 200)


# ==================== Block S: Recommendation Tests ====================

class RecommendationTest(TestCase):
    """Test AI recommendation system"""
    
    def setUp(self):
        # Create test products
        self.product1 = Product.objects.create(
            title='Python Programming',
            slug='python-programming',
            authors='John Smith',
            category='Technology',
            publisher='Tech Press',
            description='Learn Python from scratch',
            is_active=True
        )
        
        self.product2 = Product.objects.create(
            title='Java Programming',
            slug='java-programming',
            authors='John Smith',
            category='Technology',
            publisher='Tech Press',
            description='Master Java programming',
            is_active=True
        )
        
        self.product3 = Product.objects.create(
            title='Cooking 101',
            slug='cooking-101',
            authors='Jane Doe',
            category='Cooking',
            publisher='Food Books',
            description='Easy recipes for beginners',
            is_active=True
        )
    
    def test_similar_products_returns_list(self):
        """Test that similar products returns a list"""
        service = Word2VecRecommendationService()
        similar = service.get_similar_products(self.product1, top_k=2)
        self.assertIsInstance(similar, list)
    
    def test_similar_products_excludes_self(self):
        """Test that similar products doesn't return the same product"""
        service = Word2VecRecommendationService()
        similar = service.get_similar_products(self.product1, top_k=5)
        for product in similar:
            self.assertNotEqual(product.id, self.product1.id)
    
    def test_bestsellers_returns_list(self):
        """Test that bestsellers returns a list"""
        service = Word2VecRecommendationService()
        bestsellers = service.get_bestsellers(top_k=3)
        self.assertIsInstance(bestsellers, list)
        self.assertLessEqual(len(bestsellers), 3)
    
    def test_new_arrivals_returns_list(self):
        """Test that new arrivals returns a list"""
        service = Word2VecRecommendationService()
        new_arrivals = service.get_new_arrivals(top_k=3)
        self.assertIsInstance(new_arrivals, list)
        self.assertLessEqual(len(new_arrivals), 3)


# ==================== Block T: Review Tests ====================

class ReviewTest(TestCase):
    """Test customer review functionality"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='reviewuser',
            password='reviewpass123'
        )
        CustomerProfile.objects.create(
        user=self.user,
        full_name='Test User',
        shipping_address='123 Test Street, Test City, 12345'
    )
        self.product = Product.objects.create(
            title='Review Test Book',
            slug='review-test-book',
            base_price=10.00,
            is_active=True,
            is_configurable=False
        )
        self.variant =ProductVariant.objects.create(
            product=self.product,
            sku=f"TEST-REVIEW-{self.product.id}",
            price_delta=0,
            inventory_status='in_stock',
            is_default=True
        )
        order = PurchaseOrder.objects.create(
            po_number='TEST-ORDER-001',
            customer=self.user,
            customer_name_snapshot='Test User',  # 和上面一致
            shipping_address_snapshot='123 Test Street, Test City, 12345',  # 和上面一致
            status='pending',
            total_amount=10.00
    )
        PurchaseOrderItem.objects.create(
            order=order,
            product=self.product,
            variant=self.variant,
            product_title_snapshot=self.product.title,
            sku_snapshot=self.variant.sku,
            unit_price_snapshot=10.00,
            quantity=1,
            subtotal_snapshot=10.00
    )       
        self.client.login(username='reviewuser', password='reviewpass123')
    
    def test_submit_review(self):
        """Test submitting a product review"""
        response = self.client.post(
            f'/product/{self.product.id}/review/',
            {
                'rating': 5,
                'review_text': 'Excellent book! Highly recommended.'
            }
        )
        self.assertEqual(response.status_code, 302)  # Redirect after submit
        
        # Verify review was created
        review = CustomerReview.objects.filter(
            user=self.user,
            product=self.product
        ).first()
        self.assertIsNotNone(review)
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.review_text, 'Excellent book! Highly recommended.')
    
    def test_review_page_contains_form(self):
        """Test that review form appears on product page"""
        response = self.client.get(f'/product/{self.product.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rating')
        self.assertContains(response, 'review_text')