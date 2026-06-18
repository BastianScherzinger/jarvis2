from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_anfrage_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='anfrage',
            name='leistung',
            field=models.CharField(
                choices=[
                    ('komplettsanierung', 'Komplettsanierung'),
                    ('badsanierung', 'Badsanierung'),
                    ('wohnungssanierung', 'Wohnungssanierung'),
                    ('fassadensanierung', 'Fassadensanierung'),
                    ('malerarbeiten', 'Malerarbeiten'),
                    ('boden_fliesen', 'Boden & Fliesen'),
                    ('sonstiges', 'Sonstiges / Anfrage'),
                ],
                max_length=50,
                verbose_name='Leistungsart',
            ),
        ),
    ]
