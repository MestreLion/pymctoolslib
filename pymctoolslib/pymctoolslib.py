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
    'ArmorSlot',
    "ItemTypes",
    "ItemType",
    "Item",
    "Entity",
    "XpOrb",
    "basic_parser",
    "load_world",
    "get_player",
    "load_player_dimension",
    "get_chunks",
    "iter_chunks",
    "MCError",
]


import os.path as osp
import argparse
import logging
import time
import collections
import json
import re
import copy

import progressbar

# Do NOT import pymclevel here, as it takes a LONG time to import
# Lazily import inside functions and methods that need it


DATADIR = osp.join(osp.dirname(__file__), 'mceditlib', 'blocktypes')

log = logging.getLogger(__name__)




class Enum(object):
    """Placeholder for future actual Enum implementation"""
    pass


class NbtTag(Enum):
    END        =  0
    BYTE       =  1
    SHORT      =  2
    INT        =  3
    LONG       =  4
    FLOAT      =  5
    DOUBLE     =  6
    BYTE_ARRAY =  7
    STRING     =  8
    LIST       =  9
    COMPOUND   = 10
    INT_ARRAY  = 11
    LONG_ARRAY = 12


class ArmorSlot(Enum):
    HEAD  = 103
    CHEST = 102
    LEGS  = 101
    FEET  = 100
    OFFHAND = -106




class NbtObject(collections.Mapping):
    """High-level wrapper for NBT Compound tags"""

    def __init__(self, nbt):
        self._nbt = nbt

    def get_nbt(self):
        """
        Return the NBT data.
        Use should be avoided: instead, classes should provide methods to perform
        the needed actions on its own NBT data without exposing it to clients
        """
        return self._nbt

    def copy(self):
        """Get a copy of the NBT data"""
        return copy.deepcopy(self._nbt)

    def clone(self):
        """Return another object using a copy of the NBT data"""
        return self.__class__(self.copy())

    def _create_nbt_attrs(self, *tags):
        """Create attributes for the given NBT tags"""

        assert self._nbt.tagID == NbtTag.COMPOUND, \
            "Can not create attributes from a non-compound NBT tag"

        for tag in tags:
            try:
                value = self._objectify(self._nbt[tag])
            except KeyError:  # tag not in NBT
                value = None
            setattr(self, tag.lower(), value)

    def _objectify(self, nbt):
        if nbt.tagID == NbtTag.COMPOUND:
            return NbtObject(nbt)

        if nbt.tagID == NbtTag.LIST:
            return [self._objectify(_) for _ in nbt]

        return nbt.value

    def __str__(self):
        s = self.get('id') or "%d tags" % len(self)
        return "%s(%s)" % (self.__class__.__name__, s)

    def __repr__(self):
        return "<%s(%d tags)>" % (self.__class__.__name__, len(self))

    def __getattr__(self, attr):
        """
        Auto-objectifying fallback for non-objectified tags in NBT
        o.attr ==> o._nbt["attr"].value
        """
        try:
            return self._objectify(self._nbt[attr])
        except KeyError:
            lowername = attr.lower()
            for tag in self._nbt:
                if tag.lower() == lowername:
                    return self._objectify(self._nbt[tag])
            else:
                raise AttributeError("'%s' object has no attribute '%s'"
                                     % (self.__class__.__name__,
                                        attr))

    def __setitem__(self, k, v):
        """Set the NBT tag value attribute: o[k] = v ==> o._nbt[k].value = v"""
        # A true MutableMapping should also provide __delitem__()
        self._nbt[k].value = v

    def __getitem__(self, k):
        """Get the NBT tag value attribute: o[k] ==> o._nbt[k].value"""
        return self._nbt[k].value

    def __contains__(self, k):
        """Check existence of tag in NBT: if k in o ==> if k in o._nbt"""
        # Optional, as collections.Mapping provides it using __getitem__()
        # However, as __getitem__() is non-trivial by direct access to .value
        # it's safer to implement __contains__() independently
        return k in self._nbt

    def __iter__(self):
        return iter(self._nbt)

    def __len__(self):
        return len(self._nbt)




class ItemTypes(object):
    """A collection of ItemType objects"""
    items = collections.OrderedDict()
    armor = []

    _items_by_numid = collections.OrderedDict()
    _all_items = []
    _re_strid = re.compile(r'\W')  # == r'[^a-zA-Z0-9_]'

    _armor_slots =      {_[1]: ArmorSlot.HEAD - (_[0] % 4) for _ in enumerate(range(298, 318))}
    _armor_slots.update({_[1]: ArmorSlot.HEAD - (_[0] % 4) for _ in enumerate(('helmet', 'chestplate', 'leggings', 'boots'))})

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
            if (itemid, meta) not in cls._items_by_numid:
                meta = None
            return cls._items_by_numid[(int(itemid), meta)]

        # Add default prefix if needed, so 'dirt' => 'minecraft:dirt'
        if ':' not in itemid:
            itemid = ':'.join((prefix, itemid))

        if (itemid, meta) not in cls.items:
            meta = None

        return cls.items[(itemid, meta)]


    @classmethod
    def searchItems(cls, regex):
        if not cls.items:
            cls._load_default_items()
        return (cls.items[_] for _ in cls.items if re.search(regex, _[0]))


    @classmethod
    def _load_old_json(cls, path, blocks=False, prefix='minecraft'):
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
                    prefix     = prefix,
                    stacksize  = item['stacksize'],
                    obtainable = item['obtainable'],
                    _itemtypes = cls,
                )
                cls._add_item(obj, prefix=prefix)

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
        meta  = item.meta  # or 0

        # If StrID is missing, derive from name
        if not strid:
            strid = re.sub(cls._re_strid, '_', item.name).lower()

        # Append the default prefix if there is none
        if ':' not in strid:
            strid = ':'.join((prefix, strid))

        # Check for duplicate StrID and add duplicated prefix
        if (strid, meta) in cls.items:
            strid = ':'.join((duplicate_prefix, strid))
            item.removed = True

        # Check for missing numID and generate a (negative) dummy one
        if numid is None:
            numid = min(cls._items_by_numid)[0] - 1

        # Check for duplicate NumID
        if (numid, meta) in cls._items_by_numid:
            raise KeyError("Item NumID must be unique or None: {0}".format(item))

        # Armor handling
        item.armorslot = cls._armor_slots.get(numid,
                         cls._armor_slots.get(strid.split('_')[-1]))

        # Add to collections
        cls._all_items.append(item)
        cls.items[(strid, meta)] = item
        cls._items_by_numid[(numid, meta)] = item
        if item.armorslot:
            cls.armor.append(item)




class ItemType(object):
    """
    Item type data, including Block types
    Contains all item/block game data not tied to any NBT or World
    """
    def __init__(self,
        numid,
        strid,
        meta,
        name,
        obtainable = True,
        is_block   = False,
        maxdamage  = 0,
        stacksize  = 64,
        armorslot  = None,
        texture    = None,
        removed    = False,
        prefix     = 'minecraft',
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
        self.armorslot  = armorslot
        self.texture    = texture
        self.removed    = removed
        self.prefix     = prefix

        # Reference to container
        self._itemtypes = _itemtypes

        # Integrity checks --

        assert (self.maxdamage == 0) or (self.stacksize == 1), \
            "Items with durability must not stack: {0}".format(self)

        assert (self.numid is None) or (self.is_block == (self.numid < 256)), \
            "Numeric ID must be None or match Block/Item (less/greater than 256): {0}".format(self)

        assert self.is_block or self.obtainable, \
            "Non-Block Items must be obtainable: {0}".format(self)

        assert self.stacksize in (1, 16, 64), \
            "Stack size must be 1, 16 or 64: {0}".format(self)

        assert (self.armorslot is None) or (self.maxdamage > 0), \
            "Armor must have durability: {0}".format(self)


    @property
    def is_armor(self):
        return bool(self.armorslot)


    @property
    def fullstrid(self):
        return ':'.join((self.prefix, self.strid))


    def __repr__(self):
        numid = '' if self.numid is None else '{0:3d}, '.format(self.numid)
        meta  = '' if self.meta  is None else '#{0}'.format(self.meta)
        return '<{0.__class__.__name__}({1}{0.strid}{2}, "{0.name}")>'.format(
            self, numid, meta)




class Item(NbtObject):
    """Base Item for SlotItem and EntityItem"""

    def __init__(self, nbt):
        super(Item, self).__init__(nbt)
        # "tag" is optional, pre and perhaps post-flattening
        # After Flattening, "Damage" goes to "tag" as pure durability
        self._create_nbt_attrs("id", "Damage", "Count", "tag")

        # Should be a property, but for simplicity and performance it's set here
        self.type = ItemTypes.findItem(*self.key)


    @property
    def key(self):
        return (self['id'], self['Damage'])

    @property
    def name(self):
        '''Item type name and its custom name (via Anvil), if any
            Examples: `Diamond Sword`, `Combat Sword [Diamond Sword]`
        '''
        if 'tag' in self and 'display' in self['tag']:
            return "%s [%s]" % (self['tag']['display']['Name'], self.type.name)
        else:
            return self.type.name

    @property
    def fullname(self):
        '''Item name with enchantment count.
            Example: `Combat Sword [Diamond Sword] {3 enchantments}`
        '''
        if 'tag' in self and 'ench' in self['tag']:
            enchants = len(self['tag']['ench'])
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
        return "%2d %s" % (self["Count"], self.fullname)


    def __str__(self):
        '''Item count and name. Example: ` 1 Super Bow [Bow]`'''
        return "%2d %s" % (self["Count"], self.name)






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
