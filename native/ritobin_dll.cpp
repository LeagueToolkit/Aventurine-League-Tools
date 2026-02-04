/*
 * RitoBIN DLL - Fast BIN texture path extraction for Blender addon
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
#include "../ritobin-master/ritobin_lib/src/ritobin/bin_types_helper.hpp"
#include "../ritobin-master/ritobin_lib/src/ritobin/bin_io.hpp"

// Minimal BinCompat implementation (to avoid needing bin_io_dynamic.cpp)
namespace ritobin::io {
    struct BinCompatDefault : BinCompat {
        char const* name() const noexcept override {
            return "default";
        }
        bool type_to_raw(Type type, uint8_t &raw) const noexcept override {
            raw = static_cast<uint8_t>(type);
            return true;
        }
        bool raw_to_type(uint8_t raw, Type &type) const noexcept override {
            type = static_cast<Type>(raw);
            if (ValueHelper::is_primitive(type)) {
                return type <= ValueHelper::MAX_PRIMITIVE;
            } else {
                return type <= ValueHelper::MAX_COMPLEX;
            }
        }
    };
    static BinCompatDefault g_compat_default;
}

#ifdef BUILD_DLL
    #define DLL_EXPORT extern "C" __declspec(dllexport)
#else
    #define DLL_EXPORT extern "C" __declspec(dllimport)
#endif

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

// Parse BIN and extract texture mappings
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
 *   out_data  - Pointer to receive allocated string data (caller must free with free_bin_result)
 *   out_size  - Pointer to receive size of string data
 *
 * Returns:
 *   0 on success, negative error code on failure
 *
 * Output format: "MaterialName=texture_path\n..."
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
    std::string error = ritobin::io::read_binary(bin, buffer, &ritobin::io::g_compat_default);
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

DLL_EXPORT void free_bin_result(uint8_t* data) {
    if (data) free(data);
}

DLL_EXPORT const char* get_ritobin_version() {
    return "ritobin_dll 1.0";
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpReserved) {
    (void)hinstDLL; (void)lpReserved;
    return TRUE;
}
