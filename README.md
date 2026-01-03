# Aventurine: League Tools

This is a Blender addon for importing and exporting League of Legends game assets. It is designed to work with Blender 4.0 and newer.

The goal is to provide a native way to handle meshes (.skn), skeletons (.skl), and animations (.anm) without needing external converters. We also included some extra tools like physics simulation and animation retargeting to make the workflow smoother.

## Features

- Import and Export SKN models (supports most versions).
- Import and Export SKL skeletons.
- Import and Export ANM animation files.
- Built-in Physics system (based on Wiggle 2).
- Animation Retargeting tool to port animations between characters.
- In-app updater to get the latest version from GitHub.

## Installation

1. Download the latest release.
2. Open Blender and go to Edit > Preferences > Add-ons.
3. Click Install... and select the zip file.
4. Search for "Aventurine" and enable the plugin.

## How to Use

Once installed, you can find the tools in the N-panel (press N in the 3D Viewport) under the "Aventurine LoL" tab.

### Import / Export
The main panel lets you import or export the three main file types. When exporting, check your settings to ensure you are exporting the correct armature or mesh.

### Physics and Retargeting
These tools have their own tabs in the N-panel (LoL Physics and LoL Retarget) when enabled in the addon preferences. They help with automating secondary motion and transferring animations between different skeletons.

### Updating
You can check for updates in the Addon Preferences menu. If a new version is found, you can install it directly from there.

## Credits

Created by Bud and Frog.
Based on the lol_maya plugin by tarngaina.
Physics code is based on Wiggle 2 by shteeve3d.

## License

This project is licensed under the GNU General Public License v3.0 (GPLv3).
This is required because the physics module incorporates code from Wiggle 2, which is an open-source project licensed under GPLv3.
