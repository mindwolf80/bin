from netmiko import ConnectHandler
device = {
    "device_type": "cisco_ios",
    "host": "10.0.0.1",
    "username": "netops",
    "password": "changeme",
    "fast_cli": True,
}
with ConnectHandler(**device) as conn:
    print(conn.send_command("show version", read_timeout=60))
