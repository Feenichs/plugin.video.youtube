# -*- coding: utf-8 -*-
"""

    Copyright (C) 2026 plugin.video.youtube

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.
"""

from __future__ import absolute_import, division, unicode_literals

import json
import os
import re

from ...kodion.compatibility import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urlsplit,
)
from ...kodion.constants import (
    ADDON_ID,
    CLASSIC_MENU,
    CONTEXT_MENU,
    HOME_WINDOW_REQUEST,
    PATHS,
)


PLUGIN_URL = 'plugin://{0}'.format(ADDON_ID)

TAB_HOME = 'home'
TAB_SUBSCRIPTIONS = 'subscriptions'
TAB_EXPLORE = 'explore'
TAB_LIBRARY = 'library'
TAB_SEARCH = 'search'
TAB_ACCOUNT = 'account'
TABS = (
    TAB_HOME,
    TAB_SUBSCRIPTIONS,
    TAB_EXPLORE,
    TAB_LIBRARY,
    TAB_SEARCH,
    TAB_ACCOUNT,
)

ROW_FEED = 'feed'
ROW_ACTIONS = 'actions'
ROW_CONTINUE = 'continue'
ROW_SEARCH_HISTORY = 'search_history'

# Properties requested for every listed item
LIST_PROPERTIES = (
    'title',
    'art',
    'thumbnail',
    'fanart',
    'plot',
    'duration',
    'resume',
    'playcount',
    'artist',
    'premiered',
    'customproperties',
)

# Items with less progress than this are considered finished
CONTINUE_MAX_PERCENT = 92

# Root menu entries are mapped to tabs by the icon they use. Icons are unique
# per menu entry, unlike paths which depend on login state and settings.
# Entries that are slow to list (related videos: hundreds of items) or that
# are not suitable as a row (my channel, browse channels) are shown as tiles.
ICON_RULES = {
    'home.png': ((TAB_HOME, ROW_FEED),),
    'new_uploads.png': ((TAB_HOME, ROW_FEED), (TAB_SUBSCRIPTIONS, ROW_FEED)),
    'trending.png': ((TAB_HOME, ROW_FEED), (TAB_EXPLORE, ROW_FEED)),
    'related_videos.png': ((TAB_EXPLORE, ROW_ACTIONS),),
    'live.png': ((TAB_EXPLORE, ROW_FEED),),
    'location.png': ((TAB_EXPLORE, ROW_ACTIONS),),
    'browse_channels.png': ((TAB_EXPLORE, ROW_ACTIONS),),
    'channels.png': ((TAB_SUBSCRIPTIONS, ROW_FEED),),
    'history.png': ((TAB_LIBRARY, ROW_FEED),),
    'watch_later.png': ((TAB_LIBRARY, ROW_FEED),),
    'likes.png': ((TAB_LIBRARY, ROW_FEED),),
    'dislikes.png': ((TAB_LIBRARY, ROW_FEED),),
    'playlist.png': ((TAB_LIBRARY, ROW_FEED),),
    'bookmarks.png': ((TAB_LIBRARY, ROW_FEED),),
    'user.png': ((TAB_LIBRARY, ROW_ACTIONS),),
    'search.png': ((TAB_SEARCH, ROW_SEARCH_HISTORY),),
    'quick_search.png': ((TAB_SEARCH, ROW_ACTIONS),),
    'incognito_search.png': ((TAB_SEARCH, ROW_ACTIONS),),
    'sign_in.png': ((TAB_ACCOUNT, ROW_ACTIONS),),
    'sign_out.png': ((TAB_ACCOUNT, ROW_ACTIONS),),
    'settings.png': ((TAB_ACCOUNT, ROW_ACTIONS),),
}

# Paths that trigger an action rather than listing content. These must never
# be listed in the background, e.g. listing the sign in path would start the
# sign in process.
ACTION_PATHS = (
    '/sign/',
    '/users/',
    '/config/',
    PATHS.SEARCH + '/input',
    PATHS.COMMAND + '/',
)

# Preferred order of rows on the explore tab, live content first
EXPLORE_ORDER = (
    PATHS.LIVE_VIDEOS + '/',
    PATHS.LIVE_VIDEOS_UPCOMING + '/',
    PATHS.TRENDING + '/',
    PATHS.LIVE_VIDEOS_COMPLETED + '/',
)

ADDON_MEDIA = '/addons/{0}/resources/media/'.format(ADDON_ID)
LOCAL_HISTORY_URI = PLUGIN_URL + PATHS.HISTORY + '/list/'
CONTINUE_MAX_ITEMS = 20
# longer listings are cut off in rows, they are shown in full via "show all"
ROW_MAX_ITEMS = 40
INFO_RE = re.compile(r'\$INFO\[([^\]]+)\]')
LOCALIZE_RE = re.compile(r'\$LOCALIZE\[(\d+)\]')


def plugin_path(uri):
    """Return the path of a plugin uri, without the plugin://<id> prefix"""
    if not uri or not uri.startswith(PLUGIN_URL):
        return ''
    path = urlsplit(uri).path
    return path if path.endswith('/') else path + '/'


def plugin_params(uri):
    return dict(parse_qsl(urlsplit(uri).query, keep_blank_values=True))


def create_uri(path, params=None):
    path = path.strip('/')
    uri = PLUGIN_URL + ('/%s/' % path if path else '/')
    if params:
        uri = '?'.join((uri, urlencode(params)))
    return uri


def root_uri():
    return create_uri('', {CLASSIC_MENU: 'true'})


def request_uri(uri):
    """
    Mark listings requested by the home window, so that the plugin does not
    block them with modal dialogs or navigate away from the home window
    """
    parts = urlsplit(uri)
    params = parse_qsl(parts.query, keep_blank_values=True)
    params.append((HOME_WINDOW_REQUEST, 'true'))
    return ''.join((parts.scheme, '://', parts.netloc, parts.path,
                    '?', urlencode(params)))


def is_action_uri(uri):
    path = plugin_path(uri)
    return bool(path) and path.startswith(ACTION_PATHS)


def is_search_input_uri(uri):
    return plugin_path(uri).startswith(PATHS.SEARCH + '/input')


def search_query_uri(input_uri, query):
    params = plugin_params(input_uri)
    params['q'] = query
    params['category_label'] = query
    return create_uri(PATHS.SEARCH + '/query', params)


HOME_WINDOW_PARAM_RE = re.compile(
    r'(?P<sep>[?&])' + HOME_WINDOW_REQUEST + r'=[^&"\)]*(?P<end>&?)',
    re.IGNORECASE,
)


def strip_home_window_param(text):
    """
    Remove the home window marker from uris of listed items, it must only
    be set for listings requested by the home window and never for actions
    or playback, which would otherwise run without error handling
    """
    if not text or HOME_WINDOW_REQUEST not in text.lower():
        return text

    def _replace(match):
        if match.group('end'):
            return match.group('sep')
        return ''

    return HOME_WINDOW_PARAM_RE.sub(_replace, text)


def decode_image(url):
    """Kodi JSON-RPC returns art as image://<url encoded path>/"""
    if url and url.startswith('image://'):
        return unquote(url[len('image://'):].rstrip('/'))
    return url or ''


def format_duration(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ''
    if seconds <= 0:
        return ''
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return '%d:%02d:%02d' % (hours, minutes, seconds)
    return '%d:%02d' % (minutes, seconds)


def build_request(uri, properties=LIST_PROPERTIES):
    return {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'Files.GetDirectory',
        'params': {
            'directory': uri,
            'media': 'video',
            'properties': list(properties),
        },
    }


def parse_response(response):
    if not response:
        return []
    if not isinstance(response, dict):
        try:
            response = json.loads(response)
        except ValueError:
            return []
    result = response.get('result') or {}
    return result.get('files') or []


def normalise_item(raw, live_label='Live', base_uri=None):
    """Convert a JSON-RPC file entry to the dict used by the home window"""
    props = {}
    context_menu = {}
    for key, value in (raw.get('customproperties') or {}).items():
        key = key.lower()
        if key.startswith(('contextmenulabel(', 'contextmenuaction(')):
            kind, _, index = key[:-1].partition('(')
            try:
                index = int(index)
            except ValueError:
                continue
            context_menu.setdefault(index, {})[kind] = value
        else:
            props[key] = value
    uri = strip_home_window_param(raw.get('file', ''))
    art = raw.get('art') or {}
    thumb = (art.get('thumb')
             or art.get('poster')
             or raw.get('thumbnail')
             or art.get('icon')
             or '')
    fanart = art.get('fanart') or raw.get('fanart') or ''
    icon = decode_image(art.get('icon') or thumb)

    is_folder = raw.get('filetype') == 'directory'
    path = plugin_path(uri)
    # next page items link to the same path as the listing, with a page param
    is_next_page = props.get('specialsort') == 'bottom' or (
        is_folder
        and base_uri is not None
        and path == plugin_path(base_uri)
        and 'page' in plugin_params(uri)
    )
    is_playable = (not is_folder
                   and (props.get('isplayable') == 'true'
                        or path.startswith(PATHS.PLAY + '/')))
    is_video = bool(props.get('video_id')) and is_playable

    resume = raw.get('resume') or {}
    position = resume.get('position') or 0
    # duration is not returned for plugin items, but the resume total is set
    total = raw.get('duration') or resume.get('total') or 0
    progress = 0
    if position > 0 and total > 0:
        progress = min(100, int(100 * position / total))

    artists = raw.get('artist') or []
    if not isinstance(artists, (list, tuple)):
        artists = [artists]
    published = props.get('publishedsince', '')
    live = bool(published) and published == live_label
    subtitle = ' • '.join(
        part for part in (', '.join(artists), published) if part
    )

    return {
        'label': raw.get('label') or raw.get('title') or '',
        'title': raw.get('title') or raw.get('label') or '',
        'uri': uri,
        'path': path,
        'thumb': thumb,
        'fanart': fanart,
        'icon': icon,
        'plot': raw.get('plot', ''),
        'duration': total,
        'duration_label': format_duration(total),
        'resume': position,
        'total': total,
        'progress': progress,
        'playcount': raw.get('playcount') or 0,
        'artists': list(artists),
        'subtitle': subtitle,
        'live': live,
        'is_folder': is_folder,
        'is_playable': is_playable,
        'is_video': is_video,
        'is_next_page': is_next_page,
        'is_action': not is_folder and not is_playable,
        'properties': props,
        'context_menu': [
            (entry.get('contextmenulabel', ''),
             strip_home_window_param(entry.get('contextmenuaction')))
            for _, entry in sorted(context_menu.items())
        ],
        'is_nav_folder': (is_folder
                          and ADDON_MEDIA in decode_image(thumb)
                          and not is_next_page),
        'is_back': path.startswith(PATHS.COMMAND + '/Action(Back)'),
        'tile': 'video' if is_video else 'folder',
    }


def order_items(items, folders_first=False):
    """
    Listings can start with navigation folders, e.g. Shorts and Live in the
    subscription feed. Rows show videos first unless folders_first is set.
    """
    items = [item for item in items
             if not item['is_back'] and not item['is_next_page']]
    folders = [item for item in items if item['is_nav_folder']]
    content = [item for item in items if not item['is_nav_folder']]
    return folders + content if folders_first else content + folders


def make_item(**kwargs):
    """Create an item that does not come from a plugin listing, e.g. a tile"""
    item = {
        'label': '',
        'title': '',
        'uri': '',
        'path': '',
        'thumb': '',
        'fanart': '',
        'icon': '',
        'plot': '',
        'duration': 0,
        'duration_label': '',
        'resume': 0,
        'total': 0,
        'progress': 0,
        'playcount': 0,
        'artists': [],
        'subtitle': '',
        'live': False,
        'is_folder': False,
        'is_playable': False,
        'is_video': False,
        'is_next_page': False,
        'is_action': False,
        'is_nav_folder': False,
        'is_back': False,
        'properties': {},
        'context_menu': [],
        'tile': 'folder',
    }
    item.update(kwargs)
    if not item['title']:
        item['title'] = item['label']
    if item['uri'] and not item['path']:
        item['path'] = plugin_path(item['uri'])
    return item


def is_continue_candidate(item):
    return (item['is_video']
            and item['resume'] > 0
            and 0 < item['progress'] < CONTINUE_MAX_PERCENT)


def classify_root_items(items):
    """
    Distribute the entries of the classic root menu to the tabs of the home
    window. Every entry ends up in at least one tab, so no feature of the
    classic menu is lost.

    :return: dict of tab id to list of row dicts
    """
    tabs = {tab: [] for tab in TABS}
    history = None

    for item in items:
        path = item['path']
        if path.startswith(PATHS.COMMAND + '/'):
            # skip the entry that opens the home window itself
            continue

        icon = os.path.basename(item['icon'].split('?')[0])
        if path.startswith('/users/'):
            rules = ((TAB_ACCOUNT, ROW_ACTIONS),)
        elif path.startswith(('/sign/', '/config/')):
            rules = ((TAB_ACCOUNT, ROW_ACTIONS),)
        elif is_search_input_uri(item['uri']):
            rules = ((TAB_SEARCH, ROW_ACTIONS),)
        else:
            rules = ICON_RULES.get(icon)
            if not rules:
                rules = (((TAB_ACCOUNT, ROW_ACTIONS),)
                         if item['is_action'] else
                         ((TAB_LIBRARY, ROW_FEED),))

        if icon == 'history.png' and history is None:
            history = item

        for tab, row_type in rules:
            if row_type == ROW_FEED and item['is_action']:
                row_type = ROW_ACTIONS
            if row_type == ROW_FEED:
                tabs[tab].append({
                    'type': ROW_FEED,
                    'title': item['label'],
                    'uri': item['uri'],
                    'folders_first': tab == TAB_SUBSCRIPTIONS,
                })
            elif row_type == ROW_SEARCH_HISTORY:
                tabs[tab].append({
                    'type': ROW_SEARCH_HISTORY,
                    'title': item['label'],
                    'uri': item['uri'],
                })
            else:
                rows = tabs[tab]
                if rows and rows[0]['type'] == ROW_ACTIONS:
                    rows[0]['items'].append(item)
                else:
                    rows.insert(0, {
                        'type': ROW_ACTIONS,
                        'title': None,
                        'items': [item],
                    })

    # Only show a subscription feed once on the home tab
    seen = set()
    home_rows = []
    for row in tabs[TAB_HOME]:
        uri = row.get('uri')
        if uri and uri in seen:
            continue
        seen.add(uri)
        home_rows.append(row)
    tabs[TAB_HOME] = home_rows

    def _explore_order(row):
        path = plugin_path(row.get('uri', ''))
        for index, prefix in enumerate(EXPLORE_ORDER):
            if path.startswith(prefix):
                return index
        return len(EXPLORE_ORDER)

    tabs[TAB_EXPLORE].sort(key=lambda row: (row['type'] != ROW_ACTIONS,
                                            _explore_order(row)))

    # videos watched in Kodi first, the YouTube history only contains them if
    # remote history updates are enabled
    tabs[TAB_LIBRARY].sort(key=lambda row: (
        row['type'] != ROW_ACTIONS,
        plugin_path(row.get('uri', '')) != plugin_path(LOCAL_HISTORY_URI),
    ))

    # Resume points are only available from the local playback history, the
    # history entry of the menu (e.g. the YouTube history) is the fallback
    tabs[TAB_HOME].insert(0, {
        'type': ROW_CONTINUE,
        'title': None,
        'uri': LOCAL_HISTORY_URI,
        'fallback_uri': history['uri'] if history else None,
    })
    return tabs


def resolve_label(label, info_label, localize):
    """Resolve $INFO[...] and $LOCALIZE[...] in context menu labels"""
    if not label:
        return ''
    if '$LOCALIZE[' in label:
        label = LOCALIZE_RE.sub(lambda match: localize(int(match.group(1))),
                                label)
    if '$INFO[' in label:
        label = INFO_RE.sub(lambda match: info_label(match.group(1)), label)
    return label


def context_menu_entries(item):
    """Return the (label, action) pairs of the item's context menu"""
    return [
        (label, action)
        for label, action in item.get('context_menu') or ()
        if label and action and action != 'noop'
    ]


def is_refresh_action(uri):
    return plugin_params(uri).get('refresh') not in (None, '', '0')


def _strip_call(action, name):
    if action.lower().startswith(name.lower() + '(') and action.endswith(')'):
        return action[len(name) + 1:-1]
    return None


def navigation_target(action):
    """
    Return the plugin uri if the action only navigates to a plugin listing,
    so it can be shown inside the home window instead of the classic list.
    """
    action = (action or '').strip()

    uri = None
    args = _strip_call(action, 'RunPlugin')
    if args is not None:
        uri = args.split(',')[0].strip().strip('"')
        route = PLUGIN_URL + PATHS.ROUTE + '/'
        if not uri.startswith(route):
            return None
        uri = PLUGIN_URL + '/' + uri[len(route):]
    else:
        args = _strip_call(action, 'ActivateWindow')
        if args is not None:
            args = args.split(',')
            if (len(args) < 2
                    or args[0].strip().lower() not in {'videos', '10025'}):
                return None
            uri = args[1].strip().strip('"')
        else:
            args = _strip_call(action, 'Container.Update')
            if args is not None:
                uri = args.split(',')[0].strip().strip('"')

    if not uri or not uri.startswith(PLUGIN_URL):
        return None
    return uri


def resolve_uri(uri, info_label):
    """
    Resolve $INFO[...] placeholders in a plugin uri. Values are resolved per
    path segment and per parameter, then encoded again, so that resolved
    values containing reserved characters do not break the uri.
    """
    parts = urlsplit(uri)
    path = '/'.join(
        quote(INFO_RE.sub(lambda match: info_label(match.group(1)),
                          unquote(segment)), safe='')
        for segment in parts.path.split('/')
    )
    params = [
        (key, INFO_RE.sub(lambda match: info_label(match.group(1)), value))
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != CONTEXT_MENU
    ]
    uri = ''.join((parts.scheme, '://', parts.netloc, path))
    if params:
        uri = '?'.join((uri, urlencode(params)))
    return uri
