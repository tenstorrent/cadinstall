# cadinstall
EDA CAD tool installation and management utility

This utility facilitates the deployment of EDA CAD tools by copying a staged tool installation (owned by a user account) to the central tool installation area (owned by a faceless account). It achieves this by running commands via a protected setuid binary.

## Features
- Automates the deployment of EDA CAD tools.
- Ensures proper permissions and ownership during installation.
- Supports copying as a protected faceless account via setuid

## Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/tenstorrent/cadinstall
   ```
2. Navigate to the project directory:
   ```bash
   cd cadinstall
   ```
3. Install the project:
   ```bash
   pip install -e .
   ```

## Usage
Run the utility with the --help switch for full usage explanation and global switches to control stdout verbosity and dryrun mode:
```bash
cadinstall --help
```
There is currently only one subcommand supported - install. Run the subcommand with the --help switch for full usage explanation:
```bash
cadinstall install --help
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
