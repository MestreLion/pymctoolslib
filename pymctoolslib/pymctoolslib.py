#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#    Copyright (C) 2014 Rodrigo Silva (MestreLion) <linux@rodrigosilva.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program. See <http://www.gnu.org/licenses/gpl.html>

# Installing requirements in Debian/Ubuntu:
# ln -s /PATH/TO/pymclevel /PATH/TO/THIS/SCRIPT

"""
Library to manipulate Minecraft worlds

A wrapper to pymclevel with simpler API
"""

__all__ = [
    "basic_parser",
    "load_world",
    "get_player",
    "load_player_dimension",
    "Item",
    "get_chunks",
    "iter_chunks",
    "MCError",
]


import os.path as osp
import argparse
import logging
import time

import progressbar


log = logging.getLogger(__name__)


def basic_parser(description=None,
                 player=True,
                 default_world="New World",
                 default_player="Player",
                 **kw_argparser):
    parser = argparse.ArgumentParser(description=description, **kw_argparser)

    parser.add_argument('--quiet', '-q', dest='loglevel',
                        const=logging.WARNING, default=logging.INFO,
                        action="store_const",
                        help="Suppress informative messages.")

    parser.add_argument('--verbose', '-v', dest='loglevel',
                        const=logging.DEBUG,
                        action="store_const",
                        help="Verbose mode, output extra info.")

    parser.add_argument('--world', '-w', default=default_world,
                        help="Minecraft world, either its 'level.dat' file"
                            " or a name under '~/.minecraft/saves' folder."
                            " [Default: '%(default)s']")

    if player:
        parser.add_argument('--player', '-p', default=default_player,
                            help="Player name."
                                " [Default: '%(default)s']")

    return parser


def load_world(name):
    import pymclevel
    if isinstance(name, pymclevel.MCLevel):
        return name

    try:
        if osp.isfile(name):
            return pymclevel.fromFile(name)
        else:
            return pymclevel.loadWorld(name)
    except IOError as e:
        raise MCError(e)
    except pymclevel.mclevel.LoadingError:
        raise MCError("Not a valid Minecraft world: '%s'" % name)


def get_player(world, playername=None):
    import pymclevel
    if playername is None:
        playername = "Player"
    try:
        return world.getPlayerTag(playername)
    except pymclevel.PlayerNotFound:
        raise MCError("Player not found in world '%s': %s" %
                             (world.LevelName, playername))


def load_player_dimension(levelname, playername=None):
    world = load_world(levelname)
    player = get_player(world, playername)
    if not player["Dimension"].value == 0:  # 0 = Overworld
        world = world.getDimension(player["Dimension"].value)

    return world, player


class NbtObject(object):
    '''High-level wrapper for NBT Compound tags'''

    def __init__(self, nbt, keys=None):
        import pymclevel.nbt

        assert nbt.tagID == pymclevel.nbt.TAG_COMPOUND, \
            "Can not create NbtObject from a non-compound NBT tag"

        self.nbt = nbt
        self.keys = keys or []  # dummy, for now

    def __str__(self):
        return str(self.nbt)

    def __repr__(self):
        return "<%s>" % (self.__class__.__name__)

    def __setitem__(self, key, value):
        '''Set `obj.nbt["SomeKey"].value = value` as `obj["SomeKey"] = value`'''
        self.nbt[key].value = value

    def __getitem__(self, key):
        '''Access `obj.nbt["SomeKey"].value` as `obj["SomeKey"]`'''
        return self.nbt[key].value

    def __contains__(self, name):
        '''Allow `if key in obj...`'''
        return name in self.nbt


class Item(NbtObject):
    _ItemTypes = None
    armor_ids = set(range(298, 318))

    def __init__(self, nbt, keys=None):
        if keys is None:
            keys = []
        keys.extend(("id", "Damage", "Count", "tag"))
        super(Item, self).__init__(nbt, keys)

        # Improve upon pymclevel item data
        if self._ItemTypes is None:
            from pymclevel.items import items as ItemTypes

            # Correct damage values for specific items
            for itemid, maxdamage in ((298,  56),  # Leather Cap
                                      (299,  81),  # Leather_Tunic
                                      (300,  76),  # Leather_Pants
                                      (301,  66),  # Leather_Boots
                                      (302, 166),  # Chainmail_Helmet
                                      (303, 241),  # Chainmail_Chestplate
                                      (304, 226),  # Chainmail_Leggings
                                      (305, 196),  # Chainmail_Boots
                                      (306, 166),  # Iron_Helmet
                                      (307, 241),  # Iron_Chestplate
                                      (308, 226),  # Iron_Leggings
                                      (309, 196),  # Iron_Boots
                                      (310, 364),  # Diamond_Helmet
                                      (311, 529),  # Diamond_Chestplate
                                      (312, 496),  # Diamond_Leggings
                                      (313, 430),  # Diamond_Boots
                                      (314,  78),  # Golden_Helmet
                                      (315,  87),  # Golden_Chestplate
                                      (316,  76),  # Golden_Leggings
                                      (317,  66),  # Golden_Boots
                                      ):
                ItemTypes.findItem(itemid).maxdamage = maxdamage - 1

            # Correct stack size for specific items
            for itemid, stacksize in ((58,  64),  # Workbench (Crafting Table)
                                      (116, 64),  # Enchantment Table
                                      (281, 64),  # Bowl
                                      (282,  1),  # Mushroom Stew
                                      (324,  1),  # Wooden Door
                                      (337, 64),  # Clay (Ball)
                                      (344, 16),  # Egg
                                      (345, 64),  # Compass
                                      (347, 64),  # Clock
                                      (368, 16),  # Ender Pearl
                                      (379, 64),  # Brewing Stand
                                      (380, 64),  # Cauldron
                                      (395, 64),  # Empty Map
                                      ):
                ItemTypes.findItem(itemid).stacksize = stacksize

            # Set stack size for items with durability
            for itemtype in ItemTypes.itemtypes.itervalues():
                if itemtype.maxdamage is not None:
                    itemtype.stacksize = 1

            # Save the corrected data to class attribute
            self._ItemTypes = ItemTypes

        # Should be a property, but for simplicity and performance it's set here
        self.type = self._ItemTypes.findItem(*self.key)

    @property
    def is_armor(self):
        return self.nbt['id'].value in self.armor_ids

    @property
    def key(self):
        return (self.nbt['id'].value,
                self.nbt['Damage'].value,)

    @property
    def name(self):
        '''Item type name and its custom name (via Anvil), if any
            Examples: `Diamond Sword`, `Combat Sword [Diamond Sword]`
        '''
        if 'tag' in self.nbt and 'display' in self.nbt['tag']:
            return "%s [%s]" % (self.nbt['tag']['display']['Name'].value,
                                self.type.name)
        else:
            return self.type.name

    @property
    def fullname(self):
        '''Item name with enchantment count.
            Example: `Combat Sword [Diamond Sword] {3 enchantments}`
        '''
        if 'tag' in self.nbt and 'ench' in self.nbt['tag']:
            enchants = len(self.nbt['tag']['ench'])
            ench_str = " {%d enchantment%s}" % (enchants,
                                                "s" if enchants > 1 else "")
        else:
            ench_str = ""

        return "%s%s" % (self.name, ench_str)

    @property
    def description(self):
        '''Item full name with item count.
            Examples: `42 Coal`, ` 1 Super Bow [Bow] {3 enchantments}`
        '''
        return "%2d %s" % (self.nbt["Count"].value, self.fullname)

    def __str__(self):
        '''Item count and name. Example: ` 1 Super Bow [Bow]`'''
        return "%2d %s" % (self.nbt["Count"].value, self.name)


def get_chunks(world, x=None, z=None, radius=250):
    from pymclevel import box

    if x is None and z is None:
        return world.chunkCount, world.allChunks

    if x is None:
        ox = world.bounds.minx
        sx = world.bounds.maxx - ox
    else:
        ox = x - radius
        sx = 2 * radius

    if z is None:
        oz = world.bounds.minz
        sz = world.bounds.maxz - oz
    else:
        oz = z - radius
        sz = 2 * radius

    bounds = box.BoundingBox((ox, 0, oz), (sx, world.Height, sz))

    return bounds.chunkCount, bounds.chunkPositions


def iter_chunks(world, x=None, z=None, radius=250, progress=True):

    chunk_max, chunk_range = get_chunks(world, x, z, radius)

    if chunk_max <= 0:
        log.warn("No chunks found in range %d of (%d, %d)",
                 radius, x, z)
        return

    if progress:
        pbar = progressbar.ProgressBar(widgets=[' ', progressbar.Percentage(),
                                                ' Chunk ',
                                                     progressbar.SimpleProgress(),
                                                ' ', progressbar.Bar('.'),
                                                ' ', progressbar.ETA(), ' '],
                                       maxval=chunk_max).start()
    start = time.clock()
    chunk_count = 0

    for cx, cz in chunk_range:
        if not world.containsChunk(cx, cz):
            continue

        chunk = world.getChunk(cx, cz)
        chunk_count += 1

        yield chunk

        if progress:
            pbar.update(pbar.currval+1)

    if progress:
        pbar.finish()

    log.info("Data from %d chunks%s extracted in %.2f seconds",
             chunk_count,
             (" (out of %d requested)" %  chunk_max)
                if chunk_max > chunk_count else "",
             time.clock()-start)


class MCError(Exception):
    pass
