import os
import platform
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional, Union


@dataclass
class MemoryStatus:
    total_gb: Optional[float]
    available_gb: Optional[float]
    memory_pressure: Optional[float]


@dataclass
class CpuTopology:
    physical_cores: int
    logical_cores: int
    architecture: str
    numa_nodes: int
    vendor: str


def log_error(msg: str) -> None:
    """Simple error logging function"""
    print(f"Error: {msg}")


@lru_cache(maxsize=1)
def get_system_memory_status() -> MemoryStatus:
    """
    Get system memory information using only standard library.
    Returns MemoryStatus with total_gb, available_gb, and memory_pressure.
    """
    system = platform.system()

    try:
        if system == "Darwin":  # macOS
            # Get total memory
            total_bytes = int(
                subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip()
            )
            total_gb = total_bytes / (1024**3)

            # Parse vm_stat output
            vm_output = (
                subprocess.check_output(["vm_stat"])
                .decode()
                .split("\n")
            )
            # Split each line into key-value pairs
            vm_pairs = (
                line.split(":")
                for line in vm_output
                if ":" in line
            )
            vm_stats = {
                k.strip(): v.strip()
                for k, v in vm_pairs
            }
            stats = {
                k: int(v.rstrip("."))
                for k, v in vm_stats.items()
                if v.rstrip(".").isdigit()
            }

            # Calculate available memory
            page_size = 4096
            free_pages = stats.get("Pages free", 0)
            inactive_pages = stats.get("Pages inactive", 0)
            available_bytes = (free_pages + inactive_pages) * page_size
            available_gb = available_bytes / (1024**3)
            memory_pressure = (
                1 - (available_gb / total_gb) if total_gb > 0 else None
            )

        elif system == "Linux":
            with open("/proc/meminfo") as f:
                # Parse memory info lines
                lines = (line.split(":") for line in f)
                meminfo = {
                    k: int(v.split()[0]) * 1024
                    for k, v in lines
                }
                total_gb = meminfo.get("MemTotal", 0) / (1024**3)
                available_gb = meminfo.get("MemAvailable", 0) / (1024**3)
                memory_pressure = 1 - (available_gb / total_gb)

        elif system == "Windows":
            import ctypes

            kernel32 = ctypes.windll.kernel32

            # Get total memory
            total_memory = ctypes.c_ulonglong()
            kernel32.GetPhysicallyInstalledSystemMemory(
                ctypes.byref(total_memory)
            )
            total_gb = total_memory.value / (1024**2)

            # Get memory status using Windows API
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            memory_status = MEMORYSTATUSEX()
            memory_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status))

            available_gb = memory_status.ullAvailPhys / (1024**3)
            memory_pressure = memory_status.dwMemoryLoad / 100.0

        else:
            return MemoryStatus(None, None, None)

        return MemoryStatus(total_gb, available_gb, memory_pressure)

    except Exception as e:
        log_error(f"Memory detection error: {e}")
        return MemoryStatus(None, None, None)


@lru_cache(maxsize=1)
def get_cpu_topology() -> CpuTopology:
    """Get CPU topology information using standard library."""
    system = platform.system()
    default_topology = CpuTopology(
        physical_cores=1,
        logical_cores=os.cpu_count() or 1,
        architecture=platform.machine(),
        numa_nodes=1,
        vendor="unknown",
    )

    try:
        if system == "Darwin":
            sysctl_mapping = {
                "physical_cores": "hw.physicalcpu",
                "logical_cores": "hw.logicalcpu",
                "vendor": "machdep.cpu.vendor",
            }

            # Get CPU info using sysctl
            values = {}
            for key, sctl_key in sysctl_mapping.items():
                cmd = ["sysctl", "-n", sctl_key]
                values[key] = (
                    subprocess.check_output(cmd)
                    .decode()
                    .strip()
                )

            # Get NUMA info
            numa_cmd = ["sysctl", "-n", "hw.packages"]
            numa_nodes = int(
                subprocess.check_output(numa_cmd)
                .decode()
                .strip()
            )

            return CpuTopology(
                physical_cores=int(values["physical_cores"]),
                logical_cores=int(values["logical_cores"]),
                architecture=default_topology.architecture,
                numa_nodes=numa_nodes,
                vendor=values["vendor"],
            )

        elif system == "Linux":
            with open("/proc/cpuinfo") as f:
                cpuinfo = f.read().split("\n")

            # Get physical cores using set comprehension
            cores = {
                line.split(":")[1].strip()
                for line in cpuinfo
                if "physical id" in line
            }
            physical_cores = len(cores)

            # Get vendor using next() with generator expression
            vendor = next(
                (
                    line.split(":")[1].strip()
                    for line in cpuinfo
                    if "vendor_id" in line
                ),
                "unknown",
            )

            # Get NUMA nodes
            numa_path = "/sys/devices/system/node"
            has_numa = os.path.exists(numa_path)
            if has_numa:
                nodes = [
                    d for d in os.listdir(numa_path)
                    if d.startswith("node")
                ]
                numa_nodes = len(nodes)
            else:
                numa_nodes = 1

            return CpuTopology(
                physical_cores=physical_cores or default_topology.physical_cores,
                logical_cores=default_topology.logical_cores,
                architecture=default_topology.architecture,
                numa_nodes=numa_nodes,
                vendor=vendor,
            )

        elif system == "Windows":
            try:
                import winreg

                reg_path = (
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
                )
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE, reg_path
                ) as key:
                    vendor = winreg.QueryValueEx(
                        key, "VendorIdentifier"
                    )[0]
            except Exception:
                vendor = default_topology.vendor

            try:
                import wmi

                cpu_info = wmi.WMI().Win32_Processor()[0]
                return CpuTopology(
                    physical_cores=int(cpu_info.NumberOfCores),
                    logical_cores=int(
                        cpu_info.NumberOfLogicalProcessors
                    ),
                    architecture=default_topology.architecture,
                    numa_nodes=default_topology.numa_nodes,
                    vendor=vendor,
                )
            except ImportError:
                return default_topology

    except Exception as e:
        log_error(f"CPU topology detection error: {e}")
        return default_topology


def calculate_max_threads(
    max_threads_cap: int = 100,
) -> Dict[str, Union[Dict, float, int]]:
    """Calculate optimal thread count based on system resources."""
    topology = get_cpu_topology()
    memory = get_system_memory_status()

    # Determine base threads per core based on architecture and vendor
    arch_vendor_map = {
        "arm": 3,  # Conservative for ARM
        "amd": 6,  # AMD optimized
        "x86": 5,  # x86 default
        "amd64": 5,  # x86_64 default
    }

    # Check architecture and vendor
    arch_key = topology.architecture.lower()
    vendor_key = topology.vendor.lower()
    matching_key = next(
        (
            key for key in arch_vendor_map
            if key in arch_key or key in vendor_key
        ),
        None,
    )
    base_threads = arch_vendor_map.get(matching_key, 4)

    # Calculate adjustment factors
    numa_factor = max(1, topology.numa_nodes) ** 0.5
    smt_factor = 0.9 if "amd" in vendor_key else 0.8
    memory_factor = (
        1.0 - (memory.memory_pressure * 0.4)
        if memory.memory_pressure and memory.memory_pressure < 0.5
        else max(0.5, 1 - (memory.memory_pressure or 0))
    )

    # Calculate final thread count
    threads_per_core = (
        base_threads * smt_factor * memory_factor / numa_factor
    )
    thread_count = int(topology.logical_cores * threads_per_core)
    # Ensure even number of threads
    if thread_count % 2:
        thread_count += 1
    max_threads = min(thread_count, max_threads_cap)

    return {
        "topology": {
            "physical_cores": topology.physical_cores,
            "logical_cores": topology.logical_cores,
            "architecture": topology.architecture,
            "numa_nodes": topology.numa_nodes,
            "vendor": topology.vendor,
        },
        "memory": {
            "total_gb": memory.total_gb,
            "available_gb": memory.available_gb,
            "pressure": memory.memory_pressure,
        },
        "threads_per_core": threads_per_core,
        "max_threads": max_threads,
        "factors": {
            "base_threads": base_threads,
            "smt_factor": smt_factor,
            "memory_factor": memory_factor,
            "numa_factor": numa_factor,
        },
    }


if __name__ == "__main__":
    details = calculate_max_threads()
    mem, topo = details["memory"], details["topology"]

    # Format memory values using helper function
    def format_ram(val: Optional[float], unit: str = "GB") -> str:
        return f"{val:.2f} {unit}" if val is not None else "Unknown"

    ram_info = {
        "total": format_ram(mem["total_gb"]),
        "available": format_ram(mem["available_gb"]),
        "pressure": (
            f"{mem['pressure'] * 100:.1f}%"
            if mem["pressure"] is not None else "Unknown"
        ),
    }

    # Print system analysis
    print("\nSystem Hardware Analysis:")
    print("------------------------")
    print(f"CPU Architecture: {topo['architecture']}")
    print(f"CPU Vendor: {topo['vendor']}")
    print(f"Physical Cores: {topo['physical_cores']}")
    print(f"Logical Cores: {topo['logical_cores']}")
    print(f"NUMA Nodes: {topo['numa_nodes']}")

    print("\nMemory Status:")
    print("-------------")
    print(f"Total RAM: {ram_info['total']}")
    print(f"Available RAM: {ram_info['available']}")
    print(f"Memory Pressure: {ram_info['pressure']}")

    factors = details["factors"]
    print("\nThread Calculation Factors:")
    print("-------------------------")
    print(f"Base Threads per Core: {factors['base_threads']}")
    print(f"SMT Factor: {factors['smt_factor']:.2f}")
    print(f"Memory Factor: {factors['memory_factor']:.2f}")
    print(f"NUMA Factor: {factors['numa_factor']:.2f}")

    print("\nFinal Calculations:")
    print("-----------------")
    print(f"Effective Threads per Core: {details['threads_per_core']:.2f}")
    print(f"Recommended Max Threads: {details['max_threads']}")

    # Print warnings using list comprehension with better type hints
    warnings = [
        "Warning: High memory pressure detected - thread count reduced"
        for f in [factors["memory_factor"]]
        if f < 0.8
    ] + [
        "Note: Multiple NUMA nodes detected - thread distribution optimized"
        for n in [topo["numa_nodes"]]
        if n > 1
    ]

    if warnings:
        print("\n" + "\n".join(warnings))
