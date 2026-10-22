# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 plugin.video.youtube

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.
"""

from __future__ import absolute_import, division, unicode_literals


def open_home_window(context, tab=None):
    # imported lazily as the window requires a running Kodi GUI
    from .window import open_home_window as _open_home_window

    return _open_home_window(context, tab=tab)


__all__ = ('open_home_window',)
