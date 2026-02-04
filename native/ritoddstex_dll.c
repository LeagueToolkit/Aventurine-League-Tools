/*
 * Ritoddstex DLL - Fast TEX to DDS conversion for Blender addon
 * Exports functions callable from Python via ctypes
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "dds.h"
#include "tex.h"

// DLL export macro
#ifdef BUILD_DLL
    #define DLL_EXPORT __declspec(dllexport)
#else
    #define DLL_EXPORT __declspec(dllimport)
#endif

// Helper: max macro
#define MAX(a, b) ((a) > (b) ? (a) : (b))

// Helper: count leading zeros (replacement for __builtin_clz)
static inline uint32_t clz32(uint32_t x) {
    unsigned long index;
    if (_BitScanReverse(&index, x)) {
        return 31 - index;
    }
    return 32;
}

// Helper: calculate mipmap count
static inline uint32_t calc_mipmap_count(uint32_t width, uint32_t height) {
    uint32_t max_dim = MAX(width, height);
    return 32 - clz32(max_dim);
}

// Get bytes per block for format
static int get_bytes_per_block(uint8_t format) {
    switch (format) {
        case TEX_FORMAT_DXT1:  return 8;
        case TEX_FORMAT_DXT5:  return 16;
        case TEX_FORMAT_BGRA8: return 4;
        case TEX_FORMAT_RGBA16: return 8;
        default: return 0;
    }
}

// Get block size for format
static int get_block_size(uint8_t format) {
    switch (format) {
        case TEX_FORMAT_DXT1:
        case TEX_FORMAT_DXT5:
            return 4;
        case TEX_FORMAT_BGRA8:
        case TEX_FORMAT_RGBA16:
            return 1;
        default: return 1;
    }
}

/*
 * Convert TEX file to DDS bytes in memory
 *
 * Parameters:
 *   tex_path  - Path to the .tex file (UTF-8)
 *   out_data  - Pointer to receive allocated DDS data (caller must free with free_dds_bytes)
 *   out_size  - Pointer to receive size of DDS data
 *
 * Returns:
 *   0 on success, negative error code on failure
 *   -1: Failed to open file
 *   -2: Invalid TEX file
 *   -3: Unsupported format
 *   -4: Memory allocation failed
 */
DLL_EXPORT int tex_to_dds_bytes(const char* tex_path, uint8_t** out_data, uint32_t* out_size) {
    FILE* tex_file = fopen(tex_path, "rb");
    if (!tex_file) {
        return -1; // Failed to open
    }

    // Get file size
    fseek(tex_file, 0, SEEK_END);
    uint32_t file_size = (uint32_t)ftell(tex_file);
    rewind(tex_file);

    // Read and validate TEX header
    TEX_HEADER tex_header;
    if (file_size < sizeof(TEX_HEADER) ||
        fread(&tex_header, sizeof(TEX_HEADER), 1, tex_file) != 1 ||
        memcmp(tex_header.magic, TEX_MAGIC, 3) != 0) {
        fclose(tex_file);
        return -2; // Invalid TEX
    }

    // Setup DDS pixel format
    DDS_PIXELFORMAT ddspf = {0};
    ddspf.dwSize = sizeof(DDS_PIXELFORMAT);

    const char* fourcc = NULL;
    int need_dx10 = 0;

    switch (tex_header.tex_format) {
        case TEX_FORMAT_DXT1:
            fourcc = "DXT1";
            ddspf.dwFlags = DDS_FOURCC;
            break;
        case TEX_FORMAT_DXT5:
            fourcc = "DXT5";
            ddspf.dwFlags = DDS_FOURCC;
            break;
        case TEX_FORMAT_BGRA8:
            ddspf.dwFlags = DDS_RGBA;
            ddspf.dwRGBBitCount = 32;
            ddspf.dwBBitMask = 0x000000ff;
            ddspf.dwGBitMask = 0x0000ff00;
            ddspf.dwRBitMask = 0x00ff0000;
            ddspf.dwABitMask = 0xff000000;
            break;
        case TEX_FORMAT_RGBA16:
            // DX10 extended format - simplified handling
            fourcc = "DX10";
            ddspf.dwFlags = DDS_FOURCC;
            need_dx10 = 1;
            break;
        default:
            fclose(tex_file);
            return -3; // Unsupported format
    }

    if (fourcc) {
        memcpy(ddspf.dwFourCC, fourcc, 4);
    }

    // Setup DDS header
    DDS_HEADER dds_header = {0};
    dds_header.dwSize = sizeof(DDS_HEADER);
    dds_header.dwFlags = DDS_HEADER_FLAGS_TEXTURE;
    dds_header.dwHeight = tex_header.image_height;
    dds_header.dwWidth = tex_header.image_width;
    dds_header.ddspf = ddspf;
    dds_header.dwCaps = DDS_SURFACE_FLAGS_TEXTURE;

    uint32_t mipmap_count = 0;
    if (tex_header.has_mipmaps) {
        dds_header.dwFlags |= DDS_HEADER_FLAGS_MIPMAP;
        dds_header.dwCaps |= DDS_SURFACE_FLAGS_MIPMAP;
        mipmap_count = calc_mipmap_count(tex_header.image_width, tex_header.image_height);
        dds_header.dwMipMapCount = mipmap_count;
    }

    // Calculate output size
    uint32_t tex_data_size = file_size - sizeof(TEX_HEADER);
    uint32_t header_size = 4 + sizeof(DDS_HEADER); // "DDS " + header
    if (need_dx10) {
        header_size += 20; // DX10 extended header
    }
    uint32_t total_size = header_size + tex_data_size;

    // Allocate output buffer
    uint8_t* dds_data = (uint8_t*)malloc(total_size);
    if (!dds_data) {
        fclose(tex_file);
        return -4; // Alloc failed
    }

    // Write DDS magic
    uint8_t* ptr = dds_data;
    memcpy(ptr, DDS_MAGIC, 4);
    ptr += 4;

    // Write DDS header
    memcpy(ptr, &dds_header, sizeof(DDS_HEADER));
    ptr += sizeof(DDS_HEADER);

    // Write DX10 header if needed
    if (need_dx10) {
        uint8_t dx10_header[20] = {0};
        // dxgiFormat = DXGI_FORMAT_R16G16B16A16_SNORM (0x0d)
        dx10_header[0] = 0x0d;
        // resourceDimension = D3D10_RESOURCE_DIMENSION_TEXTURE2D (3)
        dx10_header[4] = 0x03;
        // arraySize = 1
        dx10_header[12] = 0x01;
        // miscFlags2 = DDS_ALPHA_MODE_STRAIGHT (1)
        dx10_header[16] = 0x01;
        memcpy(ptr, dx10_header, 20);
        ptr += 20;
    }

    // Read TEX data
    uint8_t* tex_data = (uint8_t*)malloc(tex_data_size);
    if (!tex_data) {
        free(dds_data);
        fclose(tex_file);
        return -4;
    }

    if (fread(tex_data, 1, tex_data_size, tex_file) != tex_data_size) {
        free(tex_data);
        free(dds_data);
        fclose(tex_file);
        return -2;
    }
    fclose(tex_file);

    // Handle mipmaps (TEX stores in reverse order compared to DDS)
    if (tex_header.has_mipmaps && mipmap_count > 0) {
        uint32_t block_size = get_block_size(tex_header.tex_format);
        uint32_t bytes_per_block = get_bytes_per_block(tex_header.tex_format);
        int32_t current_offset = tex_data_size;

        for (uint32_t i = 0; i < mipmap_count; i++) {
            uint32_t mip_width = MAX(tex_header.image_width >> i, 1);
            uint32_t mip_height = MAX(tex_header.image_height >> i, 1);
            uint32_t block_width = (mip_width + block_size - 1) / block_size;
            uint32_t block_height = (mip_height + block_size - 1) / block_size;
            uint32_t mip_size = bytes_per_block * block_width * block_height;

            current_offset -= mip_size;
            if (current_offset < 0) {
                break;
            }
            memcpy(ptr, tex_data + current_offset, mip_size);
            ptr += mip_size;
        }
    } else {
        // No mipmaps - straight copy
        memcpy(ptr, tex_data, tex_data_size);
    }

    free(tex_data);

    *out_data = dds_data;
    *out_size = total_size;
    return 0; // Success
}

/*
 * Free DDS bytes allocated by tex_to_dds_bytes
 */
DLL_EXPORT void free_dds_bytes(uint8_t* data) {
    if (data) {
        free(data);
    }
}

/*
 * Get version string
 */
DLL_EXPORT const char* get_version(void) {
    return "ritoddstex_dll 1.0";
}

// DLL entry point
BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpReserved) {
    (void)hinstDLL;
    (void)lpReserved;
    switch (fdwReason) {
        case DLL_PROCESS_ATTACH:
        case DLL_THREAD_ATTACH:
        case DLL_THREAD_DETACH:
        case DLL_PROCESS_DETACH:
            break;
    }
    return TRUE;
}
