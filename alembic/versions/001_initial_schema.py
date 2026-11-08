"""Initial schema for users, subscriptions, marketplace, escrow, and logs

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-11-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="USER"),
        sa.Column("reputation_score", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("total_completed_deals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=False)

    # 2. monitored_sources
    op.create_table(
        "monitored_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("handle", sa.String(length=128), nullable=False),
        sa.Column("source_id", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.Column("last_seen_post_id", sa.String(length=256), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitored_sources_platform", "monitored_sources", ["platform"])
    op.create_index("ix_monitored_sources_handle", "monitored_sources", ["handle"])
    op.create_index("ix_monitored_sources_source_id", "monitored_sources", ["source_id"])
    op.create_index("ix_monitored_sources_is_active", "monitored_sources", ["is_active"])

    # 3. subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notify_media", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["monitored_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_id", name="uq_user_source_subscription"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_source_id", "subscriptions", ["source_id"])

    # 4. marketplace_listings
    op.create_table(
        "marketplace_listings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seller_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("account_handle", sa.String(length=128), nullable=False),
        sa.Column("account_url", sa.String(length=512), nullable=True),
        sa.Column("asking_price_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("follower_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engagement_rate", sa.Float(), nullable=True),
        sa.Column("niche", sa.String(length=64), nullable=False, server_default="General"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING_VERIFICATION"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("secondary_proof_url", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marketplace_listings_seller_id", "marketplace_listings", ["seller_id"])
    op.create_index("ix_marketplace_listings_platform", "marketplace_listings", ["platform"])
    op.create_index("ix_marketplace_listings_status", "marketplace_listings", ["status"])
    op.create_index("ix_marketplace_listings_is_verified", "marketplace_listings", ["is_verified"])
    op.create_index("ix_marketplace_listings_asking_price_usd", "marketplace_listings", ["asking_price_usd"])

    # 5. ownership_verifications
    op.create_table(
        "ownership_verifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("challenge_code", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False, server_default="BIO_CODE"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("verification_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["marketplace_listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ownership_verifications_listing_id", "ownership_verifications", ["listing_id"])
    op.create_index("ix_ownership_verifications_challenge_code", "ownership_verifications", ["challenge_code"])

    # 6. escrow_transactions
    op.create_table(
        "escrow_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("escrow_reference", sa.String(length=32), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("buyer_id", sa.Integer(), nullable=False),
        sa.Column("seller_id", sa.Integer(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("fee_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("seller_receives_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="AWAITING_PAYMENT"),
        sa.Column("payment_address", sa.String(length=128), nullable=True),
        sa.Column("payment_tx_hash", sa.String(length=128), nullable=True),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("one_time_view_token", sa.String(length=64), nullable=True),
        sa.Column("is_credentials_viewed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("inspection_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooling_off_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispute_reason", sa.Text(), nullable=True),
        sa.Column("dispute_resolution", sa.Text(), nullable=True),
        sa.Column("disputed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("buyer_rating", sa.Integer(), nullable=True),
        sa.Column("seller_rating", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_id"], ["marketplace_listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_escrow_transactions_escrow_reference", "escrow_transactions", ["escrow_reference"], unique=True)
    op.create_index("ix_escrow_transactions_status", "escrow_transactions", ["status"])

    # 7. notification_logs
    op.create_table(
        "notification_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.String(length=256), nullable=False),
        sa.Column("post_title", sa.Text(), nullable=True),
        sa.Column("post_url", sa.String(length=512), nullable=True),
        sa.Column("recipients_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["monitored_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_logs_source_id", "notification_logs", ["source_id"])
    op.create_index("ix_notification_logs_post_id", "notification_logs", ["post_id"])

    # 8. processed_events
    op.create_table(
        "processed_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=256), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processed_events_event_id", "processed_events", ["event_id"], unique=True)


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("notification_logs")
    op.drop_table("escrow_transactions")
    op.drop_table("ownership_verifications")
    op.drop_table("marketplace_listings")
    op.drop_table("subscriptions")
    op.drop_table("monitored_sources")
    op.drop_table("users")

