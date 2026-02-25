def cart_count(request):
    if not request.user.is_authenticated:
        return {'nav_cart_count': 0}
    try:
        count = sum(item.quantity for item in request.user.cart.items.all())
    except Exception:
        count = 0
    return {'nav_cart_count': count}