"""add user_profiles and user_availability tables

Revision ID: 0002_user_profiles
Revises: 0001
Create Date: 2026-02-22

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_user_profiles"
down_revision = "6772fe2d6136"            # ← replace with your actual last revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enums ──────────────────────────────────────────────────────────────────
    gender_enum = postgresql.ENUM(
        "man", "woman", "non_binary", "other",
        name="gender_enum", create_type=False,
    )
    relationship_goal_enum = postgresql.ENUM(
        "serious", "casual", "open", "undecided",
        name="relationship_goal_enum", create_type=False,
    )
    relationship_stage_pref_enum = postgresql.ENUM(
        "first_date", "second_third", "together",
        name="relationship_stage_pref_enum", create_type=False,
    )
    social_energy_enum = postgresql.ENUM(
        "introvert", "ambivert", "extrovert",
        name="social_energy_enum", create_type=False,
    )
    communication_style_enum = postgresql.ENUM(
        "deep_talker", "light_banter", "mix",
        name="communication_style_enum", create_type=False,
    )
    preferred_time_enum = postgresql.ENUM(
        "weekday_evenings", "weekend_afternoons", "weekend_evenings",
        name="preferred_time_enum", create_type=False,
    )
    alcohol_preference_enum = postgresql.ENUM(
        "yes", "no", "sometimes",
        name="alcohol_preference_enum", create_type=False,
    )

    gender_enum.create(op.get_bind(), checkfirst=True)
    relationship_goal_enum.create(op.get_bind(), checkfirst=True)
    relationship_stage_pref_enum.create(op.get_bind(), checkfirst=True)
    social_energy_enum.create(op.get_bind(), checkfirst=True)
    communication_style_enum.create(op.get_bind(), checkfirst=True)
    preferred_time_enum.create(op.get_bind(), checkfirst=True)
    alcohol_preference_enum.create(op.get_bind(), checkfirst=True)

    # ── user_profiles ──────────────────────────────────────────────────────────
    op.create_table(
        "user_profiles",
        sa.Column("id",               sa.Integer(),     primary_key=True,  autoincrement=True),
        sa.Column("user_id",          sa.Integer(),     sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, unique=True),

        # Core identity
        sa.Column("date_of_birth",     sa.Date(),        nullable=True),
        sa.Column("gender",            gender_enum,      nullable=True),
        sa.Column("looking_for_gender",postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("city",              sa.String(120),   nullable=True),
        sa.Column("home_lat",          sa.Float(),       nullable=True),
        sa.Column("home_lng",          sa.Float(),       nullable=True),
        sa.Column("max_travel_km",     sa.Integer(),     nullable=True),
        sa.Column("profile_photo_url", sa.String(500),   nullable=True),

        # Relationship intent
        sa.Column("relationship_goal",       relationship_goal_enum,        nullable=True),
        sa.Column("relationship_stage_pref", relationship_stage_pref_enum,  nullable=True),

        # Personality
        sa.Column("social_energy",       social_energy_enum,      nullable=True),
        sa.Column("communication_style", communication_style_enum, nullable=True),
        sa.Column("love_language",       postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        # Date preferences
        sa.Column("preferred_mood",          sa.String(60),           nullable=True),
        sa.Column("preferred_budget",        sa.String(20),           nullable=True),
        sa.Column("preferred_time",          preferred_time_enum,     nullable=True),
        sa.Column("alcohol",                 alcohol_preference_enum, nullable=True),
        sa.Column("dietary_requirements",    sa.String(255),          nullable=True),
        sa.Column("noise_tolerance",         sa.String(20),           nullable=True),

        # Interests
        sa.Column("music_genres",        postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cuisine_preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("activities",          postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("hobbies",             postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        # Bio
        sa.Column("bio",      sa.String(300), nullable=True),
        sa.Column("fun_fact", sa.String(150), nullable=True),

        # Onboarding
        sa.Column("onboarding_answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("profile_complete",   sa.Boolean(), server_default="false", nullable=False),

        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"])
    op.create_index("ix_user_profiles_city",    "user_profiles", ["city"])

    # ── user_availability ──────────────────────────────────────────────────────
    op.create_table(
        "user_availability",
        sa.Column("id",         sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id",    sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday",    sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(),    nullable=False),
        sa.Column("end_time",   sa.Time(),    nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", "weekday", "start_time",
                             name="uq_user_availability_slot"),
    )
    op.create_index("ix_user_availability_user_id", "user_availability", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_availability")
    op.drop_index("ix_user_profiles_city",    table_name="user_profiles")
    op.drop_index("ix_user_profiles_user_id", table_name="user_profiles")
    op.drop_table("user_profiles")

    op.execute("DROP TYPE IF EXISTS alcohol_preference_enum")
    op.execute("DROP TYPE IF EXISTS preferred_time_enum")
    op.execute("DROP TYPE IF EXISTS communication_style_enum")
    op.execute("DROP TYPE IF EXISTS social_energy_enum")
    op.execute("DROP TYPE IF EXISTS relationship_stage_pref_enum")
    op.execute("DROP TYPE IF EXISTS relationship_goal_enum")
    op.execute("DROP TYPE IF EXISTS gender_enum")
