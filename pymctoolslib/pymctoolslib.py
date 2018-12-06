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

A wrapper to pymclevel/mceditlib with simpler API
"""

__all__ = [
    "basic_parser",
    "load_world",
    "get_player",
    "load_player_dimension",
    "ItemTypes",
    "ItemType",
    "Item",
    "get_chunks",
    "iter_chunks",
    "MCError",
]


import os.path as osp
import argparse
import logging
import time
import itertools
import collections
import json
import re

import progressbar


DATADIR = osp.join(osp.dirname(__file__), 'mceditlib', 'blocktypes')
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


class ItemTypes(object):
    items = collections.OrderedDict()
    _items_by_numid = collections.OrderedDict()
    _all_items = []
    _re_strid = re.compile(r'\W')  # == r'[^a-zA-Z0-9_]'

    def __init__(self):
        if not self.items:
            self._load_default_items()

    # TODO: Convert to collections.Mapping by adding these methods:
    # __getitem__, __iter__, __len__

    @classmethod
    def findItem(cls, key, meta=None, prefix='minecraft'):
        if not cls.items:
            cls._load_default_items()

        itemid = key
        if isinstance(key, (list, tuple)):
            itemid, meta = key  # meta taken from iterable, discard argument

        # Check for numeric ID and use the alternate dictionary
        if isinstance(itemid, (int, float)):
            return cls._items_by_numid[(int(itemid), meta)]

        # Add default prefix if needed, so 'dirt' => 'minecraft:dirt'
        if ':' not in itemid:
            itemid = ':'.join((prefix, itemid))

        return cls.items[(itemid, meta)]


    @classmethod
    def _load_old_json(cls, path, blocks=False):
        with open(path) as fp:
            data = json.load(fp, object_pairs_hook=collections.OrderedDict)

        for strid, item in data.items():
            # Structure integrity checks
            assert item['id'] > 0 and (blocks == (item['id'] <= 255)), \
                "ID / Block mismatch: block={0}, {1}".format(blocks, item)
            assert 'displayName' in item, \
                "Missing 'displayName' in item: {0}".format(item)
            assert blocks or 'texture' in item, \
                "Missing texture in non-block item: {0}".format(item)

            # Multi-data item (different meta / data values)
            if isinstance(item['displayName'], (list, tuple)):
                # More integrity-checks
                i = len(item['displayName'])
                assert i == item['maxdamage'] + 1, \
                    "displayNames([0}) / maxdamage mismatch: {1}".format(i, item)

                if 'texture' in item:
                    if isinstance(item['texture'], (list, tuple)):
                        assert len(item['texture']) == i, \
                            "textures([0}) / maxdamage mismatch: {1}".format(
                                len(item['texture']), item)
                        textures = item['texture']
                    else:
                        textures = i * (item['texture'],)
                else:
                    textures = i * (None,)

                items = zip(range(i), item['displayName'], textures)
                maxdamage = 0

            # Single-data
            else:
                assert not isinstance(item.get('texture', ''), (list, tuple)), \
                    "Multi-texture for single-data item: {0}".format(item)
                items = [(None, item['displayName'], item.get('texture'))]
                maxdamage = item['maxdamage']

            for meta, name, texture in items:
                obj = ItemType(
                    numid = item['id'],
                    strid = strid,
                    meta  = meta,
                    name  = name,
                    texture    = texture,
                    maxdamage  = maxdamage,
                    is_block   = blocks,
                    stacksize  = item['stacksize'],
                    obtainable = item['obtainable'],
                    _itemtypes = cls,
                )
                cls._add_item(obj)

    @classmethod
    def _load_json(cls, path):
        pass

    @classmethod
    def _load_default_items(cls):
        cls._add_item(ItemType(0, 'air', None, 'Air', False, True))
        cls._load_old_json(osp.join(DATADIR, 'tmp_itemblocks.json'), True)
        cls._load_old_json(osp.join(DATADIR, 'tmp_items.json'))

    @classmethod
    def _add_item(cls, item, prefix='minecraft', duplicate_prefix='removed'):
        strid = item.strid
        numid = item.numid

        # If StrID is missing, derive from name
        if not strid:
            strid = re.sub(cls._re_strid, '_', item.name).lower()

        # Append the default prefix if there is none
        if ':' not in strid:
            strid = ':'.join((prefix, strid))

        # Check for duplicate StrID and add duplicated prefix
        if (strid, item.meta) in cls.items:
            strid = ':'.join((duplicate_prefix, strid))
            item.removed = True

        # Check for missing numID and generate a (negative) dummy one
        if numid is None:
            numid = min(cls._items_by_numid)[0] - 1

        # Check for duplicate NumID
        if (numid, item.meta) in cls._items_by_numid:
            raise KeyError("Item NumID must be unique or None: {0}".format(item))

        # Add to collections
        cls._all_items.append(item)
        cls.items[(strid, item.meta)] = item
        cls._items_by_numid[(numid, item.meta)] = item


class ItemType(object):
    def __init__(self,
        numid,
        strid,
        meta,
        name,
        obtainable = True,
        is_block   = False,
        maxdamage  = 0,
        stacksize  = 64,
        texture    = None,
        removed    = False,
        _itemtypes = None
    ):
        # Mandatory
        self.numid = numid
        self.strid = strid
        self.meta  = meta
        self.name  = name

        # Optional
        self.obtainable = obtainable
        self.is_block   = is_block
        self.maxdamage  = maxdamage
        self.stacksize  = stacksize
        self.texture    = texture
        self.removed    = removed

        # Reference to container
        self._itemtypes = _itemtypes

        # Integrity checks --

        assert (not self.maxdamage) or (self.stacksize == 1), \
            "Items with durability must not stack: {0}".format(self)

        assert (self.numid is None) or (self.is_block == (self.numid < 256)), \
            "Numeric ID must be None or match Block/Item (less/greater than 256): {0}".format(self)

        assert self.is_block or self.obtainable, \
            "Non-Block Items must be obtainable: {0}".format(self)

        assert self.stacksize in (1, 16, 64), \
            "Stack size must be 1, 16 or 64: {0}".format(self)

    def __repr__(self):
        numid = '' if self.numid is None else '{0:3d}, '.format(self.numid)
        meta  = '' if self.meta  is None else '#{0}'.format(self.meta)
        return '<{0.__class__.__name__}({1}{0.strid}{2}, "{0.name}")>'.format(
            self, numid, meta)




class Item(NbtObject):
    _ItemTypes = None
    armor_ids = tuple(range(298, 318))
    armor_strids = tuple(
        'minecraft:{0}'.format('_'.join(_))
        for _ in
        itertools.product(('leather', 'chainmail', 'iron', 'diamond', 'golden'),
                          ('helmet', 'chestplate', 'leggings', 'boots'))
    ) + ('turtle_helmet',)

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
                                      (324, 64),  # Wooden Door, 1 before 1.8
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

        # Fix for items using non-numeric IDs
        if isinstance(self.type.id, basestring):
            self.type.name = self._type_name(self.type.id)

    @property
    def is_armor(self):
        return self.nbt['id'].value in self.armor_ids + self.armor_strids

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

    @staticmethod
    def _type_name(name):
        return name.split(':', 1)[-1].replace('_', ' ').title()




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
