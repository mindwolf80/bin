# MT7986 Wireless Offload Firmware (OpenWrt)

OpenWrt `apk` package providing MediaTek MT7986 (Filogic 830) Wi-Fi offload (WO) firmware, build `20260221-r1`.

## Installation

Copy the package to the device, then:

```sh
apk add --allow-untrusted mt7986-wo-firmware-20260221-r1.apk
```

`--allow-untrusted` is required because the package is not signed with an OpenWrt feed key.
