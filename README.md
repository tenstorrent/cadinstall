# cadinstall
EDA CAD tool installation and management utility

This utility facilitates the deployment of EDA CAD tools by copying a staged tool installation (owned by a user account) to the central tool installation area (owned by a faceless account). It achieves this by running commands via a protected setuid binary.

## Features
- Automates the deployment of EDA CAD tools.
- Ensures proper permissions and ownership during installation.
- Supports copying as a protected faceless account via setuid
- Alternative listener daemon mode for environments where setuid is not available (e.g., containers)

## Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/tenstorrent/cadinstall
   ```
2. Navigate to the project directory:
   ```bash
   cd cadinstall
   ```
3. Follow the setup instructions in the documentation.

## Usage
Run the utility with the --help switch for full usage explanation and global switches to control stdout verbosity and dryrun mode:
```bash
python cadinstall.py --help
```
There is currently only one subcommand supported - install. Run the subcommand with the --help switch for full usage explanation:
```bash
python cadinstall.py install --help
```

## No-Setuid Mode (Listener Daemon)

For environments where setuid functionality is disabled or unavailable (such as inside containers), cadinstall supports a listener daemon mode. The listener runs as a privileged user and executes commands on behalf of cadinstall.

See [LISTENER_SETUP.md](LISTENER_SETUP.md) for detailed setup instructions and [NO_SETUID.md](NO_SETUID.md) for the design document.

Quick start:
```bash
# 1. Create configuration file (if not exists)
cp config/cadinstall.json.example config/cadinstall.json

# 2. Edit config and set "enabled": true in the listener section

# 3. Start the listener daemon
sudo bin/cadinstall_listener_ctl.sh start

# 4. Use cadinstall normally - it will automatically use the listener
python cadinstall.py install --vendor synopsys --tool vcs --version 2023.12 --src /tmp/vcs_install
```

## Contributing
We welcome contributions! To contribute:
1. Fork the repository.
2. Create a new branch for your feature or bugfix:
   ```bash
   git checkout -b feature-name
   ```
3. Commit your changes and push the branch:
   ```bash
   git commit -m "Description of changes"
   git push origin feature-name
   ```
4. Open a pull request.

## License
This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.
