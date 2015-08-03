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
    "Item",
    "item_type",
    "item_name",
    "get_itemkey",
    "get_chunks",
    "iter_chunks",
    "MCError",
]


import os
import os.path as osp
import argparse
import logging
from xdg.BaseDirectory import xdg_cache_home
import time

import progressbar


log = logging.getLogger(__name__)


def setuplogging(name, level):
    # Console output
    for logger, lvl in [(log, level),
                        # pymclevel is too verbose
                        (logging.getLogger("pymclevel"), logging.WARNING)]:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        sh.setLevel(lvl)
        logger.addHandler(sh)

    # File output
    logger = logging.getLogger()  # root logger, so it also applies to pymclevel
    logger.setLevel(logging.DEBUG)  # set to minimum so it doesn't discard file output
    try:
        logdir = osp.join(xdg_cache_home, 'minecraft')
        if not osp.exists(logdir):
            os.makedirs(logdir)
        fh = logging.FileHandler(osp.join(logdir, "%s.log" % name))
        fh.setFormatter(logging.Formatter('%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s'))
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)
    except IOError as e:  # Probably access denied
        logger.warn("%s\nLogging will not work.", e)


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


_ItemTypes = None
def item_type(item):
    '''Wrapper to pymclevel Items.findItem() with corrected data'''
    global _ItemTypes
    if _ItemTypes is None:
        from pymclevel.items import items as ItemTypes

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
        for itemtype in ItemTypes.itemtypes.itervalues():
            if itemtype.maxdamage is not None:
                itemtype.stacksize = 1
        _ItemTypes = ItemTypes

    return _ItemTypes.findItem(item["id"].value,
                               item["Damage"].value)


def item_name(item, itemtype=None):
    itemtype = itemtype or item_type(item)
    if 'tag' in item and 'display' in item['tag']:
        return "%s [%s]" % (item['tag']['display']['Name'].value,
                            itemtype.name)
    else:
        return itemtype.name


def get_itemkey(item):
    return (item["id"].value,
            item["Damage"].value)


class NbtObject(object):
    '''High-level wrapper for NBT Compound tags

        HUGE FLAW: `obj.attr = value` does not update nbt!!!

    '''

    def __init__(self, nbt, attrs=()):
        import pymclevel.nbt

        assert nbt.tagID == pymclevel.nbt.TAG_COMPOUND, \
            "Can not create NbtObject from a non-compound NBT tag"

        self._nbt = nbt

        for attr in attrs:
            setattr(self, attr.lower(), self._objectify(self._nbt[attr]))

    def _objectify(self, nbt):
        import pymclevel.nbt

        if nbt.tagID == pymclevel.nbt.TAG_COMPOUND:
            return NbtObject(nbt)

        if nbt.tagID == pymclevel.nbt.TAG_LIST:
            items = []
            for item in nbt:
                items.append(self._objectify(item))
            return items

        return nbt.value

    def __str__(self):
        return str(self._nbt)

    def __repr__(self):
        return "<%s>" % (self.__class__.__name__)

    def __getitem__(self, name):
        '''Allow accessing `obj.somename` as `obj["somename"]`'''
        return getattr(self, name)

    def __contains__(self, name):
        '''Allow case-insensitive usage of `attr in obj`'''
        return name in self._nbt or hasattr(self, name)

    def __getattr__(self, name):
        '''Fallback for non-objectified attributes from nbt data
            Allow accessing `obj._nbt["SomeName"].value` as `obj.somename`
        '''
        try:
            return self._objectify(self._nbt[name])
        except KeyError:
            lowername = name.lower()
            for attr in self._nbt:
                if attr.lower() == lowername:
                    return self._objectify(self._nbt[attr])
            else:
                raise AttributeError("'%s' object has no attribute '%s'"
                                     % (self.__class__.__name__,
                                        name))


class Item(NbtObject):
    _ItemTypes = None
    armor_ids = set(range(298, 318))

    def __init__(self, nbt):
        super(Item, self).__init__(nbt, ("id", "Damage", "Count"))
        self.nbt = nbt  # avoid usage

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

        # These should be properties,
        # but for simplicity and performance they're set here
        self.key = (self.id, self.damage)
        self.type = self._ItemTypes.findItem(*self.key)
        self.name = self._name()
        self.description = self._description()
        self.is_armor = self.id in self.armor_ids

    def _name(self):
        # nbt keys are used instead of object attributes to document
        # key name with proper case
        if 'tag' in self and 'display' in self['tag']:
            return "%s [%s]" % (self['tag']['display']['Name'],
                                self.type.name)
        else:
            return self.type.name

    def _description(self):
        if 'tag' in self and 'ench' in self['tag']:
            enchants = len(self['tag']['ench'])
            strench = " {%d enchantment%s}" % (enchants,
                                               "s" if enchants > 1 else "")
        else:
            strench = ""

        return "%2d %s%s" % (self.count, self.name, strench)

    def __str__(self):
        return "%2d %s" % (self.count, self.name)



def get_chunks(world, x=None, z=None, radius=250):
    from pymclevel import box

    if x is None and z is None:
        return world.chunkCount, world.allChunks

    ox = world.bounds.minx if x is None else x - radius
    oz = world.bounds.minz if z is None else z - radius

    bounds = box.BoundingBox((ox, 0, oz),
                             (2 * radius, world.Height,
                              2 * radius))

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
