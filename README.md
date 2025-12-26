well, I have to admit that AI is much better at writing readme.md than me LOL   


# vivo-4.x-kernel-autopatch

An automated kernel patching tool for **vivo / iQOO devices running Linux 4.x kernels**.  
This tool is designed to simplify the process of patching restricted kernels so that **Magisk and root solutions can function properly**.

---

## Release Status

<img src="https://raw.githubusercontent.com/4accccc/vivo-4x-kernel-patch/refs/heads/main/autopatch-eng.png" width="27%" alt="English UI">
<img src="https://raw.githubusercontent.com/4accccc/vivo-4x-kernel-patch/refs/heads/main/autopatch-chn.png" width="25%" alt="Chinese UI">
<img src="https://raw.githubusercontent.com/4accccc/vivo-4x-kernel-patch/refs/heads/main/after_patch.png" width="50%" alt="After patch result">

👉 **Downloads:**  
[GitHub Releases](https://github.com/4accccc/vivo-4x-kernel-patch/releases)

---

## ⚠️ WARNING

**Modifying a device kernel is inherently dangerous.**  
Incorrect patching may result in a **hard brick**.

If you:
- do not fully understand what this tool does, or  
- believe the tool may contain malware, or  
- are unwilling to accept the risks  

**DO NOT USE THIS TOOL.**

You have been warned.

---

## System requirements   
 - Windows 10 / 11   
 - Android 9+
---

## Kernel Version Compatibility

| Kernel Version | 4.9.77+ | 4.14.94+ | 4.14.98 | 4.14.141+ | 4.14.186 | 4.14.190 | 4.19.191+ |
| :--------------: | :------: | :------: | :-----: | :-------: | :------: | :------: | :-------: |
| **Status** |    ❓³    |    ❓    |   ❓   |   ✔️   |   ✔️¹²   |   ❓¹   |   ✔️¹²   |

- ✔️ Tested and working
- ❓ Needs more user feedback
- ❌ Failed

**Notes:**
1. Mount fix caused a bootloop  
2. `vivo do_mount_check` patch required  
3. Works normally on Android 9 and above  

👉 Feedback welcome:  
https://github.com/4accccc/vivo-4.x-kernel-autopatch/discussions/1

---

## Features

✔ Automatically unpack `boot.img`  
✔ Automatically extract and patch kernel  
✔ Automatically repack `boot.img`  

### Additional functionality

- Automatically detects **Linux kernel major version**  
  - Warns user if kernel is **not 4.x**
- Automatically decompresses compressed kernels
- **Mount fix patch is optional**
- Optional patch for  
  [`/system → /syswxl`](https://github.com/wuxianlin/build_magisk_vivo/blob/aa744fc5d7a1cb6c1d44071651a745a80bba8e13/patches/Magisk/patch_vivo_do_mount_check.diff#L9)  
  required for Magisk on some models

---

## Project Status

This tool is **feature-complete** and **no longer under active development**.

⚠️ Important:
- This tool **ONLY patches the kernel**
- It **does NOT fix** issues caused by:
  - SELinux
  - init scripts
  - vendor framework restrictions
  - non-kernel components

If the patch does not work for your device, consider using **Magisk SUU** instead.

---

_~fxxk you vivo, fxxk you bbk, look at what you've done~_

---

## Credits

- [romanovj](https://github.com/romanovj) — kernel restriction solutions (su, mount fix)
- [wuxianlin](https://github.com/wuxianlin) — `do_mount_check` patch
- [radare2](https://github.com/radareorg/radare2) — reverse engineering framework
- [Magisk](https://github.com/topjohnwu/Magisk) — boot image unpacking and repacking
- [LoveRedscholar](https://github.com/LoveRedscholar)  
  & [Nevoraa](https://github.com/Nevoraa) — multi-device testing
- ~[vivo Open Source](https://opensource.vivo.com/Project) — useless shit~   


## Disclaimer

This project does **NOT** provide or distribute any proprietary exploits, confidential information, or undisclosed vulnerabilities.

All patching methods used by this tool are:
- **Publicly known**
- **Independently researched**
- **Previously published** in open communities

This project merely **automates an existing manual process** using publicly available tools and techniques.

The author:
- Does **not** claim ownership of the underlying methods
- Does **not** bypass any server-side or account-based protections
- Does **not** provide any commercial service

This tool is provided **for research and educational purposes only**.

Users are solely responsible for:
- How they use this tool
- Any damage to their devices
- Any legal consequences resulting from misuse

If this project violates any policy or local regulation, please open an issue for discussion.

