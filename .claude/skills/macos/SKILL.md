---
name: macos-reference
description: Reference docs for macOS menu bar app development and sandboxing. Use when implementing MenuBarExtra, NSStatusItem, entitlements, or USB device access.
---

# macOS Development Reference

Reference material for building macOS menu bar apps.

## Files

- `menubar.md` - MenuBarExtra (SwiftUI), NSStatusItem (AppKit), background-only app patterns, dynamic icons, popovers
- `sandboxing.md` - App Sandbox entitlements, security-scoped bookmarks, USB device access, file access patterns

## When to Use

- Setting up the menu bar app architecture
- Configuring entitlements for USB HID access (`device.usb`)
- Bridging between menu bar popover and settings windows
- Understanding sandbox constraints for direct distribution vs. App Store

## Sources

- menubar.md: rshankras/claude-code-apple-skills (MIT)
- sandboxing.md: rshankras/claude-code-apple-skills (MIT)
