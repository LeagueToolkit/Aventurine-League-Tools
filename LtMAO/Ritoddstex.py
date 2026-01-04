from . import lepath, pyRitoFile
import struct, math

def dds2tex(dds_path, tex_path=None):
    # prepare path
    if tex_path == None:
        tex_path = lepath.ext(dds_path, '.dds', '.tex')
    # read dds header
    with pyRitoFile.stream.BytesStream.reader(dds_path) as bs:
        signature, = bs.read_u32()
        if signature != 0x20534444:
            raise Exception(
                f'Ritoddstex: Error: dds2tex: {dds_path}: Wrong signature DDS file: {signature}')
        uints = bs.read_u32(31)
        dds_header = {
            'dwSize': uints[0],
            'dwFlags': uints[1],
            'dwHeight': uints[2],
            'dwWidth': uints[3],
            'dwPitchOrLinearSize': uints[4],
            'dwDepth': uints[5],
            'dwMipMapCount': uints[6],
            'dwReserved1': uints[7:7+11],
            'ddspf':  {
                'dwSize': uints[18],
                'dwFlags': uints[19],
                'dwFourCC': uints[20],
                'dwRGBBitCount': uints[21],
                'dwRBitMask': uints[22],
                'dwGBitMask': uints[23],
                'dwBBitMask': uints[24],
                'dwABitMask': uints[25],
            },
            'dwCaps': uints[26],
            'dwCaps2': uints[27],
            'dwCaps3': uints[28],
            'dwCaps4': uints[29],
            'dwReserved2': uints[30],
        }
        dds_pixel_format = dds_header['ddspf']
        dds_data = bs.read(-1)
    # for rgba convert
    custom_rgba_format = False
    rgba_indices = [-1, -1, -1, -1]
    mask_to_index = {
        0x000000ff: 0,
        0x0000ff00: 1,
        0x00ff0000: 2,
        0xff000000: 3
    }
    #  prepare tex header
    tex = pyRitoFile.tex.TEX()
    tex.width = dds_header['dwWidth']
    tex.height = dds_header['dwHeight']
    if dds_pixel_format['dwFourCC'] == int('DXT1'.encode('ascii')[::-1].hex(), 16):
        tex.format = pyRitoFile.tex.TEXFormat.DXT1
    elif dds_pixel_format['dwFourCC'] == int('DXT5'.encode('ascii')[::-1].hex(), 16):
        tex.format = pyRitoFile.tex.TEXFormat.DXT5
    elif (dds_pixel_format['dwFlags'] & 0x00000041) == 0x00000041:
        tex.format = pyRitoFile.tex.TEXFormat.BGRA8
        if dds_pixel_format['dwRGBBitCount'] != 32:
            raise Exception(f'Ritoddstex: Error: dds2tex: {dds_path}: dwRGBBitCount is expected 32, not {dds_pixel_format["dwRGBBitCount"]}.')
        if dds_pixel_format['dwBBitMask'] != 0x000000ff or dds_pixel_format['dwGBitMask'] != 0x0000ff00  or dds_pixel_format['dwRBitMask'] != 0x00ff0000 or dds_pixel_format['dwABitMask'] != 0xff000000:
            custom_rgba_format = True
            rgba_indices[0] = mask_to_index[dds_pixel_format['dwRBitMask']] 
            rgba_indices[1] = mask_to_index[dds_pixel_format['dwGBitMask']] 
            rgba_indices[2] = mask_to_index[dds_pixel_format['dwBBitMask']] 
            rgba_indices[3] = mask_to_index[dds_pixel_format['dwABitMask']] 
            for index in rgba_indices:
                if index == -1:
                    raise Exception(f'Ritoddstex: Error: dds2tex: {dds_path}: bitmask data invalid. Can not convert to BGRA output format.')
    else:
        raise Exception(f'Ritoddstex: Error: dds2tex: {dds_path}: Unsupported DDS format: {dds_pixel_format["dwFourCC"]}')
    # mipmaps
    if dds_header['dwMipMapCount'] > 1:
        expected_dwMipMapCount = math.floor(math.log2(max(dds_header["dwWidth"], dds_header["dwHeight"]))) + 1
        if dds_header['dwMipMapCount'] != expected_dwMipMapCount:
            raise Exception(f'Ritoddstex: Error: dds2tex: {dds_path}: Wrong DDS mipmap count: {dds_header["dwMipMapCount"]}, expected: {expected_dwMipMapCount}')
        tex.mipmaps = True
    # rgba convert
    if custom_rgba_format:
        new_data = None
        r_index, g_index, b_index, a_index = rgba_indices
        for i in range(0, len(dds_data), 4):
            current_pixel_data = 0
            current_pixel_data |= dds_data[i + b_index] << 0
            current_pixel_data |= dds_data[i + g_index] << 8
            current_pixel_data |= dds_data[i + r_index] << 16
            current_pixel_data |= dds_data[i + a_index] << 24
            new_data += struct.pack('I', current_pixel_data)
        dds_data = new_data
    # prepare tex data
    if tex.mipmaps:
        # if mipmaps and supported format
        if tex.format == pyRitoFile.tex.TEXFormat.DXT1:
            block_size = 4
            bytes_per_block = 8
        elif tex.format == pyRitoFile.tex.TEXFormat.DXT5:
            block_size = 4
            bytes_per_block = 16
        else:
            block_size = 1
            bytes_per_block = 4
        mipmap_count = dds_header['dwMipMapCount']
        current_offset = 0
        tex.data = []
        for i in range(mipmap_count):
            current_width = max(tex.width >> i, 1)
            current_height = max(tex.height >> i, 1)
            block_width = (current_width +
                           block_size - 1) // block_size
            block_height = (current_height +
                            block_size - 1) // block_size
            current_size = bytes_per_block * block_width * block_height
            data = dds_data[current_offset:current_offset+current_size]
            tex.data.append(data)
            current_offset += current_size
        # mipmap in dds file is reversed to tex file
        tex.data.reverse()
    else:
        tex.data = [dds_data]
        
    # write tex file
    tex.write(tex_path)


def tex_to_dds_bytes(tex_path):
    # Reads a .tex file and returns DDS bytes (file content equivalent) in memory
    tex = pyRitoFile.tex.TEX().read(tex_path)
    
    # Header Setup (Copied from tex2dds logic)
    dwHeight = tex.height
    dwWidth = tex.width
    dwMipMapCount = 0
    dwFlags = 0x00001007
    dwCaps = 0x00001000
    
    ddspf = {
        'dwSize': 32,
        'dwFlags': 0,
        'dwFourCC': 0,
        'dwRGBBitCount': 0,
        'dwRBitMask': 0,
        'dwGBitMask': 0,
        'dwBBitMask': 0,
        'dwABitMask': 0,
    }
    
    if tex.format == pyRitoFile.tex.TEXFormat.DXT1:
        ddspf['dwFourCC'] = 0x31545844 # DXT1
        ddspf['dwFlags'] = 0x00000004
    elif tex.format == pyRitoFile.tex.TEXFormat.DXT5:
        ddspf['dwFourCC'] = 0x35545844 # DXT5
        ddspf['dwFlags'] = 0x00000004
    elif tex.format == pyRitoFile.tex.TEXFormat.BGRA8:
        ddspf['dwFlags'] = 0x00000041
        ddspf['dwRGBBitCount'] = 32
        ddspf['dwBBitMask'] = 0x000000ff
        ddspf['dwGBitMask'] = 0x0000ff00
        ddspf['dwRBitMask'] = 0x00ff0000
        ddspf['dwABitMask'] = 0xff000000
    else:
        raise Exception(f'Unsupported TEX format: {tex.format}')
        
    if tex.mipmaps:
        dwFlags |= 0x00020000
        dwCaps |= 0x00400008
        dwMipMapCount = len(tex.data)
        
    # Write to buffer
    import io
    with io.BytesIO() as bio:
        # MAGIC
        bio.write(b'DDS ')
        
        # HEADER (124 bytes)
        # We usage struct.pack for simplicity
        # I = u32
        bio.write(struct.pack('<I', 124)) # dwSize
        bio.write(struct.pack('<I', dwFlags))
        bio.write(struct.pack('<I', dwHeight))
        bio.write(struct.pack('<I', dwWidth))
        bio.write(struct.pack('<I', 0)) # Pitch
        bio.write(struct.pack('<I', 0)) # Depth
        bio.write(struct.pack('<I', dwMipMapCount))
        bio.write(b'\x00' * 44) # reserved1
        
        # PIXEL FORMAT (32 bytes)
        bio.write(struct.pack('<I', 32)) # size
        bio.write(struct.pack('<I', ddspf['dwFlags']))
        bio.write(struct.pack('<I', ddspf['dwFourCC']))
        bio.write(struct.pack('<I', ddspf['dwRGBBitCount']))
        bio.write(struct.pack('<I', ddspf['dwRBitMask']))
        bio.write(struct.pack('<I', ddspf['dwGBitMask']))
        bio.write(struct.pack('<I', ddspf['dwBBitMask']))
        bio.write(struct.pack('<I', ddspf['dwABitMask']))
        
        # CAPS (16 bytes)
        bio.write(struct.pack('<I', dwCaps))
        bio.write(struct.pack('<I', 0)) # Caps2
        bio.write(struct.pack('<I', 0))
        bio.write(struct.pack('<I', 0))
        
        # Reserved2 (4 bytes)
        bio.write(struct.pack('<I', 0))
        
        # DATA
        if tex.mipmaps:
            for block_data in reversed(tex.data):
                bio.write(block_data)
        else:
            bio.write(tex.data[0])
            
        return bio.getvalue()

def tex2dds(tex_path, dds_path=None):
    # Wraps the byte logic to write file
    if dds_path == None:
        dds_path = tex_path.split('.tex')[0] + '.dds'
    data = tex_to_dds_bytes(tex_path)
    with open(dds_path, 'wb') as f:
        f.write(data)

# --- Pure Python DXT Decompression ---

def decompress_dxt1_block(block_data):
    # Returns 16 RGBA pixels (flattened tuples/list)
    if len(block_data) < 8: return [(0,0,0,0)]*16
    
    c0 = struct.unpack_from('<H', block_data, 0)[0]
    c1 = struct.unpack_from('<H', block_data, 2)[0]
    bits = struct.unpack_from('<I', block_data, 4)[0]
    
    # 565 to 888
    r0, g0, b0 = ((c0 >> 11) & 0x1F) << 3, ((c0 >> 5) & 0x3F) << 2, (c0 & 0x1F) << 3
    r1, g1, b1 = ((c1 >> 11) & 0x1F) << 3, ((c1 >> 5) & 0x3F) << 2, (c1 & 0x1F) << 3
    
    # Simple upsample
    r0 = r0 | (r0 >> 5); g0 = g0 | (g0 >> 6); b0 = b0 | (b0 >> 5)
    r1 = r1 | (r1 >> 5); g1 = g1 | (g1 >> 6); b1 = b1 | (b1 >> 5)
    
    colors = []
    colors.append((r0, g0, b0, 255))
    colors.append((r1, g1, b1, 255))
    
    if c0 > c1:
        colors.append(((2*r0+r1)//3, (2*g0+g1)//3, (2*b0+b1)//3, 255))
        colors.append(((r0+2*r1)//3, (g0+2*g1)//3, (b0+2*b1)//3, 255))
    else:
        colors.append(((r0+r1)//2, (g0+g1)//2, (b0+b1)//2, 255))
        colors.append((0, 0, 0, 0))
        
    pixels = []
    for y in range(4):
        for x in range(4):
            idx = (y * 4) + x
            code = (bits >> (idx * 2)) & 3
            pixels.append(colors[code])
    return pixels

def decompress_dxt5_block(block_data):
    if len(block_data) < 16: return [(0,0,0,0)]*16
    
    # Alpha
    a0 = block_data[0]
    a1 = block_data[1]
    alpha_bits_int = int.from_bytes(block_data[2:8], byteorder='little')
    
    alphas = [a0, a1]
    if a0 > a1:
        for i in range(1, 7): alphas.append(((7-i)*a0 + i*a1)//7)
    else:
        for i in range(1, 5): alphas.append(((5-i)*a0 + i*a1)//5)
        alphas.append(0)
        alphas.append(255)
        
    # Colors
    c0 = struct.unpack_from('<H', block_data, 8)[0]
    c1 = struct.unpack_from('<H', block_data, 10)[0]
    c_bits = struct.unpack_from('<I', block_data, 12)[0]
    
    r0, g0, b0 = ((c0 >> 11) & 0x1F) << 3, ((c0 >> 5) & 0x3F) << 2, (c0 & 0x1F) << 3
    r1, g1, b1 = ((c1 >> 11) & 0x1F) << 3, ((c1 >> 5) & 0x3F) << 2, (c1 & 0x1F) << 3
    
    r0 = r0 | (r0 >> 5); g0 = g0 | (g0 >> 6); b0 = b0 | (b0 >> 5)
    r1 = r1 | (r1 >> 5); g1 = g1 | (g1 >> 6); b1 = b1 | (b1 >> 5)
    
    colors = []
    colors.append((r0, g0, b0))
    colors.append((r1, g1, b1))
    colors.append(((2*r0+r1)//3, (2*g0+g1)//3, (2*b0+b1)//3))
    colors.append(((r0+2*r1)//3, (g0+2*g1)//3, (b0+2*b1)//3))
    
    pixels = []
    for y in range(4):
        for x in range(4):
            idx = y*4 + x
            a_idx = (alpha_bits_int >> (3*idx)) & 7
            alpha = alphas[a_idx]
            
            c_idx = (c_bits >> (2*idx)) & 3
            rgb = colors[c_idx]
            pixels.append((rgb[0], rgb[1], rgb[2], alpha))
            
    return pixels

def decompress_dds_bytes(dds_bytes):
    # Returns (width, height, list_of_floats_0_to_1)
    if dds_bytes[0:4] != b'DDS ': return 0,0,[]
    
    height = struct.unpack_from('<I', dds_bytes, 12)[0]
    width = struct.unpack_from('<I', dds_bytes, 16)[0]
    pf_flags = struct.unpack_from('<I', dds_bytes, 80)[0]
    fourcc = dds_bytes[84:88]
    
    data_offset = 128
    fmt = 'UNKNOWN'
    if fourcc == b'DXT1': fmt = 'DXT1'
    elif fourcc == b'DXT5': fmt = 'DXT5'
    elif pf_flags & 0x40: fmt = 'BGRA8'
    elif fourcc == b'DX10':
         dxgi = struct.unpack_from('<I', dds_bytes, 128)[0]
         data_offset += 20
         if dxgi == 71: fmt = 'DXT1'
         if dxgi == 77: fmt = 'DXT5'
    
    if fmt == 'UNKNOWN': return width, height, []
    
    pixel_data = dds_bytes[data_offset:]
    
    # We need a flat float array for Blender: R, G, B, A, R, G, B, A ... (0.0 - 1.0)
    # Pre-allocate list is faster than append in loop
    total_pixels = width * height
    # Safety clamp in case of corrupt header
    if total_pixels > 100000000: return 0,0,[] 

    output_floats = [0.0] * (total_pixels * 4)
    
    if fmt == 'BGRA8':
        # Uncompressed BGRA
        # Note: We must FLIP Y because DDS is Top-Down, Blender is Bottom-Up
        count = min(len(pixel_data)//4, total_pixels)
        # We need to process row by row to flip
        for y in range(height):
            src_y = y # Top-Down
            dst_y = height - 1 - y # Bottom-Up
            
            src_row_start = src_y * width * 4
            dst_row_start = dst_y * width * 4
            
            for x in range(width):
                src_i = src_row_start + x*4
                dst_i = dst_row_start + x*4
                
                if src_i + 4 > len(pixel_data): break
                
                b, g, r, a = pixel_data[src_i], pixel_data[src_i+1], pixel_data[src_i+2], pixel_data[src_i+3]
                
                output_floats[dst_i] = r / 255.0
                output_floats[dst_i+1] = g / 255.0
                output_floats[dst_i+2] = b / 255.0
                output_floats[dst_i+3] = a / 255.0
                
        return width, height, output_floats
        
    block_size = 8 if fmt == 'DXT1' else 16
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            if idx + block_size > len(pixel_data): break
            block = pixel_data[idx:idx+block_size]
            idx += block_size
            
            p_block = decompress_dxt1_block(block) if fmt == 'DXT1' else decompress_dxt5_block(block)
            
            # Scatter to output
            base_x, base_y = bx*4, by*4
            for py in range(4):
                y = base_y + py
                if y >= height: continue
                
                # FLIP Y for Blender (OpenGL Convention)
                # DDS is Top-Down, Blender is Bottom-Up
                dest_y = height - 1 - y
                row_offset = dest_y * width
                
                for px in range(4):
                    x = base_x + px
                    if x >= width: continue
                    
                    c = p_block[py*4 + px]
                    o = (row_offset + x) * 4
                    output_floats[o] = c[0] / 255.0
                    output_floats[o+1] = c[1] / 255.0
                    output_floats[o+2] = c[2] / 255.0
                    output_floats[o+3] = c[3] / 255.0
                    
    return width, height, output_floats

def decompress_dds_file(path):
    with open(path, 'rb') as f:
        data = f.read()
    return decompress_dds_bytes(data)

# --- Pure Python DXT Compression ---

def compress_dxt5_block(pixels, start_idx, width, output_bytes):
    # pixels: flatten list of floats (0.0-1.0)
    # Extract block
    rgba = []
    alphas = []
    
    # 4x4
    for py in range(4):
        # FLIP Y? No, we supply pixels from Blender (Bottom-Up usually), but we want to write DDS (Top-Down).
        # compress_dds_all expects pixels in Top-Down order?
        # Or we flip inside here?
        # Let's assume input pixels are ALREADY FLIPPED to Top-Down by the caller for simplicity.
        
        row_offset = py * width * 4 
        for px in range(4):
            idx = start_idx + row_offset + px*4
            try:
                r = int(pixels[idx] * 255)
                g = int(pixels[idx+1] * 255)
                b = int(pixels[idx+2] * 255)
                a = int(pixels[idx+3] * 255)
            except:
                r,g,b,a = 0,0,0,0
                
            rgba.append((r,g,b))
            alphas.append(a)

    # Compress Alpha
    min_a = min(alphas)
    max_a = max(alphas)
    
    alpha_block = bytearray(8)
    alpha_block[0] = max_a
    alpha_block[1] = min_a
    
    # 8-alpha or 6-alpha block? DXT5 usually uses 8-alpha if max > min (explicit)
    # Logic:
    pal = [max_a, min_a]
    if max_a > min_a:
        # 6 interpolated
        for i in range(1, 7): pal.append(((7-i)*max_a + i*min_a)//7)
    else:
        # 4 interpolated + 0 + 255
        for i in range(1, 5): pal.append(((5-i)*max_a + i*min_a)//5)
        pal.append(0)
        pal.append(255)
        
    # Indices
    indices_int = 0
    for i in range(16):
        a = alphas[i]
        best_diff = 999
        best_idx = 0
        for j, val in enumerate(pal):
            diff = abs(a - val)
            if diff < best_diff:
                best_diff = diff
                best_idx = j
        indices_int |= (best_idx << (3*i))
        
    # Write alpha indices (6 bytes)
    # struct pack Q is 8 bytes, we need 6.
    # Convert to bytes
    alpha_indices_bytes = indices_int.to_bytes(8, byteorder='little')
    alpha_block[2:8] = alpha_indices_bytes[0:6]
    
    output_bytes.extend(alpha_block)

    # Compress Color (Same as DXT1 but always 4 color mode?) DXT5 color is same as DXT1
    # Find endpoints
    min_lum, max_lum = 999999, -1
    c0, c1 = (0,0,0), (0,0,0)
    
    for i in range(16):
        p = rgba[i]
        lum = p[0]*2 + p[1]*4 + p[2]
        if lum < min_lum: min_lum = lum; c0 = p
        if lum > max_lum: max_lum = lum; c1 = p
        
    # 565
    i0 = ((c0[0]>>3)<<11) | ((c0[1]>>2)<<5) | (c0[2]>>3)
    i1 = ((c1[0]>>3)<<11) | ((c1[1]>>2)<<5) | (c1[2]>>3)
    
    # DXT5 doesn't usage 1-bit alpha in color block, usually sorted for 4 color interpolation
    if i0 < i1:
        i0, i1 = i1, i0 # Ensure max > min
        
    color_block = bytearray(8)
    struct.pack_into('<H', color_block, 0, i0)
    struct.pack_into('<H', color_block, 2, i1)
    
    # Palette
    r0, g0, b0 = ((i0 >> 11) & 0x1F) << 3, ((i0 >> 5) & 0x3F) << 2, (i0 & 0x1F) << 3
    r1, g1, b1 = ((i1 >> 11) & 0x1F) << 3, ((i1 >> 5) & 0x3F) << 2, (i1 & 0x1F) << 3
    
    # Expand
    r0 = r0 | (r0 >> 5); g0 = g0 | (g0 >> 6); b0 = b0 | (b0 >> 5)
    r1 = r1 | (r1 >> 5); g1 = g1 | (g1 >> 6); b1 = b1 | (b1 >> 5)
    
    c_pal = [
        (r0, g0, b0),
        (r1, g1, b1),
        ((2*r0+r1)//3, (2*g0+g1)//3, (2*b0+b1)//3),
        ((r0+2*r1)//3, (g0+2*g1)//3, (b0+2*b1)//3)
    ]
    
    c_indices = 0
    for i in range(16):
        p = rgba[i]
        best_dist = 999999
        best_idx = 0
        for j in range(4):
            c = c_pal[j]
            dist = (p[0]-c[0])**2 + (p[1]-c[1])**2 + (p[2]-c[2])**2
            if dist < best_dist:
                best_dist = dist
                best_idx = j
        c_indices |= (best_idx << (2*i))
        
    struct.pack_into('<I', color_block, 4, c_indices)
    output_bytes.extend(color_block)

def compress_dds_bytes(pixels, width, height):
    # Returns complete DDS file bytes (DXT5)
    # pixels must be list of floats 0.0-1.0 (R,G,B,A,...)
    # FLIP PIXELS HERE?
    # Blender is Bottom-Up. DDS needs Top-Down.
    # We flip row-by-row before access or during access?
    # Actually, we can just read rows in reverse order!
    
    output = bytearray()
    
    # Write Header
    import io
    with io.BytesIO() as bio:
        bio.write(b'DDS ')
        bio.write(struct.pack('<I', 124)) # dwSize
        bio.write(struct.pack('<I', 0x00001007 | 0x00000004)) # Flags + DDPF_FOURCC
        bio.write(struct.pack('<I', height))
        bio.write(struct.pack('<I', width))
        bio.write(struct.pack('<I', width * height)) # Linear Size estimate
        bio.write(struct.pack('<I', 0)) # Depth
        bio.write(struct.pack('<I', 0)) # MipMap (1)
        bio.write(b'\x00' * 44)
        
        # Pixel Format
        bio.write(struct.pack('<I', 32))
        bio.write(struct.pack('<I', 0x00000004)) # DDPF_FOURCC
        bio.write(b'DXT5')
        bio.write(struct.pack('<I', 0)) # RGBBitCount
        bio.write(struct.pack('<I', 0)); bio.write(struct.pack('<I', 0)); bio.write(struct.pack('<I', 0)); bio.write(struct.pack('<I', 0))
        
        # Caps
        bio.write(struct.pack('<I', 0x00001000))
        bio.write(b'\x00' * 16) # caps2..4, reserved2
        
        output.extend(bio.getvalue())

    # Compress Blocks
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    
    # Start iterating blocks
    for by in range(bh):
        for bx in range(bw):
            # Coordinates of block top-left
            # We want Top-Down result.
            # So block (0,0) is pixel (0,0) of SOURCE.
            # BUT SOURCE (from Blender) is Bottom-Up.
            # So Top-Left of DDS is Top-Left of Blender Image.
            # In Blender Pixel Array: index 0 is Bottom-Left.
            # Top-Left is at y = height-1.
            
            # Implementation:
            # We want to feed `compress_dxt5_block` the pixels for the block at (bx*4, by*4) in TOP-DOWN space.
            # This corresponds to (bx*4, (height - 1 - by*4)) approx in Bottom-Up space.
            # Actually, `start_idx` concept in `compress_dxt5_block` is tricky if rows are not contiguous.
            # Better to extract the 4x4 chunk here.
            
            block_pixels = []
            
            base_x = bx * 4
            base_y = by * 4 # Top-Down Y of block
            
            for py in range(4):
                # Row within block (Top-Down)
                y_top = base_y + py
                
                # Convert to Bottom-Up Y for Blender input
                y_bot = height - 1 - y_top
                
                if y_top >= height: 
                    block_pixels.extend([0.0]*4*4) # Pad
                    continue
                
                row_start = y_bot * width * 4
                
                for px in range(4):
                    x = base_x + px
                    if x >= width:
                         block_pixels.extend([0.0]*4)
                         continue
                         
                    idx = row_start + x*4
                    block_pixels.extend(pixels[idx:idx+4])
            
            # Now block_pixels contains 16 pixels (rgba floats) for this block
            # Pass to compressor
            # Modifying compress_dxt5_block to take prepared list is safer
            compress_dxt5_block_flat(block_pixels, output)
            
    return output

def compress_dxt5_block_flat(pixels, output_bytes):
    # pixels: list of 64 floats (16 * RGBA)
    rgba = []
    alphas = []
    for i in range(16):
        base = i*4
        if base+3 < len(pixels):
             r,g,b,a = int(pixels[base]*255), int(pixels[base+1]*255), int(pixels[base+2]*255), int(pixels[base+3]*255)
             rgba.append((r,g,b)); alphas.append(a)
        else:
             rgba.append((0,0,0)); alphas.append(0)

    # ... alpha logic ... (duplicated from above, I should use this helper)
    min_a, max_a = min(alphas), max(alphas)
    alpha_block = bytearray(8)
    alpha_block[0] = max_a; alpha_block[1] = min_a
    
    pal = [max_a, min_a]
    if max_a > min_a:
        for i in range(1, 7): pal.append(((7-i)*max_a + i*min_a)//7)
    else:
        for i in range(1, 5): pal.append(((5-i)*max_a + i*min_a)//5)
        pal.append(0); pal.append(255)
        
    indices_int = 0
    for i in range(16):
        a = alphas[i]
        best_diff = 999; best_idx = 0
        for j, val in enumerate(pal):
            diff = abs(a - val)
            if diff < best_diff: best_diff = diff; best_idx = j
        indices_int |= (best_idx << (3*i))
    alpha_block[2:8] = indices_int.to_bytes(8, 'little')[0:6]
    output_bytes.extend(alpha_block)
    
    # ... color logic ...
    min_lum, max_lum = 999999, -1
    c0, c1 = (0,0,0), (0,0,0)
    for i in range(16):
        p = rgba[i]
        lum = p[0]*2 + p[1]*4 + p[2]
        if lum < min_lum: min_lum = lum; c0 = p
        if lum > max_lum: max_lum = lum; c1 = p

    i0 = ((c0[0]>>3)<<11) | ((c0[1]>>2)<<5) | (c0[2]>>3)
    i1 = ((c1[0]>>3)<<11) | ((c1[1]>>2)<<5) | (c1[2]>>3)
    if i0 < i1: i0, i1 = i1, i0
    
    c_block = bytearray(8)
    struct.pack_into('<H', c_block, 0, i0)
    struct.pack_into('<H', c_block, 2, i1)
    
    r0, g0, b0 = ((i0>>11)&0x1F)<<3, ((i0>>5)&0x3F)<<2, (i0&0x1F)<<3
    r1, g1, b1 = ((i1>>11)&0x1F)<<3, ((i1>>5)&0x3F)<<2, (i1&0x1F)<<3
    
    r0=(r0|(r0>>5)); g0=(g0|(g0>>6)); b0=(b0|(b0>>5))
    r1=(r1|(r1>>5)); g1=(g1|(g1>>6)); b1=(b1|(b1>>5))
    
    c_pal = [(r0,g0,b0), (r1,g1,b1), ((2*r0+r1)//3,(2*g0+g1)//3,(2*b0+b1)//3), ((r0+2*r1)//3,(g0+2*g1)//3,(b0+2*b1)//3)]
    
    c_ind = 0
    for i in range(16):
        p = rgba[i]
        best_d = 999999; best_k = 0
        for j in range(4):
            c = c_pal[j]
            d = (p[0]-c[0])**2 + (p[1]-c[1])**2 + (p[2]-c[2])**2
            if d < best_d: best_d = d; best_k = j
        c_ind |= (best_k << (2*i))
    struct.pack_into('<I', c_block, 4, c_ind)
    output_bytes.extend(c_block)

def dds_bytes_to_tex_bytes(dds_bytes):
     # Converts DDS bytes to TEX bytes (Single Mip)
     if dds_bytes[:4] != b'DDS ': return b''
     
     height = struct.unpack_from('<I', dds_bytes, 12)[0]
     width = struct.unpack_from('<I', dds_bytes, 16)[0]
     fourcc = dds_bytes[84:88]
     pf_flags = struct.unpack_from('<I', dds_bytes, 80)[0]
     
     fmt = 0
     if fourcc == b'DXT1': fmt = 10
     elif fourcc == b'DXT5': fmt = 12
     elif fourcc == b'DX10':
         # Check DXGI
         dxgi = struct.unpack_from('<I', dds_bytes, 128)[0]
         if dxgi == 71: fmt = 10
         elif dxgi == 77: fmt = 12
     elif pf_flags & 0x40: fmt = 20 # BGRA
     
     if fmt == 0: return b'' # Unsupported
     
     data_offset = 128
     if fourcc == b'DX10': data_offset += 20
     
     data = dds_bytes[data_offset:]
     
     import io
     with io.BytesIO() as bio:
        bio.write(struct.pack('<I', 0x00584554))
        bio.write(struct.pack('<H', width))
        bio.write(struct.pack('<H', height))
        bio.write(struct.pack('<B', 1))
        bio.write(struct.pack('<B', fmt))
        bio.write(struct.pack('<B', 0))
        bio.write(struct.pack('<B', 0)) # Mipmaps False
        
        bio.write(data)
        return bio.getvalue()
