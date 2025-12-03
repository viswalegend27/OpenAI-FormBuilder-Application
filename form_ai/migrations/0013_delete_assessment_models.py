from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("form_ai", "0012_alter_candidateanswer_answers"),
    ]

    operations = [
        migrations.DeleteModel(
            name="CandidateAnswer",
        ),
        migrations.DeleteModel(
            name="TechnicalAssessment",
        ),
    ]

