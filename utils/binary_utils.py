"""Utility classes for reading/writing League of Legends binary files"""
import struct
from math import sqrt


class Vector:
    """3D Vector"""
    __slots__ = ('x', 'y', 'z')
    
    def __init__(self, x, y, z=None):
        self.x = x
        self.y = y
        self.z = z
    
    def __iter__(self):
        yield self.x
        yield self.y
        if self.z is not None:
            yield self.z


class Quaternion:
    """Quaternion for rotations"""
    __slots__ = ('x', 'y', 'z', 'w')
    
    def __init__(self, x, y, z, w):
        self.x = x
        self.y = y
        self.z = z
        self.w = w
    
    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z
        yield self.w


class BinaryStream:
    """Binary file reader/writer"""
    
    def __init__(self, f):
        self.stream = f
    
    def seek(self, pos, mode=0):
        self.stream.seek(pos, mode)
    
    def tell(self):
        return self.stream.tell()
    
    def pad(self, length):
        self.stream.seek(length, 1)
    
    def read_byte(self):
        return self.stream.read(1)
    
    def read_bytes(self, length):
        return self.stream.read(length)
    
    def read_int16(self, count=1):
        if count > 1:
            return struct.unpack(f'{count}h', self.stream.read(2*count))
        return struct.unpack('h', self.stream.read(2))[0]
    
    def read_uint16(self, count=1):
        if count > 1:
            return struct.unpack(f'{count}H', self.stream.read(2*count))
        return struct.unpack('H', self.stream.read(2))[0]
    
    def read_int32(self, count=1):
        if count > 1:
            return struct.unpack(f'{count}i', self.stream.read(4*count))
        return struct.unpack('i', self.stream.read(4))[0]
    
    def read_uint32(self, count=1):
        if count > 1:
            return struct.unpack(f'{count}I', self.stream.read(4*count))
        return struct.unpack('I', self.stream.read(4))[0]
    
    def read_uint64(self, count=1):
        if count > 1:
            return struct.unpack(f'{count}Q', self.stream.read(8*count))
        return struct.unpack('Q', self.stream.read(8))[0]
    
    def read_float(self, count=1):
        if count > 1:
            return struct.unpack(f'{count}f', self.stream.read(4*count))
        return struct.unpack('f', self.stream.read(4))[0]
    
    def read_vec2(self, count=1):
        if count > 1:
            floats = struct.unpack(f'{count*2}f', self.stream.read(8*count))
            return [Vector(floats[i], floats[i+1]) for i in range(0, len(floats), 2)]
        return Vector(*struct.unpack('2f', self.stream.read(8)))
    
    def read_vec3(self, count=1):
        if count > 1:
            floats = struct.unpack(f'{count*3}f', self.stream.read(12*count))
            return [Vector(floats[i], floats[i+1], floats[i+2]) for i in range(0, len(floats), 3)]
        return Vector(*struct.unpack('3f', self.stream.read(12)))
    
    def read_quat(self, count=1):
        if count > 1:
            floats = struct.unpack(f'{count*4}f', self.stream.read(16*count))
            return [Quaternion(floats[i], floats[i+1], floats[i+2], floats[i+3]) 
                    for i in range(0, len(floats), 4)]
        return Quaternion(*struct.unpack('4f', self.stream.read(16)))
        
    def write_ascii(self, text):
        self.stream.write(text.encode('ascii'))
        
    def write_uint32(self, *vals):
        for val in vals:
            self.stream.write(struct.pack('<I', val))
            
    def write_int32(self, *vals):
        for val in vals:
            self.stream.write(struct.pack('<i', val))
            
    def write_int16(self, *vals):
        for val in vals:
            self.stream.write(struct.pack('<h', val))
            
    def write_uint16(self, *vals):
        for val in vals:
            self.stream.write(struct.pack('<H', val))
            
    def write_uint8(self, *vals):
        for val in vals:
            self.stream.write(struct.pack('<B', int(val)))
            
    def write_float(self, *vals):
        for val in vals:
            self.stream.write(struct.pack('<f', val))
            
    def write_vec2(self, *vecs):
        for vec in vecs:
            self.stream.write(struct.pack('<2f', vec[0], vec[1]))
            
    def write_vec3(self, *vecs):
        for vec in vecs:
            self.stream.write(struct.pack('<3f', vec[0], vec[1], vec[2]))
            
    def write_quat(self, *quats):
        for quat in quats:
            # League quats are usually (x, y, z, w)
            self.stream.write(struct.pack('<4f', quat[1], quat[2], quat[3], quat[0]))
            
    def write_padded_string(self, text, length):
        encoded = text.encode('ascii', errors='replace')
        if len(encoded) > length:
            encoded = encoded[:length]
        self.stream.write(encoded)
        self.stream.write(b'\x00' * (length - len(encoded)))
    
    def read_ascii(self, length):
        return self.stream.read(length).decode('ascii')
    
    def read_padded_ascii(self, length):
        return bytes(b for b in self.stream.read(length) if b != 0).decode('ascii')
    
    def read_char_until_zero(self):
        s = []
        while True:
            b = self.stream.read(1)
            if not b or b[0] == 0:
                break
            s.append(chr(b[0]))
        return "".join(s)


def flip_coordinates(value, is_rotation=False):
    """Flip X coordinate for Y-up to Z-up conversion"""
    if isinstance(value, Vector):
        if value.z is not None:
            return Vector(-value.x, value.y, value.z)
        return Vector(-value.x, value.y)
    elif isinstance(value, Quaternion) and is_rotation:
        return Quaternion(value.x, -value.y, -value.z, value.w)
    return value


class Hash:
    """Hash utilities for League of Legends"""
    
    @staticmethod
    def elf(s):
        """ELF hash used for bone names"""
        s = s.lower()
        h = 0
        for c in s:
            h = (h << 4) + ord(c)
            t = (h & 0xF0000000)
            if t != 0:
                h ^= (t >> 24)
            h &= ~t
        return h & 0xFFFFFFFF
