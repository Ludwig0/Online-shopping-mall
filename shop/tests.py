import json
from unittest.mock import patch

from django.test import TestCase, Client
from django.contrib.auth.models import Permission, User
from django.urls import reverse
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from .models import (
    Cart,
    CartItem,
    CustomerProfile,
    CustomerReview,
    Product,
    ProductOption,
    ProductOptionValue,
    ProductVariant,
    ProductVariantSelection,
    ProductChatMessage,
    ProductChatSession,
    PurchaseOrder,
    PurchaseOrderItem,
)
from .services import Word2VecRecommendationService

# ==================== Block A: Core Functions Tests ====================

class ProductPageTest(TestCase):
    """Test product listing and detail pages"""
    
    def setUp(self):
        """Create test data before each test"""
        self.client = Client()
        self.product = Product.objects.create(
            title='Test Book',
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

    def test_product_search_matches_product_id(self):
        response = self.client.get('/', {'q': self.product.slug})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Book')
        self.assertEqual(len(self.product.slug), 8)
        self.assertTrue(self.product.slug.isdigit())


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

    def test_checkout_creates_missing_customer_profile(self):
        user = User.objects.create_user(
            username='orderuser2',
            password='orderpass456'
        )
        self.client.login(username='orderuser2', password='orderpass456')

        product = Product.objects.create(
            title='Order Test Book Two',
            base_price=18.00,
            is_active=True,
            is_configurable=False
        )
        ProductVariant.objects.create(
            product=product,
            sku=f"TEST-ORDER2-{product.id}",
            price_delta=0,
            inventory_status='in_stock',
            is_default=True
        )

        self.client.post(f'/cart/add/{product.id}/', {'quantity': 1})
        response = self.client.post('/checkout/')

        self.assertEqual(response.status_code, 302)
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())
        order = PurchaseOrder.objects.filter(customer=user).first()
        self.assertIsNotNone(order)
        self.assertEqual(order.customer_name_snapshot, 'orderuser2')


# ==================== Block S: Recommendation Tests ====================

class RecommendationTest(TestCase):
    """Test AI recommendation system"""
    
    def setUp(self):
        # Create test products
        self.product1 = Product.objects.create(
            title='Python Programming',
            authors='John Smith',
            category='Technology',
            publisher='Tech Press',
            description='Learn Python from scratch',
            is_active=True
        )
        
        self.product2 = Product.objects.create(
            title='Java Programming',
            authors='John Smith',
            category='Technology',
            publisher='Tech Press',
            description='Master Java programming',
            is_active=True
        )
        
        self.product3 = Product.objects.create(
            title='Cooking 101',
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


class AdminPortalSecurityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='portaluser',
            password='portalpass123'
        )
        self.product = Product.objects.create(
            title='Portal Test Book',
            base_price=12.00,
            is_active=True,
            is_configurable=False
        )
        ProductVariant.objects.create(
            product=self.product,
            sku=f"TEST-PORTAL-{self.product.id}",
            price_delta=0,
            inventory_status='in_stock',
            is_default=True
        )
        self.order = PurchaseOrder.objects.create(
            po_number='PORTAL-ORDER-001',
            customer=self.user,
            customer_name_snapshot='Portal User',
            shipping_address_snapshot='123 Portal Street',
            status='pending',
            total_amount=12.00
        )

    def test_admin_portal_redirects_anonymous_users_to_login(self):
        response = self.client.get('/admin-portal/products/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_admin_portal_forbids_logged_in_users_without_permissions(self):
        self.client.login(username='portaluser', password='portalpass123')
        response = self.client.get('/admin-portal/products/')
        self.assertEqual(response.status_code, 403)

    def test_admin_portal_allows_users_with_assigned_permissions(self):
        self.user.user_permissions.add(
            Permission.objects.get(codename='view_product'),
            Permission.objects.get(codename='add_product'),
            Permission.objects.get(codename='change_product'),
            Permission.objects.get(codename='view_purchaseorder'),
            Permission.objects.get(codename='change_purchaseorder'),
        )
        self.client.login(username='portaluser', password='portalpass123')

        product_response = self.client.get('/admin-portal/products/')
        order_response = self.client.get('/admin-portal/orders/')

        self.assertEqual(product_response.status_code, 200)
        self.assertEqual(order_response.status_code, 200)


class AdminProductConfigurationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='productadmin',
            password='productpass123'
        )
        self.user.user_permissions.add(
            Permission.objects.get(codename='add_product'),
            Permission.objects.get(codename='change_product'),
        )
        self.client.login(username='productadmin', password='productpass123')

    def test_admin_can_create_configurable_product_with_options_and_skus(self):
        options_payload = [
            {
                'client_key': 'option-color',
                'name': 'Color',
                'values': [
                    {
                        'client_key': 'value-white',
                        'value': 'White',
                        'price_delta': '0.00',
                        'display_image_url': 'https://example.com/white.jpg',
                    },
                    {
                        'client_key': 'value-red',
                        'value': 'Red',
                        'price_delta': '2.50',
                        'display_image_url': 'https://example.com/red.jpg',
                    },
                ],
            },
            {
                'client_key': 'option-size',
                'name': 'Size',
                'values': [
                    {
                        'client_key': 'value-small',
                        'value': 'Small',
                        'price_delta': '0.00',
                        'display_image_url': '',
                    },
                    {
                        'client_key': 'value-large',
                        'value': 'Large',
                        'price_delta': '1.50',
                        'display_image_url': '',
                    },
                ],
            },
        ]
        variants_payload = [
            {
                'client_key': 'variant-1',
                'sku': 'TSHIRT-WHITE-S',
                'inventory_status': 'in_stock',
                'is_default': True,
                'selection_keys': ['value-white', 'value-small'],
            },
            {
                'client_key': 'variant-2',
                'sku': 'TSHIRT-RED-L',
                'inventory_status': 'out_of_stock',
                'is_default': False,
                'selection_keys': ['value-red', 'value-large'],
            },
        ]

        response = self.client.post(reverse('admin_product_create'), {
            'title': 'Configurable T-Shirt',
            'description': 'A configurable shirt.',
            'authors': '',
            'publisher': '',
            'published_date': '',
            'category': 'Apparel',
            'base_price': '20.00',
            'thumbnail_url': '',
            'is_active': 'on',
            'is_configurable': 'on',
            'options_payload': json.dumps(options_payload),
            'variants_payload': json.dumps(variants_payload),
            'images-TOTAL_FORMS': '3',
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '1000',
            'images-0-image_url': 'https://example.com/main.jpg',
            'images-0-alt_text': 'Main image',
            'images-0-sort_order': '0',
            'images-1-image_url': '',
            'images-1-alt_text': '',
            'images-1-sort_order': '',
            'images-2-image_url': '',
            'images-2-alt_text': '',
            'images-2-sort_order': '',
            'save_product': '1',
        })

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(title='Configurable T-Shirt')
        self.assertTrue(product.is_configurable)
        self.assertTrue(product.slug.isdigit())
        self.assertEqual(len(product.slug), 8)
        self.assertEqual(product.options.count(), 2)
        self.assertEqual(product.variants.count(), 2)
        self.assertEqual(product.images.count(), 1)
        self.assertEqual(product.variants.get(sku='TSHIRT-RED-L').price_delta, 4)

    def test_admin_can_upload_product_image_file(self):
        image_file = SimpleUploadedFile(
            'cover.jpg',
            b'fake-image-content',
            content_type='image/jpeg'
        )

        response = self.client.post(reverse('admin_product_create'), {
            'title': 'Uploaded Image Product',
            'description': 'Product with uploaded image.',
            'authors': '',
            'publisher': '',
            'published_date': '',
            'category': 'Media',
            'base_price': '10.00',
            'thumbnail_url': '',
            'is_active': 'on',
            'options_payload': '[]',
            'variants_payload': json.dumps([
                {
                    'client_key': 'variant-1',
                    'sku': 'UPLOAD-IMG-1',
                    'inventory_status': 'in_stock',
                    'is_default': True,
                    'selection_keys': [],
                }
            ]),
            'images-TOTAL_FORMS': '3',
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '1000',
            'images-0-image_url': '',
            'images-0-image_file': image_file,
            'images-0-alt_text': 'Uploaded image',
            'images-0-sort_order': '0',
            'images-1-image_url': '',
            'images-1-alt_text': '',
            'images-1-sort_order': '',
            'images-2-image_url': '',
            'images-2-alt_text': '',
            'images-2-sort_order': '',
            'save_product': '1',
        })

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(title='Uploaded Image Product')
        image = product.images.get()
        self.assertTrue(bool(image.image_file))
        self.assertIn('/media/product_images/', image.effective_image_url)

    def test_admin_can_edit_existing_sku(self):
        product = Product.objects.create(
            title='Editable Product',
            description='',
            authors='',
            publisher='',
            published_date='',
            category='General',
            base_price='12.00',
            is_active=True,
            is_configurable=False,
        )
        variant = ProductVariant.objects.create(
            product=product,
            sku='OLD-SKU',
            price_delta=0,
            inventory_status='in_stock',
            is_default=True,
        )

        response = self.client.post(reverse('admin_product_edit', args=[product.id]), {
            'title': product.title,
            'description': product.description,
            'authors': product.authors,
            'publisher': product.publisher,
            'published_date': product.published_date,
            'category': product.category,
            'base_price': '12.00',
            'thumbnail_url': '',
            'is_active': 'on',
            'options_payload': '[]',
            'variants_payload': json.dumps([
                {
                    'id': variant.id,
                    'client_key': f'variant-{variant.id}',
                    'sku': 'NEW-SKU',
                    'inventory_status': 'out_of_stock',
                    'is_default': True,
                    'selection_keys': [],
                }
            ]),
            'images-TOTAL_FORMS': '1',
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '1000',
            'images-0-image_url': '',
            'images-0-alt_text': '',
            'images-0-sort_order': '',
            'save_product': '1',
        })

        self.assertEqual(response.status_code, 302)
        variant.refresh_from_db()
        self.assertEqual(variant.sku, 'NEW-SKU')
        self.assertEqual(variant.inventory_status, 'out_of_stock')


class ConfigurableProductCartTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='configuser',
            password='configpass123'
        )
        CustomerProfile.objects.create(
            user=self.user,
            full_name='Config User',
            shipping_address='123 Config Street'
        )
        self.client.login(username='configuser', password='configpass123')

        self.product = Product.objects.create(
            title='Configurable Hoodie',
            base_price='30.00',
            is_active=True,
            is_configurable=True
        )
        color = ProductOption.objects.create(product=self.product, name='Color')
        size = ProductOption.objects.create(product=self.product, name='Size')
        white = ProductOptionValue.objects.create(
            option=color,
            value='White',
            price_delta='0.00',
            display_image_url='https://example.com/hoodie-white.jpg'
        )
        red = ProductOptionValue.objects.create(
            option=color,
            value='Red',
            price_delta='2.00',
            display_image_url='https://example.com/hoodie-red.jpg'
        )
        small = ProductOptionValue.objects.create(option=size, value='Small', price_delta='0.00')
        large = ProductOptionValue.objects.create(option=size, value='Large', price_delta='3.00')

        self.white_small = ProductVariant.objects.create(
            product=self.product,
            sku='HOODIE-WHITE-S',
            price_delta='0.00',
            inventory_status='in_stock',
            is_default=True
        )
        ProductVariantSelection.objects.create(variant=self.white_small, option_value=white)
        ProductVariantSelection.objects.create(variant=self.white_small, option_value=small)

        self.red_large = ProductVariant.objects.create(
            product=self.product,
            sku='HOODIE-RED-L',
            price_delta='5.00',
            inventory_status='out_of_stock',
            is_default=False
        )
        ProductVariantSelection.objects.create(variant=self.red_large, option_value=red)
        ProductVariantSelection.objects.create(variant=self.red_large, option_value=large)

    def test_configurable_product_requires_selection_before_add_to_cart(self):
        response = self.client.get(reverse('product_detail', args=[self.product.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose a value for each option')

        post_response = self.client.post(reverse('add_to_cart', args=[self.product.id]), {'quantity': 1})
        self.assertEqual(post_response.status_code, 302)
        self.assertFalse(CartItem.objects.exists())

    def test_add_to_cart_uses_selected_variant(self):
        response = self.client.post(reverse('add_to_cart', args=[self.product.id]), {
            'variant_id': self.white_small.id,
            'quantity': 2,
        })

        self.assertEqual(response.status_code, 302)
        item = CartItem.objects.get()
        self.assertEqual(item.variant, self.white_small)
        self.assertEqual(item.quantity, 2)


class ProductAIChatTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='chatuser',
            password='chatpass123'
        )
        self.product = Product.objects.create(
            title='AI Chat Book',
            description='A mystery novel about memory and loss.',
            authors='Jane Author',
            publisher='Fiction House',
            category='Fiction',
            is_active=True,
        )

    def test_chat_requires_login(self):
        response = self.client.get(reverse('product_chat_history', args=[self.product.slug]))
        self.assertEqual(response.status_code, 302)

    def test_ai_chat_page_loads(self):
        response = self.client.get(reverse('product_ai_chat_page', args=[self.product.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Talk About This Book')

    @patch('shop.views.ensure_product_chat_intro')
    def test_history_returns_persisted_messages(self, mock_ensure_intro):
        self.client.login(username='chatuser', password='chatpass123')
        session = ProductChatSession.objects.create(user=self.user, product=self.product)
        ProductChatMessage.objects.create(
            session=session,
            role=ProductChatMessage.ROLE_ASSISTANT,
            content='This is a short AI intro.'
        )
        mock_ensure_intro.return_value = session

        response = self.client.get(reverse('product_chat_history', args=[self.product.slug]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['messages']), 1)
        self.assertEqual(payload['messages'][0]['content'], 'This is a short AI intro.')

    @patch('shop.views.append_product_chat_turn')
    def test_send_message_persists_per_product(self, mock_append_turn):
        self.client.login(username='chatuser', password='chatpass123')
        session = ProductChatSession.objects.create(user=self.user, product=self.product)
        ProductChatMessage.objects.create(
            session=session,
            role=ProductChatMessage.ROLE_ASSISTANT,
            content='Opening summary.'
        )
        ProductChatMessage.objects.create(
            session=session,
            role=ProductChatMessage.ROLE_USER,
            content='What kind of readers may like it?'
        )
        ProductChatMessage.objects.create(
            session=session,
            role=ProductChatMessage.ROLE_ASSISTANT,
            content='Readers who enjoy reflective mysteries may like it.'
        )
        mock_append_turn.return_value = (session, 'Readers who enjoy reflective mysteries may like it.')

        response = self.client.post(
            reverse('product_chat_send', args=[self.product.slug]),
            data=json.dumps({'message': 'What kind of readers may like it?'}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['reply'], 'Readers who enjoy reflective mysteries may like it.')
        self.assertEqual(len(payload['messages']), 3)

    def test_clear_removes_only_current_product_history(self):
        self.client.login(username='chatuser', password='chatpass123')
        another_product = Product.objects.create(
            title='Another Book',
            is_active=True,
        )
        session_a = ProductChatSession.objects.create(user=self.user, product=self.product)
        session_b = ProductChatSession.objects.create(user=self.user, product=another_product)
        ProductChatMessage.objects.create(session=session_a, role=ProductChatMessage.ROLE_ASSISTANT, content='A')
        ProductChatMessage.objects.create(session=session_b, role=ProductChatMessage.ROLE_ASSISTANT, content='B')

        response = self.client.post(reverse('product_chat_clear', args=[self.product.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(session_a.messages.exists())
        self.assertTrue(session_b.messages.exists())

    @patch('shop.views.stream_product_chat_turn')
    def test_stream_endpoint_returns_event_stream(self, mock_stream_turn):
        self.client.login(username='chatuser', password='chatpass123')
        session = ProductChatSession.objects.create(user=self.user, product=self.product)

        def fake_stream():
            yield 'data: {"type":"delta","content":"Hello"}\n\n'
            yield 'data: {"type":"done"}\n\n'

        mock_stream_turn.return_value = (session, fake_stream())

        response = self.client.post(
            reverse('product_chat_stream', args=[self.product.slug]),
            data=json.dumps({'message': 'Hello'}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response['Content-Type'])


@override_settings(
    LOGIN_FAILURE_LIMIT=2,
    LOGIN_FAILURE_WINDOW=60,
    LOGIN_LOCKOUT_SECONDS=60,
)
class LoginRateLimitTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(
            username='ratelimituser',
            password='correctpass123'
        )

    def test_login_is_temporarily_blocked_after_repeated_failures(self):
        self.client.post('/login/', {'username': 'ratelimituser', 'password': 'wrong-pass'})
        self.client.post('/login/', {'username': 'ratelimituser', 'password': 'wrong-pass'})

        response = self.client.post('/login/', {'username': 'ratelimituser', 'password': 'correctpass123'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Too many failed login attempts')
        self.assertNotIn('_auth_user_id', self.client.session)
