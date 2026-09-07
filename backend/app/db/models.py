"""SQLAlchemy models implementing DATA_MODEL.md section 2."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


UUIDPK = UUID(as_uuid=False)


# --------------------------------------------------------------- identity
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUIDPK, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('active','suspended','deleted')", name="users_status_valid"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(UUIDPK, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_hash: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------- menu
class Restaurant(Base):
    """A kitchen. One order never spans two of them (Rule K1)."""

    __tablename__ = "restaurants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    cuisine: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["MenuItem"]] = relationship(back_populates="restaurant", lazy="selectin")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    restaurant_id: Mapped[str] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    base_price: Mapped[int] = mapped_column(Integer, nullable=False)  # minor units
    dietary_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    allergens: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    allergens_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    restaurant: Mapped[Restaurant] = relationship(back_populates="items", lazy="selectin")
    option_groups: Mapped[list["MenuOptionGroup"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("base_price > 0", name="menu_items_price_positive"),
        CheckConstraint(
            "category IN ('Starters','Pizza','Pasta','Salad','Sides','Dessert','Drinks')",
            name="menu_items_category_valid",
        ),
        Index(
            "menu_items_offerable",
            "category",
            postgresql_where=text("is_active AND is_available"),
        ),
        Index(
            "menu_items_name_active_uq",
            "restaurant_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("menu_items_restaurant", "restaurant_id"),
    )


class MenuOptionGroup(Base):
    __tablename__ = "menu_option_groups"

    id: Mapped[str] = mapped_column(UUIDPK, primary_key=True, default=_uuid)
    menu_item_id: Mapped[str] = mapped_column(
        ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    min_select: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_select: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    item: Mapped[MenuItem] = relationship(back_populates="option_groups")
    options: Mapped[list["MenuOption"]] = relationship(
        back_populates="group", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (CheckConstraint("max_select >= min_select", name="mog_select_range"),)


class MenuOption(Base):
    __tablename__ = "menu_options"

    id: Mapped[str] = mapped_column(UUIDPK, primary_key=True, default=_uuid)
    option_group_id: Mapped[str] = mapped_column(
        ForeignKey("menu_option_groups.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    price_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    group: Mapped[MenuOptionGroup] = relationship(back_populates="options")


# --------------------------------------------------------------- cart
class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[str] = mapped_column(UUIDPK, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    restaurant_id: Mapped[str | None] = mapped_column(
        ForeignKey("restaurants.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    lines: Mapped[list["CartLine"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("status IN ('open','confirmed','abandoned')", name="carts_status_valid"),
        # INV-3: at most one open cart per user
        Index(
            "carts_one_open_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )


class CartLine(Base):
    __tablename__ = "cart_lines"

    id: Mapped[str] = mapped_column(UUIDPK, primary_key=True, default=_uuid)
    cart_id: Mapped[str] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), nullable=False)
    menu_item_id: Mapped[str] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cart: Mapped[Cart] = relationship(back_populates="lines")
    item: Mapped[MenuItem] = relationship(lazy="selectin")
    options: Mapped[list["CartLineOption"]] = relationship(
        back_populates="line", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 20", name="cart_lines_qty_range"),  # INV-2
        UniqueConstraint("cart_id", "menu_item_id", "options_hash", name="cart_lines_dedupe"),
    )


class CartLineOption(Base):
    __tablename__ = "cart_line_options"

    cart_line_id: Mapped[str] = mapped_column(
        ForeignKey("cart_lines.id", ondelete="CASCADE"), primary_key=True
    )
    menu_option_id: Mapped[str] = mapped_column(ForeignKey("menu_options.id"), primary_key=True)

    line: Mapped[CartLine] = relationship(back_populates="options")
    option: Mapped[MenuOption] = relationship(lazy="selectin")


class ConfirmationToken(Base):
    __tablename__ = "confirmation_tokens"

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    cart_id: Mapped[str] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cart_version: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_turn: Mapped[str | None] = mapped_column(Text)  # same-turn rejection (AGENT_SPEC 4)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------- orders
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="confirmed")
    restaurant_id: Mapped[str | None] = mapped_column(ForeignKey("restaurants.id"))
    restaurant_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fulfilment: Mapped[str] = mapped_column(String(16), nullable=False, default="pickup")
    subtotal: Mapped[int] = mapped_column(Integer, nullable=False)
    tax: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_fee: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(24), nullable=False, default="on_delivery")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    events: Mapped[list["OrderEvent"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('confirmed','preparing','ready','out_for_delivery','completed','cancelled')",
            name="orders_status_valid",
        ),
        CheckConstraint("fulfilment IN ('pickup','delivery')", name="orders_fulfilment_valid"),
        CheckConstraint("total = subtotal + tax + delivery_fee", name="orders_total_consistent"),
        Index("orders_user_recent", "user_id", "confirmed_at"),
    )


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[str] = mapped_column(UUIDPK, primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), nullable=False)
    menu_item_id: Mapped[str] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    line_total: Mapped[int] = mapped_column(Integer, nullable=False)
    options_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    order: Mapped[Order] = relationship(back_populates="lines")

    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 20", name="order_lines_qty_range"),
        CheckConstraint("line_total = unit_price * quantity", name="order_lines_total_consistent"),
    )


class OrderEvent(Base):
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped[Order] = relationship(back_populates="events")

    __table_args__ = (
        CheckConstraint("actor IN ('customer','staff','system')", name="order_events_actor_valid"),
        Index("order_events_order", "order_id", "created_at"),
    )


# --------------------------------------------------------------- conversation
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(UUIDPK, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="messages_role_valid"),
        Index("messages_conversation_recent", "conversation_id", "id"),
    )
