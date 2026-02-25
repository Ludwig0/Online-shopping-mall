from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Cart, CartItem, PurchaseOrder, PurchaseOrderItem, OrderStatusLog


def get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(customer=user)
    return cart


def generate_po_number():
    now = timezone.now()
    return f"PO{now.strftime('%Y%m%d%H%M%S%f')[-18:]}"


@transaction.atomic
def checkout_cart(user):
    cart = get_or_create_cart(user)
    items = list(cart.items.select_related('variant__product', 'variant').all())
    if not items:
        raise ValueError("Cart is empty.")

    for item in items:
        if not item.variant.is_in_stock:
            raise ValueError(f"{item.variant.product.title} ({item.variant.config_summary}) is out of stock.")

    profile = user.customer_profile

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