from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Menu(Base):
    """좌측 탭 메뉴 트리 구조 테이블"""
    __tablename__ = "menus"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(Integer, ForeignKey("menus.id", ondelete="CASCADE"), nullable=True)
    menu_key = Column(String(50), unique=True, nullable=False)
    menu_name = Column(String(100), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    # 자기 참조 관계 (부모 → 자식)
    children = relationship(
        "Menu",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="joined",
        order_by="Menu.sort_order",
    )
    parent = relationship(
        "Menu",
        back_populates="children",
        remote_side=[id],
        lazy="joined",
    )

    # 권한 관계
    permissions = relationship("UserPermission", back_populates="menu",
                               cascade="all, delete-orphan")


class UserPermission(Base):
    """사용자별 메뉴 접근 권한 테이블"""
    __tablename__ = "user_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    menu_id = Column(Integer, ForeignKey("menus.id", ondelete="CASCADE"), nullable=False)
    granted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "menu_id", name="uq_user_menu"),
    )

    # 관계
    menu = relationship("Menu", back_populates="permissions")
    user = relationship("User", foreign_keys=[user_id])
    granter = relationship("User", foreign_keys=[granted_by])
