from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Q, Avg, Count
from django.forms import inlineformset_factory
from django.http import Http404
from django.utils import timezone
from .models import OrderStatusLog
from django.shortcuts import get_object_or_404, redirect, render
from .services import get_or_create_cart, checkout_cart, transition_order_status, Word2VecRecommendationService

from .forms import RegisterForm, CartQuantityForm, ProductForm, ProductImageForm, VariantStockForm, CustomerReviewForm
from .models import (
    Product, ProductImage, ProductOption, ProductOptionValue, ProductVariant,
    ProductVariantSelection, CartItem, PurchaseOrder, CustomerReview
)
from .services import get_or_create_cart, checkout_cart, transition_order_status

def user_has_purchased_product(user, product):
    if not user.is_authenticated:
        return False
    return PurchaseOrder.objects.filter(
        customer=user,
        items__product=product
    ).exclude(
        status=PurchaseOrder.STATUS_CANCELLED
    ).exists()

def product_list(request):
    q = request.GET.get('q', '').strip()
    products = Product.objects.filter(is_active=True).prefetch_related('images', 'variants')
    
    if q:
        from django.db.models import Case, When, Value, IntegerField
        
        products = products.annotate(
            relevance=Case(
                When(title__icontains=q, then=Value(3)),
                When(authors__icontains=q, then=Value(2)),
                When(publisher__icontains=q, then=Value(1)),
                When(description__icontains=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            )
        ).filter(relevance__gt=0).order_by('-relevance', 'title')
        
    else:
        products = products.order_by('title')
    
    paginator = Paginator(products, 16)
    page_obj = paginator.get_page(request.GET.get('page'))
       # ===== Bestsellers and New Arrivals =====
    try:
        rec_service = Word2VecRecommendationService()

        bestsellers = rec_service.get_bestsellers(top_k=30)
        new_arrivals = rec_service.get_new_arrivals(top_k=6) 
    except Exception as e:
        print(f"Recommendation error: {e}")
        bestsellers = []
        new_arrivals = []
    return render(request, 'shop/product_list.html', {
        'page_obj': page_obj,
        'q': q,
        'bestsellers': bestsellers,
        'new_arrivals': new_arrivals,
        })


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.prefetch_related(
            'images',
            'options__values',
            'variants__variant_values__option_value__option',
            'imported_reviews',
            'customer_reviews__user',
        ),
        slug=slug,
        is_active=True
    )

    selected_variant = None
    selected_value_id = request.GET.get('format')
    option = product.options.first()

    if product.is_configurable and option:
        if selected_value_id and selected_value_id.isdigit():
            selected_variant = (
                product.variants.filter(variant_values__option_value_id=int(selected_value_id))
                .distinct().first()
            )
        if not selected_variant:
            selected_variant = product.variants.filter(is_default=True).first() or product.variants.first()
    else:
        selected_variant = product.variants.filter(is_default=True).first() or product.variants.first()

    can_review = user_has_purchased_product(request.user, product)
    existing_customer_review = None
    review_form = None

    if request.user.is_authenticated:
        existing_customer_review = CustomerReview.objects.filter(product=product, user=request.user).first()
        if can_review:
            review_form = CustomerReviewForm(instance=existing_customer_review)

    imported_reviews = product.imported_reviews.all()[:10]  # display first 10 imported reviews

    # Use only real customer reviews (not imported ones) to compute rating stats.
    # Limit the reviews fetched for display to keep page load fast.
    customer_reviews = CustomerReview.objects.filter(product=product).select_related('user').order_by('-created_at')[:10]
    rating_stats = CustomerReview.objects.filter(product=product).aggregate(avg=Avg('rating'), count=Count('id'))
    customer_avg_rating = rating_stats.get('avg') or 0
    customer_review_count = rating_stats.get('count') or 0

# ===== Word2Vec Recommendations =====
    try:
        rec_service = Word2VecRecommendationService()
        similar_products = rec_service.get_similar_products(product, top_k=5)
    except Exception as e:
        print(f"Recommendation error: {e}")
        similar_products = []
    # ====================================
    return render(request, 'shop/product_detail.html', {
        'product': product,
        'selected_variant': selected_variant,
        'option': option,
        'imported_reviews': imported_reviews,
        'customer_reviews': customer_reviews,
        'customer_avg_rating': customer_avg_rating,
        'customer_review_count': customer_review_count,
        'can_review': can_review,
        'existing_customer_review': existing_customer_review,
        'review_form': review_form,
        'similar_products': similar_products,
    })

@login_required
def submit_product_review(request, product_id):
    if request.method != 'POST':
        return redirect('product_list')

    product = get_object_or_404(Product, id=product_id, is_active=True)

    if not user_has_purchased_product(request.user, product):
        messages.error(request, "Only customers who purchased this product can submit a review.")
        return redirect('product_detail', slug=product.slug)

    existing_review = CustomerReview.objects.filter(product=product, user=request.user).first()
    form = CustomerReviewForm(request.POST, instance=existing_review)

    if form.is_valid():
        review = form.save(commit=False)
        review.product = product
        review.user = request.user
        review.save()
        if existing_review:
            messages.success(request, "Your review has been updated.")
        else:
            messages.success(request, "Your review has been submitted.")
    else:
        messages.error(request, "Invalid review form. Please check your rating and review text.")

    return redirect('product_detail', slug=product.slug)


def register_view(request):
    if request.user.is_authenticated:
        return redirect('product_list')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Your account has been created.")
            return redirect('product_list')
    else:
        form = RegisterForm()

    return render(request, 'shop/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('product_list')

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        messages.success(request, "Signed in successfully.")
        return redirect('product_list')

    return render(request, 'shop/login.html', {'form': form})


@login_required
def add_to_cart(request, product_id):
    if request.method != 'POST':
        return redirect('product_list')

    product = get_object_or_404(Product, id=product_id, is_active=True)
    cart = get_or_create_cart(request.user)

    variant_id = request.POST.get('variant_id')
    quantity_str = request.POST.get('quantity', '1')

    try:
        quantity = max(1, min(99, int(quantity_str)))
    except ValueError:
        quantity = 1

    if variant_id:
        variant = get_object_or_404(ProductVariant, id=variant_id, product=product)
    else:
        variant = product.variants.filter(is_default=True).first() or product.variants.first()

    if not variant:
        messages.error(request, "No purchasable SKU is configured for this product.")
        return redirect('product_detail', slug=product.slug)

    if not variant.is_in_stock:
        messages.error(request, "This configuration is currently out of stock.")
        return redirect('product_detail', slug=product.slug)

    item, created = CartItem.objects.get_or_create(cart=cart, variant=variant, defaults={'quantity': quantity})
    if not created:
        item.quantity = min(99, item.quantity + quantity)
        item.save(update_fields=['quantity'])

    messages.success(request, "Item added to cart.")
    return redirect('cart_detail')


@login_required
def cart_detail(request):
    cart = get_or_create_cart(request.user)
    items = cart.items.select_related('variant__product').all()
    forms = {item.id: CartQuantityForm(initial={'quantity': item.quantity}) for item in items}
    # ===== Cart Recommendations =====
    try:
        rec_service = Word2VecRecommendationService()
        cart_recommendations = rec_service.get_cart_recommendations(cart, top_k=5)
    except Exception as e:
        print(f"Cart recommendation error: {e}")
        cart_recommendations = []
    # ================================
    return render(request, 'shop/cart_detail.html', {
        'cart': cart, 'items': items, 'forms': forms, 'cart_recommendations': cart_recommendations})


@login_required
def cart_update_item(request, item_id):
    if request.method != 'POST':
        return redirect('cart_detail')

    cart = get_or_create_cart(request.user)
    item = get_object_or_404(CartItem, id=item_id, cart=cart)
    form = CartQuantityForm(request.POST)
    if form.is_valid():
        item.quantity = form.cleaned_data['quantity']
        item.save(update_fields=['quantity'])
        messages.success(request, "Cart updated.")
    else:
        messages.error(request, "Invalid quantity.")
    return redirect('cart_detail')


@login_required
def cart_remove_item(request, item_id):
    if request.method == 'POST':
        cart = get_or_create_cart(request.user)
        item = get_object_or_404(CartItem, id=item_id, cart=cart)
        item.delete()
        messages.success(request, "Item removed from cart.")
    return redirect('cart_detail')


@login_required
def checkout_view(request):
    if request.method != 'POST':
        return redirect('cart_detail')

    try:
        order = checkout_cart(request.user)
        messages.success(request, f"Order created: {order.po_number}")
        return redirect('order_detail', order_id=order.id)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('cart_detail')


@login_required
def order_list(request):
    status = request.GET.get('status', '').strip()
    orders = PurchaseOrder.objects.filter(customer=request.user).prefetch_related('items')

    if status:
        orders = orders.filter(status=status)

    return render(request, 'shop/order_list.html', {
        'orders': orders,
        'status': status,
        'status_choices': PurchaseOrder.STATUS_CHOICES,
    })


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(
        PurchaseOrder.objects.prefetch_related('items', 'status_logs'),
        id=order_id,
        customer=request.user
    )
    return render(request, 'shop/order_detail.html', {'order': order, 'is_vendor_view': False})


@login_required
def customer_cancel_order(request, order_id):
    if request.method != 'POST':
        return redirect('order_list')
    order = get_object_or_404(PurchaseOrder, id=order_id, customer=request.user)
    try:
        transition_order_status(order, PurchaseOrder.STATUS_CANCELLED, actor='customer')
        messages.success(request, "Order cancelled.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('order_detail', order_id=order.id)


# -----------------------------
# Admin portal (basic spec: no auth required)
# -----------------------------

def admin_product_list(request):
    q = request.GET.get('q', '').strip()
    products = Product.objects.prefetch_related('variants').all()

    if q:
        products = products.filter(
            Q(title__icontains=q) |
            Q(slug__icontains=q) |
            Q(variants__sku__icontains=q)
        ).distinct()

    return render(request, 'shop/admin/product_list.html', {'products': products.order_by('title'), 'q': q})


def admin_product_create(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save()
            messages.success(request, "Product created.")
            return redirect('admin_product_edit', product_id=product.id)
    else:
        form = ProductForm()

    return render(request, 'shop/admin/product_form.html', {'form': form, 'mode': 'Create'})


def admin_product_edit(request, product_id):
    product = get_object_or_404(Product.objects.prefetch_related('images', 'variants', 'options__values'), id=product_id)

    ImageFormSet = inlineformset_factory(Product, ProductImage, form=ProductImageForm, extra=1, can_delete=True)

    if request.method == 'POST':
        if 'save_product' in request.POST:
            form = ProductForm(request.POST, instance=product)
            formset = ImageFormSet(instance=product)
            if form.is_valid():
                form.save()
                messages.success(request, "Product saved.")
                return redirect('admin_product_edit', product_id=product.id)
        elif 'save_images' in request.POST:
            form = ProductForm(instance=product)
            formset = ImageFormSet(request.POST, instance=product)
            if formset.is_valid():
                formset.save()
                messages.success(request, "Images updated.")
                return redirect('admin_product_edit', product_id=product.id)
        else:
            form = ProductForm(instance=product)
            formset = ImageFormSet(instance=product)
    else:
        form = ProductForm(instance=product)
        formset = ImageFormSet(instance=product)

    return render(request, 'shop/admin/product_form.html', {
        'form': form,
        'formset': formset,
        'product': product,
        'mode': 'Edit'
    })


def admin_product_toggle_active(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        product.is_active = not product.is_active
        product.save(update_fields=['is_active'])
        messages.success(request, f"Product {'enabled' if product.is_active else 'disabled'}.")
    return redirect('admin_product_list')


def admin_order_list(request):
    status = request.GET.get('status', '').strip()
    orders = PurchaseOrder.objects.select_related('customer').all()
    if status:
        orders = orders.filter(status=status)
    return render(request, 'shop/admin/order_list.html', {
        'orders': orders,
        'status': status,
        'status_choices': PurchaseOrder.STATUS_CHOICES
    })


def admin_order_detail(request, order_id):
    order = get_object_or_404(PurchaseOrder.objects.prefetch_related('items', 'status_logs'), id=order_id)
    return render(request, 'shop/order_detail.html', {'order': order, 'is_vendor_view': True})


def admin_order_change_status(request, order_id, new_status):
    if request.method != 'POST':
        return redirect('admin_order_detail', order_id=order_id)
    order = get_object_or_404(PurchaseOrder, id=order_id)
    try:
        transition_order_status(order, new_status, actor='vendor')
        messages.success(request, "Order status updated.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('admin_order_detail', order_id=order.id)