"""Finder presentation for the drag-to-install disk image."""
from pathlib import Path

root = Path.cwd()
format = 'UDZO'
filesystem = 'HFS+'
files = [str(root / 'release' / 'SilicoLab.app')]
symlinks = {'Applications': '/Applications'}
icon = str(root / 'packaging/macos/assets/SilicoLab.icns')
background = str(root / 'build/dmg/dmg-background.png')
window_rect = ((260, 260), (660, 480))
icon_locations = {'SilicoLab.app': (180, 226), 'Applications': (480, 226)}
default_view = 'icon-view'
include_icon_view_settings = True
include_list_view_settings = False
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
show_icon_preview = False
icon_size = 80
text_size = 13
label_pos = 'bottom'
arrange_by = None
grid_offset = (0, 0)
