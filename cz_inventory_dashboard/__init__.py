from . import models


def uninstall_hook(env):
    """Give Inventory its standard entry page back."""
    root = env.ref('stock.menu_stock_root', raise_if_not_found=False)
    if root:
        root.action = False
    overview = env.ref('stock.stock_picking_type_menu', raise_if_not_found=False)
    if overview:
        overview.sequence = 0
