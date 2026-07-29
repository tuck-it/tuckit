"""Historical-state helpers shared by the migration tests.

These tests used to reach an old state by rolling the database BACKWARD from
the leaf. That stopped being possible with 0045_fold_tickets_and_plans: it
folds Ticket and Plan bodies into one text column, which cannot be split again,
so its `backward()` raises on purpose. Reversing anything below it now trips
over 0045 first.

`at()` therefore does what django_test_migrations' Migrator does — drop every
model table, forget the applied list, and replay FORWARD from empty up to the
target — so no migration is ever unapplied just to set up a test.

Tests that genuinely assert reversibility use `back()`, which really does
unapply. That is only safe from a state at or below the migration under test.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django_test_migrations.migrator import Migrator


def at(state):
    """Historical `apps` registry with the DB replayed forward to `state`."""
    return Migrator().apply_initial_migration(state).apps


def forward(state):
    """Apply migrations up to `state`; return the historical `apps` there."""
    return Migrator().apply_tested_migration(state).apps


def back(state):
    """Genuinely UNAPPLY down to `state`. Only for reversibility assertions,
    and only from a state below 0045 — reversing through it raises."""
    executor = MigrationExecutor(connection)
    executor.migrate([state])
    executor.loader.build_graph()
    return executor.loader.project_state([state]).apps


def leave_migrated():
    """Leave the DB at the leaf for the rest of the suite."""
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
