from sqlalchemy.orm import Session

from app.models.menu import Menu
from app.schemas.menu import MenuTreeItem


def get_all_menus(db: Session) -> list[MenuTreeItem]:
    """전체 메뉴를 트리 구조로 반환"""
    root_menus = (
        db.query(Menu)
        .filter(Menu.parent_id.is_(None), Menu.is_active.is_(True))
        .order_by(Menu.sort_order)
        .all()
    )
    return [_build_tree(m) for m in root_menus]


def _build_tree(menu: Menu) -> MenuTreeItem:
    """Menu ORM → MenuTreeItem 재귀 변환"""
    children = sorted(
        [c for c in menu.children if c.is_active],
        key=lambda c: c.sort_order,
    )
    return MenuTreeItem(
        id=menu.id,
        menu_key=menu.menu_key,
        menu_name=menu.menu_name,
        parent_id=menu.parent_id,
        sort_order=menu.sort_order,
        is_active=menu.is_active,
        children=[_build_tree(c) for c in children],
    )
