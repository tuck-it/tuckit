# Option B: make the legacy `workspace` FK nullable on all five child models.
# Root cause of the task-5 MCP server's org-to-workspace bridge helper and the
# workspace-scoped areas.py deviation: the non-null `workspace` FK forced every
# create to supply a workspace, even though `org` (added in 0020) is now the
# real tenant boundary. Making it nullable lets areas/tags/tokens/snapshots/
# activity become genuinely org-scoped — new rows get workspace=None. Does NOT
# touch any uniqueness constraint (still (workspace, slug) / (workspace, name)
# / (workspace, date) — moving those to org is Task 12's job).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_reparent_children_to_org'),
    ]

    operations = [
        migrations.AlterField(
            model_name='area',
            name='workspace',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='areas', to='core.workspace'),
        ),
        migrations.AlterField(
            model_name='tag',
            name='workspace',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tags', to='core.workspace'),
        ),
        migrations.AlterField(
            model_name='apitoken',
            name='workspace',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tokens', to='core.workspace'),
        ),
        migrations.AlterField(
            model_name='workspacestatsnapshot',
            name='workspace',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='stat_snapshots', to='core.workspace'),
        ),
        migrations.AlterField(
            model_name='activityevent',
            name='workspace',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='activity', to='core.workspace'),
        ),
    ]
