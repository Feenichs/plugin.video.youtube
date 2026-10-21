#!/usr/bin/env python3
"""
Generates the skin files of the TV interface (home window):

- resources/skins/default/1080i/script-youtube-home.xml
- resources/skins/default/media/yt_*.png

Kodi windows cannot define their own includes, and the eight content rows of
the home window use identical tile layouts, so the window XML is generated
from the templates below. Re-run this script after changing them:

    python3 .scripts/generate_home_window.py

    Copyright (C) 2026 plugin.video.youtube

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.
"""

import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIN = os.path.join(ROOT, 'resources', 'skins', 'default')
XML_PATH = os.path.join(SKIN, '1080i', 'script-youtube-home.xml')
MEDIA = os.path.join(SKIN, 'media')

ADDON = 'plugin.video.youtube'
NUM_ROWS = 8

# Colours (AARRGGBB)
BACKGROUND = 'FF0F0F0F'
TEXT = 'FFF1F1F1'
TEXT_DIM = 'FFAAAAAA'
TEXT_DARK = 'FF0F0F0F'
ACCENT = 'FFFF0033'
TILE = 'FF272727'

NAV_WIDTH = 235

# Tile geometry
TILE_WIDTH = 400
TILE_HEIGHT = 370
THUMB_LEFT = 10
THUMB_TOP = 10
THUMB_WIDTH = 380
THUMB_HEIGHT = 214


# ---------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------

def write_png(path, width, height, pixel):
    """Write an RGBA PNG, pixel(x, y) returns (r, g, b, a)"""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixel(x, y))

    def chunk(kind, payload):
        return (struct.pack('>I', len(payload))
                + kind
                + payload
                + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))

    png = b''.join((
        b'\x89PNG\r\n\x1a\n',
        chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)),
        chunk(b'IDAT', zlib.compress(bytes(raw), 9)),
        chunk(b'IEND', b''),
    ))
    with open(path, 'wb') as png_file:
        png_file.write(png)


def rounded_coverage(x, y, width, height, radius, samples=4):
    """Anti-aliased coverage (0..1) of a pixel within a rounded rectangle"""
    inside = 0
    for sub_y in range(samples):
        for sub_x in range(samples):
            px = x + (sub_x + 0.5) / samples
            py = y + (sub_y + 0.5) / samples
            cx = min(max(px, radius), width - radius)
            cy = min(max(py, radius), height - radius)
            if (px - cx) ** 2 + (py - cy) ** 2 <= radius ** 2:
                inside += 1
    return inside / (samples * samples)


def rounded(width, height, radius, outline=0):
    def pixel(x, y):
        alpha = rounded_coverage(x, y, width, height, radius)
        if outline:
            inner = rounded_coverage(x - outline,
                                     y - outline,
                                     width - 2 * outline,
                                     height - 2 * outline,
                                     max(radius - outline, 1))
            if (outline <= x < width - outline
                    and outline <= y < height - outline):
                alpha = max(0.0, alpha - inner)
        return 255, 255, 255, int(round(255 * alpha))

    return pixel


def generate_textures():
    if not os.path.isdir(MEDIA):
        os.makedirs(MEDIA)

    write_png(os.path.join(MEDIA, 'yt_white.png'), 8, 8,
              lambda x, y: (255, 255, 255, 255))
    # 9-slice textures, used with border="16" / border="31" / border="20"
    write_png(os.path.join(MEDIA, 'yt_rounded.png'), 64, 64,
              rounded(64, 64, 14))
    write_png(os.path.join(MEDIA, 'yt_pill.png'), 64, 64,
              rounded(64, 64, 31))
    write_png(os.path.join(MEDIA, 'yt_focus.png'), 64, 64,
              rounded(64, 64, 18, outline=5))
    # alpha mask for rounded 16:9 thumbnails
    write_png(os.path.join(MEDIA, 'yt_mask.png'), THUMB_WIDTH, THUMB_HEIGHT,
              rounded(THUMB_WIDTH, THUMB_HEIGHT, 14))
    # gradients used to blend the preview image into the background
    write_png(os.path.join(MEDIA, 'yt_gradient_left.png'), 256, 4,
              lambda x, y: (15, 15, 15, int(255 * (1 - x / 255.0) ** 1.4)))
    write_png(os.path.join(MEDIA, 'yt_gradient_bottom.png'), 4, 256,
              lambda x, y: (15, 15, 15, int(255 * (y / 255.0) ** 1.2)))


# ---------------------------------------------------------------------------
# Window XML
# ---------------------------------------------------------------------------

def localize(string_id):
    return '$ADDON[%s %d]' % (ADDON, string_id)


def tile_layout(list_id, focused, width=TILE_WIDTH):
    """Layout of one tile; list_id is used for focus dependent styling"""
    offset = (width - TILE_WIDTH) // 2
    has_focus = 'Control.HasFocus(%d)' % list_id
    zoom = ''
    focus_ring = ''
    title_colour = TEXT
    if focused:
        zoom = (
            '<animation effect="zoom" end="105" center="{cx},{cy}" time="150"'
            ' tween="sine" condition="{focus}">Conditional</animation>'
        ).format(cx=offset + THUMB_LEFT + THUMB_WIDTH // 2,
                 cy=THUMB_TOP + THUMB_HEIGHT // 2,
                 focus=has_focus)
        focus_ring = '''
            <control type="image">
                <left>{left}</left><top>{top}</top>
                <width>{width}</width><height>{height}</height>
                <texture border="20" colordiffuse="FFFFFFFF">yt_focus.png</texture>
                <visible>{focus}</visible>
            </control>'''.format(left=THUMB_LEFT - 7,
                                 top=THUMB_TOP - 7,
                                 width=THUMB_WIDTH + 14,
                                 height=THUMB_HEIGHT + 14,
                                 focus=has_focus)
        title_colour = 'FFFFFFFF'

    return '''
        <control type="group">
            <left>{offset}</left>
            {zoom}
            <control type="image">
                <left>{tl}</left><top>{tt}</top><width>{tw}</width><height>{th}</height>
                <texture border="16" colordiffuse="{tile}">yt_rounded.png</texture>
            </control>
            <control type="image">
                <left>{tl}</left><top>{tt}</top><width>{tw}</width><height>{th}</height>
                <aspectratio>scale</aspectratio>
                <texture background="true" diffuse="yt_mask.png">$INFO[ListItem.Art(thumb)]</texture>
                <visible>String.IsEqual(ListItem.Property(tile),video)</visible>
            </control>
            <control type="image">
                <left>{il}</left><top>{it}</top><width>{iw}</width><height>{ih}</height>
                <aspectratio>keep</aspectratio>
                <texture background="true">$INFO[ListItem.Art(thumb)]</texture>
                <visible>String.IsEqual(ListItem.Property(tile),folder)</visible>
            </control>
            <control type="label">
                <left>{tl}</left><top>{tt}</top><width>{tw}</width><height>{th}</height>
                <align>center</align><aligny>center</aligny>
                <font>font30_title</font>
                <textcolor>{text}</textcolor>
                <label>{show_all}  &#x203A;</label>
                <visible>String.IsEqual(ListItem.Property(tile),all)</visible>
            </control>
            <control type="label">
                <left>{tl}</left><top>{tt}</top><width>{tw}</width><height>{th}</height>
                <align>center</align><aligny>center</aligny>
                <font>font30_title</font>
                <textcolor>{text}</textcolor>
                <label>&#x2039;  $INFO[ListItem.Label]</label>
                <visible>String.IsEqual(ListItem.Property(tile),back)</visible>
            </control>
            <control type="label">
                <left>{tl}</left><top>{tt}</top><width>{tw}</width><height>{th}</height>
                <align>center</align><aligny>center</aligny>
                <font>font30_title</font>
                <textcolor>{text}</textcolor>
                <label>$INFO[ListItem.Label]  &#x203A;</label>
                <visible>String.IsEqual(ListItem.Property(tile),next)</visible>
            </control>
            <control type="image">
                <left>{tl}</left><top>{tt}</top><width>{tw}</width><height>{th}</height>
                <texture border="16" colordiffuse="88000000">yt_rounded.png</texture>
                <visible>String.IsEqual(ListItem.Property(watched),true)</visible>
            </control>
            <control type="progress">
                <left>{pl}</left><top>{pt}</top><width>{pw}</width><height>6</height>
                <texturebg colordiffuse="66FFFFFF">yt_white.png</texturebg>
                <midtexture colordiffuse="{accent}">yt_white.png</midtexture>
                <info>ListItem.PercentPlayed</info>
                <visible>!String.IsEmpty(ListItem.Property(progress))</visible>
            </control>
            <control type="group">
                <left>{bl}</left><top>{bt}</top>
                <visible>!String.IsEmpty(ListItem.Property(duration_label)) + !String.IsEqual(ListItem.Property(live),true)</visible>
                <control type="image">
                    <width>96</width><height>36</height>
                    <texture border="16" colordiffuse="DD000000">yt_rounded.png</texture>
                </control>
                <control type="label">
                    <width>96</width><height>36</height>
                    <align>center</align><aligny>center</aligny>
                    <font>font10</font><textcolor>FFFFFFFF</textcolor>
                    <label>$INFO[ListItem.Property(duration_label)]</label>
                </control>
            </control>
            <control type="group">
                <left>{bl}</left><top>{bt}</top>
                <visible>String.IsEqual(ListItem.Property(live),true)</visible>
                <control type="image">
                    <width>96</width><height>36</height>
                    <texture border="16" colordiffuse="{accent}">yt_rounded.png</texture>
                </control>
                <control type="label">
                    <width>96</width><height>36</height>
                    <align>center</align><aligny>center</aligny>
                    <font>font10</font><textcolor>FFFFFFFF</textcolor>
                    <label>LIVE</label>
                </control>
            </control>
            {focus_ring}
            <control type="textbox">
                <left>{xl}</left><top>{xt}</top><width>{xw}</width><height>86</height>
                <font>font13</font>
                <textcolor>{title_colour}</textcolor>
                <label>$INFO[ListItem.Label]</label>
                <visible>!String.IsEqual(ListItem.Property(tile),all) + !String.IsEqual(ListItem.Property(tile),back) + !String.IsEqual(ListItem.Property(tile),next)</visible>
            </control>
            <control type="label">
                <left>{xl}</left><top>{st}</top><width>{xw}</width><height>32</height>
                <font>font10</font>
                <textcolor>{dim}</textcolor>
                <scroll>{scroll}</scroll>
                <label>$INFO[ListItem.Label2]</label>
            </control>
        </control>'''.format(
        offset=offset,
        zoom=zoom,
        focus_ring=focus_ring,
        tl=THUMB_LEFT, tt=THUMB_TOP, tw=THUMB_WIDTH, th=THUMB_HEIGHT,
        il=THUMB_LEFT + 20, it=THUMB_TOP + 12,
        iw=THUMB_WIDTH - 40, ih=THUMB_HEIGHT - 24,
        pl=THUMB_LEFT + 12, pt=THUMB_TOP + THUMB_HEIGHT - 14,
        pw=THUMB_WIDTH - 24,
        bl=THUMB_LEFT + THUMB_WIDTH - 106, bt=THUMB_TOP + THUMB_HEIGHT - 50,
        xl=THUMB_LEFT + 2, xt=THUMB_TOP + THUMB_HEIGHT + 10,
        xw=THUMB_WIDTH - 4,
        st=THUMB_TOP + THUMB_HEIGHT + 106,
        tile=TILE, text=TEXT, dim=TEXT_DIM, accent=ACCENT,
        title_colour=title_colour,
        show_all=localize(30838),
        scroll='true' if focused else 'false',
    )


def row(index):
    list_id = 301 + index
    return '''
            <control type="group" id="{group_id}">
                <width>1920</width><height>430</height>
                <control type="label" id="{label_id}">
                    <left>80</left><top>0</top><width>1600</width><height>50</height>
                    <font>font30_title</font>
                    <textcolor>{text}</textcolor>
                </control>
                <control type="list" id="{list_id}">
                    <left>60</left><top>50</top><width>1860</width><height>380</height>
                    <orientation>horizontal</orientation>
                    <onup>{onup}</onup>
                    <ondown>{ondown}</ondown>
                    <scrolltime tween="sine">200</scrolltime>
                    <itemlayout width="{tile_width}" height="{tile_height}">{item}
                    </itemlayout>
                    <focusedlayout width="{tile_width}" height="{tile_height}">{focused}
                    </focusedlayout>
                </control>
            </control>'''.format(
        group_id=501 + index,
        label_id=401 + index,
        list_id=list_id,
        # moving between rows is handled by the window, which hides the rows
        # above the focused one, so that the focused row is always on top
        onup=list_id,
        ondown=list_id,
        text=TEXT,
        tile_width=TILE_WIDTH,
        tile_height=TILE_HEIGHT,
        item=tile_layout(list_id, False),
        focused=tile_layout(list_id, True),
    )


def nav_layout(focused):
    has_focus = 'Control.HasFocus(100)'
    active = 'String.IsEqual(ListItem.Property(active),true)'
    pill = ''
    if focused:
        pill = '''
            <control type="image">
                <left>6</left><top>6</top><width>{width}</width><height>58</height>
                <texture border="28" colordiffuse="FFFFFFFF">yt_pill.png</texture>
                <visible>{focus}</visible>
            </control>'''.format(focus=has_focus, width=NAV_WIDTH - 12)
    focus_condition = (' + !%s' % has_focus) if focused else ''
    dark_label = ''
    if focused:
        dark_label = '''
            <control type="label">
                <width>{nav_width}</width><height>70</height>
                <align>center</align><aligny>center</aligny>
                <font>font14</font><textcolor>{dark}</textcolor>
                <label>$INFO[ListItem.Label]</label>
                <visible>{focus}</visible>
            </control>'''.format(dark=TEXT_DARK, focus=has_focus,
                                 nav_width=NAV_WIDTH)
    return '''{pill}
            <control type="label">
                <width>{nav_width}</width><height>70</height>
                <align>center</align><aligny>center</aligny>
                <font>font14</font><textcolor>{text}</textcolor>
                <label>$INFO[ListItem.Label]</label>
                <visible>{active}{focus_condition}</visible>
            </control>
            <control type="label">
                <width>{nav_width}</width><height>70</height>
                <align>center</align><aligny>center</aligny>
                <font>font14</font><textcolor>{dim}</textcolor>
                <label>$INFO[ListItem.Label]</label>
                <visible>!{active}{focus_condition}</visible>
            </control>{dark_label}
            <control type="image">
                <left>{bar_left}</left><top>62</top><width>60</width><height>4</height>
                <texture colordiffuse="{accent}">yt_white.png</texture>
                <visible>{active}{focus_condition}</visible>
            </control>'''.format(
        pill=pill,
        dark_label=dark_label,
        text=TEXT,
        dim=TEXT_DIM,
        accent=ACCENT,
        active=active,
        focus_condition=focus_condition,
        nav_width=NAV_WIDTH,
        bar_left=(NAV_WIDTH - 60) // 2,
    )


WINDOW_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<!-- Generated by .scripts/generate_home_window.py - do not edit manually -->
<window>
    <defaultcontrol>100</defaultcontrol>
    <backgroundcolor>{background}</backgroundcolor>
    <animation effect="fade" time="250">WindowOpen</animation>
    <animation effect="fade" time="200">WindowClose</animation>
    <controls>
        <!--
            A video that keeps playing in the background has to be rendered,
            otherwise it runs out of sync with the audio. It is shown in the
            preview area, or dimmed behind the grid.
        -->
        <control type="videowindow">
            <width>1920</width><height>1080</height>
            <visible>Player.HasVideo + !{hero_visible}</visible>
        </control>
        <control type="image">
            <width>1920</width><height>1080</height>
            <texture colordiffuse="{background}">yt_white.png</texture>
            <visible>!Player.HasVideo | {hero_visible}</visible>
        </control>
        <control type="image">
            <width>1920</width><height>1080</height>
            <texture colordiffuse="{background_dimmed}">yt_white.png</texture>
            <visible>Player.HasVideo + !{hero_visible}</visible>
        </control>

        <!-- Preview of the selected item -->
        <control type="group">
            <visible>{hero_visible}</visible>
            <control type="image">
                <left>620</left><top>0</top><width>1300</width><height>732</height>
                <aspectratio>scale</aspectratio>
                <fadetime>300</fadetime>
                <texture background="true">$INFO[ListItem.Art(fanart)]</texture>
                <visible>!Player.HasVideo</visible>
            </control>
            <control type="image">
                <left>620</left><top>0</top><width>1300</width><height>732</height>
                <aspectratio>scale</aspectratio>
                <fadetime>300</fadetime>
                <texture background="true">$INFO[ListItem.Property(hero)]</texture>
                <visible>!Player.HasVideo + !String.IsEmpty(ListItem.Property(hero))</visible>
            </control>
            <control type="videowindow">
                <left>620</left><top>0</top><width>1300</width><height>732</height>
                <visible>Player.HasVideo</visible>
            </control>
            <control type="image">
                <left>620</left><top>0</top><width>760</width><height>732</height>
                <texture>yt_gradient_left.png</texture>
            </control>
            <control type="image">
                <left>620</left><top>380</top><width>1300</width><height>352</height>
                <texture>yt_gradient_bottom.png</texture>
            </control>
            <!-- darken the preview behind the header, two soft gradients -->
            <control type="image">
                <width>1920</width><height>300</height>
                <texture flipy="true">yt_gradient_bottom.png</texture>
            </control>
            <control type="image">
                <width>1920</width><height>170</height>
                <texture flipy="true">yt_gradient_bottom.png</texture>
            </control>
        </control>
        <control type="group">
            <left>80</left><top>150</top>
            <visible>String.IsEqual(Window.Property(view),tab)</visible>
            <control type="label">
                <width>1100</width><height>70</height>
                <font>font45_title</font>
                <textcolor>{text}</textcolor>
                <label>$INFO[ListItem.Label]</label>
            </control>
            <control type="label">
                <top>72</top><width>1000</width><height>40</height>
                <font>font13</font>
                <textcolor>{dim}</textcolor>
                <label>$INFO[ListItem.Label2]</label>
            </control>
            <control type="group">
                <top>124</top>
                <visible>!String.IsEmpty(ListItem.Property(duration_label)) | String.IsEqual(ListItem.Property(live),true)</visible>
                <control type="image">
                    <width>110</width><height>38</height>
                    <texture border="16" colordiffuse="FF3A3A3A">yt_rounded.png</texture>
                    <visible>!String.IsEqual(ListItem.Property(live),true)</visible>
                </control>
                <control type="image">
                    <width>110</width><height>38</height>
                    <texture border="16" colordiffuse="{accent}">yt_rounded.png</texture>
                    <visible>String.IsEqual(ListItem.Property(live),true)</visible>
                </control>
                <control type="label">
                    <width>110</width><height>38</height>
                    <align>center</align><aligny>center</aligny>
                    <font>font10</font><textcolor>FFFFFFFF</textcolor>
                    <label>$INFO[ListItem.Property(duration_label)]</label>
                    <visible>!String.IsEqual(ListItem.Property(live),true)</visible>
                </control>
                <control type="label">
                    <width>110</width><height>38</height>
                    <align>center</align><aligny>center</aligny>
                    <font>font10</font><textcolor>FFFFFFFF</textcolor>
                    <label>LIVE</label>
                    <visible>String.IsEqual(ListItem.Property(live),true)</visible>
                </control>
            </control>
            <control type="textbox">
                <top>180</top><width>900</width><height>176</height>
                <font>font12</font>
                <textcolor>{dim}</textcolor>
                <label>$INFO[ListItem.Plot]</label>
                <autoscroll delay="6000" time="3000" repeat="10000">Control.HasFocus(300) | Control.HasFocus(100)</autoscroll>
            </control>
        </control>

        <!-- Header -->
        <control type="image">
            <left>60</left><top>36</top><width>56</width><height>56</height>
            <aspectratio>keep</aspectratio>
            <texture>$INFO[Window.Property(icon)]</texture>
        </control>
        <control type="label">
            <left>128</left><top>36</top><width>220</width><height>56</height>
            <aligny>center</aligny>
            <font>font30_title</font>
            <textcolor>{text}</textcolor>
            <label>YouTube</label>
        </control>
        <control type="list" id="100">
            <left>320</left><top>28</top><width>1420</width><height>72</height>
            <orientation>horizontal</orientation>
            <!-- moving down is handled by the window -->
            <ondown>100</ondown>
            <scrolltime>150</scrolltime>
            <itemlayout width="{nav_width}" height="72">{nav_item}
            </itemlayout>
            <focusedlayout width="{nav_width}" height="72">{nav_focused}
            </focusedlayout>
        </control>
        <control type="label">
            <right>60</right><top>28</top><width>400</width><height>40</height>
            <align>right</align>
            <font>font14</font>
            <textcolor>{text}</textcolor>
            <label>$INFO[System.Time]</label>
        </control>
        <control type="label">
            <right>60</right><top>66</top><width>400</width><height>32</height>
            <align>right</align>
            <font>font10</font>
            <textcolor>{dim}</textcolor>
            <label>$INFO[Window.Property(user)]</label>
        </control>

        <!-- Rows -->
        <control type="grouplist" id="300">
            <left>0</left><top>570</top><width>1920</width><height>510</height>
            <orientation>vertical</orientation>
            <itemgap>10</itemgap>
            <scrolltime tween="sine">250</scrolltime>
            <onup>100</onup>
            <visible>String.IsEqual(Window.Property(view),tab)</visible>
            {rows}
        </control>

        <!-- Grid for folders, "show all" and search results -->
        <control type="group">
            <visible>String.IsEqual(Window.Property(view),grid)</visible>
            <control type="label">
                <left>80</left><top>130</top><width>1760</width><height>60</height>
                <font>font36_title</font>
                <textcolor>{text}</textcolor>
                <label>$INFO[Window.Property(grid_title)]</label>
            </control>
            <control type="panel" id="600">
                <left>60</left><top>210</top><width>1820</width><height>870</height>
                <orientation>vertical</orientation>
                <onup>100</onup>
                <scrolltime tween="sine">250</scrolltime>
                <itemlayout width="{grid_width}" height="{tile_height}">{grid_item}
                </itemlayout>
                <focusedlayout width="{grid_width}" height="{tile_height}">{grid_focused}
                </focusedlayout>
            </control>
        </control>

        <!-- Status -->
        <control type="label">
            <left>80</left><bottom>40</bottom><width>1760</width><height>40</height>
            <align>center</align>
            <font>font13</font>
            <textcolor>{dim}</textcolor>
            <label>{loading}</label>
            <visible>String.IsEqual(Window.Property(loading),true)</visible>
            <animation effect="fade" start="100" end="40" time="800" pulse="true" condition="true">Conditional</animation>
        </control>
        <control type="label">
            <left>80</left><top>700</top><width>1760</width><height>60</height>
            <align>center</align>
            <font>font14</font>
            <textcolor>{dim}</textcolor>
            <label>{empty}</label>
            <visible>String.IsEqual(Window.Property(empty),true) + !String.IsEqual(Window.Property(loading),true)</visible>
        </control>
    </controls>
</window>
'''


def generate_window():
    grid_width = 455
    xml = WINDOW_TEMPLATE.format(
        background=BACKGROUND,
        background_dimmed='E6' + BACKGROUND[2:],
        hero_visible='(String.IsEqual(Window.Property(view),tab)'
                     ' + String.IsEqual(Window.Property(hero),true))',
        text=TEXT,
        dim=TEXT_DIM,
        accent=ACCENT,
        nav_width=NAV_WIDTH,
        nav_item=nav_layout(False),
        nav_focused=nav_layout(True),
        rows=''.join(row(index) for index in range(NUM_ROWS)),
        grid_width=grid_width,
        tile_height=TILE_HEIGHT,
        grid_item=tile_layout(600, False, grid_width),
        grid_focused=tile_layout(600, True, grid_width),
        loading=localize(30839),
        empty=localize(30840),
    )
    directory = os.path.dirname(XML_PATH)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(XML_PATH, 'w', encoding='utf-8') as xml_file:
        xml_file.write(xml)


if __name__ == '__main__':
    generate_textures()
    generate_window()
    print('Generated', os.path.relpath(XML_PATH, ROOT))
