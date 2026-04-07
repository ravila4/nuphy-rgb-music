# Fallback Firmware Binaries

Recovery images for NuPhy Air75 V2 ANSI. Flash via DFU (hold Esc + plug in USB).

```bash
dfu-util -a 0 -d 0x19F5:0x3246 -s 0x08000000:leave -D <firmware.bin>
```

| File | Source | Version | Notes |
|------|--------|---------|-------|
| `nuphy_stock_v2.0.3.bin` | NuPhy official CDN | 2.0.3 | Factory restore |
| `ryodeushii_via_ryo-1.1.4.bin` | ryodeushii/qmk-firmware releases | ryo-1.1.4 | QMK + VIA, community fork |
