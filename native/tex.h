#ifndef TEX_H
#define TEX_H

#include <stdint.h>

// TEX format enum
#define TEX_FORMAT_ETC1   0x01
#define TEX_FORMAT_ETC2   0x03
#define TEX_FORMAT_DXT1   0x0A
#define TEX_FORMAT_DXT5   0x0C
#define TEX_FORMAT_BGRA8  0x14
#define TEX_FORMAT_RGBA16 0x15

// TEX magic bytes
static const uint8_t TEX_MAGIC[4] = {'T', 'E', 'X', '\0'};

#pragma pack(push, 1)
typedef struct {
    uint8_t magic[4];
    uint16_t image_width;
    uint16_t image_height;
    uint8_t unk1;
    uint8_t tex_format;
    uint8_t unk2;
    uint8_t has_mipmaps;
} TEX_HEADER;
#pragma pack(pop)

#endif // TEX_H
