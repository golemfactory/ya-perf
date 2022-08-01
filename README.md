# ya-perf

Performance analyzing tool for NET

### Available tests

* **GFTP transfer test** between Requestor and each Provider. Only one transfer at a time between Requestor and Provider.

| Command line option  | Default  | Description                            |
|----------------------|----------|----------------------------------------|
| --transfer           | disabled | Optional flag to enable test           |
| --transfer-file-size | 10       | Sets transferred file size (in Mbytes) |

WARNING: Be aware that large size of transferred files increase total test time.

* **Command output test** between Requestor and each Provider.

| Command line option | Default   | Description                               |
|---------------------|-----------|-------------------------------------------|
| --cmd-output-count  | 0         | Specifies the number of commands to send. |
| --cmd-output-size   | 393216    | Sets command output size (in bytes).      |

* **VPN ping test** between Providers. Only one ping test at a time between Providers. Each Provider is engaged in only one call at a time, as a client or a server.
Test is only completed when each Provider call others (total number of ping test: _n(n-1)_ where _n_ is number of instances). In example the VPN ping test is completed when 
3 nodes (A,B,C) complete 6 tests (A->B, B->A, A->C, C->A, B->C, C->B).

| Command line option | Default  | Description                                   |
|---------------------|----------|-----------------------------------------------|
| --vpn-ping          | disabled | Optional flag to enable test                  |
| --ping-count        | 10       | Specifies the number of ping packets to send. |

* **VPN transfer test** between Providers. Only one transfer test at a time between Providers. Each Provider is engaged in only one call at a time, as a client or a server.
Test is only completed when each Provider call others (total number of transfer test: _n(n-1)_ where _n_ is number of instances). In example the VPN transfer test is completed when 
3 nodes (A,B,C) complete 6 tests (A->B, B->A, A->C, C->A, B->C, C->B). In the background script uses by default `iperf 3.10.1` as a performance testing tool. Bandwidth is measured on TCP protocol.
TCP window size is set to 60000 bytes. Default performance testing tool can be switched to `scp` utility with --scp flag. Remember that TCP, Encryption, and SSH control messages add overhead, so your true throughput will be a little higher than the number reported by `scp` for the file transfer.
`scp` randomly transfers 10MB file. The file size can be set up using --scp-transfer-file-size option.

| Command line option      | Default  | Description                            |
|--------------------------|----------|----------------------------------------|
| --vpn-transfer           | disabled | Optional flag to enable test           |
| --scp                    | disabled | Optional flag to enable test           |
| --scp-transfer-file-size | 10       | Sets transferred file size (in Mbytes) |

### General options

| Command line option          | Default        | Description                                                                    |
|------------------------------|----------------|--------------------------------------------------------------------------------|
| --num-instances              | 2              | Number of provider nodes to be tested                                          |
| --subnet-tag                 | devnet-beta    | Set subnet name                                                                |
| --payment-driver, --driver   | erc20          | Set payment network driver                                                     |
| --payment-network, --network | rinkeby        | Set payment network name                                                       |
| --json                       | disabled       | Set the flag and save results in JSON format                                   |
| --log-file                   | ya-perf        | Log file for YAPAPI                                                            |
| --running-time               | 1200           | Option to set time the instance run before the cluster is stopped (in seconds) |
| --output-dir                 | main directory | Sets output directory for results                                              |

### Filtering nodes
You can use any Providers in the subnet (by default) or specify nodes to test. If order to filter nodes, enter Provider ID in `providers_list.json` file,
i.e.
```json
[
  "0x83a086e7779c31476eefee36ab8814bca3d35aa2",
  "0xd2ca30dff73047cb3619416b9de187686c31c6f6",
  "0xb7925f9378650e7291836ef9249e2fcdf8a378da",
  "0x02a71376b982cb3752e99252625aa4cc33b7ed3d",
  "0x0d6beaeec5e3a250ef909ffad58271780a340fea",
  "0xdf4b685011fb4b061e6ecb1f418d44e6cb3504d6"
]
```
Providers are selected for the test according to the order given in the file.

### Example

```bash
python3 performance.py --num-instances 2 --subnet-tag testnet --transfer --transfer-file-size 25 --vpn-ping --ping-count 5 --vpn-transfer --json
```

# GSB perf

Measuring local GSB performance. File is published and downloaded on the same machine.

`poetry run python3 gsb-perf.py --transfer-file-size 100`


# Saturate

Harness for the [`saturate` tool](https://github.com/golemfactory/ya-relay/blob/main/client/examples/saturate.rs) from
the `ya-relay` repository.

`saturate` is a `ya-relay` client, executed in either listening or sending mode. The latter discovers the former
via a designated relay server, establishes a connection, and tries to send as much data as possible. The listener tracks
inbound speed rates and dumps that data to a CSV file.

## Prerequisites

1. `saturate` supporting CSV file dumps (https://github.com/golemfactory/ya-relay/pull/181)

2. `saturate` binary is present on PATH

3. This tool requires key-authorized SSH access to all hosts specified in the configuration file
    - the SSH daemon must be running on each designated host
    - runner host on must be pre-authorized on each host
      (no password or key acknowledgment prompts are supported)

## Usage

Run a test suite, download CSV results and generate plots:

```bash
poetry run python3 saturate.py config.json ./saturate-output run
```

Generate plots from CSV data in a `saturate-output` directory:

```bash
poetry run python3 saturate.py config.json ./saturate-output gen
```

## Configuration

An example configuration file can be found [here](saturate-template.json).

Available configuration options:
  - `hosts` - SSH destination hosts (w/ an optional username)
  - `ports` - (optional) ya-relay client bind ports, specified 1:1 for hosts 
  - `env` - environment variables to create a product of; a test will be run for each entry
  - `time` - testing time in seconds


# Cross-SCP

A tool for executing SCP file transfers between hosts. The scripts dumps a summary output file on successful execution.

## Prerequisites

- your SSH key needs to be trusted by each node you're executing the script on
- node id to name map file is mandatory; it serves as a source of input node combinations
- YAML node file definition file is mandatory; in case that some configuration is missing, try creating a custom definition file

## Options

| Command line option | Default | Description                                                                  |
|---------------------|---------|------------------------------------------------------------------------------|
| -n, --nodes         | -       | Node id to name map file (JSON)                                              |
| -y, --yaml          | -       | `yagna-testnet-scripts` YAML node file definition                            |
| -d, --dir           | -       | directory to scan for YAML node file definitions (e.g. testnet scripts repo) |
| -s, --size          | 100M    | file size to transfer                                                        |
