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

All classes modeling game objects should inherit from either NbtObject,
NbtListObject, or one of their subclasses. Constructors should have `nbt` as
their only parameter and methods should expect similar high-level objects
"""

__all__ = [
    'ArmorSlot',
    "ItemTypes",
    "ItemType",
    "Item",
    "Player",
    "Entity",
    "XpOrb",
    "Mob",
    "Villager",
    "BookAndQuill",
    "World",
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
logging.getLogger('.'.join((__package__, 'pymclevel'))).setLevel(logging.WARNING)



class _EnumMeta(type):
    def __init__(self, *args, **kwargs):
        self._members = {k: v for k, v in vars(self).items() if not k.startswith('_')}
        super(_EnumMeta, self).__init__(*args, **kwargs)

    def __iter__(self):
        """Iterate over sorted member values"""
        return (_ for _ in sorted(self._members.values()))

    def __len__(self):
        """Number of members"""
        return len(self._members)

    def __contains__(self, value):
        """Check member value"""
        return value in self._members.values()


class Enum(object):
    """Placeholder for future actual Enum implementation"""
    __metaclass__ = _EnumMeta


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




class NbtBase(collections.Sized, collections.Iterable, collections.Container):
    """Base class for NbtObject and NbtListObject"""
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

    def __iter__(self):
        return iter(self._nbt)

    def __len__(self):
        return len(self._nbt)




class NbtListObject(NbtBase, collections.MutableSequence):
    """
    High-level wrapper for NBT List tags.
    Subclasses SHOULD override ElementClass to a specialized element class
    """
    ElementClass = NbtBase

    def __init__(self, nbt):
        super(NbtListObject, self).__init__(nbt)
        self._list = [self.ElementClass(_) for _ in nbt]

    def __getitem__(self, idx):
        """
        For slices, return an NbtListObject (or a subclass) instance.
        For integer indexes, return the (object) element
        """
        if isinstance(idx, int):
            return self._list[idx]
        elif isinstance(idx, slice):
            return self.__class__(self._nbt[idx])
        raise TypeError("%s indices must be integers or slices, not %s".
                        format(self.__class__.__name__, type(idx)))

    def __setitem__(self, idx, obj):
        if not isinstance(idx, (int, slice)):
            raise TypeError("%s indices must be integers or slices, not %s".
                            format(self.__class__.__name__, type(idx)))
        assert isinstance(obj, (self.ElementClass, self.__class__))
        self._list[idx] = obj
        if isinstance(obj, self.__class__):
            self._nbt[idx] = [_.get_nbt() for _ in obj]
        else:
            self._nbt[idx] = obj.get_nbt()

    def __delitem__(self, idx):
        if not isinstance(idx, (int, slice)):
            raise TypeError("%s indices must be integers or slices, not %s".
                            format(self.__class__.__name__, type(idx)))
        del self._list[idx]
        del self._nbt[idx]

    def __len__(self):
        length = len(self._list)
        assert length == len(self._nbt)
        return length

    def insert(self, idx, obj):
        assert isinstance(obj, self.ElementClass)
        self._list.insert(idx, obj)
        self._nbt.insert(idx, obj.get_nbt())

    def __contains__(self, element):
        """Check existence of element in list, NOT value in elements' .value"""
        # Optional, as collections.Sequence provides using __getitem__()
        # However, as __getitem__() is non-trivial by direct access to .value
        # it's safer to implement __contains__() independently
        return isinstance(element, self.ElementClass) and element in self._list

    def __iter__(self):
        """Iterate on the elements list, NOT on NBT data"""
        return iter(self._list)




class NbtObject(NbtBase, collections.Mapping):
    """High-level wrapper for NBT Compound tags"""

    def __init__(self, nbt=None):
        if nbt is None:
            import pymclevel.nbt
            nbt = pymclevel.nbt.TAG_Compound()
        super(NbtObject, self).__init__(nbt)

    def add_tag(self, name, value, TagClass, overwrite=False):
        """Add a new NBT tag, possibly overwriting an existing one"""
        if name in self and not overwrite:
            raise MCError("%r already has a tag named '%s'" % (self, name))
        self._nbt[name] = TagClass(value)

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
        Compound tags are converted to NbtObject, and List tags have each
        item objectified
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

    def __setitem__(self, tag, value):
        """
        Set the value attribute of an existing NBT tag
        o[tag] = value ==> o._nbt[tag].value = value
        Raise KeyError if tag is not found
        """
        # A true MutableMapping should also provide __delitem__()
        self._nbt[tag].value = value

    def __getitem__(self, tag):
        """Get the NBT tag value attribute: o[tag] ==> o._nbt[tag].value"""
        return self._nbt[tag].value

    def __contains__(self, k):
        """Check existence of tag in NBT: if k in o ==> if k in o._nbt"""
        # Optional, as collections.Mapping provides it using __getitem__()
        # However, as __getitem__() is non-trivial by direct access to .value
        # it's safer to implement __contains__() independently
        return k in self._nbt




class ItemTypes(object):
    """A singleton collection of ItemType objects"""
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
                )
                cls.add_item(obj, prefix=prefix)

    @classmethod
    def _load_json(cls, path):
        pass

    @classmethod
    def _load_default_items(cls):
        cls.add_item(ItemType(0, 'air', None, 'Air', False, True))
        cls._load_old_json(osp.join(DATADIR, 'tmp_itemblocks.json'), True)
        cls._load_old_json(osp.join(DATADIR, 'tmp_items.json'))

    @classmethod
    def add_item(cls, item, prefix='minecraft', duplicate_prefix='removed'):
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


    def to_item(self, count=1, slot=None):
        """Create an Item from an ItemType"""

        import pymclevel.nbt as nbt

        item = NbtObject(nbt.TAG_Compound())  # == NbtObject()

        if self.strid:
            item.add_tag('id', self.fullstrid, nbt.TAG_String)
        else:
            item.add_tag('id', self.numid, nbt.TAG_Short)

        item.add_tag('Damage', self.meta or 0, nbt.TAG_Short)
        item.add_tag('Count', count, nbt.TAG_Byte)  # -127 to 127, must not be 0

        item = Item(item.get_nbt())

        if slot:
            item.set_slot(slot)

        return item


    @classmethod
    def from_item(cls, item):
        """Create an ItemType from an Item. Useful for unknown types"""

        assert isinstance(item, BaseItem), \
            "Must be BaseItem instance: {0}".format(repr(item))

        if isinstance(item['id'], int):
            numid = item['id']
            strid = None
            name  = "Unknown Item {0}".format(numid)
            is_block = (numid <= 255)  # Per Minecraft convention
        else:
            numid = None
            strid = item['id']
            name  = strid.split(':', 1)[-1].replace('_', ' ').title()
            is_block = False  # No way to know for sure

        obj = cls(
            numid = numid,
            strid = strid,
            name  = name,
            meta  = item['Damage'],  # Can't tell if Data Value or Durability
            is_block  = is_block,
            maxdamage = 0,  # No way to know if it has durability or not
            stacksize = item['Count'],  # at least
        )
        ItemTypes.add_item(obj, "unknown")
        return obj


    def __repr__(self):
        numid = '' if self.numid is None else '{0:3d}, '.format(self.numid)
        meta  = '' if self.meta  is None else '/{0}'.format(self.meta)
        return '<{0.__class__.__name__}({1}{0.strid}{2}, "{0.name}")>'.format(
            self, numid, meta)




class BaseItem(NbtObject):
    """Base Item for Inventory and Entity Items"""

    def __init__(self, nbt):
        super(BaseItem, self).__init__(nbt)
        # "tag" is optional, pre and perhaps post-flattening
        # After Flattening, "Damage" goes to "tag" as pure durability
        self._create_nbt_attrs("id", "Damage", "Count", "tag")

        # Should be a property, but for simplicity and performance it's set here
        try:
            self.type = ItemTypes.findItem(*self.key)
        except KeyError:
            self.type = ItemType.from_item(self)
            log.warning("Unknown item type for %r, created %r", self, self.type)

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


    def specialize(self):
        pass


    def __str__(self):
        '''Item count and name. Example: ` 1 Super Bow [Bow]`'''
        return "%2d %s" % (self["Count"], self.name)

    def __repr__(self):
        return '<{0}({1}, {2})>'.format(self.__class__.__name__,
                                       self.key, self["Count"])




class Item(BaseItem):
    """Item in an inventory slot"""
    def __init__(self, nbt):
        super(Item, self).__init__(nbt)
        self._create_nbt_attrs("Slot")

    def set_slot(self, slot):
        from pymclevel import nbt

        if 'Slot' in self:
            self['Slot'] = slot
            return
        self.add_tag('Slot', slot, nbt.TAG_Byte)

    def __str__(self):
        s = super(Item, self).__str__()
        return s if 'Slot' not in self else "%s in slot %s" % (s, self['Slot'])




class Pos(collections.Sequence):
    def __init__(self, value):
        self._value = tuple(value)
        self.x, self.y, self.z = self._value
        self.cx, self.cz = self.chunkCoords()

    def __getitem__(self, index):
        return self._value[index]

    def __len__(self):
        return len(self._value)

    def __str__(self):
        strpos = "(%4d, %4d, %4d)" % self._value
        strreg = "(%3d, %3d)" % self.regionCoords()
        stroff = "(%2d, %2d)" % self.regionPos()
        strcnk = "(%4d, %4d)" % self.chunkCoords()
        return ("%s [Region %s, Chunk %s / %s]" %
                (strpos,
                 strreg,
                 stroff,
                 strcnk))

    def __repr__(self):
        return "<{0}({1:6.1f},{2:5.1f},{3:6.1f})>".format(
            self.__class__.__name__, *self._value)

    def chunkCoords(self):
        '''Return (cx, cz), the coordinates of position's chunk'''
        return (int(self.x) >> 4,
                int(self.z) >> 4)

    def chunkPos(self):
        '''Return (xc, zc, y), the position in its chunk'''
        return (int(self.x) & 0xf,
                int(self.z) & 0xf,
                int(self.y))

    def regionCoords(self):
        '''Return (rx, rz), the coordinates of position's region'''
        cx, cz = self.chunkCoords()
        return (cx >> 5,
                cz >> 5)

    def regionPos(self):
        '''Return (cxr, czr), the chunk's position in its region'''
        cx, cz = self.chunkCoords()
        return (cx & 0x1F,
                cz & 0x1F)




class BaseEntity(NbtObject):
    """Base class for all entities and the player"""
    def __init__(self, nbt):
        super(BaseEntity, self).__init__(nbt)
        self.pos = Pos((_.value for _ in self._nbt["Pos"]))

    def __str__(self):
        return "%s, %s" % (self.pos, self.__class__.__name__)




class Player(BaseEntity):
    """The Player, an id-less Entity"""
    def __init__(self, nbt):
        super(Player, self).__init__(nbt)
        self.inventory = PlayerInventory(self["Inventory"])  # why not get_nbt() ?

    @property
    def name(self):
        return self.get_nbt().name




class Entity(BaseEntity):
    """Base for all Entities with id"""
    def __init__(self, nbt):
        super(Entity, self).__init__(nbt)
        self._create_nbt_attrs("id")

    @property
    def name(self):
        return self['id'].split(':', 1)[-1].replace('_', ' ').title()

    def __str__(self):
        return "%s, %s '%s'" % (self.pos, self.__class__.__name__, self.name)




class XpOrb(Entity):
    pass




class Mob(Entity):
    pass




class Offer(NbtObject):
    def __init__(self, nbt):
        super(Offer, self).__init__(nbt)
        self.buy = []
        for tag in ("buy", "buyB"):
            if tag in self:
                self.buy.append(Item(self.get_nbt()[tag]))
        self.sell = Item(self.get_nbt()['sell'])
        self.name = "%s for %s" % (self.sell,
                                   ", ".join([str(_) for _ in self.buy]),
                                   )

    def __str__(self):
        return "[%2d/%2d] %s" % (self.uses,
                                 self.maxuses,
                                 self.name,
                                 )


class Villager(Mob):
    professions = {0: "Farmer",
                   1: "Librarian",
                   2: "Priest",
                   3: "Blacksmith",
                   4: "Butcher"}

    def __init__(self, nbt):
        super(Villager, self).__init__(nbt)
        self.profession = self.professions[self["Profession"]]
        self.offers = []
        if "Offers" in self:
            for offer in self["Offers"]["Recipes"]:
                self.offers.append(Offer(offer))

    def __str__(self):
        return ("%s: %s\n\t%s"
                % (super(Villager, self).__str__(),
                   self.profession,
                   "\n\t".join([str(_) for _ in self.offers]))
                ).strip()




class Inventory(NbtListObject):
    """Base class for Inventories"""
    ElementClass = Item

    def item(self, slot):
        """Return the Item in a Slot"""
        for item in self:
            if item['Slot'] == slot:
                return item
        else:
            raise MCError("Slot {0} is empty".format(slot))


    def find(self, ID, meta=None, label=None):
        """
        Return an item in Inventory that matches `ID` and `meta` (Damage)
        `ID` can be int, string, or (ID, meta) iterable. `meta` is ignored if None.
        """
        if not isinstance(ID, (int, basestring)):
            ID, meta = ID

        for item in self:
            if item['id'] == ID and (meta is None or item['Damage'] == meta):
                return item
        else:
            if label:
                msg = "No {0} found in inventory".format(label)
            else:
                msg = "Not found in inventory: {0}".format((ID, meta))
            raise MCError(msg)




class PlayerInventory(Inventory):
    """A Player's Inventory"""

    def __init__(self, nbt):
        super(PlayerInventory, self).__init__(nbt)

        if len(self) == 40:  # shortcut for full inventory
            self.free_slots = []
            self.free_armor = []
        else:
            slots = set(_["Slot"] for _ in self)
            self.free_slots = sorted(set(range(36))       - slots)
            self.free_armor = sorted(set(range(100, 104)) - slots)


    def stack_item(self, item, wear_armor=True):
        """
        Add an item clone to the inventory, trying to stack it with other items
        according to item's max stack size. Original item is never changed.
        Raise ValueError if item count is zero or greater than max stack size.
        Return a 3-tuple (count_remaining, [slots, ...], [counts, ...])
        """
        item = item.clone()

        size = item.type.stacksize
        count = item["Count"]  # item.count will not be changed until fully stacked

        # Assertions
        if count == 0:
            raise ValueError("Item count is zero: %s" % item)

        if count > size:
            raise ValueError(
                "Item count is greater than max stack size (%d/%d): %s" %
                (count, size, item))

        # Shortcut 1-stack items like tools, armor, weapons, etc
        if size == 1:
            try:
                return 0, [(self.add_item(item, wear_armor, clone=True), 1)]
            except MCError:
                return count, []

        # Loop each inventory slot, stacking the item onto similar items
        # that are not maximized until item count is 0
        slots  = []
        for stack in self:
            if (stack.key == item.key and
                stack.name == item.name and  # avoid stacking named items
                stack["Count"] < size):

                total = stack["Count"] + count
                diff = min(size, total) - stack["Count"]
                stack["Count"] += diff
                count          -= diff

                slots.append((stack["Slot"], diff))

                if count == 0:
                    break

        if count > 0:
            item["Count"] = count
            try:
                slots.append((self.add_item(item, wear_armor, clone=False),
                              count))
                count = 0
            except MCError:
                pass

        return count, slots


    def add_item(self, item, wear_armor=True, clone=True):
        """Add an item (or a clone) to a free inventory slot.
            Return the used slot space, if any, or raise mc.MCError
        """
        e = MCError("No suitable free inventory slot to add %s" %
                    item.description)

        # shortcut for no free slots
        if not self.free_slots and not self.free_armor:
            raise e

        # Get a free slot suitable for the item
        # For armor, try to wear in its corresponding slot
        slot = None
        if wear_armor and item.type.is_armor:
            slot = item.type.armorslot
            if slot in self.free_armor:
                self.free_armor.remove(slot)
            else:
                # Corresponding armor slot is not free
                slot = None

        if slot is None:
            if not self.free_slots:
                raise e

            slot = self.free_slots.pop(0)

        # Add the item
        if clone:
            item = item.clone()
        item.set_slot(slot)
        self.append(item)

        return slot




class BookAndQuill(Item):

    @property
    def pages(self):
        if 'tag' not in self:
            return []
            #self.get_nbt().append(self._blank_tag())
        return self['tag']['pages']
    @pages.setter
    def pages(self, value):
        if 'tag' not in self:
            self.get_nbt().append(self._blank_tag())
        self['tag']['pages'] = value

    def _blank_tag(self):
        """
        Books that were never written or opened contain no 'tag' key
        Return such key as the game does for a book that was just opened for the
        first time: with a "pages" list containing an empty string as 1st page
        """
        from pymclevel import nbt
        return nbt.TAG_Compound([nbt.TAG_List([nbt.TAG_String()], 'pages')], 'tag')




class World(NbtObject):
    """Minecraft World"""
    def __init__(self, name):
        """
        Load a Minecraft World
        `name` can be either a 'level.dat' file path, a directory path,
        or a directory basename from default Minecraft saves directory
        (on Linux, ~/.minecraft/saves)
        """

        # pymclevel.infiniteworld.MCInfdevOldLevel instance
        self.level = self._load(name)

        # World NBT is level root tag NBT
        super(World, self).__init__(self.level.root_tag['Data'])

        # If Blocks/Items IDs are Numeric (until 1.7) or String (1.8 onwards)
        # Check for known world's tags: 'Version' (1.9, 15w32a) or
        # 'logAdminCommands' (14w03a, the same snapshot ID type changed)
        self.is_numeric_id = (
            'Version' in self.level.root_tag['Data'] or
            'logAdminCommands' in self.level.root_tag['Data']['GameRules']
        )

        # Default player
        self.player = Player(self.level.root_tag['Data']['Player'])


    @property
    def name(self):
        return self['LevelName']
    @name.setter
    def name(self, value):
        self['LevelName'] = value


    @property
    def filename(self):
        return self.level.filename


    def get_player(self, name=None):
        """Get a named player (server) or the world default player"""
        if name is None or name == 'Player':
            return self.player

        from pymclevel import PlayerNotFound

        try:
            return Player(self.level.getPlayerTag(name))
        except PlayerNotFound:
            raise MCError("Player not found in world '%s': %s" %
                          (self.name, name))


    def get_dimension(self, dim=None):
        """Return a Dimension, by default the Player's current one"""
        if dim is None:
            dim = self.player['Dimension']

        if dim == 0:
            return self.level
        else:
            return self.level.getDimension(dim)


    def get_chunk_positions(self, dim=None, x=None, z=None, size=250):
        """
        Get chunk positions from a Dimension, by default the Player's current,
        optionally box-bounded `size`x`size` centered on X, Z. Some chunks in
        the box might not exist if not yet generated in-game.

        Return a 2-tuple (number of chunks found, chunks iterable)
        """
        from pymclevel import box

        world = self.get_dimension(dim)

        if x is None and z is None:
            return world.chunkCount, world.allChunks

        if x is None:
            ox = world.bounds.minx
            sx = world.bounds.maxx - ox
        else:
            ox = x - size
            sx = 2 * size

        if z is None:
            oz = world.bounds.minz
            sz = world.bounds.maxz - oz
        else:
            oz = z - size
            sz = 2 * size

        bounds = box.BoundingBox((ox, 0, oz), (sx, world.Height, sz))

        return bounds.chunkCount, bounds.chunkPositions


    def iter_chunks(self, dim=None, x=None, z=None, size=250, progress=True):
        """
        Return a chunk iterator, optionally with console progressbar
        Other parameters are same as get_chunks()
        """
        chunk_max, chunk_range = self.get_chunk_positions(dim, x, z, size)

        if chunk_max <= 0:
            log.warn("No chunks found in range %d of (%d, %d)",
                     size, x, z)
            return

        world = self.get_dimension(dim)

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


    def _load(self, name):
        import pymclevel
        try:
            if osp.isfile(name):
                return pymclevel.fromFile(name)
            elif osp.isdir(name):
                return pymclevel.fromFile(osp.join(name, 'level.dat'))
            else:
                return pymclevel.loadWorld(name)
        except IOError as e:
            raise MCError(e)
        except pymclevel.mclevel.LoadingError:
            raise MCError("Not a valid Minecraft world: '%s'" % name)




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

    parser.add_argument('--apply', '-A',
                        default=False, action="store_true",
                        help="Apply changes and save the world.")

    return parser




def load_world(name):
    """Return pymclevel level. Deprecated, use World(name).level instead"""
    return World(name).level




def get_player(world, playername=None):
    """Return Player NBT. Deprecated, use World().player.get_nbt() instead"""

    # New World class
    if isinstance(world, World):
        return world.get_player(playername).get_nbt()

    # Old pymclevel world Level
    import pymclevel
    if playername is None:
        playername = "Player"
    try:
        return world.getPlayerTag(playername)
    except pymclevel.PlayerNotFound:
        raise MCError("Player not found in world '%s': %s" %
                             (world.LevelName, playername))




def load_player_dimension(levelname, playername=None):
    """
    Return 2-tuple, the Dimension where the Player is, and the Player NBT
    Deprecated
    """
    world = World(levelname)
    player = world.get_player(playername)

    if not player["Dimension"] == 0:  # 0 = Overworld
        dim = world.level.getDimension(player["Dimension"])
        return dim, player.get_data()

    return world.level, player.get_nbt()




def get_chunks(world, x=None, z=None, radius=250):
    """Deprecated, use World().get_chunk_positions()"""
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
    """Deprecated, use World().iter_chunks()"""
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
