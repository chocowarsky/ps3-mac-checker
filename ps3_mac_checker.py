#!/usr/bin/env python3
"""
PS3 Controller MAC Address Checker
Reads Master MAC and Device MAC from Sony PlayStation 3 (DualShock 3 / Sixaxis) controllers
via USB HID feature reports on Linux.
"""

import sys
import os
import glob
import time
import fcntl

# Ensure line-buffered output so text appears immediately in terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)


def HIDIOCGFEAT(size):
    """Compute ioctl number for HIDIOCGFEAT(len)."""
    # _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, size)
    return (3 << 30) | (size << 16) | (ord('H') << 8) | 0x07


def clear_screen():
    print("\033[H\033[J", end="")


def get_ps3_devices():
    """Find sysfs device entries for connected PS3 controllers (Sony 054C:0268)."""
    return glob.glob('/sys/bus/hid/devices/*054C:0268*') + glob.glob('/sys/bus/hid/devices/*054c:0268*')


def find_hidraw_node(device_path):
    """Find corresponding /dev/hidrawX character device node."""
    hidraw_paths = glob.glob(os.path.join(device_path, 'hidraw', 'hidraw*'))
    if hidraw_paths:
        node_name = os.path.basename(hidraw_paths[0])
        return f'/dev/{node_name}'
    return None


def read_device_mac(device_path):
    """Read physical Bluetooth Device MAC address of the controller."""
    # 1. Read HID_UNIQ from sysfs uevent
    uevent_file = os.path.join(device_path, 'uevent')
    if os.path.exists(uevent_file):
        try:
            with open(uevent_file, 'r') as f:
                for line in f:
                    if line.startswith('HID_UNIQ='):
                        return line.strip().split('=', 1)[1]
        except Exception:
            pass

    # 2. Fallback to sysfs input*/uniq
    uniq_files = glob.glob(os.path.join(device_path, 'input', 'input*', 'uniq'))
    if uniq_files and os.path.exists(uniq_files[0]):
        try:
            with open(uniq_files[0], 'r') as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    return "Unavailable"


def read_master_mac(devnode):
    """
    Read Master Host Bluetooth MAC stored inside PS3 controller memory.
    Uses HID Feature Report 0xF5 (similar to sixpair utility).
    """
    fd = os.open(devnode, os.O_RDWR)
    try:
        buf = bytearray([0xf5] + [0] * 63)
        fcntl.ioctl(fd, HIDIOCGFEAT(len(buf)), buf)
        mac_bytes = buf[2:8]
        return ':'.join(f'{b:02x}' for b in mac_bytes)
    finally:
        os.close(fd)


def main():
    clear_screen()
    print("============================================================")
    print("           PS3 CONTROLLER MAC ADDRESS CHECKER               ")
    print("============================================================")
    print()

    devices = get_ps3_devices()
    if not devices:
        print("[i] Waiting for PS3 controller connection via USB cable...")
        print("    (Connect mini-USB cable to computer, or press Ctrl+C to cancel)")
        while not devices:
            time.sleep(1)
            devices = get_ps3_devices()

    print("[✓] PS3 Controller detected!")
    dev_path = devices[0]
    devnode = find_hidraw_node(dev_path)

    if not devnode or not os.path.exists(devnode):
        print(f"[!] Controller hidraw node is not ready ({devnode}). Try reconnecting the cable.")
        input("\nPress [Enter] to exit...")
        return

    # Check permission and read Master MAC
    try:
        master_mac = read_master_mac(devnode)
    except PermissionError:
        # Re-elevate with sudo if permission denied
        if os.geteuid() != 0:
            print("[*] Administrator privileges (sudo) required to read controller memory...")
            args = ['sudo', sys.executable] + sys.argv
            os.execvp('sudo', args)
            return
        else:
            print(f"[!] Access denied to {devnode}.")
            input("\nPress [Enter] to exit...")
            return
    except Exception as e:
        print(f"[!] Failed to read Master MAC: {e}")
        input("\nPress [Enter] to exit...")
        return

    device_mac = read_device_mac(dev_path)

    print()
    print("------------------------------------------------------------")
    print("1. MASTER MAC (Required for ESP32 / Ps3.begin):")
    print(f"   >>  {master_mac}  <<")
    print()
    print("   Paste this into setup() in your Arduino IDE:")
    print(f'   Ps3.begin("{master_mac}");')
    print("------------------------------------------------------------")
    print("2. DEVICE MAC (Physical Bluetooth Address of Controller):")
    print(f"   >>  {device_mac}  <<")
    print("------------------------------------------------------------")
    print()
    input("Done! Press [Enter] to close terminal...")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
