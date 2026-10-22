# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 plugin.video.youtube

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.
"""

from __future__ import absolute_import, division, unicode_literals

import json
import os
import threading
import time

from . import data
from ...kodion import logging
from ...kodion.compatibility import xbmc, xbmcgui
from ...kodion.constants import (
    ADDON_ID,
    ARTIST,
    BOOKMARK_ID,
    CHANNEL_ID,
    CONTAINER_ID,
    HOME_WINDOW_ACTIVE,
    MARK_AS_LABEL,
    PLAYLIST_ID,
    PLAYLIST_ITEM_ID,
    SUBSCRIPTION_ID,
    TITLE,
    URI,
    VIDEO_ID,
)
from ...kodion.utils.system_version import current_system_version


ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2
ACTION_MOVE_UP = 3
ACTION_MOVE_DOWN = 4
ACTION_PREVIOUS_MENU = 10
ACTION_SHOW_INFO = 11
ACTION_NAV_BACK = 92
ACTION_CONTEXT_MENU = 117
ACTION_MOUSE_LONG_CLICK = 108

NAV_LIST = 100
ROWS_GROUPLIST = 300
ROW_LISTS = tuple(range(301, 309))
ROW_LABELS = tuple(range(401, 409))
ROW_GROUPS = tuple(range(501, 509))
GRID_PANEL = 600

CACHE_SECONDS = 300
# items per grid page, independent of the page size of the listings
GRID_PAGE_SIZE = 30
HERO_IMAGE = 'https://i.ytimg.com/vi/{0}/{1}.jpg'
TAB_SWITCH_DELAY = 0.35
# delay before refreshing after playback has ended, so that the history and
# resume points are updated and a following playlist item has started
PLAYBACK_END_DELAY = 2

# Properties mirrored to Window(home) for the plugin's context menu actions,
# the same way the service does it for the classic list views
ITEM_PROPERTIES = (
    VIDEO_ID,
    BOOKMARK_ID,
    CHANNEL_ID,
    PLAYLIST_ID,
    PLAYLIST_ITEM_ID,
    SUBSCRIPTION_ID,
)

TAB_LABELS = {
    data.TAB_HOME: ('home_window.tab.home', 'home_window.tab.home.description'),
    data.TAB_SUBSCRIPTIONS: ('home_window.tab.subscriptions',
                             'home_window.tab.subscriptions.description'),
    data.TAB_EXPLORE: ('home_window.tab.explore',
                       'home_window.tab.explore.description'),
    data.TAB_LIBRARY: ('home_window.tab.library',
                       'home_window.tab.library.description'),
    data.TAB_SEARCH: ('search', 'home_window.tab.search.description'),
    data.TAB_ACCOUNT: ('home_window.tab.account',
                       'home_window.tab.account.description'),
}


class HomeWindow(xbmcgui.WindowXML):
    log = logging.getLogger(__name__)

    def __init__(self, *args, **kwargs):
        super(HomeWindow, self).__init__(*args, **kwargs)
        self._context = None
        self._ui = None
        self._lock = threading.RLock()
        self._generation = 0
        self._cache = {}
        self._tabs = {}
        self._tab_ids = []
        self._current_tab = None
        self._tab_timer = None
        self._stack = []
        self._row_data = {}
        self._grid = None
        self._initialised = False
        self._closing = False
        self._restore = None
        self._focus_rows = False
        # index of the topmost visible row, rows above it are hidden
        self._row_offset = 0
        self._grid_origin = None
        self._window_id = None
        # refresh postponed while a video is playing in the background
        self._refresh_pending = False
        self._player = _PlayerEvents(self._on_playback_end)

    def setup(self, context):
        self._context = context
        self._ui = context.get_ui()
        return self

    # Kodi callbacks

    def onInit(self):
        # remember the window id, so that the window can be brought back to
        # the front if it is opened again while it is still running
        self._window_id = xbmcgui.getCurrentWindowId()
        self._ui.set_property(HOME_WINDOW_ACTIVE, str(self._window_id))
        if self._initialised:
            # returning from playback or another window
            if xbmc.getCondVisibility('Player.HasMedia'):
                # reloading all rows while a video keeps playing in the
                # background takes away resources from the playback, refresh
                # once playback has ended instead
                self._refresh_pending = True
                self._restore = None
                self._sync_row_focus()
                return
            self._refresh_pending = False
            self._refresh_view(delay=0)
            return
        self._initialised = True

        context = self._context
        settings = context.get_settings()
        self.setProperty('hero', 'true' if settings.get_bool(
            settings.HOME_WINDOW_HERO, True
        ) else 'false')
        self.setProperty('icon', self._media_path('icon.png'))
        self.setProperty('view', 'tab')
        self._update_user()
        self._build_nav()
        self._load_root()

    def onAction(self, action):
        action_id = action.getId()
        focus_id = self.getFocusId()

        if action_id in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU):
            self._on_back(focus_id)
            return

        if action_id in (ACTION_CONTEXT_MENU, ACTION_MOUSE_LONG_CLICK):
            item = self._focused_item(focus_id)
            if item:
                self._show_context_menu(focus_id, item)
            return

        if action_id == ACTION_SHOW_INFO:
            item = self._focused_item(focus_id)
            if item:
                xbmcgui.Dialog().textviewer(item['title'], item['plot'] or '')
            return

        if focus_id == NAV_LIST and action_id in (ACTION_MOVE_LEFT,
                                                  ACTION_MOVE_RIGHT):
            self._schedule_tab_switch()
            return

        if focus_id == NAV_LIST and action_id == ACTION_MOVE_DOWN:
            self._focus_content()
            return

        if focus_id in ROW_LISTS and action_id in (ACTION_MOVE_UP,
                                                   ACTION_MOVE_DOWN):
            self._move_row(ROW_LISTS.index(focus_id),
                           up=action_id == ACTION_MOVE_UP)

    def onClick(self, control_id):
        if control_id == NAV_LIST:
            self._switch_tab(self._selected_tab(), focus_rows=True)
            return

        item = self._focused_item(control_id)
        if item:
            self._activate(control_id, item)

    # Navigation

    def _on_back(self, focus_id):
        if self._stack:
            self._close_grid()
            return
        if focus_id != NAV_LIST:
            self._set_row_offset(0)
            self.setFocusId(NAV_LIST)
            return
        self.close_window()

    def _focus_content(self):
        if self._grid:
            self.setFocusId(GRID_PANEL)
            return
        rows = [row for row in self._filled_rows() if row >= self._row_offset]
        if rows:
            self.setFocusId(ROW_LISTS[rows[0]])
        else:
            # rows are still loading, focus them once the first is shown
            self._focus_rows = True

    def _filled_rows(self):
        return sorted(ROW_LISTS.index(list_id) for list_id in self._row_data)

    def _sync_row_focus(self):
        """
        Make the focused row the topmost visible one, Kodi may restore the
        focus to a row while the rows above it are shown
        """
        if self._stack:
            return
        focus_id = self.getFocusId()
        if focus_id not in ROW_LISTS:
            return
        index = ROW_LISTS.index(focus_id)
        if index in self._filled_rows():
            if index != self._row_offset:
                self._set_row_offset(index)
        else:
            self._set_row_offset(0)
            self._focus_content()

    def _set_row_offset(self, offset):
        """Show the filled rows from offset on, hide the rows above"""
        self._row_offset = offset
        for index in self._filled_rows():
            self.getControl(ROW_GROUPS[index]).setVisible(index >= offset)

    def _move_row(self, index, up):
        filled = self._filled_rows()
        if up:
            above = [row for row in filled if row < index]
            if not above:
                self._set_row_offset(0)
                self.setFocusId(NAV_LIST)
                return
            target = above[-1]
        else:
            below = [row for row in filled if row > index]
            if not below:
                return
            target = below[0]
        self._set_row_offset(target)
        self.setFocusId(ROW_LISTS[target])

    def close_window(self):
        self._closing = True
        with self._lock:
            self._generation += 1
        if self._tab_timer:
            self._tab_timer.cancel()
        self.close()

    def _build_nav(self):
        localize = self._context.localize
        fanart = self._media_path('fanart.jpg')
        nav = self.getControl(NAV_LIST)
        nav.reset()
        items = []
        for tab in data.TABS:
            label, description = TAB_LABELS[tab]
            list_item = xbmcgui.ListItem(label=localize(label),
                                         label2=localize(description),
                                         offscreen=True)
            list_item.setArt({'fanart': fanart, 'thumb': fanart})
            list_item.setProperty('tab', tab)
            items.append(list_item)
        nav.addItems(items)
        self._tab_ids = list(data.TABS)

    def _selected_tab(self):
        position = self.getControl(NAV_LIST).getSelectedPosition()
        if 0 <= position < len(self._tab_ids):
            return self._tab_ids[position]
        return data.TAB_HOME

    def _schedule_tab_switch(self):
        if self._tab_timer:
            self._tab_timer.cancel()
        timer = threading.Timer(TAB_SWITCH_DELAY,
                                lambda: self._switch_tab(self._selected_tab()))
        timer.daemon = True
        self._tab_timer = timer
        timer.start()

    def _switch_tab(self, tab, focus_rows=False, force=False):
        if self._closing:
            return
        if self._stack:
            self._stack = []
            self._grid = None
            self.setProperty('view', 'tab')
        if tab != self._current_tab or force:
            if tab != self._current_tab:
                self._restore = None
            self._current_tab = tab
            nav = self.getControl(NAV_LIST)
            for position, tab_id in enumerate(self._tab_ids):
                nav.getListItem(position).setProperty(
                    'active', 'true' if tab_id == tab else ''
                )
            self._show_rows(self._tabs.get(tab) or [])
        if focus_rows:
            self._focus_content()

    # Root and rows

    def _load_root(self, tab=None):
        self.setProperty('loading', 'true')
        live_label = self._context.localize('live')

        def _run():
            raw = self._get_directory(data.root_uri(), use_cache=False)
            items = [data.normalise_item(item, live_label) for item in raw]
            items = [item for item in items if not item['is_back']]
            tabs = data.classify_root_items(items)
            self._add_builtin_rows(tabs)
            self._tabs = tabs
            if self._closing:
                return
            self._switch_tab(tab or self._current_tab or data.TAB_HOME,
                             force=True)
            if not tab:
                self.setFocusId(NAV_LIST)

        self._start(_run)

    def _add_builtin_rows(self, tabs):
        localize = self._context.localize

        def _tile(label, uri, icon, action=None):
            return data.make_item(label=label,
                                  uri=uri,
                                  thumb=self._media_path(icon),
                                  icon=icon,
                                  is_action=True,
                                  builtin=action)

        # A search tile is always available, even if the search entry is
        # hidden in the classic menu
        search_rows = tabs[data.TAB_SEARCH]
        new_search = _tile(localize('search.new'),
                           data.create_uri(data.PATHS.SEARCH + '/input'),
                           'new_search.png')
        if search_rows and search_rows[0]['type'] == data.ROW_ACTIONS:
            search_rows[0]['items'].insert(0, new_search)
        else:
            search_rows.insert(0, {
                'type': data.ROW_ACTIONS,
                'title': None,
                'items': [new_search],
            })

        account_rows = tabs[data.TAB_ACCOUNT]
        builtin = [
            _tile(localize('settings'), '', 'settings.png',
                  'Addon.OpenSettings({0})'.format(ADDON_ID)),
            _tile(localize('home_window.classic'), data.root_uri(),
                  'home.png', 'classic'),
        ]
        if account_rows and account_rows[0]['type'] == data.ROW_ACTIONS:
            account_rows[0]['items'].extend(builtin)
        else:
            account_rows.insert(0, {
                'type': data.ROW_ACTIONS,
                'title': None,
                'items': builtin,
            })
        if not account_rows[0]['title']:
            account_rows[0]['title'] = localize('home_window.account_settings')
        # untitled tile rows, e.g. on the search, explore and library tabs
        for rows in tabs.values():
            for row in rows:
                if row['type'] == data.ROW_ACTIONS and not row['title']:
                    row['title'] = localize('home_window.shortcuts')

    def _show_rows(self, rows):
        with self._lock:
            self._generation += 1
            generation = self._generation
        self._row_data = {}
        self._row_offset = 0

        rows = rows[:len(ROW_LISTS)]
        for index, group_id in enumerate(ROW_GROUPS):
            self.getControl(ROW_LISTS[index]).reset()
            self.getControl(group_id).setVisible(False)

        self.setProperty('empty', '')
        if not rows:
            self.setProperty('loading', '')
            self.setProperty('empty', 'true')
            return

        self.setProperty('loading', 'true')

        def _run():
            shown = 0
            for index, row in enumerate(rows):
                if self._stale(generation):
                    return
                items, title = self._row_items(row)
                if not items:
                    continue
                with self._lock:
                    if self._stale(generation):
                        return
                    self._fill_row(index, title, items, row)
                shown += 1
                if self._focus_rows:
                    self._focus_rows = False
                    self._focus_content()
            if not self._stale(generation):
                self.setProperty('loading', '')
                if not shown:
                    self.setProperty('empty', 'true')
                with self._lock:
                    if self._restore and self._restore[0] in ROW_LISTS:
                        # the remembered row is empty now
                        self._restore = None
                    self._sync_row_focus()

        self._start(_run)

    def _row_items(self, row):
        localize = self._context.localize
        row_type = row['type']
        if row_type == data.ROW_ACTIONS:
            return list(row['items']), row['title']

        if row_type == data.ROW_CONTINUE:
            settings = self._context.get_settings()
            if not settings.get_bool(settings.HOME_WINDOW_CONTINUE, True):
                return [], None
            items = []
            for uri in (row['uri'], row.get('fallback_uri')):
                if not uri:
                    continue
                items = [
                    item for item in self._list_items(uri)
                    if data.is_continue_candidate(item)
                ][:data.CONTINUE_MAX_ITEMS]
                if items:
                    break
            return items, localize('home_window.continue_watching')

        items = self._list_items(row['uri'])

        if row_type == data.ROW_SEARCH_HISTORY:
            items = [item for item in items
                     if not data.is_search_input_uri(item['uri'])]
            return items, localize('home_window.recent_searches')

        has_more = any(item['is_next_page'] for item in items)
        items = data.order_items(items, row.get('folders_first'))
        if len(items) > data.ROW_MAX_ITEMS:
            items = items[:data.ROW_MAX_ITEMS]
            has_more = True
        if items and (has_more or len(items) > 12):
            items.append(self._show_all_item(row))
        return items, row['title']

    def _list_items(self, uri, use_cache=True):
        live_label = self._context.localize('live')
        return [
            data.normalise_item(item, live_label, base_uri=uri)
            for item in self._get_directory(uri, use_cache=use_cache)
        ]

    def _show_all_item(self, row):
        return data.make_item(
            label=self._context.localize('home_window.show_all'),
            title=row['title'],
            uri=row['uri'],
            subtitle=row['title'],
            is_folder=True,
            tile='all',
        )

    def _fill_row(self, index, title, items, row):
        list_id = ROW_LISTS[index]
        control = self.getControl(list_id)
        control.reset()
        control.addItems([self._make_listitem(item) for item in items])
        self.getControl(ROW_LABELS[index]).setLabel(title or '')
        self._row_data[list_id] = {'items': items, 'row': row}
        self.getControl(ROW_GROUPS[index]).setVisible(index >= self._row_offset)
        self._restore_focus(list_id, control, len(items))

    # Grid view for folders, "show all" and search results

    def _open_grid(self, title, uri=None, page=1, source=None):
        """
        Open a grid page. The pages of a grid show GRID_PAGE_SIZE items each,
        independent of the pages of the listing, which are loaded from the
        source of the grid as required.
        """
        focus_id = self.getFocusId()
        if self._stack:
            # remember the focused tile of the current grid to return to it
            if focus_id == GRID_PANEL:
                self._stack[-1]['position'] = (
                    self.getControl(GRID_PANEL).getSelectedPosition()
                )
        elif focus_id in ROW_LISTS:
            # remember the tile the grid was opened from to return to it
            self._grid_origin = (
                focus_id,
                self.getControl(focus_id).getSelectedPosition(),
            )
        else:
            self._grid_origin = None
        if source is None:
            source = self._new_source(uri)
        self._stack.append({
            'base_title': title,
            'title': (' \u00b7 '.join((
                title, self._context.localize('home_window.page', page)
            )) if page > 1 else title),
            'source': source,
            'position': None,
            'page': page,
        })
        self._show_grid()

    @staticmethod
    def _new_source(uri):
        return {
            'uri': uri,
            'items': [],
            'next_uri': uri,
            'seen': set(),
            'lock': threading.Lock(),
        }

    def _open_next_page(self):
        """Show the next page on its own, Back returns to the previous one"""
        view = self._stack[-1]
        self._open_grid(view['base_title'],
                        page=view['page'] + 1,
                        source=view['source'])

    def _close_grid(self):
        self._stack.pop()
        if self._stack:
            view = self._stack[-1]
            if view.get('position') is not None:
                self._restore = (GRID_PANEL, view['position'])
            self._show_grid()
            return
        self._grid = None
        self.setProperty('view', 'tab')
        self.setProperty('empty', '')
        with self._lock:
            self._generation += 1
        self._restore = self._grid_origin
        self._focus_rows = not self._restore
        self._show_rows(self._tabs.get(self._current_tab) or [])

    def _show_grid(self, refresh=False):
        with self._lock:
            self._generation += 1
            generation = self._generation

        view = self._stack[-1]
        source = view['source']
        page = view['page']
        if refresh:
            source.update(self._new_source(source['uri']))

        panel = self.getControl(GRID_PANEL)
        self.setProperty('view', 'grid')
        self.setProperty('grid_title', view['title'])
        self.setProperty('empty', '')
        panel.reset()
        self._grid = {'title': view['title'], 'items': []}
        self.setProperty('loading', 'true')
        localize = self._context.localize

        def _run():
            start = (page - 1) * GRID_PAGE_SIZE
            end = start + GRID_PAGE_SIZE
            # load one more item than shown to know if there is a next page
            if not self._load_source(source, end + 1, generation, refresh):
                return
            items = source['items'][start:end]
            if page > 1:
                items.insert(0, data.make_item(
                    label=localize('home_window.previous_page'),
                    is_folder=True,
                    tile='back',
                ))
            if len(source['items']) > end or source['next_uri']:
                items.append(data.make_item(
                    label=localize('home_window.next_page', page + 1),
                    is_folder=True,
                    tile='next',
                ))
            with self._lock:
                if self._stale(generation):
                    return
                self._fill_grid(panel, items)

        self._start(_run)

    def _load_source(self, source, num_items, generation, refresh=False):
        """
        Load listing pages into the source until it has num_items items or
        the listing has no more pages. Duplicates of videos are skipped.
        """
        with source['lock']:
            while len(source['items']) < num_items and source['next_uri']:
                if self._stale(generation):
                    return False
                next_uri = None
                for item in self._list_items(source['next_uri'],
                                             use_cache=not refresh):
                    if item['is_back']:
                        continue
                    if item['is_next_page']:
                        next_uri = item['uri']
                        continue
                    video_id = item['properties'].get('video_id')
                    if video_id:
                        if video_id in source['seen']:
                            continue
                        source['seen'].add(video_id)
                    source['items'].append(item)
                # a next page that links back to the loaded page would loop
                if next_uri == source['next_uri']:
                    next_uri = None
                source['next_uri'] = next_uri
        return not self._stale(generation)

    def _fill_grid(self, panel, items):
        grid = self._grid
        grid['items'].extend(items)
        panel.addItems([self._make_listitem(item) for item in items])
        self.setProperty('loading', '')
        if not grid['items']:
            self.setProperty('empty', 'true')
            return
        if self._restore_focus(GRID_PANEL, panel, len(grid['items'])):
            return
        # focus the first video rather than the previous page tile
        position = 1 if (len(grid['items']) > 1
                         and grid['items'][0]['tile'] == 'back') else 0
        panel.selectItem(position)
        self.setFocusId(GRID_PANEL)

    # Item handling

    def _make_listitem(self, item):
        list_item = xbmcgui.ListItem(label=item['label'],
                                     label2=item['subtitle'],
                                     path=item['uri'],
                                     offscreen=True)
        thumb = item['thumb']
        fanart = item['fanart'] or thumb
        video_id = item['properties'].get('video_id')
        hero = ''
        if item['is_video'] and video_id:
            # the listing only has small thumbnails, use larger ones for the
            # preview: maxres if available, hq (always available) beneath
            fanart = HERO_IMAGE.format(video_id, 'hqdefault')
            hero = HERO_IMAGE.format(video_id, 'maxresdefault')
        list_item.setArt({
            'thumb': thumb,
            'icon': thumb,
            'poster': thumb,
            'fanart': fanart,
        })

        properties = {
            key: value
            for key, value in item['properties'].items()
            if value
        }
        properties.update({
            'hero': hero,
            'tile': item['tile'],
            'duration_label': item['duration_label'],
            'live': 'true' if item['live'] else '',
            'watched': 'true' if item['playcount'] and item['is_video'] else '',
            'progress': str(item['progress']) if item['progress'] else '',
        })
        for key, value in properties.items():
            list_item.setProperty(key, value)

        self._set_info(list_item, item)
        return list_item

    @staticmethod
    def _set_info(list_item, item):
        if current_system_version.compatible(20):
            info_tag = list_item.getVideoInfoTag()
            info_tag.setTitle(item['title'])
            info_tag.setPlot(item['plot'])
            if item['artists']:
                info_tag.setArtists(item['artists'])
            if item['duration']:
                info_tag.setDuration(int(item['duration']))
            if item['playcount']:
                info_tag.setPlaycount(int(item['playcount']))
            if item['resume'] and item['total']:
                info_tag.setResumePoint(float(item['resume']),
                                        float(item['total']))
            return

        info = {
            'title': item['title'],
            'plot': item['plot'],
        }
        if item['artists']:
            info['artist'] = item['artists']
        if item['duration']:
            info['duration'] = int(item['duration'])
        if item['playcount']:
            info['playcount'] = int(item['playcount'])
        list_item.setInfo('video', info)
        if item['resume'] and item['total']:
            list_item.setProperty('ResumeTime', str(item['resume']))
            list_item.setProperty('TotalTime', str(item['total']))

    def _focused_item(self, control_id):
        if control_id == GRID_PANEL:
            items = self._grid['items'] if self._grid else []
        elif control_id in ROW_LISTS:
            row = self._row_data.get(control_id)
            items = row['items'] if row else []
        else:
            return None
        position = self.getControl(control_id).getSelectedPosition()
        if 0 <= position < len(items):
            return items[position]
        return None

    def _activate(self, control_id, item):
        builtin = item.get('builtin')
        if builtin == 'classic':
            self._execute('ActivateWindow(Videos,{0},return)'.format(
                data.root_uri()
            ))
            return
        if builtin:
            self._execute(builtin, refresh_root=True)
            return

        if item['tile'] == 'back':
            self._close_grid()
            return

        if item['tile'] == 'all':
            self._open_grid(item['title'], item['uri'])
            return

        if item['tile'] == 'next':
            self._open_next_page()
            return

        if data.is_search_input_uri(item['uri']):
            self._search(item['uri'])
            return

        if item['uri'].startswith('command://'):
            self._execute(item['uri'][len('command://'):])
            return

        if item['is_playable']:
            self._play(item)
            return

        if item['is_folder'] and not data.is_action_uri(item['uri']):
            self._open_grid(item['label'], item['uri'])
            return

        # actions such as sign in/out, switch user or the setup wizard change
        # the content of the menu, so the root menu is reloaded afterwards
        self._set_item_properties(control_id, item)
        self._execute('RunPlugin({0})'.format(item['uri']),
                      refresh_root=data.is_action_uri(item['uri']))

    def _play(self, item):
        uri = item['uri']
        if item['resume'] > 0 and item['progress'] < 100:
            localize = self._context.localize
            choice = xbmcgui.Dialog().contextmenu([
                localize('home_window.resume_from',
                         data.format_duration(item['resume'])),
                localize('home_window.play_from_start'),
            ])
            if choice < 0:
                return
            if choice == 0:
                uri = data.seek_uri(uri, item['resume'])
        self._remember_focus()
        # the plugin seeks to the resume point, a bookmark of Kodi must not
        # move the start position as well
        xbmc.executebuiltin('PlayMedia({0},noresume)'.format(uri))

    def _search(self, input_uri):
        localize = self._context.localize
        query = xbmcgui.Dialog().input(localize('search.title'))
        if not query:
            return
        self._open_grid(query, data.search_query_uri(input_uri, query))

    def _show_context_menu(self, control_id, item):
        if item.get('builtin') or item['tile'] in {'all', 'back', 'next'}:
            return
        localize = self._context.localize

        self._set_item_properties(control_id, item)
        entries = data.context_menu_entries(item)
        if not entries:
            if item['is_playable']:
                entries = [(localize('video.play'), None)]
            elif item['is_folder']:
                entries = [(localize('home_window.open'), None)]
            else:
                return

        labels = [
            data.resolve_label(label,
                               xbmc.getInfoLabel,
                               xbmc.getLocalizedString)
            for label, _ in entries
        ]
        choice = xbmcgui.Dialog().contextmenu(labels)
        if choice < 0:
            return
        action = entries[choice][1]
        if not action:
            self._activate(control_id, item)
            return

        target = data.navigation_target(action)
        if target:
            if data.is_refresh_action(target):
                self._cache = {}
                self._start(self._refresh_view)
                return
            target = data.resolve_uri(target, xbmc.getInfoLabel)
            self._open_grid(labels[choice], target)
            return

        if action == 'Action(Queue)':
            # Kodi queues the focused item of a media window, which does not
            # exist in the home window, so add the item to the playlist here
            playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            playlist.add(item['uri'], self._make_listitem(item))
            return
        if action.startswith('PlayMedia('):
            self._execute(action)
            return
        self._execute(action, refresh_view=True)

    def _set_item_properties(self, control_id, item):
        """
        Set the properties of the item the context menu belongs to. The
        plugin resolves $INFO[Window(home).Property(...)] placeholders of the
        context menu actions from these properties.
        """
        set_property = self._ui.set_property
        clear_property = self._ui.clear_property
        properties = item['properties']
        for name in ITEM_PROPERTIES:
            value = properties.get(name)
            if value:
                set_property(name, value)
            else:
                clear_property(name)
        set_property(URI, item['uri'])
        set_property(TITLE, item['title'] or item['label'])
        if item['artists']:
            set_property(ARTIST, ', '.join(item['artists']))
        else:
            clear_property(ARTIST)
        localize = self._context.localize
        set_property(MARK_AS_LABEL, localize(
            'history.mark.unwatched'
            if item['playcount'] else
            'history.mark.watched'
        ))
        set_property(CONTAINER_ID, str(control_id))

    # Helpers

    def _execute(self, command, refresh_view=False, refresh_root=False):
        self.log.debug('Executing: %r', command)
        xbmc.executebuiltin(command)
        if refresh_root or refresh_view:
            self._start(self._wait_and_refresh, refresh_root)

    def _wait_and_refresh(self, refresh_root):
        """Wait until the triggered action has finished, then refresh"""
        monitor = xbmc.Monitor()
        if monitor.waitForAbort(1):
            return
        for _ in range(240):
            if self._closing:
                return
            if xbmc.getCondVisibility('Player.HasMedia'):
                # onInit refreshes the view once playback has ended
                return
            if not xbmc.getCondVisibility(
                    'System.HasActiveModalDialog'
                    ' | Window.IsActive(busydialog)'
                    ' | Window.IsActive(busydialognocancel)'
            ):
                break
            if monitor.waitForAbort(0.5):
                return
        self._cache = {}
        if refresh_root:
            self._update_user()
            self._load_root(tab=self._current_tab)
        else:
            self._refresh_view(delay=0)

    def _on_playback_end(self):
        if not self._refresh_pending or self._closing:
            return
        monitor = xbmc.Monitor()
        if monitor.waitForAbort(PLAYBACK_END_DELAY):
            return
        if (self._closing
                or xbmc.getCondVisibility('Player.HasMedia')
                or xbmcgui.getCurrentWindowId() != self._window_id):
            # still playing or the window is not shown, onInit refreshes
            # the view once it is shown again
            return
        self._refresh_pending = False
        self._refresh_view(delay=0)

    def _remember_focus(self):
        focus_id = self.getFocusId()
        if focus_id == GRID_PANEL or focus_id in ROW_LISTS:
            position = self.getControl(focus_id).getSelectedPosition()
            self._restore = (focus_id, position)
        else:
            self._restore = None

    def _refresh_view(self, delay=0):
        if delay:
            time.sleep(delay)
        # the focus is remembered before playback, as Kodi may move it while
        # the window is activated again
        if self._restore and ((self._restore[0] == GRID_PANEL)
                              != bool(self._grid and self._stack)):
            # remembered for another view
            self._restore = None
        if not self._restore:
            self._remember_focus()
        if self._grid and self._stack:
            self._show_grid(refresh=True)
        elif self._current_tab:
            self._cache = {}
            self._show_rows(self._tabs.get(self._current_tab) or [])

    def _restore_focus(self, control_id, control, num_items):
        restore = self._restore
        if not restore or restore[0] != control_id:
            return False
        self._restore = None
        position = min(restore[1], num_items - 1)
        if position >= 0:
            control.selectItem(position)
        if control_id in ROW_LISTS:
            self._set_row_offset(ROW_LISTS.index(control_id))
        self.setFocusId(control_id)
        return True

    def _media_path(self, filename):
        return os.path.join(self._context.get_addon_path(),
                            'resources',
                            'media',
                            filename)

    def _update_user(self):
        access_manager = self._context.get_access_manager()
        try:
            username = access_manager.get_username()
        except Exception:
            username = ''
        self.setProperty('user', username or '')

    def _get_directory(self, uri, use_cache=True):
        now = time.time()
        if use_cache:
            cached = self._cache.get(uri)
            if cached and now - cached[0] < CACHE_SECONDS:
                return cached[1]
        response = xbmc.executeJSONRPC(json.dumps(
            data.build_request(data.request_uri(uri))
        ))
        items = data.parse_response(response)
        self._cache[uri] = (now, items)
        return items

    def _stale(self, generation):
        return self._closing or generation != self._generation

    def _start(self, target, *args):
        def _run():
            try:
                target(*args)
            except Exception:
                self.log.exception('Home window task failed')
                self.setProperty('loading', '')

        thread = threading.Thread(target=_run)
        thread.daemon = True
        thread.start()
        return thread


class _PlayerEvents(xbmc.Player):
    def __init__(self, on_playback_end):
        super(_PlayerEvents, self).__init__()
        self._on_playback_end = on_playback_end

    def _notify(self):
        thread = threading.Thread(target=self._on_playback_end)
        thread.daemon = True
        thread.start()

    def onPlayBackEnded(self):
        self._notify()

    def onPlayBackStopped(self):
        self._notify()

    def onPlayBackError(self):
        self._notify()


def _activate_running_window(value, timeout=3):
    """
    Bring an already running home window to the front.

    :return: True if the home window is running, False if it is not, e.g. if
             it was not closed cleanly
    """
    if value.startswith('starting:'):
        # still starting, ignore unless it never finished starting
        try:
            return time.time() - float(value.partition(':')[2]) < 30
        except ValueError:
            return False
    if not value.isdigit():
        return False
    xbmc.executebuiltin('ActivateWindow({0})'.format(value))
    monitor = xbmc.Monitor()
    for _ in range(timeout * 10):
        if xbmc.getCondVisibility('Window.IsActive({0})'.format(value)):
            return True
        if monitor.waitForAbort(0.1):
            break
    return False


def open_home_window(context):
    ui = context.get_ui()
    running = ui.get_property(HOME_WINDOW_ACTIVE)
    if running and _activate_running_window(running):
        return
    ui.set_property(HOME_WINDOW_ACTIVE, 'starting:{0}'.format(time.time()))
    try:
        window = HomeWindow('script-youtube-home.xml',
                            context.get_addon_path(),
                            'default',
                            '1080i').setup(context)
        window.doModal()
        del window
    finally:
        ui.clear_property(HOME_WINDOW_ACTIVE)
