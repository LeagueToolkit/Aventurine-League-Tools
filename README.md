# Aventurine: League Tools

> A comprehensive Blender addon for working with League of Legends game assets

Aventurine provides a native solution for handling League of Legends meshes, skeletons, and animations directly within Blender 4.0 and newer, eliminating the need for external converters.

![Aventurine Preview](https://github.com/user-attachments/assets/ccb4b2fd-de63-4a3e-aa69-49d37d3dba53)

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
  - [Import and Export](#import-and-export)
  - [Physics Simulation](#physics-simulation)
  - [Animation Retargeting](#animation-retargeting)
  - [Updating](#updating)
- [Technical Details](#technical-details)
- [Credits](#credits)
- [License](#license)

---

## Features

**Core Functionality**
- **SKN Models**: Full import and export support for most SKN versions
- **SKL Skeletons**: Complete skeleton import and export capabilities
- **ANM Animations**: Native animation file handling

**Advanced Tools**
- **Physics System**: Built-in physics simulation based on Wiggle 2
- **Animation Retargeting**: Port animations between different character rigs
- **Auto-Updater**: Keep your addon current with the latest GitHub releases

---

## Installation

### Quick Start

1. Download the latest release from the [Releases](../../releases) page
2. Open Blender and navigate to **Edit → Preferences → Add-ons**
3. Click **Install...** and select the downloaded ZIP file
4. Search for "Aventurine" in the addon list
5. Enable the checkbox next to the addon

The addon is now ready to use.

---

## Usage

Access all Aventurine tools through the **N-panel** in the 3D Viewport (press `N` to toggle) under the **"Aventurine LoL"** tab.

### Import and Export

The main panel provides controls for importing and exporting League of Legends asset files:

- **SKN files**: Mesh data with vertex weights and materials
- **SKL files**: Skeletal armature structures
- **ANM files**: Animation data compatible with League rigs

**Important**: When exporting, verify your settings to ensure the correct armature or mesh is selected for export.

### Physics Simulation

Enable Animation Tools in the addon preferences to access the **Animation Tools** tab in the N-panel. This feature automates secondary motion for elements like hair, cloth, and accessories, providing realistic movement without manual keyframing.

### Animation Retargeting

The **LoL Retarget** option (available when enabled in preferences) allows you to transfer animations between different skeletons. This is particularly useful for:

- Adapting animations to custom rigs
- Sharing animations across different champions
- Testing animations on various character models

### Updating

Check for updates directly within Blender:

1. Navigate to **Edit → Preferences → Add-ons**
2. Find Aventurine in the addon list
3. Expand the addon details
4. Click **Check for Updates** in the preferences panel
5. If an update is available, install it with one click

---

## Technical Details

**Compatibility**
- Blender 4.0 or newer
- Supports multiple SKN format versions
- Cross-compatible with League of Legends game files

**Architecture**
- Native Python implementation with optimized C/C++ DLLs for file parsing
- No external dependencies or converters required
- Modular design for easy maintenance and updates

---

## Credits

**Development Team**
- **Bud** - Creator/Developer
- **Frog** - Developer

**Acknowledgments**
- Based on the `lol_maya` plugin by [tarngaina](https://github.com/tarngaina)
- Physics implementation derived from [Wiggle 2](https://github.com/shteeve3d/wiggle) by shteeve3d
- BIN file parsing powered by [ritobin](https://github.com/moonshadow565/ritobin) by moonshadow565
- TEX to DDS conversion powered by [Ritoddstex](https://github.com/Morilli/Ritoddstex) by Morilli

See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for full license details of third-party components.

---

## License

This project is licensed under the **GNU General Public License v3.0 (GPLv3)**.

The GPLv3 license is required because the physics module incorporates code from Wiggle 2, which is distributed under the same license. This ensures compliance with open-source licensing requirements and allows the community to freely use, modify, and distribute the addon.

For full license details, see the [LICENSE](LICENSE) file in this repository.

---

**Questions or Issues?** Open an issue on the [GitHub Issues](../../issues) page.