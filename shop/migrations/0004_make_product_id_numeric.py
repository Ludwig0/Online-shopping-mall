from django.db import migrations, models


def set_numeric_product_ids(apps, schema_editor):
    Product = apps.get_model('shop', 'Product')
    for product in Product.objects.order_by('id').iterator():
        Product.objects.filter(pk=product.pk).update(slug=f'tmp-{product.pk}')
    for product in Product.objects.order_by('id').iterator():
        Product.objects.filter(pk=product.pk).update(slug=str(product.pk))


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0003_product_is_duplicate_product_master_product'),
    ]

    operations = [
        migrations.RunPython(set_numeric_product_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='slug',
            field=models.SlugField(editable=False, max_length=20, unique=True),
        ),
    ]
