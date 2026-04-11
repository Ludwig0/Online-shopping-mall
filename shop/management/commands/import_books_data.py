import ast
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from shop.models import (
    Product, ProductImage,
    ProductOption, ProductOptionValue,
    ProductVariant, ProductVariantSelection,
    BookReview
)


class Command(BaseCommand):
    help = "Import books.csv and ratings.csv, and create configurable variants (Paperback/Hardcover)."

    def add_arguments(self, parser):
        parser.add_argument('--books', default='books.csv')
        parser.add_argument('--ratings', default='ratings.csv')
        parser.add_argument('--reset', action='store_true')

    def _safe_price(self, raw):
        try:
            return Decimal(str(raw)).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError):
            return Decimal('10.00')

    @transaction.atomic
    def handle(self, *args, **options):
        books_path = Path(options['books'])
        ratings_path = Path(options['ratings'])

        if not books_path.exists():
            raise CommandError(f"books file not found: {books_path}")
        if not ratings_path.exists():
            raise CommandError(f"ratings file not found: {ratings_path}")

        if options['reset']:
            self.stdout.write("Resetting imported data...")
            BookReview.objects.all().delete()
            ProductVariantSelection.objects.all().delete()
            ProductVariant.objects.all().delete()
            ProductOptionValue.objects.all().delete()
            ProductOption.objects.all().delete()
            ProductImage.objects.all().delete()
            Product.objects.all().delete()

        title_to_product = {}

        self.stdout.write("Importing books...")
        with books_path.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=1):
                title = (row.get('Title') or '').strip()
                if not title:
                    continue

                category = ''
                raw_categories = (row.get('categories') or '').strip()
                try:
                    parsed_categories = ast.literal_eval(raw_categories) if raw_categories else []
                    if isinstance(parsed_categories, list) and parsed_categories:
                        category = str(parsed_categories[0])
                    else:
                        category = raw_categories[:255]
                except Exception:
                    category = raw_categories[:255]

                base_price = self._safe_price(row.get('price', 0))

                product = Product.objects.create(
                    title=title,
                    description=(row.get('description') or '').strip(),
                    authors=', '.join(ast.literal_eval(row.get('authors', '[]'))) if row.get('authors') else '',
                    publisher=(row.get('publisher') or '').strip(),
                    published_date=(row.get('publishedDate') or '').strip(),
                    category=category,
                    base_price=base_price,
                    thumbnail_url=(row.get('image') or '').strip(),
                    is_active=True,
                    is_configurable=True,  # Block D demo: every imported book uses Format option
                )

                # Multiple photos support (B1). We use the same image URL as seed + placeholders to show feature support.
                main_image = (row.get('image') or '').strip()
                if main_image:
                    ProductImage.objects.create(product=product, image_url=main_image, alt_text=f"{title} cover", sort_order=0)
                    ProductImage.objects.create(product=product, image_url=main_image, alt_text=f"{title} preview", sort_order=1)
                else:
                    placeholder = "https://via.placeholder.com/300x420?text=Book"
                    ProductImage.objects.create(product=product, image_url=placeholder, alt_text=f"{title} image", sort_order=0)

                # Block D configurable product: Format option => Paperback (+0), Hardcover (+5)
                option = ProductOption.objects.create(product=product, name='Format')
                paperback = ProductOptionValue.objects.create(
                    option=option, value='Paperback', price_delta=Decimal('0.00'),
                    display_image_url=main_image
                )
                hardcover = ProductOptionValue.objects.create(
                    option=option, value='Hardcover', price_delta=Decimal('5.00'),
                    display_image_url=main_image
                )

                sku_base = f"BK-{product.id:05d}"
                v1 = ProductVariant.objects.create(
                    product=product,
                    sku=f"{sku_base}-PB",
                    price_delta=Decimal('0.00'),
                    inventory_status='in_stock',
                    is_default=True
                )
                v2 = ProductVariant.objects.create(
                    product=product,
                    sku=f"{sku_base}-HC",
                    price_delta=Decimal('5.00'),
                    inventory_status='in_stock',
                    is_default=False
                )

                ProductVariantSelection.objects.create(variant=v1, option_value=paperback)
                ProductVariantSelection.objects.create(variant=v2, option_value=hardcover)

                # Make a small subset out-of-stock to demonstrate D5 behavior
                if product.id % 17 == 0:
                    v2.inventory_status = 'out_of_stock'
                    v2.save(update_fields=['inventory_status'])

                title_to_product[title] = product

                if idx % 100 == 0:
                    self.stdout.write(f"  imported {idx} books...")

        self.stdout.write("Importing reviews...")
        review_count = 0
        with ratings_path.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = (row.get('Title') or '').strip()
                product = title_to_product.get(title)
                if not product:
                    continue

                score_raw = row.get('review/score', '0')
                try:
                    score = Decimal(str(score_raw)).quantize(Decimal('0.1'))
                except Exception:
                    score = Decimal('0.0')

                BookReview.objects.create(
                    product=product,
                    external_user_id=(row.get('User_id') or '').strip(),
                    profile_name=(row.get('profileName') or '').strip(),
                    score=score,
                    review_text=(row.get('review/text') or '').strip(),
                )
                review_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Products={Product.objects.count()}, Reviews={review_count}, Variants={ProductVariant.objects.count()}"
        ))
