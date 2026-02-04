/*
 * LoL Native DLL - Fast TEX/BIN operations for Blender addon
 * Combines TEX→DDS conversion and BIN texture path extraction
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <string>
#include <vector>
#include <unordered_map>
#include <fstream>
#include <sstream>

// Include ritobin for BIN parsing
#include "../ritobin-master/ritobin_lib/src/ritobin/bin_types.hpp"
#include "../ritobin-master/ritobin_lib/src/ritobin/bin_io.hpp"

#ifdef BUILD_DLL
    #define DLL_EXPORT extern "C" __declspec(dllexport)
#else
    #define DLL_EXPORT extern "C" __declspec(dllimport)
#endif

// ============================================================================
// TEX to DDS Conversion (from ritoddstex)
// ============================================================================

#define TEX_FORMAT_DXT1   0x0A
#define TEX_FORMAT_DXT5   0x0C
#define TEX_FORMAT_BGRA8  0x14
#define TEX_FORMAT_RGBA16 0x15

#define DDS_HEADER_FLAGS_TEXTURE  0x00001007
#define DDS_HEADER_FLAGS_MIPMAP   0x00020000
#define DDS_FOURCC                0x00000004
#define DDS_RGBA                  0x00000041
#define DDS_SURFACE_FLAGS_TEXTURE 0x00001000
#define DDS_SURFACE_FLAGS_MIPMAP  0x00400008

#pragma pack(push, 1)
struct TEX_HEADER {
    uint8_t magic[4];
    uint16_t image_width;
    uint16_t image_height;
    uint8_t unk1;
    uint8_t tex_format;
    uint8_t unk2;
    uint8_t has_mipmaps;
};

struct DDS_PIXELFORMAT {
    uint32_t dwSize;
    uint32_t dwFlags;
    uint8_t  dwFourCC[4];
    uint32_t dwRGBBitCount;
    uint32_t dwRBitMask;
    uint32_t dwGBitMask;
    uint32_t dwBBitMask;
    uint32_t dwABitMask;
};

struct DDS_HEADER {
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
};
#pragma pack(pop)

static inline uint32_t calc_mipmap_count(uint32_t width, uint32_t height) {
    uint32_t max_dim = (width > height) ? width : height;
    uint32_t count = 0;
    while (max_dim > 0) { count++; max_dim >>= 1; }
    return count;
}

static int get_bytes_per_block(uint8_t format) {
    switch (format) {
        case TEX_FORMAT_DXT1:  return 8;
        case TEX_FORMAT_DXT5:  return 16;
        case TEX_FORMAT_BGRA8: return 4;
        case TEX_FORMAT_RGBA16: return 8;
        default: return 0;
    }
}

static int get_block_size(uint8_t format) {
    switch (format) {
        case TEX_FORMAT_DXT1:
        case TEX_FORMAT_DXT5:
            return 4;
        default:
            return 1;
    }
}

DLL_EXPORT int tex_to_dds_bytes(const char* tex_path, uint8_t** out_data, uint32_t* out_size) {
    FILE* tex_file = fopen(tex_path, "rb");
    if (!tex_file) return -1;

    fseek(tex_file, 0, SEEK_END);
    uint32_t file_size = (uint32_t)ftell(tex_file);
    rewind(tex_file);

    TEX_HEADER tex_header;
    if (file_size < sizeof(TEX_HEADER) ||
        fread(&tex_header, sizeof(TEX_HEADER), 1, tex_file) != 1 ||
        memcmp(tex_header.magic, "TEX", 3) != 0) {
        fclose(tex_file);
        return -2;
    }

    DDS_PIXELFORMAT ddspf = {};
    ddspf.dwSize = sizeof(DDS_PIXELFORMAT);
    const char* fourcc = nullptr;
    bool need_dx10 = false;

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
            fourcc = "DX10";
            ddspf.dwFlags = DDS_FOURCC;
            need_dx10 = true;
            break;
        default:
            fclose(tex_file);
            return -3;
    }

    if (fourcc) memcpy(ddspf.dwFourCC, fourcc, 4);

    DDS_HEADER dds_header = {};
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

    uint32_t tex_data_size = file_size - sizeof(TEX_HEADER);
    uint32_t header_size = 4 + sizeof(DDS_HEADER);
    if (need_dx10) header_size += 20;
    uint32_t total_size = header_size + tex_data_size;

    uint8_t* dds_data = (uint8_t*)malloc(total_size);
    if (!dds_data) { fclose(tex_file); return -4; }

    uint8_t* ptr = dds_data;
    memcpy(ptr, "DDS ", 4); ptr += 4;
    memcpy(ptr, &dds_header, sizeof(DDS_HEADER)); ptr += sizeof(DDS_HEADER);

    if (need_dx10) {
        uint8_t dx10_header[20] = {};
        dx10_header[0] = 0x0d;
        dx10_header[4] = 0x03;
        dx10_header[12] = 0x01;
        dx10_header[16] = 0x01;
        memcpy(ptr, dx10_header, 20);
        ptr += 20;
    }

    uint8_t* tex_data = (uint8_t*)malloc(tex_data_size);
    if (!tex_data) { free(dds_data); fclose(tex_file); return -4; }

    if (fread(tex_data, 1, tex_data_size, tex_file) != tex_data_size) {
        free(tex_data); free(dds_data); fclose(tex_file);
        return -2;
    }
    fclose(tex_file);

    if (tex_header.has_mipmaps && mipmap_count > 0) {
        uint32_t block_size = get_block_size(tex_header.tex_format);
        uint32_t bytes_per_block = get_bytes_per_block(tex_header.tex_format);
        int32_t current_offset = tex_data_size;

        for (uint32_t i = 0; i < mipmap_count; i++) {
            uint32_t mip_width = (tex_header.image_width >> i);
            uint32_t mip_height = (tex_header.image_height >> i);
            if (mip_width < 1) mip_width = 1;
            if (mip_height < 1) mip_height = 1;
            uint32_t block_width = (mip_width + block_size - 1) / block_size;
            uint32_t block_height = (mip_height + block_size - 1) / block_size;
            uint32_t mip_size = bytes_per_block * block_width * block_height;

            current_offset -= mip_size;
            if (current_offset < 0) break;
            memcpy(ptr, tex_data + current_offset, mip_size);
            ptr += mip_size;
        }
    } else {
        memcpy(ptr, tex_data, tex_data_size);
    }

    free(tex_data);
    *out_data = dds_data;
    *out_size = total_size;
    return 0;
}

DLL_EXPORT void free_bytes(uint8_t* data) {
    if (data) free(data);
}

// ============================================================================
// BIN Texture Parsing
// ============================================================================

// Hash constants (FNV-1a hashes of property names)
static const uint32_t HASH_SKIN_MESH_PROPERTIES = 0x45ff5904;
static const uint32_t HASH_TEXTURE = 0x3c6468f4;
static const uint32_t HASH_MATERIAL_OVERRIDE = 0x24725910;
static const uint32_t HASH_NAME = 0xaad7612c;
static const uint32_t HASH_MATERIAL_LINK = 0xd2e4d060;
static const uint32_t HASH_PROPERTIES_LIST = 0x0a6f0eb5;
static const uint32_t HASH_PROP_NAME = 0xb311d4ef;
static const uint32_t HASH_PROP_VALUE = 0xf0a363e3;

// Helper to get string value from a Value
static std::string get_string_value(const ritobin::Value& val) {
    if (auto* s = std::get_if<ritobin::String>(&val)) {
        return s->value;
    }
    return "";
}

// Helper to get hash value from a Value
static uint32_t get_hash_value(const ritobin::Value& val) {
    if (auto* h = std::get_if<ritobin::Hash>(&val)) {
        return h->value.hash();
    }
    if (auto* l = std::get_if<ritobin::Link>(&val)) {
        return l->value.hash();
    }
    return 0;
}

// Find field by hash in an Embed
static const ritobin::Field* find_field(const ritobin::Embed& embed, uint32_t hash) {
    for (const auto& field : embed.items) {
        if (field.key.hash() == hash) {
            return &field;
        }
    }
    return nullptr;
}

// Find field by hash in a Pointer
static const ritobin::Field* find_field(const ritobin::Pointer& ptr, uint32_t hash) {
    for (const auto& field : ptr.items) {
        if (field.key.hash() == hash) {
            return &field;
        }
    }
    return nullptr;
}

// Parse BIN and extract texture mappings
// Returns: "BASE=texture_path\nMaterialName=texture_path\n..."
static std::string extract_textures(const ritobin::Bin& bin) {
    std::unordered_map<std::string, std::string> results;
    std::unordered_map<uint32_t, const ritobin::Embed*> entries_map;

    // Get entries section
    auto entries_it = bin.sections.find("entries");
    if (entries_it == bin.sections.end()) return "";

    const auto* entries_map_val = std::get_if<ritobin::Map>(&entries_it->second);
    if (!entries_map_val) return "";

    // Build hash->entry map for link resolution
    for (const auto& pair : entries_map_val->items) {
        const auto* key_hash = std::get_if<ritobin::Hash>(&pair.key);
        const auto* entry = std::get_if<ritobin::Embed>(&pair.value);
        if (key_hash && entry) {
            entries_map[key_hash->value.hash()] = entry;
        }
    }

    // Traverse entries looking for skinMeshProperties
    for (const auto& pair : entries_map_val->items) {
        const auto* entry = std::get_if<ritobin::Embed>(&pair.value);
        if (!entry) continue;

        for (const auto& field : entry->items) {
            if (field.key.hash() != HASH_SKIN_MESH_PROPERTIES) continue;

            // skinMeshProperties is an Embed
            const auto* skin_mesh = std::get_if<ritobin::Embed>(&field.value);
            if (!skin_mesh) continue;

            // Look for texture (default) and materialOverride
            for (const auto& sub_field : skin_mesh->items) {
                // Default texture
                if (sub_field.key.hash() == HASH_TEXTURE) {
                    std::string tex = get_string_value(sub_field.value);
                    if (!tex.empty()) {
                        results["BASE"] = tex;
                    }
                }

                // Material overrides (list of embeds)
                if (sub_field.key.hash() == HASH_MATERIAL_OVERRIDE) {
                    const auto* override_list = std::get_if<ritobin::List>(&sub_field.value);
                    if (!override_list) continue;

                    for (const auto& override_elem : override_list->items) {
                        const auto* override_embed = std::get_if<ritobin::Embed>(&override_elem.value);
                        if (!override_embed) continue;

                        std::string mat_name;
                        std::string tex_path;
                        uint32_t linked_mat_hash = 0;

                        for (const auto& prop : override_embed->items) {
                            if (prop.key.hash() == HASH_NAME) {
                                mat_name = get_string_value(prop.value);
                            }
                            if (prop.key.hash() == HASH_TEXTURE) {
                                tex_path = get_string_value(prop.value);
                            }
                            if (prop.key.hash() == HASH_MATERIAL_LINK) {
                                linked_mat_hash = get_hash_value(prop.value);
                            }
                        }

                        // If no direct texture, try to follow material link
                        if (tex_path.empty() && linked_mat_hash != 0) {
                            auto mat_it = entries_map.find(linked_mat_hash);
                            if (mat_it != entries_map.end()) {
                                const auto* mat_entry = mat_it->second;

                                // Look for Properties list
                                const auto* props_field = find_field(*mat_entry, HASH_PROPERTIES_LIST);
                                if (props_field) {
                                    const auto* props_list = std::get_if<ritobin::List>(&props_field->value);
                                    if (props_list) {
                                        for (const auto& prop_elem : props_list->items) {
                                            const auto* prop_embed = std::get_if<ritobin::Embed>(&prop_elem.value);
                                            if (!prop_embed) continue;

                                            std::string p_name, p_val;
                                            for (const auto& pf : prop_embed->items) {
                                                if (pf.key.hash() == HASH_PROP_NAME) {
                                                    p_name = get_string_value(pf.value);
                                                }
                                                if (pf.key.hash() == HASH_PROP_VALUE) {
                                                    p_val = get_string_value(pf.value);
                                                }
                                            }
                                            if (p_name == "Diffuse_Texture" && !p_val.empty()) {
                                                tex_path = p_val;
                                                break;
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        if (!mat_name.empty() && !tex_path.empty()) {
                            results[mat_name] = tex_path;
                        }
                    }
                }
            }
        }
    }

    // Build output string: "key=value\n..."
    std::ostringstream oss;
    for (const auto& [key, value] : results) {
        oss << key << "=" << value << "\n";
    }
    return oss.str();
}

/*
 * Parse BIN file and extract texture mappings
 *
 * Parameters:
 *   bin_path  - Path to the .bin file (UTF-8)
 *   out_data  - Pointer to receive allocated string data (caller must free with free_bytes)
 *   out_size  - Pointer to receive size of string data (not including null terminator)
 *
 * Returns:
 *   0 on success, negative error code on failure
 *   -1: Failed to open file
 *   -2: Failed to parse BIN
 *   -4: Memory allocation failed
 *
 * Output format: "MaterialName=texture_path\n..." (newline separated key=value pairs)
 */
DLL_EXPORT int parse_bin_textures(const char* bin_path, uint8_t** out_data, uint32_t* out_size) {
    // Read file
    std::ifstream file(bin_path, std::ios::binary | std::ios::ate);
    if (!file.is_open()) return -1;

    std::streamsize size = file.tellg();
    file.seekg(0, std::ios::beg);

    std::vector<char> buffer(size);
    if (!file.read(buffer.data(), size)) {
        return -1;
    }
    file.close();

    // Parse BIN
    ritobin::Bin bin;
    auto compat = ritobin::io::BinCompat::get("default");
    std::string error = ritobin::io::read_binary(bin, buffer, compat);
    if (!error.empty()) {
        return -2;
    }

    // Extract textures
    std::string result = extract_textures(bin);

    // Allocate output
    uint32_t result_size = (uint32_t)result.size();
    uint8_t* result_data = (uint8_t*)malloc(result_size + 1);
    if (!result_data) return -4;

    memcpy(result_data, result.c_str(), result_size + 1);

    *out_data = result_data;
    *out_size = result_size;
    return 0;
}

DLL_EXPORT const char* get_version() {
    return "lol_native 1.0";
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpReserved) {
    (void)hinstDLL; (void)lpReserved;
    return TRUE;
}
