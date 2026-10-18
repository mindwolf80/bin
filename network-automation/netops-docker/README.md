# NetOps Docker

Alpine-based Python 3.12 container for network automation, published as `ghcr.io/mindwolf80/netops-alpine`.

## Included Tooling

| Package | Version |
|---|---|
| netmiko | 4.4.0 |
| scrapli | 2024.7.30 |
| paramiko | 3.4.0 |
| ntc-templates | 5.1.0 |
| textfsm | 1.1.3 |
| rich | 13.7.1 |
| tqdm | 4.66.4 |
| pandas | 2.2.2 |

System packages: `openssh-client`, `git`, `bash`, `nano`, `tzdata`, `ca-certificates`.

## Layout

```
netops-docker/
├── Dockerfile
├── run-netops.sh          # Pulls latest image and starts an interactive shell
├── scripts/
│   └── example_netmiko.py
└── data/
    ├── inventory.csv      # host,device_type,username,password,secret
    └── commands.txt
```

## Usage

### Run the published image

```bash
./run-netops.sh
```

The script prompts for `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` when unset, then mounts `$WORKDIR` (default `/srv/netops`) at `/work`.

### Build locally

```bash
docker build -t netops-alpine .
docker run --rm -it -v "$PWD":/work netops-alpine
```
