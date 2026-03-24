from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone


class CustomerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_profile')
    full_name = models.CharField(max_length=200)
    shipping_address = models.TextField()

    def __str__(self):
        return self.full_name


class Product(models.Model):
    title = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=300, unique=True)
    description = models.TextField(blank=True)
    authors = models.CharField(max_length=500, blank=True)
    publisher = models.CharField(max_length=255, blank=True)
    published_date = models.CharField(max_length=50, blank=True)
    category = models.CharField(max_length=255, blank=True, db_index=True)

    base_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    thumbnail_url = models.URLField(max_length=1000, blank=True)

    is_active = models.BooleanField(default=True)
    is_configurable = models.BooleanField(default=False)
    is_duplicate = models.BooleanField(default=False)
    master_product = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='duplicates')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    @property
    def display_price(self):
        default_variant = self.variants.filter(is_default=True).first()
        if default_variant:
            return default_variant.effective_price
        return self.base_price


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image_url = models.URLField(max_length=1000)
    alt_text = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.product.title} image {self.id}"


class ProductOption(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='options')
    name = models.CharField(max_length=100)  # e.g. Format

    class Meta:
        unique_together = ('product', 'name')

    def __str__(self):
        return f"{self.product.title} - {self.name}"


class ProductOptionValue(models.Model):
    option = models.ForeignKey(ProductOption, on_delete=models.CASCADE, related_name='values')
    value = models.CharField(max_length=100)  # e.g. Paperback / Hardcover
    price_delta = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    display_image_url = models.URLField(max_length=1000, blank=True)  # for D2 visual differentiation

    class Meta:
        unique_together = ('option', 'value')
        ordering = ['id']

    def __str__(self):
        return f"{self.option.name}: {self.value}"


class ProductVariant(models.Model):
    INVENTORY_STATUS_CHOICES = [
        ('in_stock', 'In stock'),
        ('out_of_stock', 'Out of stock'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=64, unique=True, db_index=True)
    price_delta = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    inventory_status = models.CharField(max_length=20, choices=INVENTORY_STATUS_CHOICES, default='in_stock')
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.sku

    @property
    def effective_price(self):
        return self.product.base_price + self.price_delta

    @property
    def is_in_stock(self):
        return self.inventory_status == 'in_stock'

    @property
    def config_summary(self):
        pairs = self.variant_values.select_related('option_value__option').all()
        if not pairs.exists():
            return "Simple"
        return ", ".join([f"{p.option_value.option.name}: {p.option_value.value}" for p in pairs])


class ProductVariantSelection(models.Model):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='variant_values')
    option_value = models.ForeignKey(ProductOptionValue, on_delete=models.CASCADE, related_name='variant_links')

    class Meta:
        unique_together = ('variant', 'option_value')

    def __str__(self):
        return f"{self.variant.sku} -> {self.option_value}"


class BookReview(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='imported_reviews')
    external_user_id = models.CharField(max_length=100, blank=True)
    profile_name = models.CharField(max_length=255, blank=True)
    score = models.DecimalField(max_digits=3, decimal_places=1)
    review_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.product.title} review {self.id}"


class Cart(models.Model):
    customer = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart({self.customer.username})"

    @property
    def total_amount(self):
        total = Decimal('0.00')
        for item in self.items.select_related('variant__product'):
            total += item.subtotal
        return total


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('cart', 'variant')

    def __str__(self):
        return f"{self.variant.sku} x {self.quantity}"

    @property
    def subtotal(self):
        return self.variant.effective_price * self.quantity


class PurchaseOrder(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_HOLD = 'hold'
    STATUS_SHIPPED = 'shipped'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_HOLD, 'Hold'),
        (STATUS_SHIPPED, 'Shipped'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    po_number = models.CharField(max_length=20, unique=True, db_index=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    customer_name_snapshot = models.CharField(max_length=200)
    shipping_address_snapshot = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    purchase_date = models.DateTimeField(default=timezone.now)
    hold_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchase_date', '-id']

    def __str__(self):
        return self.po_number


class PurchaseOrderItem(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='ordered_items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='ordered_items')

    product_title_snapshot = models.CharField(max_length=255)
    variant_summary_snapshot = models.CharField(max_length=255, blank=True)
    sku_snapshot = models.CharField(max_length=64)
    unit_price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)

    quantity = models.PositiveIntegerField(default=1)
    subtotal_snapshot = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.order.po_number} - {self.sku_snapshot}"


class OrderStatusLog(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='status_logs')
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-changed_at', '-id']

    def __str__(self):
        return f"{self.order.po_number}: {self.from_status} -> {self.to_status}"

class CustomerReview(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='customer_reviews')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_reviews')

    rating = models.PositiveSmallIntegerField()  # 1-5
    review_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        unique_together = ('product', 'user')  # one review per user per product

    def __str__(self):
        return f"{self.product.title} - {self.user.username} ({self.rating})"

