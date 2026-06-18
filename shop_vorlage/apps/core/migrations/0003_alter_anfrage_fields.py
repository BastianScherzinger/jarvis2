from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_anfrage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='anfrage',
            name='leistung',
            field=models.CharField(
                choices=[
                    ('anfrage', 'Allgemeine Anfrage'),
                    ('beratung', 'Beratung'),
                    ('auftrag', 'Auftrag'),
                    ('sonstiges', 'Sonstiges'),
                ],
                max_length=50,
                verbose_name='Leistungsart',
            ),
        ),
        migrations.AlterField(
            model_name='anfrage',
            name='adresse',
            field=models.CharField(blank=True, max_length=500, verbose_name='Adresse'),
        ),
    ]
