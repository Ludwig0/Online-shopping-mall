from django.db import migrations, models


def set_fixed_width_product_ids(apps, schema_editor):
    Product = apps.get_model('shop', 'Product')
    Product.objects.all().update(slug=None)
    for product in Product.objects.order_by('id').iterator():
        Product.objects.filter(pk=product.pk).update(slug=f'{product.pk:08d}')


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0004_make_product_id_numeric'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='slug',
            field=models.SlugField(blank=True, editable=False, max_length=8, null=True, unique=True),
        ),
        migrations.RunPython(set_fixed_width_product_ids, migrations.RunPython.noop),
    ]
