#ifndef DDS_H
#define DDS_H

#include <stdint.h>

// DDS flags
#define DDS_HEADER_FLAGS_TEXTURE  0x00001007
#define DDS_HEADER_FLAGS_MIPMAP   0x00020000
#define DDS_FOURCC                0x00000004
#define DDS_RGBA                  0x00000041
#define DDS_SURFACE_FLAGS_TEXTURE 0x00001000
#define DDS_SURFACE_FLAGS_MIPMAP  0x00400008

// DDS magic
static const uint8_t DDS_MAGIC[4] = {'D', 'D', 'S', ' '};

#pragma pack(push, 1)
typedef struct {
    uint32_t dwSize;
    uint32_t dwFlags;
    uint8_t  dwFourCC[4];
    uint32_t dwRGBBitCount;
    uint32_t dwRBitMask;
    uint32_t dwGBitMask;
    uint32_t dwBBitMask;
    uint32_t dwABitMask;
} DDS_PIXELFORMAT;

typedef struct {
    uint32_t        dwSize;
    uint32_t        dwFlags;
    uint32_t        dwHeight;
    uint32_t        dwWidth;
    uint32_t        dwPitchOrLinearSize;
    uint32_t        dwDepth;
    uint32_t        dwMipMapCount;
    uint32_t        dwReserved1[11];
    DDS_PIXELFORMAT ddspf;
    uint32_t        dwCaps;
    uint32_t        dwCaps2;
    uint32_t        dwCaps3;
    uint32_t        dwCaps4;
    uint32_t        dwReserved2;
} DDS_HEADER;
#pragma pack(pop)

#endif // DDS_H
