"""photos bucket and per-user upload policy

Revision ID: 8f3a1c5d9b27
Revises: 53b296888cb8
Create Date: 2026-09-25 00:00:00.000000

Why this exists: the mobile app uploads photos straight to Supabase
Storage as the signed-in user (SPEC.md's signed-upload-URL flow), not
through the backend. Storage enforces row-level security on
storage.objects for that caller, and with no policy every upload is
rejected ("new row violates row-level security policy"). The backend
never needed one because it uses the secret key, which bypasses RLS --
so the missing policy only surfaced once the app uploaded from a device.
The bucket and this policy had been set up by hand in the Supabase
dashboard; this puts both in the repo so a fresh project isn't broken.

What it does:
  * Ensures the private `photos` bucket exists (no-op if it does).
  * Lets an authenticated user INSERT objects into `photos` only under
    their own `<user_id>/` folder -- the same `photos/<user_id>/<uuid>.jpg`
    layout the backend's from-photo path check enforces.
  * INSERT only. No user-facing SELECT/UPDATE/DELETE: reads go through
    backend-signed URLs and deletes through the backend, both using the
    secret key.

Guarded no-op off Supabase: the test suite runs `alembic upgrade head`
against a plain Postgres container that has no `storage` schema and no
`auth.uid()`. Both statements check for storage.objects / storage.buckets
first and do nothing when they're absent.

Applying it to a project that already has a hand-made policy: this
creates its own named policy and does not touch yours. If yours is
equivalent the two just overlap (permissive policies are OR'd), which is
harmless -- but drop the hand-made one afterward to avoid confusion.

Downgrade removes the policy only. It deliberately leaves the bucket
alone: dropping it would delete users' photos.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f3a1c5d9b27"
down_revision: str | Sequence[str] | None = "53b296888cb8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICY_NAME = "photos: users insert into own folder"


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('storage.buckets') IS NOT NULL THEN
                INSERT INTO storage.buckets (id, name, public)
                VALUES ('photos', 'photos', false)
                ON CONFLICT (id) DO NOTHING;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('storage.objects') IS NOT NULL THEN
                DROP POLICY IF EXISTS "{_POLICY_NAME}" ON storage.objects;
                CREATE POLICY "{_POLICY_NAME}"
                    ON storage.objects
                    FOR INSERT
                    TO authenticated
                    WITH CHECK (
                        bucket_id = 'photos'
                        AND (storage.foldername(name))[1] = (SELECT auth.uid())::text
                    );
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('storage.objects') IS NOT NULL THEN
                DROP POLICY IF EXISTS "{_POLICY_NAME}" ON storage.objects;
            END IF;
        END
        $$;
        """
    )
