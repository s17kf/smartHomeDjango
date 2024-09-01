# Generated by Django 5.0.2 on 2024-09-01 15:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0009_relayperiodicday_relayperiodicperiod'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='type',
            field=models.CharField(choices=[('switch', 'Switch'), ('relay - periodic', 'Periodic relay')], default='switch', max_length=20),
            preserve_default=False,
        ),
    ]
